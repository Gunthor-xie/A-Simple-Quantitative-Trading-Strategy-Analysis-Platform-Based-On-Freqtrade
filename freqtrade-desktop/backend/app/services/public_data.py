"""Public-market data downloader (no bot, no API key, no ccxt).

OKX throttles the ccxt/aiohttp client on some networks, which makes
``freqtrade download-data`` fail. This module talks to the OKX v5 public
market endpoints directly with ``requests`` and writes files in exactly the
layout freqtrade expects (jsongz), so backtests can consume them offline.

Written layouts
- spot    : data/<exchange>/<PAIR>-<tf>.json.gz
- futures : data/<exchange>/futures/<PAIR>-<tf>-futures.json.gz
- mark    : data/<exchange>/futures/<PAIR>-<tf>-mark.json.gz
- index   : data/<exchange>/futures/<PAIR>-<tf>-index.json.gz
- funding : data/<exchange>/futures/<PAIR>-8h-funding_rate.json.gz
  (funding rows follow freqtrade's 6-column format: [ts, rate, 0, 0, 0, 0])
"""

from __future__ import annotations

import gzip
import json
import os
import random
import socket
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from ..schemas import DownloadParams


OKX_BASE = "https://www.okx.com"

# freqtrade uses lowercase timeframes; OKX uses uppercase for >= 1 hour.
OKX_BAR = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D",
}


class PublicDataError(Exception):
    pass


def to_instrument(pair: str, trading_mode: str) -> str:
    """BTC/USDT -> BTC-USDT (spot); BTC/USDT:USDT -> BTC-USDT-SWAP (futures)."""
    if trading_mode == "spot":
        return pair.split(":")[0].replace("/", "-")
    base_quote = pair if ":" in pair else f"{pair}:USDT"
    base, rest = base_quote.split("/", 1)
    quote, settle = rest.split(":", 1)
    return f"{base}-{quote}-SWAP"


def to_futures_symbol(pair: str) -> str:
    """BTC/USDT -> BTC/USDT:USDT (futures symbol used in file names)."""
    return pair if ":" in pair else f"{pair}:USDT"


def parse_timerange(timerange: str | None) -> tuple[int, int]:
    """'20260101-20260901' -> (start_ms, end_ms); open sides allowed."""
    now = int(time.time() * 1000)
    start, end = 0, now
    if not timerange:
        return start, end
    parts = timerange.split("-")

    def to_ms(value: str, end_of_day: bool) -> int | None:
        value = value.strip()
        if not value:
            return None
        try:
            if len(value) == 10 and value.isdigit():  # epoch seconds
                return int(value) * 1000
            if len(value) == 13 and value.isdigit():  # epoch ms
                return int(value)
            y, m, d = int(value[0:4]), int(value[4:6]), int(value[6:8])
            dt = datetime(y, m, d, tzinfo=timezone.utc)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    left = to_ms(parts[0], False) if parts and parts[0] else None
    right = to_ms(parts[1], True) if len(parts) > 1 and parts[1] else None
    return (left or 0), (right or now)


