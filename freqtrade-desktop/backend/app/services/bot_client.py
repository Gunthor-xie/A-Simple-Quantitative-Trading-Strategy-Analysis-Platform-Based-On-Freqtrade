from __future__ import annotations

import httpx
from typing import Any

from ..schemas import BotConnection
from ..security import SecretUnavailable, secret_store


class BotClientError(Exception):
    pass


class BotClient:
    """Minimal authenticated client for the freqtrade REST API.

    Login follows the freqtrade JWT flow (Basic auth -> Bearer token) and
    transparently re-authenticates on 401. ``remote`` connections are supported
    by the same client, which keeps the v2 server migration a pure config change.
    """

    def __init__(self, connection: BotConnection, transport: httpx.BaseTransport | None = None) -> None:
        self.connection = connection
        self.base_url = connection.url.rstrip("/")
        self.username = connection.username or "Freqtrader"
        self._password = connection.password
        self._token: str | None = None
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=15.0,
            transport=transport,
            # The bot API is always on localhost/private tunnels; never route it
            # through HTTP(S)_PROXY inherited from the environment (which would
            # return 502 for 127.0.0.1 targets).
            trust_env=False,
        )

    def _resolve_password(self) -> str:
        if self._password:
            return self._password
        if self.connection.id:
            try:
                return secret_store.get(f"conn:{self.connection.id}:password")
            except SecretUnavailable:
                pass
        raise BotClientError(f"连接 {self.connection.name} 缺少密码（JWT 认证必需）")

    def login(self) -> None:
        try:
            resp = self._http.post(
                "/api/v1/token/login",
                auth=(self.username, self._resolve_password()),
            )
            resp.raise_for_status()
            payload = resp.json()
            token = payload.get("access_token")
            if not token:
                raise BotClientError("登录响应中没有 access_token")
            self._token = token
        except httpx.HTTPError as exc:
            raise BotClientError(f"登录失败（{self.base_url}）：{exc}") from exc

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if path != "/api/v1/ping" and self._token is None:
            self.login()
        headers = kwargs.pop("headers", {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            resp = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise BotClientError(f"请求 {path} 失败：{exc}") from exc
        if resp.status_code in (401, 403) and path != "/api/v1/token/login":
            self._token = None
            self.login()
            headers["Authorization"] = f"Bearer {self._token}"
            try:
                resp = self._http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise BotClientError(f"请求 {path} 失败：{exc}") from exc
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise BotClientError(f"{method} {path} 返回 {resp.status_code}: {detail}")
        if not resp.content:
            return None
        return resp.json()

    def close(self) -> None:
        self._http.close()

    # ---- read endpoints ----

    def ping(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/ping")

    def version(self) -> str:
        data = self.request("GET", "/api/v1/version")
        return data.get("version", "") if isinstance(data, dict) else str(data)

    def status(self) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/status")

    def profit(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/profit")

    def balance(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/balance")

    def trades(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.request("GET", "/api/v1/trades", params={"limit": limit})

    def count(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/count")

    def whitelist(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/whitelist")

    def blacklist(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/blacklist")

    def locks(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/locks")

    def show_config(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/show_config")

    def sysinfo(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/sysinfo")

    def health(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/health")

    def logs(self, limit: int = 100) -> dict[str, Any]:
        return self.request("GET", "/api/v1/logs", params={"limit": limit})

    def strategies(self) -> list[str]:
        data = self.request("GET", "/api/v1/strategies")
        return data.get("strategies", []) if isinstance(data, dict) else list(data)

    def pair_history(
        self,
        pair: str,
        timeframe: str,
        strategy: str,
        timerange: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pair": pair, "timeframe": timeframe, "strategy": strategy}
        if timerange:
            params["timerange"] = timerange
        return self.request("GET", "/api/v1/pair_history", params=params)

    def plot_config(self, strategy: str) -> dict[str, Any]:
        return self.request("GET", "/api/v1/plot_config", params={"strategy": strategy})

    # ---- control endpoints ----

    def start(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/start")

    def pause(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/pause")

    def stop(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/stop")

    def stopbuy(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/stopbuy")

    def reload_config(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/reload_config")

    def force_enter(
        self,
        pair: str,
        side: str = "long",
        price: float | None = None,
        ordertype: str | None = None,
        stake_amount: float | None = None,
        leverage: float | None = None,
        enter_tag: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"pair": pair, "side": side}
        if price is not None:
            payload["price"] = price
        if ordertype:
            payload["ordertype"] = ordertype
        if stake_amount is not None:
            payload["stakeamount"] = stake_amount
        if leverage is not None:
            payload["leverage"] = leverage
        if enter_tag:
            payload["enter_tag"] = enter_tag
        return self.request("POST", "/api/v1/forceenter", json=payload)

    def force_exit(
        self,
        tradeid: int | str,
        ordertype: str | None = None,
        amount: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"tradeid": tradeid}
        if ordertype:
            payload["ordertype"] = ordertype
        if amount is not None:
            payload["amount"] = amount
        return self.request("POST", "/api/v1/forceexit", json=payload)

    def blacklist_add(self, pair: str) -> dict[str, Any]:
        return self.request("POST", "/api/v1/blacklist", json={"blacklist": [pair]})

    def lock_add(self, pair: str, until: str, reason: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"pair": pair, "until": until}
        if reason:
            payload["reason"] = reason
        return self.request("POST", "/api/v1/locks", json=payload)


def get_client(connection: BotConnection) -> BotClient:
    return BotClient(connection)
