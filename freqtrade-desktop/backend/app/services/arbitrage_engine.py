"""Delta-neutral funding/basis executor.

Two directions are supported:

* ``long_spot_short_perp`` (default) - cash-and-carry: buy spot, short the
  perpetual, collect positive funding.
* ``short_spot_long_perp`` - the mirror trade for negative funding. The
  short-spot leg needs OKX **margin** enabled for the pair.

The legs are placed sequentially, safest first, so a failed second leg can be
rolled back instead of leaving a naked short.

Before opening, the requested leverage is checked against a leverage suggested
from the pair's two-year worst single-day move; exceeding it is refused.

Only a single position per call is opened; there is no automated strategy loop.
Every action is gated on ``arb_trade_enabled`` (default off) and recorded in
``arb_legs`` / ``arb_events`` for audit.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from ..schemas import utcnow_iso
from ..storage import db as default_db
from .funding_monitor import (
    max_daily_amplitude,
    pair_to_inst,
    pair_to_symbol,
    spot_inst,
    suggest_leverage,
)
from .okx_client import TRADE_PREFIX, OkxClient, OkxError, has_credentials


DEFAULT_LEVERAGE = 3.0
DEFAULT_FEE_BPS = 5.0
DIRECTION_LONG_SPOT = "long_spot_short_perp"
DIRECTION_SHORT_SPOT = "short_spot_long_perp"
DIRECTIONS = (DIRECTION_LONG_SPOT, DIRECTION_SHORT_SPOT)


class ArbError(Exception):
    pass


# --------------------------------------------------------------- gating
# Shared by the router and the scheduler so the two never diverge.
def trade_enabled(store=default_db) -> bool:
    return (store.get_setting("arb_trade_enabled") or "0") == "1"


def trade_demo(store=default_db) -> bool:
    return (store.get_setting("arb_trade_demo") or "1") == "1"


def exec_mode(store=default_db) -> str:
    """``paper`` (default, local simulation, no keys) or ``live`` (real OKX)."""
    mode = (store.get_setting("arb_exec_mode") or "paper").strip().lower()
    return mode if mode in ("paper", "live") else "paper"


def risk_params(store=default_db) -> dict[str, float]:
    """Risk-check thresholds + the (round-trip) fee assumption, all editable."""

    def num(key: str, default: float) -> float:
        try:
            return float(store.get_setting(key) or default)
        except (TypeError, ValueError):
            return default

    return {
        "warn_liq_distance_pct": num("arb_warn_liq_distance_pct", 0.12),
        "max_delta_pct": num("arb_max_delta_pct", 0.03),
        "fee_bps": num("arb_fee_bps", DEFAULT_FEE_BPS),
    }


class PaperClient:
    """In-process paper-trading stand-in for :class:`OkxClient`.

    Real-time dry run without keys and without touching OKX order endpoints:
    orders are filled at the current *public* ticker price, and ``positions()``
    is synthesised from the open rows in ``arb_positions`` so the engine's
    delta / liquidation math runs completely unchanged. Only public market data
    is fetched (prices, instruments, funding history) - never a private call.
    """

    demo = True
    simulated = True

    def __init__(self, store=default_db, *, market: "OkxClient | None" = None) -> None:
        self.db = store
        # Public-only client; honor the app's proxy setting so this works on
        # networks where OKX is only reachable through a proxy.
        self._market = market or OkxClient(
            "", "", "", proxy=store.get_setting("http_proxy") or None
        )
        self._seq = 0

    # ---- market data (delegated to the public client) ----
    def ticker(self, inst_id: str) -> dict:
        return self._market.ticker(inst_id)

    def instruments(self, inst_type: str) -> list[dict]:
        return self._market.instruments(inst_type)

    def funding_rate_history(self, inst_id: str, **kwargs) -> list[dict]:
        return self._market.funding_rate_history(inst_id, **kwargs)

    def funding_rate(self, inst_id: str) -> dict:
        return self._market.funding_rate(inst_id)

    def candles(self, inst_id: str, bar: str = "1D", limit: int = 100,
                after: int | None = None) -> list[list]:
        return self._market.candles(inst_id, bar, limit, after)

    def close(self) -> None:
        self._market.close()

    # ---- account (synthetic) ----
    def account_config(self) -> dict:
        return {"acctLv": "2", "posMode": "net_mode", "role": "paper"}

    def balance(self) -> list[dict]:
        return [{"totalEq": "0", "ccy": "USDT", "details": []}]

    def set_leverage(self, inst_id, lever, mgn_mode="cross", pos_side=None) -> list[dict]:
        return [{}]

    def positions(self, inst_type: str | None = None) -> list[dict]:
        out: list[dict] = []
        for pos in self.db.list_arb_positions(status="open"):
            mark = float(self.ticker(pos["inst_perp"]).get("last") or pos["perp_entry_px"] or 0)
            entry = pos.get("perp_entry_px") or mark
            lev = pos.get("leverage") or 1
            # Crude isolated-short liquidation estimate: entry * (1 + 1/leverage).
            liq = entry * (1 + 1 / lev) if lev else 0.0
            out.append(
                {
                    "instId": pos["inst_perp"],
                    "markPx": str(mark),
                    "liqPx": str(liq),
                    "pos": str(-(pos["perp_contracts"] or 0)),
                    "avgPx": str(entry),
                }
            )
        return out

    # ---- simulated fills ----
    def place_order(self, inst_id, side, ordertype, sz, *, px=None, td_mode="cross",
                    pos_side=None, reduce_only=False, cl_ord_id=None, tgt_ccy=None) -> dict:
        price = float(px) if (ordertype == "limit" and px) else float(
            self.ticker(inst_id).get("last") or 0
        )
        if price <= 0:
            raise OkxError(f"无法获取 {inst_id} 价格，纸面下单失败")
        self._seq += 1
        return {"ordId": f"paper-{self._seq}", "px": str(price), "simulated": True}


def build_trade_client(store=default_db):
    """Return the trading client for the configured mode.

    ``paper`` needs no keys and never reaches OKX's order endpoints; ``live``
    requires the isolated ``okx_trade`` credentials.
    """
    if exec_mode(store) == "paper":
        return PaperClient(store)
    if not has_credentials(TRADE_PREFIX):
        raise ArbError("未配置 OKX 交易密钥（okx_trade）")
    try:
        return OkxClient.from_store(
            TRADE_PREFIX, demo=trade_demo(store), proxy=store.get_setting("http_proxy") or None
        )
    except OkxError as exc:
        raise ArbError(str(exc)) from exc


def _round_down(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 8)
    return round(math.floor(value / step + 1e-9) * step, 8)


def _iso_to_ms(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except ValueError:
        return 0


@dataclass
class LegPlan:
    pair: str
    symbol: str
    direction: str
    inst_spot: str
    inst_perp: str
    spot_side: str
    perp_side: str
    spot_qty: float
    perp_contracts: float
    spot_price: float
    perp_price: float
    ct_val: float
    spot_notional: float
    perp_notional: float
    leverage: float
    fee_bps: float
    funding_annualized: float
    round_trip_fee: float
    expected_annual: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _leg_sides(direction: str) -> tuple[str, str]:
    """Return ``(spot_side, perp_side)`` for a direction."""
    if direction == DIRECTION_SHORT_SPOT:
        return "sell", "buy"
    return "buy", "sell"


class ArbitrageEngine:
    def __init__(
        self,
        client: OkxClient | PaperClient,
        store=default_db,
        *,
        leverage: float = DEFAULT_LEVERAGE,
    ) -> None:
        self.client = client
        self.db = store
        self.leverage = leverage
        self._instruments: dict[str, dict[str, dict]] = {}

    # --------------------------------------------------------- metadata
    def instrument(self, inst_type: str, inst_id: str) -> dict:
        cache = self._instruments.get(inst_type)
        if cache is None:
            cache = {i["instId"]: i for i in self.client.instruments(inst_type)}
            self._instruments[inst_type] = cache
        return cache.get(inst_id, {})

    # -------------------------------------------------- leverage guardrail
    def suggested_leverage(self, inst_perp: str, *, days: int = 730) -> tuple[int, float]:
        """``(suggested_leverage, max_daily_amplitude)`` from ~2y of daily K."""
        rows: list[list] = []
        after: int | None = None
        for _ in range(8):  # 100/day -> 8 pages covers ~2 years
            page = self.client.candles(inst_perp, "1D", 100, after)
            if not page:
                break
            rows.extend(page)
            oldest = min(int(row[0]) for row in page)
            if len(page) < 100 or oldest <= 0:
                break
            after = oldest
        amplitude, _ = max_daily_amplitude(rows)
        return suggest_leverage(amplitude), amplitude

    # ---------------------------------------------------------- planning
    def plan(
        self,
        pair: str,
        capital_usd: float,
        leverage: float | None = None,
        direction: str = DIRECTION_LONG_SPOT,
    ) -> LegPlan:
        if capital_usd <= 0:
            raise ArbError("资金必须为正")
        if direction not in DIRECTIONS:
            raise ArbError(f"未知方向 {direction}")

        symbol = pair_to_symbol(pair)
        inst_perp = pair_to_inst(pair)
        inst_spot = spot_inst(inst_perp)
        perp_meta = self.instrument("SWAP", inst_perp)
        if not perp_meta:
            raise ArbError(f"{pair} 没有对应的永续合约（{inst_perp}）")
        spot_meta = self.instrument("SPOT", inst_spot)
        if not spot_meta:
            # OKX lists perps for tokenised equities/commodities/pre-IPO names
            # that have no spot market at all, so a hedge cannot be built.
            raise ArbError(
                f"{pair} 没有现货交易对（{inst_spot}），无法构建现货+永续对冲；"
                "该类标的（如代币化股票/商品）在 OKX 仅有合约，请改选有现货的标的"
            )

        eff_leverage = float(leverage or self.leverage)
        if eff_leverage <= 0:
            raise ArbError("杠杆必须为正")

        spot_px = float(self.client.ticker(inst_spot).get("last") or 0)
        perp_px = float(self.client.ticker(inst_perp).get("last") or 0)
        if spot_px <= 0 or perp_px <= 0:
            raise ArbError(f"无法获取 {pair} 最新价")

        # Spot notional N plus perp margin N/lev must fit in the capital.
        notional = capital_usd / (1 + 1 / eff_leverage)
        ct_val = float(perp_meta.get("ctVal") or 0) or 1.0
        spot_qty = _round_down(notional / spot_px, float(spot_meta.get("lotSz") or 0))
        perp_contracts = _round_down(
            notional / (ct_val * perp_px), float(perp_meta.get("lotSz") or 0)
        )
        if spot_qty < float(spot_meta.get("minSz") or 0):
            raise ArbError(f"{pair} 现货腿低于最小下单量")
        if perp_contracts < float(perp_meta.get("minSz") or 0):
            raise ArbError(f"{pair} 永续腿低于最小下单量")
        if spot_qty <= 0 or perp_contracts <= 0:
            raise ArbError(f"{pair} 资金不足以满足最小下单量")

        fee_bps = risk_params(self.db)["fee_bps"]
        funding_annual = self._funding_annualized(inst_perp)
        # Cash-and-carry earns positive funding; the mirror trade earns negative.
        carry = funding_annual if direction == DIRECTION_LONG_SPOT else -funding_annual
        round_trip_fee = 4 * fee_bps / 10_000.0  # open+close on both legs
        spot_side, perp_side = _leg_sides(direction)

        return LegPlan(
            pair=pair,
            symbol=symbol,
            direction=direction,
            inst_spot=inst_spot,
            inst_perp=inst_perp,
            spot_side=spot_side,
            perp_side=perp_side,
            spot_qty=spot_qty,
            perp_contracts=perp_contracts,
            spot_price=spot_px,
            perp_price=perp_px,
            ct_val=ct_val,
            spot_notional=round(spot_qty * spot_px, 4),
            perp_notional=round(perp_contracts * ct_val * perp_px, 4),
            leverage=eff_leverage,
            fee_bps=fee_bps,
            funding_annualized=round(funding_annual, 6),
            round_trip_fee=round(round_trip_fee, 6),
            expected_annual=round(carry - round_trip_fee, 6),
        )

    def _funding_annualized(self, inst_perp: str) -> float:
        """Current funding scaled to a year using the settlement cadence."""
        record = self.client.funding_rate(inst_perp)
        try:
            rate = float(record.get("fundingRate") or 0)
            funding_time = float(record.get("fundingTime") or 0)
            next_time = float(record.get("nextFundingTime") or 0)
        except (TypeError, ValueError):
            return 0.0
        hours = 8.0
        if funding_time and next_time > funding_time:
            candidate = (next_time - funding_time) / 3_600_000
            if 0.5 <= candidate <= 24:
                hours = candidate
        return rate * (24.0 / hours) * 365.0

    def preview(
        self,
        pair: str,
        capital_usd: float,
        leverage: float | None = None,
        direction: str = DIRECTION_LONG_SPOT,
    ) -> dict[str, Any]:
        """Plan + expected annualised carry + the leverage guardrail verdict."""
        plan = self.plan(pair, capital_usd, leverage, direction)
        data = plan.as_dict()
        try:
            suggested, amplitude = self.suggested_leverage(plan.inst_perp)
            data["suggested_leverage"] = suggested
            data["max_daily_amplitude"] = amplitude
            data["leverage_ok"] = plan.leverage <= suggested
        except Exception:  # noqa: BLE001 - report "unknown" instead of failing the preview
            data["suggested_leverage"] = None
            data["max_daily_amplitude"] = None
            data["leverage_ok"] = None
        return data

    # ------------------------------------------------------------ orders
    def _place(
        self,
        position_id: int,
        kind: str,
        inst_id: str,
        side: str,
        ordertype: str,
        sz: float,
        px: float,
        *,
        tgt_ccy: str | None = None,
        reduce_only: bool = False,
        td_mode: str = "cross",
    ) -> dict | None:
        try:
            result = self.client.place_order(
                inst_id,
                side,
                ordertype,
                sz,
                px=px if ordertype == "limit" else None,
                td_mode=td_mode,
                reduce_only=reduce_only,
                tgt_ccy=tgt_ccy,
            )
        except OkxError as exc:
            self.db.insert_arb_leg(
                position_id,
                {"kind": kind, "inst_id": inst_id, "side": side, "ordertype": ordertype,
                 "sz": sz, "px": px, "status": "failed", "detail": str(exc)[:300]},
            )
            self.db.add_arb_event(
                position_id, f"{kind}_order_failed", level="error", detail=str(exc)[:300]
            )
            return None
        self.db.insert_arb_leg(
            position_id,
            {"kind": kind, "inst_id": inst_id, "side": side, "ordertype": ordertype,
             "sz": sz, "px": px, "ord_id": result.get("ordId"), "status": "placed"},
        )
        self.db.add_arb_event(
            position_id, f"{kind}_order_placed", detail=f"{side} {sz} {inst_id}"
        )
        return result

    # ------------------------------------------------------------ lifecycle
    def open_position(
        self,
        pair: str,
        capital_usd: float,
        *,
        leverage: float | None = None,
        direction: str = DIRECTION_LONG_SPOT,
        ordertype: str = "market",
        note: str = "",
    ) -> dict[str, Any]:
        if not trade_enabled(self.db):
            raise ArbError("下单未开启：请先在套利页开启交易并确认风险")
        plan = self.plan(pair, capital_usd, leverage, direction)

        # Hard guardrail: never open above the leverage suggested by the worst
        # single-day move over the last two years.
        try:
            suggested, amplitude = self.suggested_leverage(plan.inst_perp)
        except Exception as exc:  # noqa: BLE001
            raise ArbError(f"无法获取日K计算建议杠杆，已阻止开仓：{exc}") from exc
        if plan.leverage > suggested:
            raise ArbError(
                f"杠杆 {plan.leverage:g}x 超过建议杠杆 {suggested}x"
                f"（近两年单日最大振幅 {amplitude:.1%}），已阻止开仓"
            )

        position_id = self.db.create_arb_position(
            {
                "pair": plan.pair,
                "symbol": plan.symbol,
                "inst_spot": plan.inst_spot,
                "inst_perp": plan.inst_perp,
                "direction": plan.direction,
                "status": "opening",
                "notional_usd": plan.perp_notional,
                "spot_qty": plan.spot_qty,
                "perp_contracts": plan.perp_contracts,
                "ct_val": plan.ct_val,
                "leverage": plan.leverage,
                "spot_entry_px": plan.spot_price,
                "perp_entry_px": plan.perp_price,
                "demo": 1 if self.client.demo else 0,
                "note": note,
            }
        )
        self.db.add_arb_event(
            position_id, "open_requested",
            detail=(
                f"{plan.pair} {direction} 每腿≈${plan.perp_notional:,.0f} "
                f"杠杆{plan.leverage:g}x 预计年化{plan.expected_annual:.2%}"
            ),
        )
        try:
            self.client.set_leverage(plan.inst_perp, int(plan.leverage), mgn_mode="cross")
        except OkxError as exc:
            self.db.add_arb_event(
                position_id, "set_leverage_failed", level="warn", detail=str(exc)[:200]
            )

        # Safe leg first: spot only (long) or spot short (margin, but bounded),
        # so a failed perp leg can be rolled back.
        spot_td_mode = "cash" if plan.spot_side == "buy" else "cross"
        spot_ok = self._place(
            position_id, "spot", plan.inst_spot, plan.spot_side, ordertype,
            plan.spot_qty, plan.spot_price,
            tgt_ccy="base_ccy" if plan.spot_side == "buy" else None,
            td_mode=spot_td_mode,
        )
        if spot_ok is None:
            self.db.update_arb_position(position_id, status="error", note="现货腿下单失败")
            return self.db.get_arb_position(position_id) or {}

        perp_ok = self._place(
            position_id, "perp", plan.inst_perp, plan.perp_side, ordertype,
            plan.perp_contracts, plan.perp_price,
        )
        if perp_ok is None:
            self.db.add_arb_event(
                position_id, "rollback_spot", level="warn", detail="永续腿失败，回滚现货腿"
            )
            self._place(
                position_id, "spot", plan.inst_spot,
                "sell" if plan.spot_side == "buy" else "buy", "market",
                plan.spot_qty, plan.spot_price,
                tgt_ccy="base_ccy" if plan.spot_side == "buy" else None,
                td_mode=spot_td_mode,
            )
            self.db.update_arb_position(
                position_id, status="error", note="永续腿失败，已回滚现货腿"
            )
            return self.db.get_arb_position(position_id) or {}

        self.db.update_arb_position(position_id, status="open")
        self.db.add_arb_event(position_id, "opened", detail="双腿已建仓")
        return self.db.get_arb_position(position_id) or {}

    def close_position(self, position_id: int) -> dict[str, Any]:
        if not trade_enabled(self.db):
            raise ArbError("下单未开启：请先在套利页开启交易并确认风险")
        pos = self.db.get_arb_position(position_id)
        if not pos:
            raise ArbError("持仓不存在")
        if pos["status"] != "open":
            raise ArbError(f"持仓状态为 {pos['status']}，无法平仓")
        self.db.update_arb_position(position_id, status="closing")
        direction = pos.get("direction") or DIRECTION_LONG_SPOT
        spot_side, perp_side = _leg_sides(direction)
        spot_long = spot_side == "buy"
        perp_long = perp_side == "buy"

        # Unwind the perp leg first: it is the one carrying liquidation risk.
        perp_px = float(self.client.ticker(pos["inst_perp"]).get("last") or pos["perp_entry_px"] or 0)
        self._place(
            position_id, "perp", pos["inst_perp"],
            "sell" if perp_long else "buy", "market",
            pos["perp_contracts"], perp_px, reduce_only=True,
        )
        spot_px = float(self.client.ticker(pos["inst_spot"]).get("last") or pos["spot_entry_px"] or 0)
        self._place(
            position_id, "spot", pos["inst_spot"],
            "sell" if spot_long else "buy", "market",
            pos["spot_qty"], spot_px,
            tgt_ccy="base_ccy" if not spot_long else None,
            td_mode="cash" if spot_long else "cross",
        )

        spot_move = (spot_px - (pos["spot_entry_px"] or spot_px)) * pos["spot_qty"]
        perp_move = (perp_px - (pos["perp_entry_px"] or perp_px)) * pos["perp_contracts"] * pos["ct_val"]
        spot_pnl = spot_move if spot_long else -spot_move
        perp_pnl = perp_move if perp_long else -perp_move
        realized = spot_pnl + perp_pnl + (pos.get("funding_accrued") or 0.0)
        self.db.update_arb_position(
            position_id,
            status="closed",
            spot_close_px=spot_px,
            perp_close_px=perp_px,
            realized_pnl=round(realized, 6),
            closed_at=utcnow_iso(),
        )
        self.db.add_arb_event(
            position_id, "closed", detail=f"已平双腿，估算盈亏 ${realized:,.2f}"
        )
        return self.db.get_arb_position(position_id) or {}

    # -------------------------------------------------------------- monitor
    def _funding_since(self, inst_id: str, since_ms: int, notional_usd: float) -> float:
        """Accrued funding for a short perp leg since ``since_ms`` (positive = income).

        OKX ``before`` returns records *older* than the cursor, so we walk
        backwards from the newest settlement until we pass ``since_ms``.
        """
        total = 0.0
        before: int | None = None
        for _ in range(20):  # bounded paging
            page = self.client.funding_rate_history(inst_id, before=before, limit=100)
            if not page:
                break
            oldest: int | None = None
            for item in page:
                try:
                    ts = int(item.get("fundingTime") or 0)
                    rate = float(item.get("fundingRate") or 0)
                except (TypeError, ValueError):
                    continue
                oldest = ts if oldest is None else min(oldest, ts)
                if ts >= since_ms:
                    total += rate
            if oldest is None or oldest <= since_ms or len(page) < 100:
                break
            before = oldest
        return round(total * notional_usd, 6)

    def refresh(self, position_id: int) -> dict[str, Any]:
        pos = self.db.get_arb_position(position_id)
        if not pos:
            raise ArbError("持仓不存在")
        if pos["status"] != "open":
            return pos

        fields: dict[str, Any] = {}
        try:
            live = [p for p in self.client.positions("SWAP") if p.get("instId") == pos["inst_perp"]]
        except OkxError:
            live = []
        if live:
            mark = float(live[0].get("markPx") or 0)
            liq = float(live[0].get("liqPx") or 0)
            if mark:
                fields["mark_px"] = mark
                if liq:
                    fields["liq_distance_pct"] = round(abs(mark - liq) / mark, 6)

        mark = fields.get("mark_px") or pos.get("perp_entry_px") or 0
        perp_base = pos["perp_contracts"] * pos["ct_val"]
        fields["delta_usd"] = round((pos["spot_qty"] - perp_base) * mark, 6)
        since_ms = _iso_to_ms(pos.get("created_at"))
        if since_ms:
            accrued = self._funding_since(
                pos["inst_perp"], since_ms, pos.get("notional_usd") or 0.0
            )
            # `_funding_since` assumes a short perp (receives positive funding);
            # the mirror trade is long the perp, so it pays instead.
            if (pos.get("direction") or DIRECTION_LONG_SPOT) == DIRECTION_SHORT_SPOT:
                accrued = -accrued
            fields["funding_accrued"] = accrued
        self.db.update_arb_position(position_id, **fields)
        return self.db.get_arb_position(position_id) or pos

    def maybe_unwind(self) -> list[dict[str, Any]]:
        """Close any open position whose risk trigger has tripped."""
        if not trade_enabled(self.db):
            return []
        limits = risk_params(self.db)
        warn_liq = limits["warn_liq_distance_pct"]
        max_delta = limits["max_delta_pct"]
        unwound: list[dict[str, Any]] = []
        for pos in self.db.list_arb_positions(status="open"):
            try:
                fresh = self.refresh(pos["id"])
            except ArbError:
                continue
            liq = fresh.get("liq_distance_pct")
            delta_pct = abs(fresh.get("delta_usd") or 0) / max(fresh.get("notional_usd") or 0.0, 1e-9)
            reason = None
            if liq is not None and liq < warn_liq:
                reason = f"爆仓距离过低 {liq:.2%} < {warn_liq:.2%}"
            elif delta_pct > max_delta:
                reason = f"delta 偏离过大 {delta_pct:.2%} > {max_delta:.2%}"
            if not reason:
                continue
            self.db.add_arb_event(pos["id"], "auto_unwind", level="warn", detail=reason)
            try:
                self.close_position(pos["id"])
            except ArbError as exc:
                self.db.add_arb_event(
                    pos["id"], "auto_unwind_failed", level="error", detail=str(exc)[:200]
                )
                continue
            unwound.append({"id": pos["id"], "pair": pos["pair"], "reason": reason})
        return unwound
