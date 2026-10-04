"""Factor-research data layer: universe selection, data download, panel building.

Implements tickets 01 and 02 of ``.scratch/factor-screening``:

* ``build_universe``  - classify OKX SWAP instruments into research pools from the
  live instrument/ticker snapshot (crypto majors, tokenized-equity perps, commodities).
* ``download_universe`` - fetch candles/mark/index/funding through the existing
  :class:`~app.services.public_data.PublicDataDownloader` (freqtrade file layout).
* ``build_panel`` - align everything into one long panel ``ts x pair x field`` with
  strict causality (funding/index merged with a backward as-of join).

Nothing here talks to OKX at factor-evaluation time; the panel is a local artifact
so research is reproducible offline (same principle as ADR-0001).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import requests

from .public_data import PublicDataDownloader

OKX_BASE = "https://www.okx.com"
FACTOR_DIR = "factors"

# Category codes observed on OKX SWAP instruments (2026-09-25):
#   1 = crypto, 3 = tokenized equities/ETFs/pre-IPO, 4 = commodities & indices.
CAT_CRYPTO = "1"
CAT_EQUITY = "3"
CAT_COMMODITY = "4"

_PROXY_CANDIDATES = ("http://127.0.0.1:17891",)


class FactorDataError(Exception):
    pass


# --------------------------------------------------------------------- http

def _proxies() -> dict[str, str] | None:
    """Return a working proxy mapping, or None for a direct connection."""
    candidates: list[str] = []
    for key in ("FTDESK_HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY",
                "http_proxy", "ALL_PROXY", "all_proxy"):
        import os

        value = os.environ.get(key)
        if value:
            candidates.append(value)
    try:
        proxies_map = urllib.request.getproxies()
        for key in ("https", "http"):
            if proxies_map.get(key):
                candidates.append(proxies_map[key])
    except Exception:  # pragma: no cover - platform dependent
        pass
    candidates.extend(_PROXY_CANDIDATES)

    for candidate in dict.fromkeys(candidates):
        mapping = {"http": candidate, "https": candidate}
        try:
            response = requests.get(f"{OKX_BASE}/api/v5/public/time", proxies=mapping, timeout=8)
            if response.status_code == 200:
                return mapping
        except Exception:
            continue
    return None


def _get_json(path: str, params: dict[str, Any] | None = None,
              http_get: Callable[..., Any] | None = None, retries: int = 4) -> Any:
    """GET an OKX public endpoint with direct-then-proxy fallback and retries."""
    last_error: Exception | None = None
    proxies = None if http_get is not None else _proxies()
    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {"params": params or {}, "timeout": 40}
            if proxies:
                kwargs["proxies"] = proxies
            getter = http_get or requests.get
            response = getter(f"{OKX_BASE}{path}", **kwargs)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in ("0", 0):
                raise FactorDataError(f"OKX error {payload.get('code')}: {payload.get('msg')}")
            return payload
        except Exception as exc:  # network hiccups / throttling
            last_error = exc
            if attempt < retries - 1:
                time.sleep(min(10.0, 1.5 * (attempt + 1)))
    raise FactorDataError(f"请求 {path} 失败：{last_error}")


def _snapshot(user_data: Path, name: str, path: str, params: dict[str, Any],
              max_age_seconds: float, http_get: Callable[..., Any] | None = None) -> list[dict]:
    """Read a cached OKX snapshot, refreshing it when older than ``max_age_seconds``."""
    target = Path(user_data) / "data" / f"okx_{name}.json"
    if target.exists() and time.time() - target.stat().st_mtime < max_age_seconds:
        try:
            return json.loads(target.read_text(encoding="utf-8")).get("data", [])
        except Exception:
            pass
    payload = _get_json(path, params, http_get=http_get)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return payload.get("data", [])


def fetch_instruments(user_data: Path, inst_type: str = "SWAP",
                      http_get: Callable[..., Any] | None = None) -> list[dict]:
    """Live instrument metadata (12h cache)."""
    return _snapshot(user_data, f"instruments_{inst_type}", "/api/v5/public/instruments",
                     {"instType": inst_type}, 12 * 3600, http_get=http_get)


def fetch_tickers(user_data: Path, inst_type: str = "SWAP",
                  http_get: Callable[..., Any] | None = None) -> list[dict]:
    """Live ticker snapshot used as the liquidity proxy (1h cache)."""
    return _snapshot(user_data, f"tickers_{inst_type}", "/api/v5/market/tickers",
                     {"instType": inst_type}, 3600, http_get=http_get)


# ---------------------------------------------------------------- universe

def to_pair(inst_id: str) -> str:
    """``TSLA-USDT-SWAP`` -> ``TSLA/USDT:USDT`` (freqtrade futures pair)."""
    parts = inst_id.split("-")
    if len(parts) != 3:
        raise FactorDataError(f"无法解析合约 id：{inst_id}")
    base, quote, _ = parts
    return f"{base}/{quote}:{quote}"


def pair_symbol(pair: str) -> str:
    """``TSLA/USDT:USDT`` -> ``TSLA_USDT_USDT`` (freqtrade file-name symbol)."""
    return pair.replace("/", "_").replace(":", "_")


def notional_usd(ticker: dict[str, Any]) -> float:
    """24h traded notional in USDT (``volCcy24h`` is denominated in the contract base)."""
    try:
        return float(ticker.get("volCcy24h") or 0.0) * float(ticker.get("last") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _days_listed(list_time: str | int, now_ms: int | None = None) -> float:
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    try:
        return max(0.0, (now - int(list_time)) / 86_400_000)
    except (TypeError, ValueError):
        return 0.0


def _pool_entry(inst: dict, ticker: dict, now_ms: int) -> dict:
    return {
        "instId": inst["instId"],
        "pair": to_pair(inst["instId"]),
        "name": inst["instId"].split("-")[0],
        "listTime": int(inst["listTime"]),
        "days_listed": round(_days_listed(inst["listTime"], now_ms), 1),
        "adv_usd": round(notional_usd(ticker)),
        "lever": inst.get("lever", ""),
        "tickSz": inst.get("tickSz", ""),
        "instCategory": inst.get("instCategory", ""),
    }


def build_universe(
    user_data: Path,
    *,
    crypto_min_days: float = 730,
    crypto_min_adv: float = 2e7,
    equity_min_days: float = 90,
    equity_min_adv: float = 5e6,
    max_per_pool: int = 30,
    now_ms: int | None = None,
    http_get: Callable[..., Any] | None = None,
) -> dict:
    """Classify OKX USDT perpetuals into research pools.

    Pools follow ``.scratch/factor-screening/spec.md`` section 5. Selection only uses
    information observable today (listing age + trailing 24h notional), so re-running
    this later cannot introduce look-ahead into the research pool itself.
    """
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    instruments = [i for i in fetch_instruments(user_data, "SWAP", http_get)
                   if i.get("state") == "live" and i.get("settleCcy") == "USDT"]
    tickers = {t["instId"]: t for t in fetch_tickers(user_data, "SWAP", http_get)}

    pools: dict[str, list[dict]] = {
        "crypto_majors": [], "equity_liquid": [], "commodity_index": [], "preipo_watch": [],
    }
    excluded: list[dict] = []
    for inst in instruments:
        ticker = tickers.get(inst["instId"])
        if not ticker:
            continue
        entry = _pool_entry(inst, ticker, now)
        category = inst.get("instCategory")
        if category == CAT_CRYPTO:
            if entry["days_listed"] >= crypto_min_days and entry["adv_usd"] >= crypto_min_adv:
                pools["crypto_majors"].append(entry)
            else:
                excluded.append({**entry, "reason": "crypto: 历史或流动性不足"})
        elif category == CAT_EQUITY:
            if entry["days_listed"] >= equity_min_days and entry["adv_usd"] >= equity_min_adv:
                pools["equity_liquid"].append(entry)
            else:
                excluded.append({**entry, "reason": "equity: 历史或流动性不足"})
        elif category == CAT_COMMODITY:
            pools["commodity_index"].append(entry)

    for name in pools:
        pools[name] = sorted(pools[name], key=lambda e: -e["adv_usd"])[:max_per_pool]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "filters": {
            "crypto_min_days": crypto_min_days, "crypto_min_adv": crypto_min_adv,
            "equity_min_days": equity_min_days, "equity_min_adv": equity_min_adv,
            "max_per_pool": max_per_pool,
        },
        "pools": pools,
        "excluded_count": len(excluded),
    }


def universe_path(user_data: Path) -> Path:
    return Path(user_data) / FACTOR_DIR / "universes.json"


def save_universe(config: dict, user_data: Path) -> Path:
    target = universe_path(user_data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_universe(user_data: Path) -> dict:
    target = universe_path(user_data)
    if not target.exists():
        raise FactorDataError(f"标的池配置不存在：{target}，先运行 factor_research universe")
    return json.loads(target.read_text(encoding="utf-8"))


def pool_pairs(config: dict, pool: str) -> list[str]:
    return [entry["pair"] for entry in config["pools"].get(pool, [])]


# --------------------------------------------------------------- download

def download_pool(
    user_data: Path,
    pairs: Iterable[str],
    *,
    timeframes: tuple[str, ...] = ("1h", "1d"),
    timerange: str | None = None,
    candle_types: tuple[str, ...] = ("futures", "funding_rate"),
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Download a pool's market data into the freqtrade layout."""
    from ..schemas import DownloadParams

    params = DownloadParams(
        exchange="okx",
        pairs=list(pairs),
        timeframes=list(timeframes),
        timerange=timerange,
        trading_mode="futures",
        candle_types=list(candle_types),
    )
    downloader = PublicDataDownloader(Path(user_data), progress=progress)
    return downloader.download(params)


