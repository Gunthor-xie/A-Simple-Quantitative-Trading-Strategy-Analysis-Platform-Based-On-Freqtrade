"""OKX public forced-liquidation / open-interest / taker-flow collector.

Why: the platform has no historical liquidation archive (Binance returns 404 for
``liquidationSnapshot``, OKX only exposes a rolling window through
``/public/liquidation-orders``), so the only way to test the strategy's actual
premise - "fade a forced-liquidation cascade" - is to record the real flow
ourselves and re-run the backtest once enough weeks have accumulated.

Streams (all public, no API key)
--------------------------------
* ``/api/v5/public/liquidation-orders`` (SWAP, state=filled): individual
  liquidation orders. ``details[].posSide`` is the side that got liquidated,
  ``sz`` is in contracts, so notional = sz x ctVal x bkPx.
  Pagination semantics (verified 2026-09-21): ``before=<ts>`` returns records
  *newer* than ts, ``after=<ts>`` returns records *older* than ts.
* ``/api/v5/rubik/stat/contracts/open-interest-volume`` (5m): OI in USD + coin.
* ``/api/v5/rubik/stat/taker-volume`` (5m, instType=CONTRACTS): taker sell/buy
  volume in USD - the venue-consistent replacement for Binance's taker split.

Output (append-only JSONL, one file per stream, crash-safe):
    user_data/liquidation/<PAIR>-liq-raw.jsonl
    user_data/liquidation/<PAIR>-okx-oi.jsonl
    user_data/liquidation/<PAIR>-okx-taker.jsonl

``aggregate_liquidations`` turns the raw JSONL into the per-minute frame the
feature builder already understands (``date``/``side``/``notional``).
"""

from __future__ import annotations

import gzip
import json
import os
import random
import time
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import requests


OKX_BASE = "https://www.okx.com"
BAR_MS = 60_000
LOCAL_PROXY = "http://127.0.0.1:17891"


class LiquidationCollectorError(Exception):
    """Raised when a stream cannot be fetched or parsed."""


def pair_slug(pair: str) -> str:
    return pair.replace("/", "_").replace(":", "_")


def swap_inst_id(pair: str) -> str:
    """``BTC/USDT:USDT`` -> ``BTC-USDT-SWAP``."""
    base, rest = pair.split("/", 1)
    quote = rest.split(":", 1)[0]
    return f"{base}-{quote}-SWAP"


