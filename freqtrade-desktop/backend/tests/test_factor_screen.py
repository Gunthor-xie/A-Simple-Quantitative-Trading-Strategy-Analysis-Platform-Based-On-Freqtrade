from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import factor_lib as fl
from app.services import factor_portfolio as fport
from app.services import factor_screen as fs

BAR_MS = 3_600_000
BASE_TS = 1_780_000_000_000 - (1_780_000_000_000 % BAR_MS)


def synthetic_panel(bars: int = 1_500, pairs: int = 10, *, seed: int = 17,
                    block: int = 100, drift_scale: float = 0.0008,
                    noise: float = 0.004) -> pd.DataFrame:
    """Hourly panel with block-persistent drift: momentum is genuinely present.

    The drift is held constant inside each block (~4 days), so a past-window return
    predicts the next window while prices stay in a realistic range.
    """
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(bars / block))
    drift = np.repeat(drift_scale * rng.standard_normal((blocks, pairs)), block, axis=0)[:bars]
    returns = drift + noise * rng.standard_normal((bars, pairs))
    close = 100.0 * np.cumprod(1 + returns, axis=0)
    ts = BASE_TS + np.arange(bars) * BAR_MS
    frames = []
    for index in range(pairs):
        prices = close[:, index]
        frame = pd.DataFrame({
            "ts": ts,
            "pair": f"P{index:02d}/USDT:USDT",
            "open": prices,
            "high": prices * 1.001,
            "low": prices * 0.999,
            "close": prices,
            "volume": 1_000.0,
            "funding_rate": 0.0001,
            "funding_settled": (np.arange(bars) % 8 == 0).astype("int8"),
            "index_close": prices,
        })
        frames.append(frame)
    panel = pd.concat(frames, ignore_index=True)
    panel["dt"] = pd.to_datetime(panel["ts"], unit="ms", utc=True)
    panel["hour"] = panel["dt"].dt.hour.astype("int16")
    panel["dow"] = panel["dt"].dt.dayofweek.astype("int8")
    return panel


def test_rank_ic_is_one_for_perfect_signal():
    rng = np.random.default_rng(2)
    factor = pd.DataFrame(rng.standard_normal((60, 8)))
    fwd = factor.copy()
    ic = fs.rank_ic(factor, fwd, 5)
    assert len(ic) == 60
    assert np.allclose(ic.to_numpy(), 1.0)


def test_rank_ic_needs_enough_pairs():
    rng = np.random.default_rng(3)
    factor = pd.DataFrame(rng.standard_normal((10, 4)))
    fwd = pd.DataFrame(rng.standard_normal((10, 4)))
    assert fs.rank_ic(factor, fwd, min_pairs=5).empty
    assert len(fs.rank_ic(factor, fwd, min_pairs=4)) == 10


def test_newey_west_flags_noise_and_signal():
    rng = np.random.default_rng(4)
    noise = pd.Series(rng.standard_normal(400))
    t_noise, p_noise = fs.newey_west_t(noise, 5)
    assert abs(t_noise) < 3
    assert p_noise > 0.05

    signal = pd.Series(0.02 + 0.05 * rng.standard_normal(400))
    t_signal, p_signal = fs.newey_west_t(signal, 5)
    assert t_signal > 5
    assert p_signal < 1e-3


def test_bh_fdr_is_monotone_in_p():
    q = fs.bh_fdr({"a": 0.001, "b": 0.01, "c": 0.2, "d": 0.9})
    assert q["a"] <= q["b"] <= q["c"] <= q["d"]
    assert q["a"] == pytest.approx(0.004)
    assert q["d"] <= 1.0
    assert fs.bh_fdr({}) == {}


def test_on_grid_keeps_time_cadence_for_sparse_factors():
    index = pd.Index(BASE_TS + np.arange(100) * BAR_MS)
    sparse = pd.Series(index[::24], index=index[::24], dtype="float64")
    kept = fs.on_grid(sparse, index, 24)
    assert len(kept) == len(sparse)  # already on the daily grid, not thinned to 1


def test_momentum_detected_and_noise_rejected():
    panel = synthetic_panel()
    wide = fl.make_wide(panel)
    factors = fl.compute_factors(wide, ["mom_1d", "mom_7d"])
    rng = np.random.default_rng(8)
    factors["noise"] = pd.DataFrame(rng.standard_normal(wide.close.shape),
                                    index=wide.close.index, columns=wide.close.columns)
    report = fs.screen_all(factors, wide.close, fs.ScreenConfig(
        horizon_bars=24, train_obs=20, test_obs=5, min_pairs=5, min_coverage=0.3))

    momentum = report["results"]["mom_1d"]
    assert momentum["ic_mean"] > 0
    assert momentum["ic_t_nw"] > 3
    assert momentum["fdr_q"] < 0.1
    assert momentum["verdict"] == "promising"

    noise = report["results"]["noise"]
    assert noise["verdict"] == "rejected"
    assert abs(noise["ic_mean"]) < 0.1


def test_verdict_reports_every_failed_gate():
    record = {"window_positive_frac": 0.4, "ic_t_nw": 1.0, "max_drawdown": -0.5}
    state, reasons = fs.verdict(record, 0.5, fs.ScreenConfig())
    assert state == "rejected"
    assert len(reasons) == 4