# ------------------------------------------------------------- local files

def candle_path(user_data: Path, pair: str, timeframe: str, kind: str = "futures") -> Path:
    symbol = pair_symbol(pair)
    suffix = {"futures": "-futures", "mark": "-mark", "index": "-index"}.get(kind, "")
    return Path(user_data) / "data" / "okx" / "futures" / f"{symbol}-{timeframe}{suffix}.json.gz"


def funding_path(user_data: Path, pair: str, timeframe: str = "8h") -> Path:
    return (Path(user_data) / "data" / "okx" / "futures"
            / f"{pair_symbol(pair)}-{timeframe}-funding_rate.json.gz")


def contract_values(user_data: Path, inst_type: str = "SWAP") -> dict[str, float]:
    """``ctVal`` per pair from the cached instrument snapshot.

    OKX candle ``volume`` is denominated in **contracts**, and a contract is worth
    ``ctVal`` units of the base (0.01 BTC for ``BTC-USDT-SWAP``, 1 share for equity
    perps). Without this conversion, dollar-volume factors are contaminated by a
    per-pair constant and the capacity estimate is wrong by that factor.
    """
    path = Path(user_data) / "data" / f"okx_instruments_{inst_type}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    values: dict[str, float] = {}
    for item in payload.get("data", []):
        try:
            values[to_pair(item["instId"])] = float(item.get("ctVal") or 1.0)
        except (KeyError, TypeError, ValueError, FactorDataError):
            continue
    return values


