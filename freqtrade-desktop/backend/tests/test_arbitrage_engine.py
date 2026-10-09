from __future__ import annotations

import pytest

from app.services.arbitrage_engine import ArbError, ArbitrageEngine
from app.services.okx_client import OkxError
from app.storage import Database


BASE = 1_767_225_600_000  # 2026-01-01 00:00 UTC
HOUR = 3_600_000


class FakeClient:
    """Minimal stand-in for OkxClient covering exactly what the engine calls."""

    demo = True

    def __init__(self, *, fail_perp: bool = False, fail_spot: bool = False,
                 mark_px: float = 100_000.0, liq_px: float = 8_000.0,
                 daily_rows: list | None = None) -> None:
        self.fail_perp = fail_perp
        self.fail_spot = fail_spot
        self.mark_px = mark_px
        self.liq_px = liq_px
        self.daily_rows = daily_rows or []
        self.orders: list[dict] = []
        self.leverage: list[tuple] = []

    def instruments(self, inst_type: str) -> list[dict]:
        if inst_type == "SPOT":
            return [{"instId": "BTC-USDT", "lotSz": "0.00000001", "minSz": "0.00001"}]
        return [{"instId": "BTC-USDT-SWAP", "lotSz": "0.01", "minSz": "0.01", "ctVal": "0.01"}]

    def ticker(self, inst_id: str) -> dict:
        return {"last": "100000"}

    def funding_rate(self, inst_id: str) -> dict:
        return {
            "fundingRate": "0.0001",
            "fundingTime": str(BASE),
            "nextFundingTime": str(BASE + 8 * HOUR),
        }

    def candles(self, inst_id: str, bar: str = "1D", limit: int = 100,
                after: int | None = None) -> list[list]:
        return self.daily_rows

    def set_leverage(self, inst_id, lever, mgn_mode="cross", pos_side=None) -> list[dict]:
        self.leverage.append((inst_id, lever, mgn_mode))
        return [{}]

    def place_order(self, inst_id, side, ordertype, sz, *, px=None, td_mode="cross",
                    pos_side=None, reduce_only=False, cl_ord_id=None, tgt_ccy=None) -> dict:
        # Record the attempt even when it is rejected, so tests can assert the
        # exact sequence of calls the engine made.
        self.orders.append(
            {"inst_id": inst_id, "side": side, "sz": sz, "reduce_only": reduce_only,
             "tgt_ccy": tgt_ccy}
        )
        if self.fail_spot and inst_id == "BTC-USDT" and side == "buy":
            raise OkxError("spot rejected")
        if self.fail_perp and inst_id == "BTC-USDT-SWAP" and side == "sell":
            raise OkxError("perp rejected")
        return {"ordId": f"o{len(self.orders)}"}

    def positions(self, inst_type: str | None = None) -> list[dict]:
        return [{"instId": "BTC-USDT-SWAP", "markPx": str(self.mark_px), "liqPx": str(self.liq_px)}]

    def funding_rate_history(self, inst_id, *, after=None, before=None, limit=100) -> list[dict]:
        return [{"fundingTime": str(BASE + i * 8 * HOUR), "fundingRate": "0.0001"} for i in (2, 1, 0)]

    def close(self) -> None:
        pass


@pytest.fixture()
def store(tmp_path) -> Database:
    return Database(tmp_path / "arb.db")


def _enabled(store: Database) -> None:
    store.set_setting("arb_trade_enabled", "1")


def _engine(store: Database, client: FakeClient) -> ArbitrageEngine:
    return ArbitrageEngine(client, store)


def test_plan_sizing(store: Database) -> None:
    plan = _engine(store, FakeClient()).plan("BTC/USDT:USDT", 1000, leverage=3)
    assert plan.inst_spot == "BTC-USDT"
    assert plan.inst_perp == "BTC-USDT-SWAP"
    # 1000 / (1 + 1/3) = 750 per leg
    assert plan.spot_notional == pytest.approx(750)
    assert plan.perp_notional == pytest.approx(750)
    assert plan.spot_qty == pytest.approx(0.0075)
    assert plan.perp_contracts == pytest.approx(0.75)


