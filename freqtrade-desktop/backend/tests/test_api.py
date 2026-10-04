from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_run_timerange_ms_month_end() -> None:
    from app.routers.api import _run_timerange_ms

    start, end = _run_timerange_ms("20250101-20251231")
    assert start == 1735689600000
    assert end == 1767225600000


def test_score_weights_roundtrip() -> None:
    with TestClient(app) as client:
        weights = {
            "sharpe": 0.3,
            "sortino": 0.2,
            "calmar": 0.05,
            "profit_factor": 0.15,
            "winrate": 0.05,
            "max_drawdown": 0.15,
            "expectancy": 0.1,
        }
        put = client.put("/api/score/weights", json=weights)
        assert put.status_code == 200
        got = client.get("/api/score/weights").json()
        assert got["sharpe"] == 0.3


def test_invalid_weights_rejected() -> None:
    with TestClient(app) as client:
        resp = client.put("/api/score/weights", json={"sharpe": 1.0})
        assert resp.status_code == 422


def test_settings_status_reports_freqtrade_availability() -> None:
    with TestClient(app) as client:
        data = client.get("/api/settings/status").json()
        assert "freqtrade_available" in data
        assert "user_data" in data


def test_build_config_writes_file(monkeypatch, tmp_path) -> None:
    # build-config resolves the data root at request time (DB setting or default),
    # so patch that resolver for the test instead of the static settings field.
    from app.routers import api as api_module

    monkeypatch.setattr(api_module, "current_user_data", lambda: tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/settings/build-config",
            json={
                "exchange": "okx",
                "trading_mode": "futures",
                "dry_run": True,
                "pairs": ["BTC/USDT:USDT"],
                "telegram_token": "123:abc",
                "telegram_chat_id": "42",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
    config_file = tmp_path / "config.json"
    assert config_file.exists()
    import json

    content = json.loads(config_file.read_text(encoding="utf-8"))
    assert content["exchange"]["name"] == "okx"
    assert content["trading_mode"] == "futures"
    assert content["telegram"]["enabled"] is True
    assert content["api_server"]["listen_ip_address"] == "127.0.0.1"
