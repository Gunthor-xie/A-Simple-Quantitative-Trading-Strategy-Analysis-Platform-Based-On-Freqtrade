from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from app.services.binance_archive import (
    BinanceArchive,
    BinanceArchiveError,
    archive_path,
    days_between,
    parse_csv_bytes,
    to_binance_symbol,
    to_freqtrade_pair,
)


def test_symbol_mapping() -> None:
    assert to_binance_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert to_binance_symbol("ETHUSDT") == "ETHUSDT"
    assert to_freqtrade_pair("BTCUSDT") == "BTC/USDT:USDT"
    with pytest.raises(BinanceArchiveError):
        to_freqtrade_pair("BTC")


def test_archive_path_layout() -> None:
    daily = archive_path("klines", "BTCUSDT", stamp="2025-09-01")
    assert daily == "data/futures/um/daily/klines/BTCUSDT/BTCUSDT-1m-2025-09-01.zip"
    monthly = archive_path("fundingRate", "BTCUSDT", period="monthly", stamp="2025-09")
    assert monthly == "data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-09.zip"
    with pytest.raises(BinanceArchiveError):
        archive_path("liquidationSnapshot", "BTCUSDT", stamp="2025-09-01")


def test_days_between_is_inclusive() -> None:
    days = days_between(date(2025, 9, 1), date(2025, 9, 3))
    assert [day.isoformat() for day in days] == ["2025-09-01", "2025-09-02", "2025-09-03"]
    with pytest.raises(BinanceArchiveError):
        days_between(date(2025, 9, 3), date(2025, 9, 1))


def test_parse_csv_accepts_headered_and_headerless() -> None:
    headered = b"timestamp,percentage,depth,notional\n2025-09-01 00:00:07,-1,10,100\n"
    frame = parse_csv_bytes(headered, "bookDepth")
    assert list(frame.columns) == ["timestamp", "percentage", "depth", "notional"]
    assert frame["notional"].iloc[0] == 100

    headerless = b"2025-09-01 00:00:07,-1,10,100\n"
    frame = parse_csv_bytes(headerless, "bookDepth")
    assert list(frame.columns) == ["timestamp", "percentage", "depth", "notional"]
    assert frame["depth"].iloc[0] == 10


def _zip_bytes(name: str, payload: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(name, payload)
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


def test_fetch_day_caches_and_parses(tmp_path) -> None:
    payload = _zip_bytes(
        "BTCUSDT-metrics-2025-09-01.csv",
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        "2025-09-01 00:00:00,BTCUSDT,100,1000,1,1,1,0.5\n",
    )
    calls: list[str] = []

    def fake_get(url, timeout=None):
        calls.append(url)
        return _FakeResponse(payload)

    archive = BinanceArchive(tmp_path, http_get=fake_get, sleep=lambda _s: None)
    frame = archive.load("metrics", "BTCUSDT", day=date(2025, 9, 1))
    assert len(frame) == 1 and calls == [
        "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2025-09-01.zip"
    ]
    # Second call is served from the on-disk cache.
    archive.load("metrics", "BTCUSDT", day=date(2025, 9, 1))
    assert len(calls) == 1


def test_fetch_reports_failure(tmp_path) -> None:
    def failing_get(url, timeout=None):
        raise OSError("no route to host")

    archive = BinanceArchive(tmp_path, http_get=failing_get, sleep=lambda _s: None, retries=2)
    with pytest.raises(BinanceArchiveError):
        archive.fetch_day("klines", "BTCUSDT", date(2025, 9, 1))
    assert not list(tmp_path.rglob("*.zip"))
