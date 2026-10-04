"""Binance USD-M futures public archive client (``data.binance.vision``).

Why this module exists
----------------------
The Freqtrade engine can only backtest on candles (``futures``/``mark``/
``index``/``funding_rate``). A liquidation-cascade strategy additionally needs
forced-liquidation flow, open interest, order-book depth and tick trades, and
none of those is a candle type.

Binance publishes daily/monthly archives for USD-M futures that cover most of
that need (URLs and schemas verified 2026-09-21):

    klines/{tf}          OHLCV (1m available)
    markPriceKlines/{tf} mark price OHLCV
    metrics/             OI, OI notional, taker long/short vol ratio (5m rows)
    bookDepth/           top-5 percentage-band depth, ~30s snapshots
    aggTrades/           tick aggregated trades (aggressor flagged)
    fundingRate/         funding rate history

There is **no** liquidation archive on that host: every
``.../liquidationSnapshot/...`` URL returns HTTP 404. Historical forced
liquidation flow therefore has to be approximated from the datasets above, or
bought from a vendor; live flow has to be collected from the exchange
websocket (see ``liquidation_collector.py``).

Downloads are cached on disk and never fetched twice. Tests inject ``http_get``
so nothing here needs the network.
"""

from __future__ import annotations

import io
import random
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests


BASE = "https://data.binance.vision"
DAILY = "daily"
MONTHLY = "monthly"

# dataset -> (path segment, file-name template)
DATASETS: dict[str, tuple[str, str]] = {
    "klines": ("klines", "{sym}-{interval}-{stamp}.zip"),
    "markPriceKlines": ("markPriceKlines", "{sym}-{interval}-{stamp}.zip"),
    "metrics": ("metrics", "{sym}-metrics-{stamp}.zip"),
    "bookDepth": ("bookDepth", "{sym}-bookDepth-{stamp}.zip"),
    "aggTrades": ("aggTrades", "{sym}-aggTrades-{stamp}.zip"),
    "fundingRate": ("fundingRate", "{sym}-fundingRate-{stamp}.zip"),
}

# Column names for the header-less variant. Binance started writing a header
# row into these CSVs in 2025, so both variants are handled.
CSV_COLUMNS: dict[str, list[str]] = {
    "klines": [
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume",
        "ignore",
    ],
    "markPriceKlines": [
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume",
        "ignore",
    ],
    "metrics": [
        "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
        "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
        "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
    ],
    "bookDepth": ["timestamp", "percentage", "depth", "notional"],
    "aggTrades": [
        "agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id",
        "transact_time", "is_buyer_maker",
    ],
    "fundingRate": ["calc_time", "funding_interval_hours", "last_funding_rate"],
}


class BinanceArchiveError(Exception):
    """Raised when an archive file cannot be fetched or parsed."""


def to_binance_symbol(pair: str) -> str:
    """``BTC/USDT:USDT`` -> ``BTCUSDT`` (also accepts an already-joined symbol)."""
    if "/" not in pair:
        return pair.upper()
    base, rest = pair.split("/", 1)
    quote = rest.split(":", 1)[0]
    return f"{base}{quote}".replace("-", "").upper()


def to_freqtrade_pair(symbol: str) -> str:
    """``BTCUSDT`` -> ``BTC/USDT:USDT`` for the USDⓈ-M perpetual."""
    upper = symbol.upper()
    for quote in ("USDT", "USDC", "BUSD", "FDUSD"):
        if upper.endswith(quote) and len(upper) > len(quote):
            base = upper[: -len(quote)]
            return f"{base}/{quote}:{quote}"
    raise BinanceArchiveError(f"cannot map symbol to a freqtrade pair: {symbol}")


def archive_path(
    dataset: str,
    symbol: str,
    *,
    period: str = DAILY,
    stamp: str,
    interval: str = "1m",
) -> str:
    """Relative archive path, e.g. ``data/futures/um/daily/metrics/BTCUSDT/...``."""
    if dataset not in DATASETS:
        raise BinanceArchiveError(f"unknown dataset: {dataset}")
    segment, template = DATASETS[dataset]
    if period not in (DAILY, MONTHLY):
        raise BinanceArchiveError(f"unknown period: {period}")
    name = template.format(sym=symbol, interval=interval, stamp=stamp)
    return f"data/futures/um/{period}/{segment}/{symbol}/{name}"


