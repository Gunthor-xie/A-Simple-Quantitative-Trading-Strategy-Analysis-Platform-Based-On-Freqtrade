"""Offline tests for the OKX liquidation / OI / taker collector."""

from __future__ import annotations

import json

import pytest

from app.services.liquidation_collector import (
    LiquidationCollector,
    aggregate_liquidations,
    pair_slug,
    read_jsonl_frame,
    swap_inst_id,
)


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def liquidation_payload(rows: list[tuple[int, str, float, float]]) -> dict:
    """rows: (ts, posSide, size_in_contracts, bkPx) for BTC-USDT-SWAP."""
    return {
        "code": "0",
        "data": [
            {
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "uly": "BTC-USDT",
                "details": [
                    {
                        "bkPx": str(price),
                        "posSide": side,
                        "side": "buy" if side == "short" else "sell",
                        "sz": str(size),
                        "ts": str(ts),
                    }
                    for ts, side, size, price in rows
                ],
            }
        ],
    }


def make_collector(tmp_path, handler, **kwargs) -> LiquidationCollector:
    instrument_dir = tmp_path / "data"
    instrument_dir.mkdir(parents=True, exist_ok=True)
    (instrument_dir / "okx_instruments_SWAP.json").write_text(
        json.dumps({"data": [{"instId": "BTC-USDT-SWAP", "ctVal": "0.01"}]}),
        encoding="utf-8",
    )
    return LiquidationCollector(
        tmp_path, "BTC/USDT:USDT", http_get=handler, sleep=lambda _s: None, progress=lambda _m: None,
        **kwargs,
    )


def test_id_mapping() -> None:
    assert swap_inst_id("BTC/USDT:USDT") == "BTC-USDT-SWAP"
    assert pair_slug("BTC/USDT:USDT") == "BTC_USDT_USDT"


def test_collects_notional_and_dedupes(tmp_path) -> None:
    calls: list[dict] = []
    payload = liquidation_payload(
        [(1_789_957_987_538, "long", 0.64, 81_137.0),
         (1_789_957_740_911, "short", 23.34, 81_481.1)]
    )

    def handler(url, params=None, timeout=None):
        calls.append(dict(params or {}))
        return _Response(payload)

    collector = make_collector(tmp_path, handler)
    first = collector.collect_liquidations()
    assert len(first) == 2
    # 0.64 contracts x 0.01 BTC x 81,137 = 519.28 USD
    long_row = next(row for row in first if row["pos_side"] == "long")
    assert long_row["notional"] == pytest.approx(0.64 * 0.01 * 81_137.0)
    assert long_row["order_side"] == "sell"
    collector._append_jsonl(collector.raw_path, first)

    # Same payload again -> nothing new, and the cursor is now used as `before`.
    second = collector.collect_liquidations()
    assert second == []
    assert calls[-1]["before"] == "1789957987538"


def test_pagination_walks_back_to_the_cursor(tmp_path) -> None:
    # A full page (>= limit) forces the collector to keep walking back.
    page_new = liquidation_payload(
        [(ts, "short", 1.0, 80_000.0) for ts in range(30_000, 17_900, -100)]
    )
    page_old = liquidation_payload(
        [(ts, "long", 1.0, 79_000.0) for ts in range(17_900, 6_000, -100)]
    )
    state = {"calls": 0}

    def handler(url, params=None, timeout=None):
        state["calls"] += 1
        return _Response(page_new if state["calls"] == 1 else page_old)

    collector = make_collector(tmp_path, handler)
    collector._last_liq_ts = 10_000
    rows = collector.collect_liquidations()
    # Everything newer than the cursor is kept, older records are dropped.
    assert rows and min(row["ts"] for row in rows) > 10_000
    assert max(row["ts"] for row in rows) == 30_000
    assert state["calls"] >= 2


def test_collects_oi_and_taker(tmp_path) -> None:
    def handler(url, params=None, timeout=None):
        if "open-interest-volume" in url:
            return _Response({"code": "0", "data": [["1789954500000", "3153866296.5467", "81248763.0213"]]})
        if "taker-volume" in url:
            return _Response({"code": "0", "data": [["1789954500000", "5644768.3946", "19274765.7725"]]})
        return _Response(liquidation_payload([]))

    collector = make_collector(tmp_path, handler)
    oi = collector.collect_oi()
    assert oi[0]["oi_notional"] == pytest.approx(3_153_866_296.5467)
    assert oi[0]["oi"] == pytest.approx(81_248_763.0213)
    taker = collector.collect_taker()
    assert taker[0]["taker_sell_usd"] == pytest.approx(5_644_768.3946)
    assert taker[0]["taker_buy_usd"] == pytest.approx(19_274_765.7725)


def test_collect_once_writes_and_resumes(tmp_path) -> None:
    payload = liquidation_payload([(1_700_000_060_000, "long", 10.0, 50_000.0)])

    def handler(url, params=None, timeout=None):
        if "open-interest" in url:
            return _Response({"code": "0", "data": [["1700000400000", "1000.0", "20.0"]]})
        if "taker-volume" in url:
            return _Response({"code": "0", "data": [["1700000400000", "100.0", "200.0"]]})
        return _Response(payload)

    collector = make_collector(tmp_path, handler)
    summary = collector.collect_once()
    assert summary["liquidations"] == 1 and summary["oi"] == 1 and summary["taker"] == 1

    # A fresh collector rebuilds cursors from disk and does not duplicate rows.
    resumed = make_collector(tmp_path, handler)
    resumed._load_state()
    assert resumed._last_liq_ts == 1_700_000_060_000
    assert resumed.collect_once()["liquidations"] == 0
    assert resumed._append_jsonl(resumed.oi_path, resumed.collect_oi()) == 0


def test_status_reports_coverage(tmp_path) -> None:
    def handler(url, params=None, timeout=None):
        return _Response(liquidation_payload([(1_700_000_060_000, "long", 10.0, 50_000.0)]))

    collector = make_collector(tmp_path, handler)
    collector.collect_once(derivatives=False)
    report = collector.status()
    entry = report["files"]["liquidations"]
    assert entry["rows"] == 1
    assert entry["notional_usd"] == pytest.approx(10.0 * 0.01 * 50_000.0)
    assert entry["first"].startswith("2023-11-14")


def test_aggregate_liquidations_frame(tmp_path) -> None:
    path = tmp_path / "liq.jsonl"
    rows = [
        {"ts": 1_700_000_001_000, "pos_side": "long", "notional": 100.0},
        {"ts": 1_700_000_020_000, "pos_side": "long", "notional": 50.0},
        {"ts": 1_700_000_030_000, "pos_side": "short", "notional": 25.0},
        {"ts": 1_700_000_100_000, "pos_side": "long", "notional": 5.0},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    frame = aggregate_liquidations(path)
    assert len(frame) == 4
    assert set(frame["side"]) == {"long", "short"}
    windowed = aggregate_liquidations(path, 1_700_000_000_000, 1_700_000_059_999)
    assert len(windowed) == 3

    # Missing posSide falls back to the order side.
    fallback = tmp_path / "fallback.jsonl"
    fallback.write_text(json.dumps({"ts": 1, "order_side": "sell", "notional": 1.0}), encoding="utf-8")
    assert aggregate_liquidations(fallback)["side"].iloc[0] == "long"
    assert read_jsonl_frame(fallback).shape[0] == 1