class LiquidationCollector:
    """Polls OKX public endpoints and appends normalised records to JSONL files."""

    def __init__(
        self,
        user_data: str | Path,
        pair: str = "BTC/USDT:USDT",
        *,
        proxy: str | None = None,
        http_get: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        progress: Callable[[str], None] | None = None,
        retries: int = 4,
        timeout: float = 30.0,
        poll_seconds: float = 30.0,
        derivatives_seconds: float = 300.0,
        catchup_pages: int = 20,
        backfill_pages: int = 5,
    ) -> None:
        self.user_data = Path(user_data)
        self.pair = pair
        self.slug = pair_slug(pair)
        self.inst_id = swap_inst_id(pair)
        self.ccy = pair.split("/", 1)[0]
        self._dir = self.user_data / "liquidation"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._sleep = sleep or time.sleep
        self._progress = progress or (lambda _msg: None)
        self._retries = max(1, retries)
        self._timeout = timeout
        self.poll_seconds = poll_seconds
        self.derivatives_seconds = derivatives_seconds
        # How many extra pages to walk back through: on a normal poll this only
        # matters when >100 liquidations appeared since the previous poll; on the
        # very first run it grabs a bit of the still-published history.
        self.catchup_pages = max(0, catchup_pages)
        self.backfill_pages = max(0, backfill_pages)

        self._session = requests.Session()
        self._session.trust_env = False
        self._get = http_get or self._session.get
        self._custom_get = http_get is not None
        self._explicit_proxy = (proxy or "").strip() or None
        self._proxies: dict[str, str] | None = None
        self._proxy_resolved = False

        self._seen: OrderedDict[str, None] = OrderedDict()
        self._last_liq_ts = 0
        self._last_oi_ts = 0
        self._last_taker_ts = 0
        self._ct_val: float | None = None

    # ------------------------------------------------------------- files
    @property
    def raw_path(self) -> Path:
        return self._dir / f"{self.slug}-liq-raw.jsonl"

    @property
    def oi_path(self) -> Path:
        return self._dir / f"{self.slug}-okx-oi.jsonl"

    @property
    def taker_path(self) -> Path:
        return self._dir / f"{self.slug}-okx-taker.jsonl"

    # ------------------------------------------------------------- http
    def _resolve_proxies(self) -> dict[str, str] | None:
        if self._proxy_resolved:
            return self._proxies
        self._proxy_resolved = True
        if self._custom_get:
            return None
        candidates: list[str] = []
        explicit = self._explicit_proxy or os.environ.get("FTDESK_HTTP_PROXY")
        if explicit:
            candidates.append(explicit)
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
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
        candidates.append(LOCAL_PROXY)

        for candidate in dict.fromkeys(candidates):
            proxies = {"http": candidate, "https": candidate}
            try:
                response = requests.get(f"{OKX_BASE}/api/v5/public/time", proxies=proxies,
                                        timeout=8)
                if response.status_code == 200:
                    self._proxies = proxies
                    self._progress(f"using proxy {candidate}")
                    return proxies
            except Exception:
                continue
        self._progress("no working proxy found, using direct connection")
        self._proxies = None
        return None

    def _fetch(self, path: str, params: dict[str, Any]) -> list[Any]:
        last_error: Exception | None = None
        proxies = self._resolve_proxies()
        for attempt in range(self._retries):
            try:
                kwargs: dict[str, Any] = {"params": params, "timeout": self._timeout}
                if proxies and not self._custom_get:
                    kwargs["proxies"] = proxies
                response = self._get(f"{OKX_BASE}{path}", **kwargs)
                response.raise_for_status()
                payload = response.json()
                code = payload.get("code")
                if code not in ("0", 0):
                    if str(code) in ("50011", "50013", "50026"):
                        wait = min(30.0, 5.0 * (attempt + 1)) + random.random()
                        self._progress(f"rate limited by OKX, sleeping {wait:.0f}s")
                        self._sleep(wait)
                        last_error = LiquidationCollectorError(f"OKX rate limit {code}")
                        continue
                    raise LiquidationCollectorError(
                        f"OKX error {payload.get('code')}: {payload.get('msg')}"
                    )
                return payload.get("data", []) or []
            except Exception as exc:  # noqa: BLE001 - retried below
                last_error = exc
                if attempt < self._retries - 1:
                    wait = min(20.0, 2.0 * (attempt + 1)) + random.random()
                    self._progress(f"network error, retry in {wait:.0f}s ({type(exc).__name__})")
                    self._sleep(wait)
        raise LiquidationCollectorError(f"request {path} failed: {last_error}")

    # ------------------------------------------------------------- helpers
    def contract_value(self) -> float:
        """Base currency per contract (BTC-USDT-SWAP = 0.01 BTC)."""
        if self._ct_val is not None:
            return self._ct_val
        path = self.user_data / "data" / "okx_instruments_SWAP.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for instrument in payload.get("data", []):
                if instrument.get("instId") == self.inst_id:
                    self._ct_val = float(instrument.get("ctVal") or 0.01)
                    return self._ct_val
        except Exception:
            pass
        self._ct_val = 0.01
        return self._ct_val

    def _append_jsonl(self, path: Path, rows: Iterable[dict[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        return len(rows)

    def _load_state(self) -> None:
        """Rebuild the dedupe set and cursors from what is already on disk."""
        if self.raw_path.exists():
            tail: list[str] = []
            with self.raw_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    tail.append(line)
                    if len(tail) > 4000:
                        tail.pop(0)
            for line in tail:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._seen[str(row.get("key"))] = None
                self._last_liq_ts = max(self._last_liq_ts, int(row.get("ts", 0)))
        for path, attr in ((self.oi_path, "_last_oi_ts"), (self.taker_path, "_last_taker_ts")):
            if not path.exists():
                continue
            latest = 0
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        latest = max(latest, int(json.loads(line).get("ts", 0)))
                    except json.JSONDecodeError:
                        continue
            setattr(self, attr, latest)

    # ---------------------------------------------------------- collectors
    def _base_params(self) -> dict[str, Any]:
        return {
            "instType": "SWAP",
            "uly": f"{self.ccy}-USDT",
            "state": "filled",
            "limit": "100",
        }

    def _parse_liquidation_page(self, payload: list[Any]) -> list[dict[str, Any]]:
        ct_val = self.contract_value()
        page: list[dict[str, Any]] = []
        for item in payload:
            for detail in item.get("details", []) or []:
                try:
                    ts = int(detail.get("ts"))
                    size = float(detail.get("sz"))
                    price = float(detail.get("bkPx"))
                except (TypeError, ValueError):
                    continue
                key = f"{item.get('instId')}|{ts}|{detail.get('posSide')}|{size}|{price}"
                page.append(
                    {
                        "ts": ts,
                        "key": key,
                        "instId": item.get("instId"),
                        "pos_side": str(detail.get("posSide", "")).lower(),
                        "order_side": str(detail.get("side", "")).lower(),
                        "contracts": size,
                        "qty": size * ct_val,
                        "price": price,
                        "notional": size * ct_val * price,
                        "source": "okx",
                    }
                )
        return page

    def _keep_fresh(self, page: list[dict[str, Any]], since: int) -> list[dict[str, Any]]:
        fresh: list[dict[str, Any]] = []
        for row in page:
            if row["ts"] > since and row["key"] not in self._seen:
                self._seen[row["key"]] = None
                fresh.append(row)
        while len(self._seen) > 20_000:
            self._seen.popitem(last=False)
        return fresh

    def collect_liquidations(self) -> list[dict[str, Any]]:
        """Fetch every liquidation order published since the last poll.

        OKX pagination (verified live): ``before=<ts>`` returns records *newer*
        than ts, ``after=<ts>`` returns records *older* than ts. So the
        incremental poll asks for ``before=cursor``, and if that page comes back
        full we walk backwards with ``after`` until the page's oldest record
        reaches the cursor - otherwise a burst of >100 liquidations between two
        polls would silently drop the middle of the burst.
        """
        since = self._last_liq_ts
        records: list[dict[str, Any]] = []

        params = self._base_params()
        if since:
            params["before"] = str(since)
        page = self._parse_liquidation_page(
            self._fetch("/api/v5/public/liquidation-orders", params)
        )
        records.extend(self._keep_fresh(page, since))

        pages = 0
        max_catchup = self.catchup_pages if since else self.backfill_pages
        while page and len(page) >= 100 and pages < max_catchup:
            oldest = min(row["ts"] for row in page)
            if since and oldest <= since:
                break
            older_params = self._base_params()
            older_params["after"] = str(oldest)
            page = self._parse_liquidation_page(
                self._fetch("/api/v5/public/liquidation-orders", older_params)
            )
            pages += 1
            records.extend(self._keep_fresh(page, since))
            self._sleep(0.25)
        if records:
            self._last_liq_ts = max(self._last_liq_ts, max(row["ts"] for row in records))
        return sorted(records, key=lambda row: row["ts"])

    def collect_oi(self) -> list[dict[str, Any]]:
        payload = self._fetch(
            "/api/v5/rubik/stat/contracts/open-interest-volume",
            {"ccy": self.ccy, "period": "5m"},
        )
        rows = []
        for item in payload:
            try:
                ts = int(item[0])
                rows.append(
                    {
                        "ts": ts,
                        "oi_notional": float(item[1]),
                        "oi": float(item[2]),
                        "source": "okx-rubik",
                    }
                )
            except (TypeError, ValueError, IndexError):
                continue
        fresh = [row for row in rows if row["ts"] > self._last_oi_ts]
        if fresh:
            self._last_oi_ts = max(row["ts"] for row in fresh)
        return sorted(fresh, key=lambda row: row["ts"])

    def collect_taker(self) -> list[dict[str, Any]]:
        payload = self._fetch(
            "/api/v5/rubik/stat/taker-volume",
            {"ccy": self.ccy, "instType": "CONTRACTS", "period": "5m"},
        )
        rows = []
        for item in payload:
            try:
                ts = int(item[0])
                rows.append(
                    {
                        "ts": ts,
                        "taker_sell_usd": float(item[1]),
                        "taker_buy_usd": float(item[2]),
                        "source": "okx-rubik",
                    }
                )
            except (TypeError, ValueError, IndexError):
                continue
        fresh = [row for row in rows if row["ts"] > self._last_taker_ts]
        if fresh:
            self._last_taker_ts = max(row["ts"] for row in fresh)
        return sorted(fresh, key=lambda row: row["ts"])

    # --------------------------------------------------------------- loop
    def collect_once(self, *, derivatives: bool = True) -> dict[str, Any]:
        # Always rebuild cursors/dedupe state first: `--once` may be run from a
        # scheduler, and without this the same rows would be appended twice.
        self._load_state()
        summary: dict[str, Any] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "liquidations": 0,
            "oi": 0,
            "taker": 0,
            "liq_notional_usd": 0.0,
        }
        liquidations = self.collect_liquidations()
        if liquidations:
            self._append_jsonl(self.raw_path, liquidations)
            summary["liquidations"] = len(liquidations)
            summary["liq_notional_usd"] = round(
                sum(row["notional"] for row in liquidations), 2
            )
        if derivatives:
            oi = self.collect_oi()
            if oi:
                self._append_jsonl(self.oi_path, oi)
                summary["oi"] = len(oi)
            taker = self.collect_taker()
            if taker:
                self._append_jsonl(self.taker_path, taker)
                summary["taker"] = len(taker)
        return summary

    def compact(self) -> dict[str, int]:
        """Rewrite the JSONL files without duplicate rows (safe while stopped)."""
        removed: dict[str, int] = {}
        for label, path, key in (
            ("liquidations", self.raw_path, "key"),
            ("oi", self.oi_path, "ts"),
            ("taker", self.taker_path, "ts"),
        ):
            if not path.exists():
                removed[label] = 0
                continue
            seen: set[str] = set()
            kept: list[str] = []
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    marker = str(row.get(key))
                    if marker in seen:
                        continue
                    seen.add(marker)
                    kept.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            removed[label] = 0
            with path.open("r", encoding="utf-8") as handle:
                removed[label] = max(0, sum(1 for _ in handle) - len(kept))
            path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        self._seen.clear()
        self._last_liq_ts = 0
        self._last_oi_ts = 0
        self._last_taker_ts = 0
        self._load_state()
        return removed

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        self._load_state()
        self._progress(
            f"collector started for {self.pair} (ctVal={self.contract_value()}); "
            f"cursor ts={self._last_liq_ts}"
        )
        iterations = 0
        last_derivatives = 0.0
        while True:
            started = time.time()
            try:
                derivatives_due = (started - last_derivatives) >= self.derivatives_seconds
                summary = self.collect_once(derivatives=derivatives_due)
                if derivatives_due:
                    last_derivatives = started
                if summary["liquidations"] or summary["oi"] or summary["taker"]:
                    self._progress(
                        f"{summary['time']} +{summary['liquidations']} liq "
                        f"(${summary['liq_notional_usd']:,.0f}) "
                        f"+{summary['oi']} oi +{summary['taker']} taker"
                    )
            except Exception as exc:  # keep the collector alive across hiccups
                self._progress(f"collect failed: {type(exc).__name__}: {exc}")
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            elapsed = time.time() - started
            self._sleep(max(1.0, self.poll_seconds - elapsed))

    # ------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {"pair": self.pair, "files": {}}
        for label, path in (("liquidations", self.raw_path), ("oi", self.oi_path),
                            ("taker", self.taker_path)):
            if not path.exists():
                report["files"][label] = {"path": str(path), "rows": 0}
                continue
            rows = 0
            first = last = None
            notional = 0.0
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = int(row.get("ts", 0))
                    rows += 1
                    first = ts if first is None else min(first, ts)
                    last = ts if last is None else max(last, ts)
                    notional += float(row.get("notional", 0.0))
            entry: dict[str, Any] = {
                "path": str(path),
                "rows": rows,
                "first": _iso(first),
                "last": _iso(last),
                "days": round((last - first) / 86_400_000, 2) if first and last else 0.0,
            }
            if label == "liquidations":
                entry["notional_usd"] = round(notional, 2)
            report["files"][label] = entry
        return report


def _iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------- aggregation
def aggregate_liquidations(
    path: str | Path,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    """Raw JSONL -> per-minute frame (``date``/``side``/``notional``) for the builder."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["date", "side", "notional"])
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = int(row.get("ts", 0))
            if start_ms and ts < start_ms:
                continue
            if end_ms and ts > end_ms:
                continue
            side = str(row.get("pos_side", "")).lower()
            if side not in ("long", "short"):
                # posSide is missing in some responses; fall back to order side
                side = "long" if str(row.get("order_side", "")).lower() == "sell" else "short"
            rows.append({"date": ts, "side": side, "notional": float(row.get("notional", 0.0))})
    if not rows:
        return pd.DataFrame(columns=["date", "side", "notional"])
    return pd.DataFrame(rows)


def read_jsonl_frame(path: str | Path) -> pd.DataFrame:
    """Generic JSONL -> DataFrame (used for the OI / taker streams)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).drop_duplicates(subset=["ts"], keep="last")
    return frame.sort_values("ts").reset_index(drop=True)
