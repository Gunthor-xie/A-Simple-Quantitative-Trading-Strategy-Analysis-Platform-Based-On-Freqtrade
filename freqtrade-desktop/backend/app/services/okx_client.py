"""Read-only OKX v5 REST client (private account endpoints)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any

import httpx

from ..security import SecretUnavailable, secret_store


class OkxError(Exception):
    pass


class OkxClient:
    BASE = "https://www.okx.com"

    def __init__(self, api_key: str, secret: str, passphrase: str) -> None:
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self._http = httpx.Client(base_url=self.BASE, timeout=20.0, trust_env=False)

    @classmethod
    def from_store(cls) -> "OkxClient":
        try:
            key = secret_store.get("okx_read:key")
            secret = secret_store.get("okx_read:secret")
            passphrase = secret_store.get("okx_read:passphrase")
        except SecretUnavailable as exc:
            raise OkxError(f"未配置 OKX 只读密钥：{exc}") from exc
        return cls(key, secret, passphrase)

    def _sign(self, method: str, path: str, body: str, ts: str) -> str:
        message = f"{ts}{method}{path}{body}"
        digest = hmac.new(
            self.secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return base64.b64encode(digest).decode()

    def request(self, method: str, path: str, params: dict | None = None,
                body: dict | None = None) -> Any:
        ts = str(int(time.time() * 1000))
        query = ""
        if params:
            query = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        payload = body if body is not None else {}
        json_body = ""
        if payload:
            import json

            json_body = json.dumps(payload)
        sign = self._sign(method, f"{path}{query}", json_body, ts)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        try:
            response = self._http.request(
                method, f"{path}{query}", headers=headers, content=json_body or None
            )
        except httpx.HTTPError as exc:
            raise OkxError(f"OKX 请求失败：{exc}") from exc
        if response.status_code >= 400:
            raise OkxError(f"OKX {method} {path} -> {response.status_code}: {response.text[:300]}")
        data = response.json()
        if data.get("code") not in ("0", 0):
            raise OkxError(f"OKX 业务错误 {data.get('code')}: {data.get('msg')}")
        return data.get("data", [])

    def balance(self) -> list[dict]:
        return self.request("GET", "/api/v5/account/balance")

    def positions(self, inst_type: str | None = None) -> list[dict]:
        params = {"instType": inst_type} if inst_type else {}
        return self.request("GET", "/api/v5/account/positions", params=params)

    def open_orders(self, inst_type: str | None = None) -> list[dict]:
        params = {"instType": inst_type} if inst_type else {}
        return self.request("GET", "/api/v5/trade/orders-pending", params=params)

    def recent_fills(self, inst_type: str | None = None) -> list[dict]:
        params = {"instType": inst_type} if inst_type else {}
        return self.request("GET", "/api/v5/trade/fills", params=params)

    def close(self) -> None:
        self._http.close()


def has_credentials() -> bool:
    for name in ("okx_read:key", "okx_read:secret", "okx_read:passphrase"):
        try:
            secret_store.get(name)
        except SecretUnavailable:
            return False
    return True
