from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx

from app.services.okx_client import OkxClient, OkxError


def _client_with(handler, *, demo: bool = False) -> OkxClient:
    return OkxClient(
        "key", "secret", "pass", demo=demo, transport=httpx.MockTransport(handler)
    )


def test_sign_matches_okx_spec() -> None:
    client = _client_with(lambda r: httpx.Response(200, json={"code": "0", "data": []}))
    try:
        sig = client._sign("GET", "/api/v5/account/balance", "", "1700000000000")
    finally:
        client.close()
    expected = base64.b64encode(
        hmac.new(
            b"secret", b"1700000000000GET/api/v5/account/balance", hashlib.sha256
        ).digest()
    ).decode()
    assert sig == expected


def test_place_order_payload_and_demo_header() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.read().decode())
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200, json={"code": "0", "data": [{"ordId": "1", "sCode": "0", "sMsg": ""}]}
        )

    client = _client_with(handler, demo=True)
    try:
        result = client.place_order(
            "BTC-USDT-SWAP", "sell", "limit", 1, px=50000, td_mode="cross", pos_side="short"
        )
    finally:
        client.close()
    assert result["ordId"] == "1"
    assert captured["path"] == "/api/v5/trade/order"
    body = captured["body"]
    assert body["instId"] == "BTC-USDT-SWAP"
    assert body["side"] == "sell"
    assert body["ordType"] == "limit"
    assert body["sz"] == "1"
    assert body["px"] == "50000"
    assert body["posSide"] == "short"
    assert captured["headers"]["x-simulated-trading"] == "1"
    assert captured["headers"]["ok-access-key"] == "key"


def test_place_order_rejects_on_scode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "0", "data": [{"ordId": "", "sCode": "51008", "sMsg": "insufficient"}]},
        )

    client = _client_with(handler)
    try:
        try:
            client.place_order("BTC-USDT-SWAP", "sell", "market", 1)
            raise AssertionError("should have raised")
        except OkxError as exc:
            assert "51008" in str(exc)
    finally:
        client.close()


def test_cancel_order_requires_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "0", "data": [{"ordId": "9", "sCode": "0"}]})

    client = _client_with(handler)
    try:
        result = client.cancel_order("BTC-USDT-SWAP", ord_id="9")
    finally:
        client.close()
    assert result["ordId"] == "9"


def test_config_and_leverage_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v5/account/config":
            return httpx.Response(200, json={"code": "0", "data": [{"acctLv": "2", "posMode": "net_mode"}]})
        return httpx.Response(200, json={"code": "0", "data": [{}]})

    client = _client_with(handler)
    try:
        assert client.account_config()["acctLv"] == "2"
        client.set_leverage("BTC-USDT-SWAP", 3)
        client.set_position_mode("net_mode")
    finally:
        client.close()
    assert paths == [
        "/api/v5/account/config",
        "/api/v5/account/set-leverage",
        "/api/v5/account/set-position-mode",
    ]


def test_business_error_raises_okx_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "50111", "msg": "Invalid API Key"})

    client = _client_with(handler)
    try:
        try:
            client.account_config()
            raise AssertionError("should have raised")
        except OkxError as exc:
            assert "50111" in str(exc)
    finally:
        client.close()


# ------------------------------------------------------------------ router
def test_trade_gates() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        status = client.get("/api/arb/trade/status")
        assert status.status_code == 200
        assert {"configured", "enabled", "demo", "mode"} <= set(status.json())
        # Paper mode is the default (local simulation, no keys needed).
        assert status.json()["mode"] == "paper"

        # Credentials require an explicit risk confirmation.
        resp = client.post(
            "/api/arb/trade/credentials",
            json={"api_key": "k", "secret": "s", "passphrase": "p"},
        )
        assert resp.status_code == 400

        # Switching to live without trade keys is refused.
        resp = client.post("/api/arb/trade/settings", json={"mode": "live"})
        assert resp.status_code == 400

        # Ordering is off by default (make it deterministic first).
        client.post("/api/arb/trade/settings", json={"enabled": False})
        resp = client.post(
            "/api/arb/trade/order",
            json={"inst_id": "BTC-USDT-SWAP", "side": "sell", "ordertype": "market", "sz": 1, "confirm": True},
        )
        assert resp.status_code == 403
