"""OKX v5 REST client.

Two credential namespaces are kept deliberately separate:

* ``okx_read:*``  - read-only keys: balance / positions / orders / fills.
* ``okx_trade:*`` - trade-enabled keys used only by the (explicitly gated)
  order-placement methods below. Never mix the two.

Trade methods reuse the same HMAC-SHA256 signing as the read methods. They are
inert unless the caller supplies trade credentials and calls them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from ..security import SecretUnavailable, secret_store
from .proxy import resolve_proxy


READ_PREFIX = "okx_read"
TRADE_PREFIX = "okx_trade"


class OkxError(Exception):
    pass


class OkxClient:
    BASE = "https://www.okx.com"

    def __init__(
        self,
        api_key: str,
        secret: str,
        passphrase: str,
        *,
        demo: bool = False,
        transport: httpx.BaseTransport | None = None,
        proxy: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        # Demo/simulated trading uses the same host with a marker header, which
        # makes signing-verification and end-to-end tests safe against real keys.
        self.demo = demo
        # trust_env stays off so a stale HTTP(S)_PROXY never hijacks requests;
        # the app's explicit setting wins, and otherwise the same auto-detected
        # route as the rest of the app is used (some networks need a proxy).
        if proxy is None and transport is None:
            proxy = resolve_proxy()
        kwargs: dict = {"base_url": self.BASE, "timeout": 20.0, "trust_env": False,
                        "transport": transport}
        if proxy:
            kwargs["proxy"] = proxy
        self._http = httpx.Client(**kwargs)

    @classmethod
    def from_store(
        cls,
        prefix: str = READ_PREFIX,
        *,
        demo: bool = False,
        transport: httpx.BaseTransport | None = None,
        proxy: str | None = None,
    ) -> "OkxClient":
        try:
            key = secret_store.get(f"{prefix}:key")
            secret = secret_store.get(f"{prefix}:secret")
            passphrase = secret_store.get(f"{prefix}:passphrase")
        except SecretUnavailable as exc:
            raise OkxError(f"未配置 OKX 密钥（{prefix}）：{exc}") from exc
        return cls(key, secret, passphrase, demo=demo, transport=transport, proxy=proxy)

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
            json_body = json.dumps(payload)
        sign = self._sign(method, f"{path}{query}", json_body, ts)
        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }
        if self.demo:
            headers["x-simulated-trading"] = "1"
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

    # ------------------------------------------------------------- read-only
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

    def account_config(self) -> dict:
        """Account mode / position mode / fee tier (``acctLv``, ``posMode``)."""
        data = self.request("GET", "/api/v5/account/config")
        return data[0] if data else {}

    # ---------------------------------------------------------- public market
    def ticker(self, inst_id: str) -> dict:
        data = self.request("GET", "/api/v5/market/ticker", params={"instId": inst_id})
        return data[0] if data else {}

    def instruments(self, inst_type: str) -> list[dict]:
        return self.request("GET", "/api/v5/public/instruments", params={"instType": inst_type})

    def funding_rate_history(
        self, inst_id: str, *, after: int | None = None, before: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        params: dict[str, Any] = {"instId": inst_id, "limit": str(limit)}
        if after:
            params["after"] = str(after)
        if before:
            params["before"] = str(before)
        return self.request("GET", "/api/v5/public/funding-rate-history", params=params)

    def funding_rate(self, inst_id: str) -> dict:
        """Current + next funding for one instrument."""
        data = self.request("GET", "/api/v5/public/funding-rate", params={"instId": inst_id})
        return data[0] if data else {}

    def candles(
        self, inst_id: str, bar: str = "1D", limit: int = 100, after: int | None = None
    ) -> list[list]:
        params: dict[str, Any] = {"instId": inst_id, "bar": bar, "limit": str(limit)}
        if after:
            params["after"] = str(after)
        return self.request("GET", "/api/v5/market/candles", params=params)

    # --------------------------------------------------------------- trading
    def set_leverage(
        self, inst_id: str, lever: int | str, mgn_mode: str = "cross",
        pos_side: str | None = None,
    ) -> list[dict]:
        body: dict[str, Any] = {"instId": inst_id, "lever": str(lever), "mgnMode": mgn_mode}
        if pos_side:
            body["posSide"] = pos_side
        return self.request("POST", "/api/v5/account/set-leverage", body=body)

    def set_position_mode(self, pos_mode: str = "net_mode") -> list[dict]:
        """``net_mode`` (single net position) or ``long_short_mode`` (hedge)."""
        return self.request(
            "POST", "/api/v5/account/set-position-mode", body={"posMode": pos_mode}
        )

    def place_order(
        self,
        inst_id: str,
        side: str,
        ordertype: str,
        sz: str | float,
        *,
        px: str | float | None = None,
        td_mode: str = "cross",
        pos_side: str | None = None,
        reduce_only: bool = False,
        cl_ord_id: str | None = None,
        tgt_ccy: str | None = None,
    ) -> dict:
        """Submit a single order.

        OKX answers HTTP 200 with a top-level ``code: "0"`` even when an
        individual order is rejected, signalling the real result in
        ``sCode``/``sMsg``; those are surfaced as :class:`OkxError`.

        ``tgt_ccy="base_ccy"`` makes a spot *market buy* size in the base
        currency, so ``sz`` means the same thing as on a market sell.
        """
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": ordertype,
            "sz": str(sz),
        }
        if px is not None:
            body["px"] = str(px)
        if pos_side:
            body["posSide"] = pos_side
        if reduce_only:
            body["reduceOnly"] = True
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        if tgt_ccy:
            body["tgtCcy"] = tgt_ccy
        return self._order_result(self.request("POST", "/api/v5/trade/order", body=body))

    def cancel_order(
        self, inst_id: str, *, ord_id: str | None = None, cl_ord_id: str | None = None
    ) -> dict:
        body: dict[str, Any] = {"instId": inst_id}
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        return self._order_result(self.request("POST", "/api/v5/trade/cancel-order", body=body))

    @staticmethod
    def _order_result(data: list[dict]) -> dict:
        result = data[0] if data else {}
        code = str(result.get("sCode", "0"))
        if code not in ("0", ""):
            raise OkxError(f"OKX 订单被拒 {code}: {result.get('sMsg')}")
        return result

    def close(self) -> None:
        self._http.close()


def has_credentials(prefix: str = READ_PREFIX) -> bool:
    for name in (f"{prefix}:key", f"{prefix}:secret", f"{prefix}:passphrase"):
        try:
            secret_store.get(name)
        except SecretUnavailable:
            return False
    return True