class PublicDataDownloader:
    def __init__(
        self,
        user_data: str | Path,
        http_get: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        progress: Callable[[str], None] | None = None,
        proxy: str | None = None,
        pause: float = 0.12,
        retries: int = 6,
    ) -> None:
        self.user_data = Path(user_data)
        # Always connect directly: the backend process may inherit a stale
        # HTTP(S)_PROXY (observed: WinError 10061 proxy refused) which would
        # otherwise break every download. trust_env=False ignores env proxies.
        self._session = requests.Session()
        self._session.trust_env = False
        self._get = http_get or self._session.get
        self._sleep = sleep or time.sleep
        self._progress = progress or (lambda _msg: None)
        self._pause = pause
        self._retries = retries
        self._explicit_proxy = (proxy or "").strip() or None
        # Tests inject their own http_get; in that case never probe proxies.
        self._custom_get = http_get is not None
        self._proxies: dict[str, str] | None = None
        self._proxy_resolved = False

    def _resolve_proxies(self) -> dict[str, str] | None:
        """Find a working HTTP(S) proxy.

        Some sandboxes only allow outbound traffic through a local proxy
        (observed: http://127.0.0.1:17891) while direct sockets to the exchange
        time out. Prefer an explicit setting, then environment/registry, then
        the well-known local proxy address.
        """
        if self._proxy_resolved:
            return self._proxies
        self._proxy_resolved = True
        if self._custom_get:
            return None
        candidates: list[str] = []
        explicit = self._explicit_proxy or os.environ.get("FTDESK_HTTP_PROXY")
        if explicit:
            candidates.append(explicit)
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            value = os.environ.get(key)
            if value:
                candidates.append(value)
        try:
            for key in ("https", "http"):
                value = urllib.request.getproxies().get(key)
                if value:
                    candidates.append(value)
        except Exception:
            pass
        candidates.append("http://127.0.0.1:17891")

        for candidate in dict.fromkeys(candidates):
            proxies = {"http": candidate, "https": candidate}
            try:
                response = requests.get(
                    f"{OKX_BASE}/api/v5/public/time", proxies=proxies, timeout=8
                )
                if response.status_code == 200:
                    self._proxies = proxies
                    self._progress(f"using proxy {candidate}")
                    return proxies
            except Exception:
                continue
        self._progress("no working proxy found, using direct connection")
        self._proxies = None
        return None

    # ------------------------------------------------------------------ http
    def _fetch(self, path: str, params: dict[str, Any]) -> list[list[Any]]:
        last_error: Exception | None = None
        proxies = self._resolve_proxies()
        for attempt in range(self._retries):
            try:
                kwargs: dict[str, Any] = {"params": params, "timeout": 45}
                if proxies and not self._custom_get:
                    kwargs["proxies"] = proxies
                response = self._get(f"{OKX_BASE}{path}", **kwargs)
                response.raise_for_status()
                payload = response.json()
                code = payload.get("code")
                if code not in ("0", 0):
                    if str(code) in ("50011", "50013", "50026"):  # OKX rate limit codes
                        wait = min(30, 5 * (attempt + 1)) + random.random()
                        self._progress(f"rate limited by OKX, sleeping {wait:.0f}s")
                        self._sleep(wait)
                        last_error = PublicDataError(f"OKX rate limit {code}")
                        continue
                    raise PublicDataError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
                return payload.get("data", [])
            except Exception as exc:  # network hiccups / throttling
                last_error = exc
                if attempt < self._retries - 1:
                    wait = min(20.0, 2.0 * (attempt + 1)) + random.random()
                    self._progress(f"network error, retry in {wait:.0f}s ({type(exc).__name__})")
                    self._sleep(wait)
        raise PublicDataError(f"请求 {path} 失败：{last_error}")

    def _paginate(
        self,
        path: str,
        base_params: dict[str, Any],
        start_ms: int,
        end_ms: int,
        kind: str,
        label: str,
    ) -> list[list[float]]:
        rows: dict[int, list[float]] = {}
        # OKX pages backwards from "after" (records earlier than that ts). Start at
        # the requested window end instead of letting the API default to "now":
        # downloading a window that is far in the past would otherwise walk every
        # page between now and the window (observed: ~5.5k wasted pages for a
        # one-day 1m request), which made the download look like a hang.
        after: str | None = str(end_ms)
        previous_oldest: int | None = None
        pages = 0
        while True:
            params = dict(base_params)
            if after:
                params["after"] = after
            batch = self._fetch(path, params)
            if not batch:
                break
            page_oldest = None
            for item in batch:
                try:
                    if kind == "funding_rate":
                        ts = int(item.get("fundingTime"))
                        value = float(item.get("fundingRate"))
                        row = [ts, value, 0.0, 0.0, 0.0, 0.0]
                    else:
                        ts = int(item[0])
                        row = [
                            ts,
                            float(item[1]),
                            float(item[2]),
                            float(item[3]),
                            float(item[4]),
                            float(item[5]) if len(item) > 5 and item[5] is not None else 0.0,
                        ]
                except (TypeError, ValueError, IndexError):
                    continue
                page_oldest = ts if page_oldest is None else min(page_oldest, ts)
                if start_ms <= ts <= end_ms:
                    rows[ts] = row
            pages += 1
            if pages % 20 == 0:
                self._progress(f"{label}: {len(rows)} rows (page {pages})")
            if page_oldest is None or page_oldest <= start_ms:
                break
            if previous_oldest is not None and page_oldest >= previous_oldest:
                # Guard against a non-advancing cursor (would loop forever).
                self._progress(f"{label}: pagination stalled at {page_oldest}, stopping")
                break
            previous_oldest = page_oldest
            after = str(page_oldest)
            self._sleep(self._pause)
        return [rows[k] for k in sorted(rows)]

    # --------------------------------------------------------------- outputs
    def _write(self, path: Path, rows: Iterable[list[float]]) -> int:
        """Merge with any existing file so repeated runs resume instead of losing data."""
        merged: dict[int, list[float]] = {}
        if path.exists():
            try:
                for row in json.loads(gzip.decompress(path.read_bytes()).decode()):
                    merged[int(row[0])] = row
            except Exception:
                merged = {}
        for row in rows:
            merged[int(row[0])] = row
        data = [merged[k] for k in sorted(merged)]
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(gzip.compress(json.dumps(data).encode()))
        os.replace(tmp, path)
        return len(data)

    def _pair_file(self, exchange: str, pair: str, timeframe: str, trading_mode: str,
                   kind: str) -> Path:
        if trading_mode == "spot":
            safe = pair.split(":")[0].replace("/", "_")
            return self.user_data / "data" / exchange / f"{safe}-{timeframe}.json.gz"
        symbol = to_futures_symbol(pair).replace("/", "_").replace(":", "_")
        suffix = {"futures": "-futures", "mark": "-mark", "index": "-index", "funding_rate": "-funding_rate"}.get(kind, "")
        return self.user_data / "data" / exchange / "futures" / f"{symbol}-{timeframe}{suffix}.json.gz"

    # ---------------------------------------------------------------- public
    def download(self, params: DownloadParams) -> dict[str, Any]:
        start_ms, end_ms = parse_timerange(params.timerange)
        candle_types = set(params.candle_types or [])
        if params.trading_mode == "futures":
            candle_types = candle_types or {"futures", "mark", "funding_rate"}
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for pair in params.pairs:
            inst = to_instrument(pair, params.trading_mode)
            if params.trading_mode == "spot":
                kinds = ["futures"]  # spot candles
            else:
                kinds = [k for k in ("futures", "mark", "index") if k in candle_types]
            for timeframe in params.timeframes:
                bar = OKX_BAR.get(timeframe)
                if bar is None:
                    continue
                for kind in kinds:
                    if kind == "futures":
                        endpoint = "/api/v5/market/history-candles"
                        query = {"instId": inst, "bar": bar, "limit": "100"}
                    elif kind == "mark":
                        endpoint = "/api/v5/market/mark-price-candles"
                        query = {"instId": inst, "bar": bar, "limit": "100"}
                    else:
                        endpoint = "/api/v5/market/index-candles"
                        query = {"instId": inst.rsplit("-", 1)[0], "bar": bar, "limit": "100"}
                    label = f"{pair} {timeframe} {kind}"
                    self._progress(f"downloading {label}")
                    try:
                        rows = self._paginate(endpoint, query, start_ms, end_ms, kind, label)
                    except Exception as exc:
                        errors.append({"pair": pair, "timeframe": timeframe, "kind": kind,
                                       "error": str(exc)[:300]})
                        self._progress(f"FAILED {label}: {str(exc)[:120]}")
                        continue
                    if not rows:
                        continue
                    target = self._pair_file(params.exchange, pair, timeframe,
                                             params.trading_mode, kind)
                    count = self._write(target, rows)
                    results.append({
                        "pair": pair, "timeframe": timeframe, "kind": kind,
                        "file": str(target), "rows": count,
                        "first": rows[0][0], "last": rows[-1][0],
                    })
                    self._sleep(0.3)
            # funding rate has a fixed 8h cadence and is downloaded once per pair
            if params.trading_mode == "futures" and "funding_rate" in candle_types:
                label = f"{pair} funding_rate"
                self._progress(f"downloading {label}")
                try:
                    rows = self._paginate(
                        "/api/v5/public/funding-rate-history",
                        {"instId": inst, "limit": "100"},
                        start_ms, end_ms, "funding_rate", label,
                    )
                except Exception as exc:
                    errors.append({"pair": pair, "timeframe": "8h", "kind": "funding_rate",
                                   "error": str(exc)[:300]})
                    self._progress(f"FAILED {label}: {str(exc)[:120]}")
                    rows = []
                if rows:
                    target = self._pair_file(params.exchange, pair, "8h", params.trading_mode, "funding_rate")
                    count = self._write(target, rows)
                    results.append({
                        "pair": pair, "timeframe": "8h", "kind": "funding_rate",
                        "file": str(target), "rows": count,
                        "first": rows[0][0], "last": rows[-1][0],
                    })
        if not results and errors:
            raise PublicDataError(errors[0]["error"])
        return {"files": results, "total_files": len(results), "errors": errors}