class BinanceArchive:
    """Fetch + parse Binance USD-M futures public archives, with a disk cache."""

    def __init__(
        self,
        cache_dir: str | Path,
        http_get: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] | None = None,
        progress: Callable[[str], None] | None = None,
        retries: int = 4,
        timeout: float = 180.0,
        pause: float = 0.25,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sleep = sleep or time.sleep
        self._progress = progress or (lambda _msg: None)
        self._retries = max(1, retries)
        self._timeout = timeout
        # Bulk downloads hit CDN throttling that shows up as spurious 404s, so
        # space requests out instead of hammering the host.
        self._pause = max(0.0, pause)

        # Same reasoning as PublicDataDownloader: ignore inherited env proxies
        # that are usually stale in this environment (WinError 10061).
        self._session = requests.Session()
        self._session.trust_env = False
        self._get = http_get or self._session.get

    # ---------------------------------------------------------------- fetch
    def url(
        self,
        dataset: str,
        symbol: str,
        *,
        period: str = DAILY,
        stamp: str,
        interval: str = "1m",
    ) -> str:
        return f"{BASE}/{archive_path(dataset, symbol, period=period, stamp=stamp, interval=interval)}"

    def fetch(
        self,
        dataset: str,
        symbol: str,
        *,
        day: date | None = None,
        month: str | None = None,
        interval: str = "1m",
    ) -> Path:
        """Download one archive file (cached) and return its local path."""
        if (day is None) == (month is None):
            raise BinanceArchiveError("pass exactly one of day / month")
        period = DAILY if day is not None else MONTHLY
        stamp = day.isoformat() if day is not None else str(month)
        rel = archive_path(dataset, symbol, period=period, stamp=stamp, interval=interval)
        dest = self.cache_dir / rel
        if dest.exists() and dest.stat().st_size > 0:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._download(f"{BASE}/{rel}", dest)
        return dest

    def fetch_day(
        self, dataset: str, symbol: str, day: date, *, interval: str = "1m"
    ) -> Path:
        return self.fetch(dataset, symbol, day=day, interval=interval)

    def fetch_month(
        self, dataset: str, symbol: str, month: str, *, interval: str = "1m"
    ) -> Path:
        return self.fetch(dataset, symbol, month=month, interval=interval)

    def _download(self, url: str, dest: Path) -> None:
        last_error: Exception | None = None
        for attempt in range(self._retries):
            try:
                response = self._get(url, timeout=self._timeout)
                response.raise_for_status()
                payload = response.content
                if not payload:
                    raise BinanceArchiveError(f"empty response for {url}")
                tmp = dest.with_suffix(dest.suffix + ".part")
                tmp.write_bytes(payload)
                tmp.replace(dest)
                self._progress(f"downloaded {dest.name} ({len(payload)} bytes)")
                if self._pause:
                    self._sleep(self._pause)
                return
            except Exception as exc:  # noqa: BLE001 - retried below
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                # The archive CDN answers 404 (not 429) once a client has been
                # pulling bulk data for a while; it clears after a short pause.
                wait = (
                    min(30.0, 10.0 * (attempt + 1)) + random.random() * 3
                    if status == 404
                    else min(15.0, 3.0 * (attempt + 1)) + random.random()
                )
                self._progress(
                    f"retry {attempt + 1}/{self._retries} for {url} in {wait:.0f}s: {exc}"
                )
                self._sleep(wait)
        raise BinanceArchiveError(f"failed to download {url}: {last_error}")

    # ----------------------------------------------------------------- read
    def read(self, path: str | Path, dataset: str) -> pd.DataFrame:
        """Parse a cached archive zip into a DataFrame (header-aware)."""
        path = Path(path)
        try:
            with zipfile.ZipFile(path) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not members:
                    raise BinanceArchiveError(f"no csv inside {path.name}")
                raw = zf.read(members[0])
        except zipfile.BadZipFile as exc:
            raise BinanceArchiveError(f"{path.name} is not a valid zip: {exc}") from exc
        return parse_csv_bytes(raw, dataset)

    def load(
        self,
        dataset: str,
        symbol: str,
        *,
        day: date | None = None,
        month: str | None = None,
        interval: str = "1m",
    ) -> pd.DataFrame:
        """Fetch (cached) + parse one archive file."""
        path = self.fetch(dataset, symbol, day=day, month=month, interval=interval)
        return self.read(path, dataset)


def parse_csv_bytes(raw: bytes, dataset: str) -> pd.DataFrame:
    """Parse archive CSV bytes, accepting both the headered and header-less form."""
    if dataset not in CSV_COLUMNS:
        raise BinanceArchiveError(f"unknown dataset: {dataset}")
    columns = CSV_COLUMNS[dataset]
    head = raw[:512].decode("utf-8", "replace").split("\n", 1)[0]
    headered = any(name in head for name in columns)
    frame = pd.read_csv(
        io.BytesIO(raw),
        header=0 if headered else None,
        names=None if headered else columns,
    )
    if not headered and len(frame.columns) != len(columns):
        raise BinanceArchiveError(
            f"{dataset}: expected {len(columns)} columns, got {len(frame.columns)}"
        )
    return frame


def days_between(start: date, end: date) -> list[date]:
    """Inclusive list of UTC dates."""
    if end < start:
        raise BinanceArchiveError("end date must not be before start date")
    span = (end - start).days
    return [date.fromordinal(start.toordinal() + i) for i in range(span + 1)]


def parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