def test_portfolio_is_dollar_neutral_and_cost_sensitive():
    panel = synthetic_panel(bars=1_200)
    wide = fl.make_wide(panel)
    factors = fl.compute_factors(wide, ["mom_1d"])
    composite = fport.build_composite(factors, ["mom_1d"])
    settled = pd.DataFrame(
        np.broadcast_to((np.arange(len(wide.close.index)) % 8 == 0)[:, None].astype(float),
                        wide.close.shape),
        index=wide.close.index, columns=wide.close.columns)
    cheap = fport.simulate(wide.close, composite, funding=wide.funding,
                           funding_settled=settled,
                           cfg=fport.PortfolioConfig(k=2, fee_bps=5, slippage_bps=2))
    pricey = fport.simulate(wide.close, composite, funding=wide.funding,
                            funding_settled=settled,
                            cfg=fport.PortfolioConfig(k=2, fee_bps=30, slippage_bps=10))

    assert cheap["stats"]["periods"] > 20
    assert cheap["stats"]["total_return"] > pricey["stats"]["total_return"]
    assert cheap["leverage"].max() <= 2.0 + 1e-9
    assert cheap["mean_turnover"] > 0


def test_portfolio_charges_funding_only_at_settlements():
    """A funding spread between the long and short legs must show up as a cost."""
    bars, pairs = 240, 2
    ts = BASE_TS + np.arange(bars) * BAR_MS
    prices = np.linspace(100, 101, bars)
    close = pd.DataFrame({f"P{i}/USDT:USDT": prices for i in range(pairs)},
                         index=pd.Index(ts))
    # Asset 0 is always ranked above asset 1 -> long 0 / short 1.
    composite = pd.DataFrame({"P0/USDT:USDT": 1.0, "P1/USDT:USDT": -1.0},
                             index=pd.Index(ts))
    funding = pd.DataFrame({"P0/USDT:USDT": 0.0005, "P1/USDT:USDT": -0.0005},
                           index=pd.Index(ts))
    settled = pd.DataFrame(
        np.broadcast_to((np.arange(bars) % 8 == 0)[:, None].astype(float),
                        (bars, pairs)),
        index=pd.Index(ts), columns=close.columns)
    result = fport.simulate(close, composite, funding=funding, funding_settled=settled,
                            cfg=fport.PortfolioConfig(k=1, target_vol=10.0,
                                                      max_leverage=1.0, rebalance_bars=24))
    # Funding P&L is -w*f: the long pays a positive rate (+0.25bp on a 0.5 weight)
    # and the short pays a negative rate (+0.25bp on a -0.5 weight) -> +0.0005 per
    # settlement event, three settlements per 24h holding window.
    assert result["funding_total"] > 0
    assert result["funding_total"] == pytest.approx(
        0.0005 * 3 * len(result["returns"]), rel=0.1)


def test_capacity_estimate_uses_adv_cap():
    panel = synthetic_panel(bars=900)
    wide = fl.make_wide(panel)
    composite = fport.build_composite(fl.compute_factors(wide, ["mom_1d"]), ["mom_1d"])
    adv = fport.trailing_adv(wide.volume, wide.close)
    result = fport.simulate(wide.close, composite, adv=adv,
                            cfg=fport.PortfolioConfig(k=2, max_adv_share=0.005,
                                                      min_adv_usd=0.0))
    # Daily ADV ~ 1000 * 100 * 24 = 2.4M; 0.5% of it over a 50% notional weight
    # (0.5/k with k=2, times the 2x leverage cap) bounds the book at ~24,000 USD.
    assert result["capacity_usd"] is not None
    assert 5_000 < result["capacity_usd"] < 100_000


def test_performance_summary_math():
    returns = pd.Series([0.01] * 100)
    stats = fport.performance(returns, periods_per_year=365)
    assert stats["total_return"] == pytest.approx(1.01 ** 100 - 1)
    assert stats["max_drawdown"] == pytest.approx(0.0)
    assert stats["hit_rate"] == 1.0
    assert fport.performance(pd.Series(dtype="float64")) == {"periods": 0}


def test_walk_forward_composite_never_uses_future_data():
    """Changing the future must not change the composite on the same past rows."""
    panel = synthetic_panel(bars=1_200, seed=21)
    wide = fl.make_wide(panel)
    factors = fl.compute_factors(wide, ["mom_1d"])
    full = fport.walk_forward_composite(wide.close, factors, ["mom_1d"])

    cut = 900
    cutoff_ts = wide.close.index[cut - 1]
    truncated = fl.make_wide(panel[panel["ts"] <= cutoff_ts])
    prefix_factors = fl.compute_factors(truncated, ["mom_1d"])
    prefix = fport.walk_forward_composite(truncated.close, prefix_factors, ["mom_1d"])

    # Drop the final horizon worth of rows: the prefix sample has no forward returns
    # there, so those ICs are legitimately incomplete.
    shared = prefix.index[: len(prefix.index) - 25]
    assert len(shared) > 100
    pd.testing.assert_frame_equal(full.reindex(shared), prefix.reindex(shared),
                                  check_freq=False)


def test_walk_forward_orientation_flips_a_wrong_prior():
    """When the prior direction is wrong, the causal orientation must correct it."""
    panel = synthetic_panel(bars=1_500, seed=5)
    wide = fl.make_wide(panel)
    momentum = fl.compute_factors(wide, ["mom_1d"])["mom_1d"]
    # Negate the factor: now the economic prior (+1) points the wrong way.
    flipped = {"mom_1d": -momentum}
    composite = fport.walk_forward_composite(wide.close, flipped, ["mom_1d"])
    fwd = fs.forward_returns(wide.close, 24)
    ic = fs.rank_ic(composite, fwd, 5)
    assert float(ic.mean()) > 0.1
