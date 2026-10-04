from __future__ import annotations

import gzip
import json

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import BacktestResult
from app.services.chart_service import ChartService
from app.storage import db


def test_local_chart_route_exists_and_hints_on_missing_data() -> None:
    with TestClient(app) as client:
        ok = client.get(
            "/api/charts/local",
            params={
                "pair": "ETH/USDT:USDT",
                "timeframe": "5m",
                "trading_mode": "futures",
                "limit": 10,
            },
        )
        assert ok.status_code == 200
        payload = ok.json()
        assert len(payload["candles"]) == 10

        missing = client.get(
            "/api/charts/local",
            params={
                "pair": "NOPE/USDT",
                "timeframe": "15m",
                "trading_mode": "spot",
                "limit": 10,
            },
        )
        assert missing.status_code == 404
        assert "available local data" in missing.json()["detail"]


def test_load_candles_open_ended_timerange(tmp_path) -> None:
    rows = [
        [1735689600000, 100.0, 110.0, 90.0, 105.0, 10.0],
        [1735689690000, 105.0, 115.0, 100.0, 110.0, 20.0],
        [1735689780000, 110.0, 120.0, 105.0, 115.0, 30.0],
    ]
    file_path = (
        tmp_path / "data" / "okx" / "futures" / "BTC_USDT_USDT-15m-futures.json.gz"
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(file_path, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)

    service = ChartService(tmp_path, db)

    open_end = service.load_candles(
        "okx",
        "BTC/USDT:USDT",
        "15m",
        trading_mode="futures",
        timerange=(rows[1][0], None),
        full_range=True,
    )
    assert [candle.time for candle in open_end] == [1735689690, 1735689780]

    open_start = service.load_candles(
        "okx",
        "BTC/USDT:USDT",
        "15m",
        trading_mode="futures",
        timerange=(None, rows[1][0]),
        full_range=True,
    )
    assert [candle.time for candle in open_start] == [1735689600, 1735689690]


def test_overlay_line_color_follows_direction_not_pnl(tmp_path) -> None:
    result = BacktestResult(
        trades=[
            {
                "pair": "BTC/USDT:USDT",
                "is_short": False,
                "open_date": "2025-01-01 00:00:00",
                "close_date": "2025-01-01 01:00:00",
                "open_rate": 100.0,
                "close_rate": 90.0,
                "profit_abs": -10.0,
                "profit_ratio": -0.1,
            },
            {
                "pair": "BTC/USDT:USDT",
                "is_short": True,
                "open_date": "2025-01-02 00:00:00",
                "close_date": "2025-01-02 01:00:00",
                "open_rate": 100.0,
                "close_rate": 90.0,
                "profit_abs": 10.0,
                "profit_ratio": 0.1,
            },
        ]
    )
    service = ChartService(tmp_path, db)

    overlays = service.overlays_from_trades(result, "BTC/USDT:USDT")
    # connectors: long is green, short is red, independent of profit
    assert [overlay.color for overlay in overlays] == ["#26a69a", "#ef5350"]
    assert [overlay.pnl for overlay in overlays] == [-10.0, 10.0]

    markers = service.markers_from_trades(result, "BTC/USDT:USDT")
    exit_markers = [marker for marker in markers if marker.shape == "circle"]
    # profit numbers keep their pnl colour: loser red, winner green
    assert [marker.color for marker in exit_markers] == ["#ef5350", "#26a69a"]
