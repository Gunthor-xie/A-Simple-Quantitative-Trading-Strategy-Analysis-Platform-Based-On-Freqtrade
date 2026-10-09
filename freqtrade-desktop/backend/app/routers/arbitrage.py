"""Arbitrage endpoints.

Two layers:

* Funding/basis monitoring (§Phase 1) - pure reads from local data.
* Trade capability (§Phase 2) - OKX order placement using a *separate*
  ``okx_trade:*`` credential namespace, behind two explicit gates: the
  ``arb_trade_enabled`` setting (default off) and a per-request ``confirm``.
  No automated execution loop lives here yet.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..schemas import ArbRiskSettings, FundingBasisStats, FundingHistory, FundingScanResult
from ..security import SecretUnavailable, secret_store
from ..services.arbitrage_engine import (
    DIRECTION_LONG_SPOT,
    ArbError,
    ArbitrageEngine,
    build_trade_client,
    exec_mode,
    risk_params,
    trade_demo,
    trade_enabled,
)
from ..services.funding_monitor import FundingError, FundingMonitor, FundingTimeout
from ..services.okx_client import (
    TRADE_PREFIX,
    OkxClient,
    OkxError,
    has_credentials,
)
from ..storage import db


router = APIRouter(prefix="/api/arb")


# --------------------------------------------------------------- monitoring
def _monitor() -> FundingMonitor:
    # Live-only: every scan hits OKX; nothing is read from disk.
    return FundingMonitor(proxy=db.get_setting("http_proxy") or None)


def _monitor_call(action) -> Any:
    try:
        return action(_monitor())
    except FundingTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except FundingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc


@router.get("/funding", response_model=FundingScanResult)
def funding_scan(
    limit: int = Query(100, ge=1, le=300),
    min_volume_usd: float = Query(1_000_000, ge=0, description="24h成交额下限，默认100万"),
    require_spot: bool = Query(
        True, description="仅返回有现货交易对、可做现货+永续对冲的标的"
    ),
    with_history: bool = Query(
        True, description="为返回的标的附带历史统计（均值/标准差/连续/反转/半衰期）"
    ),
) -> FundingScanResult:
    """Live OKX scan; reports a network timeout when OKX does not answer in 10s."""
    return _monitor_call(
        lambda monitor: monitor.live_scan(
            min_volume_usd=min_volume_usd,
            limit=limit,
            require_spot=require_spot,
            with_history=with_history,
        )
    )


@router.get("/funding/history", response_model=FundingHistory)
def funding_history(
    pair: str = Query(..., description="形如 BTC/USDT:USDT"),
    days: int = Query(90, ge=1, le=730),
) -> FundingHistory:
    return _monitor_call(lambda monitor: monitor.history(pair, days=days))


@router.get("/funding/amplitude")
def funding_amplitude(
    pair: str = Query(..., description="形如 BTC/USDT:USDT"),
    days: int = Query(730, ge=30, le=1460),
) -> dict[str, Any]:
    """~2y of daily K -> max single-day amplitude + suggested leverage."""
    return _monitor_call(lambda monitor: monitor.daily_stats(pair, days=days))


@router.get("/funding/basis", response_model=FundingBasisStats)
def funding_basis(
    pair: str = Query(..., description="形如 BTC/USDT:USDT"),
    days: int = Query(365, ge=30, le=1460),
) -> FundingBasisStats:
    """Basis history for one symbol: percentile, volatility, convergence.

    Fetched on demand (two paginated candle calls), never during the scan.
    """
    return _monitor_call(lambda monitor: monitor.basis_stats_for(pair, days=days))


# ------------------------------------------------------------------- risk
@router.get("/risk", response_model=ArbRiskSettings)
def get_risk() -> ArbRiskSettings:
    return ArbRiskSettings(**risk_params(db))


@router.put("/risk", response_model=ArbRiskSettings)
def put_risk(settings: ArbRiskSettings) -> ArbRiskSettings:
    db.set_setting("arb_warn_liq_distance_pct", str(settings.warn_liq_distance_pct))
    db.set_setting("arb_max_delta_pct", str(settings.max_delta_pct))
    db.set_setting("arb_fee_bps", str(settings.fee_bps))
    return ArbRiskSettings(**risk_params(db))


# ------------------------------------------------------------------ trading
def _trade_client() -> OkxClient:
    try:
        return build_trade_client(db)
    except ArbError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _call_okx(action) -> Any:
    client = _trade_client()
    try:
        return action(client)
    except OkxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    finally:
        client.close()


def _engine() -> ArbitrageEngine:
    return ArbitrageEngine(_trade_client(), db)


def _run_engine(action) -> Any:
    engine = _engine()
    try:
        return action(engine)
    except ArbError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OkxError as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc
    finally:
        engine.client.close()


@router.get("/trade/status")
def trade_status() -> dict[str, Any]:
    return {
        "configured": has_credentials(TRADE_PREFIX),
        "enabled": trade_enabled(db),
        "demo": trade_demo(db),
        "mode": exec_mode(db),
    }


@router.post("/trade/credentials")
def save_trade_credentials(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail="请先勾选风险确认后再保存交易密钥")
    missing = [k for k in ("api_key", "secret", "passphrase") if not payload.get(k)]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少字段：{', '.join(missing)}")
    try:
        secret_store.set(f"{TRADE_PREFIX}:key", payload["api_key"])
        secret_store.set(f"{TRADE_PREFIX}:secret", payload["secret"])
        secret_store.set(f"{TRADE_PREFIX}:passphrase", payload["passphrase"])
    except SecretUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "configured": has_credentials(TRADE_PREFIX)}


@router.delete("/trade/credentials")
def clear_trade_credentials() -> dict[str, Any]:
    for name in ("key", "secret", "passphrase"):
        secret_store.delete(f"{TRADE_PREFIX}:{name}")
    db.set_setting("arb_trade_enabled", "0")
    return {"ok": True, "configured": False, "enabled": False}


@router.post("/trade/settings")
def update_trade_settings(payload: dict[str, Any]) -> dict[str, Any]:
    if "mode" in payload:
        mode = str(payload["mode"]).strip().lower()
        if mode not in ("paper", "live"):
            raise HTTPException(status_code=400, detail="mode 只能是 paper / live")
        if mode == "live" and not has_credentials(TRADE_PREFIX):
            raise HTTPException(status_code=400, detail="切换到实盘前请先保存交易密钥")
        db.set_setting("arb_exec_mode", mode)
    if "enabled" in payload:
        enabled = bool(payload["enabled"])
        if enabled and exec_mode(db) == "live" and not has_credentials(TRADE_PREFIX):
            raise HTTPException(status_code=400, detail="实盘模式请先保存交易密钥再开启下单")
        db.set_setting("arb_trade_enabled", "1" if enabled else "0")
    if "demo" in payload:
        db.set_setting("arb_trade_demo", "1" if payload["demo"] else "0")
    return {"enabled": trade_enabled(db), "demo": trade_demo(db), "mode": exec_mode(db)}


@router.get("/trade/account")
def trade_account() -> dict[str, Any]:
    def action(client: OkxClient) -> dict[str, Any]:
        return {
            "config": client.account_config(),
            "balance": client.balance(),
            "positions": client.positions(),
        }

    return _call_okx(action)


@router.post("/trade/leverage")
def trade_leverage(payload: dict[str, Any]) -> dict[str, Any]:
    inst_id = payload.get("inst_id")
    lever = payload.get("lever")
    if not inst_id or not lever:
        raise HTTPException(status_code=400, detail="需要 inst_id 与 lever")

    def action(client: OkxClient) -> Any:
        return client.set_leverage(
            inst_id,
            lever,
            mgn_mode=payload.get("mgn_mode", "cross"),
            pos_side=payload.get("pos_side"),
        )

    return {"ok": True, "data": _call_okx(action)}


@router.post("/trade/position-mode")
def trade_position_mode(payload: dict[str, Any]) -> dict[str, Any]:
    pos_mode = payload.get("pos_mode", "net_mode")
    if pos_mode not in ("net_mode", "long_short_mode"):
        raise HTTPException(status_code=400, detail="pos_mode 只能是 net_mode / long_short_mode")

    def action(client: OkxClient) -> Any:
        return client.set_position_mode(pos_mode)

    return {"ok": True, "data": _call_okx(action)}


@router.post("/trade/order")
def trade_order(payload: dict[str, Any]) -> dict[str, Any]:
    if not trade_enabled(db):
        raise HTTPException(status_code=403, detail="下单未开启：请先在套利页开启交易并确认风险")
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail="请在页面勾选确认后再次提交")
    inst_id = payload.get("inst_id")
    side = payload.get("side")
    ordertype = payload.get("ordertype", "limit")
    sz = payload.get("sz")
    if not inst_id or side not in ("buy", "sell") or not sz:
        raise HTTPException(status_code=400, detail="需要 inst_id / side(buy|sell) / sz")
    if ordertype == "limit" and payload.get("px") in (None, ""):
        raise HTTPException(status_code=400, detail="限价单需要 px")

    def action(client: OkxClient) -> Any:
        return client.place_order(
            inst_id,
            side,
            ordertype,
            sz,
            px=payload.get("px"),
            td_mode=payload.get("td_mode", "cross"),
            pos_side=payload.get("pos_side"),
            reduce_only=bool(payload.get("reduce_only")),
        )

    return {"ok": True, "data": _call_okx(action)}


@router.post("/trade/cancel")
def trade_cancel(payload: dict[str, Any]) -> dict[str, Any]:
    if not trade_enabled(db):
        raise HTTPException(status_code=403, detail="下单未开启：请先在套利页开启交易")
    inst_id = payload.get("inst_id")
    if not inst_id:
        raise HTTPException(status_code=400, detail="需要 inst_id")
    if not payload.get("ord_id") and not payload.get("cl_ord_id"):
        raise HTTPException(status_code=400, detail="需要 ord_id 或 cl_ord_id")

    def action(client: OkxClient) -> Any:
        return client.cancel_order(
            inst_id, ord_id=payload.get("ord_id"), cl_ord_id=payload.get("cl_ord_id")
        )

    return {"ok": True, "data": _call_okx(action)}


# --------------------------------------------------- positions (two-leg)
@router.get("/positions")
def list_positions(status: str | None = Query(None), limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    return {"positions": db.list_arb_positions(status, limit)}


@router.get("/positions/{position_id}")
def get_position(position_id: int) -> dict[str, Any]:
    pos = db.get_arb_position(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="持仓不存在")
    return {
        "position": pos,
        "legs": db.list_arb_legs(position_id),
        "events": db.list_arb_events(position_id, limit=100),
    }


@router.post("/positions/plan")
def plan_position(payload: dict[str, Any]) -> dict[str, Any]:
    """Dry-run sizing + expected annualised carry + the leverage guardrail."""
    pair = payload.get("pair")
    capital = payload.get("capital_usd")
    if not pair or not capital:
        raise HTTPException(status_code=400, detail="需要 pair 与 capital_usd")
    return _run_engine(
        lambda engine: engine.preview(
            pair,
            float(capital),
            payload.get("leverage"),
            payload.get("direction", DIRECTION_LONG_SPOT),
        )
    )


@router.post("/positions/open")
def open_position(payload: dict[str, Any]) -> dict[str, Any]:
    if not trade_enabled(db):
        raise HTTPException(status_code=403, detail="下单未开启：请先在套利页开启交易并确认风险")
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail="请在页面勾选确认后再次提交")
    pair = payload.get("pair")
    capital = payload.get("capital_usd")
    if not pair or not capital:
        raise HTTPException(status_code=400, detail="需要 pair 与 capital_usd")
    return _run_engine(
        lambda engine: engine.open_position(
            pair,
            float(capital),
            leverage=payload.get("leverage"),
            direction=payload.get("direction", DIRECTION_LONG_SPOT),
            ordertype=payload.get("ordertype", "market"),
            note=payload.get("note", ""),
        )
    )


@router.post("/positions/{position_id}/close")
def close_position(position_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    if not payload.get("confirm"):
        raise HTTPException(status_code=400, detail="请勾选确认后再平仓")
    return _run_engine(lambda engine: engine.close_position(position_id))


@router.post("/positions/{position_id}/refresh")
def refresh_position(position_id: int) -> dict[str, Any]:
    return _run_engine(lambda engine: engine.refresh(position_id))


@router.post("/positions/unwind")
def unwind_positions() -> dict[str, Any]:
    """Run the risk check once; closes any position that tripped a trigger."""
    if not trade_enabled(db):
        raise HTTPException(status_code=403, detail="下单未开启")
    return {"unwound": _run_engine(lambda engine: engine.maybe_unwind())}


@router.get("/events")
def list_events(
    position_id: int | None = Query(None), limit: int = Query(200, ge=1, le=1000)
) -> dict[str, Any]:
    return {"events": db.list_arb_events(position_id, limit)}
