from __future__ import annotations

import gzip
import json

from app.schemas import DownloadParams
from app.services.coverage import scan
from app.services.public_data import (
    PublicDataDownloader,
    network_diagnostics,
    parse_timerange,
    to_futures_symbol,
    to_instrument,
)


def test_instrument_mapping() -> None:
    assert to_instrument("BTC/USDT", "spot") == "BTC-USDT"
    assert to_instrument("BTC/USDT:USDT", "futures") == "BTC-USDT-SWAP"
    assert to_instrument("BTC/USDT", "futures") == "BTC-USDT-SWAP"
    assert to_futures_symbol("BTC/USDT") == "BTC/USDT:USDT"


def test_downloader_bypasses_environment_proxy(tmp_path) -> None:
    downloader = PublicDataDownloader(tmp_path)
    assert downloader._session.trust_env is False


def test_funding_file_name_keeps_kind_suffix(tmp_path) -> None:
    downloader = PublicDataDownloader(tmp_path)
    path = downloader._pair_file("okx", "BTC/USDT:USDT", "8h", "futures", "funding_rate")
    assert path.name == "BTC_USDT_USDT-8h-funding_rate.json.gz"
    assert path.parent.name == "futures"


def test_parse_timerange() -> None:
    start, end = parse_timerange("20260101-20260102")
    assert start == 1767225600000  # 2026-01-01 00:00 UTC
    assert end > start
    default_start, _ = parse_timerange(None)
    assert default_start == 0


def test_download_writes_freqtrade_jsongz(tmp_path) -> None:
    calls: list[dict] = []
    base_ts = 1767225600000

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {})})
        if len([c for c in calls if c["url"] == url]) == 1:
            return FakeResponse({
                "code": "0",
                "data": [
                    [base_ts + 900000, 2, 3, 1.5, 2.5, 20],
                    [base_ts, 1, 2, 0.5, 1.5, 10],
                ],
            })
        return FakeResponse({"code": "0", "data": []})

    downloader = PublicDataDownloader(tmp_path, http_get=fake_get, sleep=lambda _s: None)
    result = downloader.download(
        DownloadParams(
            exchange="okx",
            pairs=["BTC/USDT"],
            timeframes=["15m"],
            timerange="20260101-20260102",
            trading_mode="spot",
            candle_types=["spot"],
        )
    )
    assert result["total_files"] == 1
    path = tmp_path / "data" / "okx" / "BTC_USDT-15m.json.gz"
    assert path.exists()
    rows = json.load(gzip.open(path, "rt"))
    assert [r[0] for r in rows] == [base_ts, base_ts + 900000]
    assert calls[0]["params"]["bar"] == "15m"
    inventory = scan(tmp_path, write_file=False)
    assert inventory["okx"]["BTC_USDT"]["15m"]["spot"]["count"] == 2


def _fake_response(payload: dict):
    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    return _Resp()


def test_resume_merges_existing_file(tmp_path) -> None:
    target = tmp_path / "data" / "okx" / "BTC_USDT-15m.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    old_ts = 1767225600000
    target.write_bytes(gzip.compress(json.dumps([[old_ts, 1, 1, 1, 1, 1]]).encode()))
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_response({"code": "0", "data": [[old_ts + 900000, 2, 2, 2, 2, 2]]})
        return _fake_response({"code": "0", "data": []})

    downloader = PublicDataDownloader(tmp_path, http_get=fake_get, sleep=lambda _s: None)
    downloader.download(
        DownloadParams(pairs=["BTC/USDT"], timeframes=["15m"],
                       timerange="20260101-20260102", trading_mode="spot")
    )
    rows = json.load(gzip.open(target, "rt"))
    assert [r[0] for r in rows] == [old_ts, old_ts + 900000]


def test_partial_failure_keeps_other_files(tmp_path) -> None:
    calls: list[dict] = []
    window_start = 1767225600000  # 2026-01-01 00:00 UTC

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {})})
        if "funding-rate-history" in url:
            raise RuntimeError("connect timeout")
        # OKX pages *backwards* from `after`; the downloader starts at the
        # requested window end instead of walking back from "now".
        after = int((params or {}).get("after") or window_start + 10_000_000)
        if after <= window_start:
            return _fake_response({"code": "0", "data": []})
        return _fake_response({"code": "0", "data": [[window_start, 1, 2, 0.5, 1.5, 5]]})

    downloader = PublicDataDownloader(tmp_path, http_get=fake_get, sleep=lambda _s: None, retries=2)
    result = downloader.download(
        DownloadParams(pairs=["ETH/USDT:USDT"], timeframes=["15m"],
                       timerange="20260101-20260102", trading_mode="futures",
                       candle_types=["futures", "funding_rate"])
    )
    assert result["total_files"] == 1
    assert result["errors"] and result["errors"][0]["kind"] == "funding_rate"
    candle_calls = [c for c in calls if "candles" in c["url"]]
    # 2026-01-02 23:59:59 UTC - the requested window end, not "now".
    assert candle_calls[0]["params"]["after"] == "1767398399000"


def test_network_diagnostics_prefers_working_proxy(monkeypatch) -> None:
    import app.services.public_data as pd

    class _Resp:
        status_code = 200

    def fake_get(url, proxies=None, timeout=None):
        if proxies and proxies.get("https") == "http://127.0.0.1:17891":
            return _Resp()
        raise RuntimeError("direct blocked")

    monkeypatch.setattr(pd.requests, "get", fake_get)
    monkeypatch.setattr(pd.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("1.2.3.4", 443))])

    class _Sock:
        def settimeout(self, _t): return None
        def connect(self, _addr): raise TimeoutError("blocked")
        def close(self): return None

    monkeypatch.setattr(pd.socket, "socket", lambda *a, **k: _Sock())
    result = network_diagnostics()
    assert "127.0.0.1:17891" in result["conclusion"]