def test_open_requires_enabled(store: Database) -> None:
    client = FakeClient()
    with pytest.raises(ArbError):
        _engine(store, client).open_position("BTC/USDT:USDT", 1000)
    assert client.orders == []


def test_open_places_spot_then_perp(store: Database) -> None:
    _enabled(store)
    client = FakeClient()
    pos = _engine(store, client).open_position("BTC/USDT:USDT", 1000, leverage=3)
    assert pos["status"] == "open"
    assert [o["inst_id"] for o in client.orders] == ["BTC-USDT", "BTC-USDT-SWAP"]
    assert client.orders[0]["side"] == "buy" and client.orders[0]["tgt_ccy"] == "base_ccy"
    assert client.orders[1]["side"] == "sell"
    assert client.leverage and client.leverage[0][1] == 3
    legs = store.list_arb_legs(pos["id"])
    assert {leg["kind"] for leg in legs} == {"spot", "perp"}
    assert all(leg["status"] == "placed" for leg in legs)


def test_perp_failure_rolls_back_spot(store: Database) -> None:
    _enabled(store)
    client = FakeClient(fail_perp=True)
    pos = _engine(store, client).open_position("BTC/USDT:USDT", 1000, leverage=3)
    assert pos["status"] == "error"
    # spot buy -> perp sell (rejected) -> spot sell rollback
    assert [(o["inst_id"], o["side"]) for o in client.orders] == [
        ("BTC-USDT", "buy"),
        ("BTC-USDT-SWAP", "sell"),
        ("BTC-USDT", "sell"),
    ]
    assert any(e["event"] == "rollback_spot" for e in store.list_arb_events(pos["id"]))
    legs = store.list_arb_legs(pos["id"])
    assert any(leg["status"] == "failed" and leg["kind"] == "perp" for leg in legs)


def test_spot_failure_aborts_without_perp(store: Database) -> None:
    _enabled(store)
    client = FakeClient(fail_spot=True)
    pos = _engine(store, client).open_position("BTC/USDT:USDT", 1000)
    assert pos["status"] == "error"
    assert [o["inst_id"] for o in client.orders] == ["BTC-USDT"]


def test_close_position(store: Database) -> None:
    _enabled(store)
    client = FakeClient()
    engine = _engine(store, client)
    pos = engine.open_position("BTC/USDT:USDT", 1000, leverage=3)
    closed = engine.close_position(pos["id"])
    assert closed["status"] == "closed"
    assert closed["closed_at"]
    # perp buy (reduce-only) then spot sell
    tail = [(o["inst_id"], o["side"]) for o in client.orders[-2:]]
    assert tail == [("BTC-USDT-SWAP", "buy"), ("BTC-USDT", "sell")]
    assert client.orders[-2]["reduce_only"] is True
    assert closed["realized_pnl"] == pytest.approx(0.0)


def test_refresh_computes_delta_and_liquidation_distance(store: Database) -> None:
    _enabled(store)
    client = FakeClient(mark_px=100_000.0, liq_px=8_000.0)
    engine = _engine(store, client)
    pos = engine.open_position("BTC/USDT:USDT", 1000, leverage=3)
    fresh = engine.refresh(pos["id"])
    assert fresh["delta_usd"] == pytest.approx(0.0, abs=1e-6)
    assert fresh["liq_distance_pct"] == pytest.approx((100_000 - 8_000) / 100_000)


def test_funding_since(store: Database) -> None:
    engine = _engine(store, FakeClient())
    value = engine._funding_since("BTC-USDT-SWAP", BASE, 1000.0)
    assert value == pytest.approx(0.0001 * 3 * 1000.0)