def _read_rows(path: Path) -> list[list[float]]:
    import gzip

    if not path.exists():
        return []
    try:
        return json.loads(gzip.decompress(path.read_bytes()).decode())
    except Exception as exc:  # pragma: no cover - corrupt download
        raise FactorDataError(f"无法读取 {path}: {exc}") from exc


def load_candles(user_data: Path, pair: str, timeframe: str, kind: str = "futures") -> pd.DataFrame:
    """Load a local candle file as ``ts/open/high/low/close/volume`` (ts = epoch ms UTC)."""
    rows = _read_rows(candle_path(user_data, pair, timeframe, kind))
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    frame = _normalize_candle_rows(rows)
    if frame.empty:
        return frame
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["ts"]).astype({"ts": "int64"}).sort_values("ts").reset_index(drop=True)


def _normalize_candle_rows(rows: list[list[float]]) -> pd.DataFrame:
    """Accept ``[ts, o, h, l, c, v]`` and shorter ``[ts, close]`` rows alike."""
    normalized: list[list[float | None]] = []
    for row in rows:
        values = list(row)
        if len(values) >= 6:
            normalized.append(values[:6])
        elif len(values) == 2:  # index/mark candles: [ts, close]
            ts, close = values
            normalized.append([ts, close, close, close, close, 0.0])
        else:  # pad defensively rather than guessing
            normalized.append(values + [None] * (6 - len(values)))
    frame = pd.DataFrame(normalized, columns=["ts", "open", "high", "low", "close", "volume"])
    return frame


