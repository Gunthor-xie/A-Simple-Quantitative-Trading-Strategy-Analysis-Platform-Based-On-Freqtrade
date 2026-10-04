from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..security import SecretUnavailable, secret_store
from ..services.bot_client import BotClient, BotClientError
from ..services.okx_client import OkxClient, OkxError, has_credentials
from .api import _connection_from_row
from ..storage import db


router = APIRouter(prefix="/api/okx")


@router.get("/status")
def okx_status() -> dict[str, Any]:
    return {"configured": has_credentials()}


@router.post("/credentials")
def save_credentials(payload: dict[str, str]) -> dict[str, Any]:
    missing = [k for k in ("api_key", "secret", "passphrase") if not payload.get(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少字段：{', '.join(missing)}")
    try:
        secret_store.set("okx_read:key", payload["api_key"])
        secret_store.set("okx_read:secret", payload["secret"])
        secret_store.set("okx_read:passphrase", payload["passphrase"])
    except SecretUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "configured": has_credentials()}


@router.delete("/credentials")
def clear_credentials() -> dict[str, Any]:
    for name in ("okx_read:key", "okx_read:secret", "okx_read:passphrase"):
        secret_store.delete(name)
    return {"ok": True}


def _client() -> OkxClient:
    try:
        return OkxClient.from_store()
    except OkxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/summary")
def okx_summary() -> dict[str, Any]:
    client = _client()
    try:
        balance = client.balance()
        return {
            "balance": balance,
            "positions": client.positions(),
            "open_orders": client.open_orders(),
            "recent_fills": client.recent_fills()[:30],
        }
    except OkxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()


@router.post("/reconcile")
def reconcile(payload: dict[str, Any]) -> dict[str, Any]:
    connection_id = payload.get("connection_id")
    client = _client()
    try:
        okx_positions = client.positions()
    except OkxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()
    diffs: list[dict[str, Any]] = []
    if not connection_id:
        return {"diffs": diffs, "warning": "未选择机器人连接，仅展示 OKX 持仓", "okx_positions": okx_positions}
    row = db.get_connection(connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    bot = BotClient(_connection_from_row(row))
    try:
        bot_status = bot.status()
    except BotClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        bot.close()
    okx_pairs = {p.get("instId", "").split("-")[0] + "/USDT" for p in okx_positions}
    bot_pairs = {t.get("pair") for t in bot_status}
    for pair in sorted(okx_pairs - bot_pairs):
        diffs.append({"level": "high", "pair": pair, "detail": "OKX 有持仓但机器人未记录"})
    for pair in sorted(bot_pairs - okx_pairs):
        diffs.append({"level": "low", "pair": pair, "detail": "机器人有交易但 OKX 无持仓（dry-run 正常）"})
    return {"diffs": diffs, "okx_positions": okx_positions, "bot_pairs": sorted(bot_pairs)}