def network_diagnostics(proxy: str | None = None) -> dict[str, Any]:
    """Probe every possible route to OKX so the UI can show a clear verdict."""
    result: dict[str, Any] = {
        "env_proxies": {},
        "system_proxies": {},
        "dns": [],
        "tcp": [],
        "requests": [],
        "conclusion": "",
    }
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
                "all_proxy", "FTDESK_HTTP_PROXY"):
        value = os.environ.get(key)
        if value:
            result["env_proxies"][key] = value
    try:
        result["system_proxies"] = dict(urllib.request.getproxies())
    except Exception as exc:
        result["system_proxies"] = {"error": str(exc)[:120]}

    try:
        infos = socket.getaddrinfo("www.okx.com", 443, proto=socket.IPPROTO_TCP)
        result["dns"] = sorted({i[4][0] for i in infos})
    except Exception as exc:
        result["dns"] = [f"DNS_FAIL: {type(exc).__name__}"]

    for address in [a for a in result["dns"] if "." in a][:3]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(6)
        t0 = time.time()
        try:
            sock.connect((address, 443))
            result["tcp"].append({"address": address, "ok": True,
                                  "seconds": round(time.time() - t0, 2)})
        except Exception as exc:
            result["tcp"].append({"address": address, "ok": False,
                                  "error": f"{type(exc).__name__}: {exc}"[:120]})
        finally:
            try:
                sock.close()
            except Exception:
                pass

    candidates: list[str] = []
    if proxy:
        candidates.append(proxy)
    if os.environ.get("FTDESK_HTTP_PROXY"):
        candidates.append(os.environ["FTDESK_HTTP_PROXY"])
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY",
                "all_proxy"):
        if os.environ.get(key):
            candidates.append(os.environ[key])
    proxies_map = result["system_proxies"]
    if isinstance(proxies_map, dict):
        for key in ("https", "http"):
            if proxies_map.get(key):
                candidates.append(proxies_map[key])
    candidates.append("http://127.0.0.1:17891")

    def attempt(label: str, proxies: dict[str, str] | None) -> dict[str, Any]:
        t0 = time.time()
        try:
            response = requests.get(f"{OKX_BASE}/api/v5/public/time", proxies=proxies, timeout=12)
            return {"route": label, "ok": response.status_code == 200,
                    "status": response.status_code, "seconds": round(time.time() - t0, 2)}
        except Exception as exc:
            return {"route": label, "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:160],
                    "seconds": round(time.time() - t0, 2)}

    result["requests"].append(attempt("direct", None))
    for candidate in dict.fromkeys(candidates):
        result["requests"].append(attempt(f"proxy {candidate}", {"http": candidate, "https": candidate}))

    working = [r for r in result["requests"] if r.get("ok")]
    if working:
        result["conclusion"] = f"可用通道：{working[0]['route']}"
    else:
        result["conclusion"] = (
            "所有通道均不可用：直连被阻断且未找到可用代理，请在设置中填写可用代理"
            "（例如本机 VPN/代理的端口）后重试"
        )
    return result