def load_funding(user_data: Path, pair: str) -> pd.DataFrame:
    """Load the funding-rate series as ``ts/funding_rate`` (settlement timestamps)."""
    rows = _read_rows(funding_path(user_data, pair))
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["ts", "funding_rate"])
    frame = frame.iloc[:, :2]
    frame.columns = ["ts", "funding_rate"]
    frame["ts"] = pd.to_numeric(frame["ts"], errors="coerce")
    frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
    return frame.dropna(subset=["ts"]).astype({"ts": "int64"}).sort_values("ts").reset_index(drop=True)


def build_panel(
    user_data: Path,
    pairs: Iterable[str],
    timeframe: str = "1h",
    *,
    with_index: bool = True,
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    """Build the long research panel for one pool.

    Causality rules:
      * candle fields are as-of their own bar timestamp;
      * ``funding_rate`` is the last settlement at or before the bar (backward as-of);
      * ``index_close`` is the last index close at or before the bar (backward as-of).
    """
    say = progress or (lambda _m: None)
    frames: list[pd.DataFrame] = []
    contract_sizes = contract_values(user_data)
    for pair in pairs:
        candles = load_candles(user_data, pair, timeframe, "futures")
        if candles.empty:
            say(f"{pair}: 无 {timeframe} K 线，跳过")
            continue
        frame = candles.copy()
        frame["volume"] = frame["volume"] * contract_sizes.get(pair, 1.0)
        funding = load_funding(user_data, pair)
        if not funding.empty:
            frame = pd.merge_asof(frame, funding, on="ts", direction="backward")
            settlements = set(int(value) for value in funding["ts"])
            frame["funding_settled"] = frame["ts"].isin(settlements).astype("int8")
        else:
            frame["funding_rate"] = float("nan")
            frame["funding_settled"] = 0
        if with_index:
            index = load_candles(user_data, pair, timeframe, "index")
            if not index.empty:
                index = index[["ts", "close"]].rename(columns={"close": "index_close"})
                frame = pd.merge_asof(frame, index, on="ts", direction="backward")
            else:
                frame["index_close"] = float("nan")
        frame["pair"] = pair
        frames.append(frame)
        say(f"{pair}: {len(frame)} 行")
    if not frames:
        raise FactorDataError("面板为空：没有任何可用的本地 K 线文件")
    panel = pd.concat(frames, ignore_index=True)
    panel["dt"] = pd.to_datetime(panel["ts"], unit="ms", utc=True)
    panel["hour"] = panel["dt"].dt.hour.astype("int16")
    panel["dow"] = panel["dt"].dt.dayofweek.astype("int8")
    columns = ["ts", "dt", "pair", "open", "high", "low", "close", "volume",
               "funding_rate", "funding_settled", "index_close", "hour", "dow"]
    return panel[columns].sort_values(["pair", "ts"]).reset_index(drop=True)


def panel_path(user_data: Path, universe: str, timeframe: str) -> Path:
    return Path(user_data) / FACTOR_DIR / universe / f"panel-{timeframe}.parquet"


def write_panel(panel: pd.DataFrame, user_data: Path, universe: str, timeframe: str) -> Path:
    target = panel_path(user_data, universe, timeframe)
    target.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(target, index=False)
    return target


def read_panel(user_data: Path, universe: str, timeframe: str) -> pd.DataFrame:
    target = panel_path(user_data, universe, timeframe)
    if not target.exists():
        raise FactorDataError(f"面板不存在：{target}")
    return pd.read_parquet(target)


def pivot(panel: pd.DataFrame, field: str) -> pd.DataFrame:
    """Long panel -> wide matrix ``ts x pair`` (the working shape of factor code)."""
    return panel.pivot_table(index="ts", columns="pair", values=field, aggfunc="last").sort_index()