def test_maybe_unwind_on_low_liquidation_distance(store: Database) -> None:
    _enabled(store)
    # liq price 1% below mark -> below the 12% warning threshold
    client = FakeClient(mark_px=100_000.0, liq_px=99_000.0)
    engine = _engine(store, client)
    pos = engine.open_position("BTC/USDT:USDT", 1000, leverage=3)
    unwound = engine.maybe_unwind()
    assert [item["id"] for item in unwound] == [pos["id"]]
    assert store.get_arb_position(pos["id"])["status"] == "closed"


def test_maybe_unwind_noop_when_disabled(store: Database) -> None:
    _enabled(store)
    client = FakeClient(mark_px=100_000.0, liq_px=99_000.0)
    engine = _engine(store, client)
    engine.open_position("BTC/USDT:USDT", 1000, leverage=3)
    store.set_setting("arb_trade_enabled", "0")
    assert engine.maybe_unwind() == []


# --------------------------------------------------------------- paper mode
class FakeMarket:
    """Public-market stand-in for the PaperClient's data source."""

    def __init__(self, last: str = "100000") -> None:
        self.last = last

    def ticker(self, inst_id: str) -> dict:
        return {"last": self.last}

    def funding_rate(self, inst_id: str) -> dict:
        return {"fundingRate": "0.0001", "fundingTime": str(BASE), "nextFundingTime": str(BASE + 8 * HOUR)}

    def candles(self, inst_id: str, bar: str = "1D", limit: int = 100,
                after: int | None = None) -> list[list]:
        return []

    def instruments(self, inst_type: str) -> list[dict]:
        if inst_type == "SPOT":
            return [{"instId": "BTC-USDT", "lotSz": "0.00000001", "minSz": "0.00001"}]
        return [{"instId": "BTC-USDT-SWAP", "lotSz": "0.01", "minSz": "0.01", "ctVal": "0.01"}]

    def funding_rate_history(self, inst_id, **kwargs) -> list[dict]:
        return []

    def close(self) -> None:
        pass


def test_build_trade_client_defaults_to_paper(store: Database, monkeypatch) -> None:
    import app.services.okx_client as okx_module

    # Keep the test hermetic: no real proxy probe when the client is built.
    monkeypatch.setattr(okx_module, "resolve_proxy", lambda *a, **k: None)

    from app.services.arbitrage_engine import PaperClient, build_trade_client, exec_mode

    assert exec_mode(store) == "paper"
    client = build_trade_client(store)
    assert isinstance(client, PaperClient)
    assert client.simulated is True


def test_paper_client_simulates_fills(store: Database) -> None:
    from app.services.arbitrage_engine import PaperClient

    paper = PaperClient(store, market=FakeMarket())
    fill = paper.place_order("BTC-USDT-SWAP", "sell", "market", 0.75)
    assert fill["simulated"] is True
    assert fill["ordId"].startswith("paper-")
    assert float(fill["px"]) == pytest.approx(100000)
    assert paper.demo is True
    assert paper.account_config()["role"] == "paper"


def test_paper_client_missing_price_raises(store: Database) -> None:
    from app.services.arbitrage_engine import PaperClient

    paper = PaperClient(store, market=FakeMarket(last="0"))
    with pytest.raises(OkxError):
        paper.place_order("BTC-USDT-SWAP", "sell", "market", 1)


def test_paper_mode_end_to_end(store: Database) -> None:
    from app.services.arbitrage_engine import PaperClient

    _enabled(store)
    engine = ArbitrageEngine(PaperClient(store, market=FakeMarket()), store)
    pos = engine.open_position("BTC/USDT:USDT", 1000, leverage=3)
    assert pos["status"] == "open"
    assert pos["demo"] == 1

    fresh = engine.refresh(pos["id"])
    # spot 0.0075 - perp base (0.75 * 0.01) = 0 -> delta neutral
    assert fresh["delta_usd"] == pytest.approx(0.0, abs=1e-6)
    # liq = entry * (1 + 1/3); mark == entry -> ~33% away, above the 12% warning
    assert fresh["liq_distance_pct"] == pytest.approx(1 / 3, rel=1e-3)

    closed = engine.close_position(pos["id"])
    assert closed["status"] == "closed"
    assert closed["realized_pnl"] == pytest.approx(0.0)
    assert store.list_arb_legs(pos["id"])


