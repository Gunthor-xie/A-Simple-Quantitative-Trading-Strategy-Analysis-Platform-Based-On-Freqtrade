from __future__ import annotations

import httpx

from app.schemas import BotConnection
from app.services.bot_client import BotClient, BotClientError


def _client_with(handler) -> BotClient:
    transport = httpx.MockTransport(handler)
    connection = BotConnection(
        id="test",
        name="test",
        kind="local",
        url="http://127.0.0.1:8080",
        username="Freqtrader",
        password="secret",
    )
    return BotClient(connection, transport=transport)


def test_login_and_ping() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "jwt-token"})
        if request.url.path == "/api/v1/ping":
            return httpx.Response(200, json={"status": "pong"})
        if request.url.path == "/api/v1/version":
            assert request.headers["Authorization"] == "Bearer jwt-token"
            return httpx.Response(200, json={"version": "2026.7"})
        return httpx.Response(404, json={})

    client = _client_with(handler)
    try:
        assert client.ping() == {"status": "pong"}
        assert client.version() == "2026.7"
    finally:
        client.close()
    assert "/api/v1/token/login" in calls


def test_401_retries_with_new_token() -> None:
    state = {"attempts": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "fresh-token"})
        if request.url.path == "/api/v1/status":
            state["attempts"] += 1
            if state["attempts"] == 1:
                return httpx.Response(401, json={"error": "not authenticated"})
            return httpx.Response(200, json=[{"trade_id": 1}])
        return httpx.Response(404, json={})

    client = _client_with(handler)
    try:
        assert client.status() == [{"trade_id": 1}]
    finally:
        client.close()
    assert state["attempts"] == 2


def test_force_enter_payload() -> None:
    captured: dict | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/v1/forceenter":
            captured = request.read().decode()
            return httpx.Response(200, json={"status": "created"})
        return httpx.Response(404, json={})

    client = _client_with(handler)
    try:
        client.force_enter("BTC/USDT:USDT", side="long", ordertype="limit", enter_tag="manual")
    finally:
        client.close()
    assert captured is not None
    assert '"pair":"BTC/USDT:USDT"' in captured
    assert '"enter_tag":"manual"' in captured


def test_error_raises_bot_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/token/login":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(500, text="boom")

    client = _client_with(handler)
    try:
        try:
            client.status()
            raise AssertionError("should have raised")
        except BotClientError as exc:
            assert "500" in str(exc)
    finally:
        client.close()