# ------------------------------------------------- direction / fee / guardrail
def test_preview_reports_expected_annual_and_guardrail(store: Database) -> None:
    data = _engine(store, FakeClient()).preview("BTC/USDT:USDT", 1000, 3)
    assert data["direction"] == "long_spot_short_perp"
    assert data["spot_side"] == "buy" and data["perp_side"] == "sell"
    # 0.0001 * 3 * 365 = 0.1095, minus 4 * 5bps round-trip fee = 0.0020
    assert data["funding_annualized"] == pytest.approx(0.1095)
    assert data["round_trip_fee"] == pytest.approx(0.002)
    assert data["expected_annual"] == pytest.approx(0.1075)
    # no daily rows -> amplitude 0 -> permissive cap of 5
    assert data["suggested_leverage"] == 5
    assert data["leverage_ok"] is True


def test_mirror_direction_earns_negative_funding(store: Database) -> None:
    data = _engine(store, FakeClient()).preview(
        "BTC/USDT:USDT", 1000, 3, direction="short_spot_long_perp"
    )
    assert data["spot_side"] == "sell" and data["perp_side"] == "buy"
    assert data["expected_annual"] == pytest.approx(-0.1095 - 0.002)


def test_open_blocked_above_suggested_leverage(store: Database) -> None:
    _enabled(store)
    # a 60% worst day -> suggested 1x, so asking for 3x must be refused
    client = FakeClient(daily_rows=[[BASE, 80, 128, 32, 80, 1]])
    with pytest.raises(ArbError):
        _engine(store, client).open_position("BTC/USDT:USDT", 1000, leverage=3)
    assert client.orders == []
    assert store.list_arb_positions() == []


class _NoSpotClient(FakeClient):
    def instruments(self, inst_type: str) -> list[dict]:
        if inst_type == "SPOT":
            return []  # OKX perp exists but there is no spot pair to hedge with
        return super().instruments(inst_type)


class _NoPerpClient(FakeClient):
    def instruments(self, inst_type: str) -> list[dict]:
        if inst_type == "SWAP":
            return []
        return super().instruments(inst_type)


def test_plan_explains_missing_spot_pair(store: Database) -> None:
    # The perp exists but OKX has no spot pair -> cannot build the hedge.
    with pytest.raises(ArbError) as excinfo:
        _engine(store, _NoSpotClient()).plan("BTC/USDT:USDT", 1000)
    assert "没有现货交易对" in str(excinfo.value)


def test_plan_explains_missing_perp(store: Database) -> None:
    with pytest.raises(ArbError) as excinfo:
        _engine(store, _NoPerpClient()).plan("BTC/USDT:USDT", 1000)
    assert "没有对应的永续合约" in str(excinfo.value)


def test_mirror_direction_order_sides(store: Database) -> None:
    _enabled(store)
    client = FakeClient()
    engine = _engine(store, client)
    pos = engine.open_position(
        "BTC/USDT:USDT", 1000, leverage=3, direction="short_spot_long_perp"
    )
    assert pos["direction"] == "short_spot_long_perp"
    assert [(o["inst_id"], o["side"]) for o in client.orders] == [
        ("BTC-USDT", "sell"),
        ("BTC-USDT-SWAP", "buy"),
    ]
    engine.close_position(pos["id"])
    assert [(o["inst_id"], o["side"]) for o in client.orders[-2:]] == [
        ("BTC-USDT-SWAP", "sell"),
        ("BTC-USDT", "buy"),
    ]
