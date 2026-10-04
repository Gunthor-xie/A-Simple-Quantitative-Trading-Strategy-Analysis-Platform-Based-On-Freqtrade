from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.cascade_features import (
    CascadeFeatureError,
    build_features,
    cascade_events,
    feature_file_name,
    feature_path,
    load_features,
    write_features,
)


BAR_MS = 60_000
BASE_TS = 1_756_684_800_000  # 2025-09-01 00:00:00 UTC


def make_klines(minutes: int = 400, *, drop_at: int = 300, drop_pct: float = 0.004) -> pd.DataFrame:
    """Flat market with one sharp sell-off that reverts two bars later."""
    rng = np.random.default_rng(7)
    price = np.full(minutes, 100_000.0) * (1 + 0.00015 * rng.standard_normal(minutes))
    for i in range(drop_at, minutes):
        if i < drop_at + 2:
            price[i] = price[i - 1] * (1 - drop_pct)
        elif i < drop_at + 8:
            price[i] = price[i - 1] * (1 + drop_pct / 3)
        else:
            price[i] = price[i - 1]
    open_time = BASE_TS + np.arange(minutes) * BAR_MS
    frame = pd.DataFrame(
        {
            "open_time": open_time,
            "open": price,
            "high": price * 1.0002,
            "low": price * 0.9998,
            "close": price,
            "volume": 10.0,
            "quote_volume": 100.0,
            "count": 500,
            "taker_buy_volume": 5.0,
            "taker_buy_quote_volume": 50.0,
        }
    )
    frame.loc[drop_at, ["low"]] = price[drop_at] * 0.9985
    frame.loc[drop_at, "taker_buy_quote_volume"] = 12.0  # heavy aggressive selling
    frame.loc[drop_at, "quote_volume"] = 200.0
    return frame


def make_metrics(minutes: int = 400, *, drop_at: int = 300) -> pd.DataFrame:
    rows = []
    for minute in range(0, minutes, 5):
        oi = 90_000.0
        if minute >= drop_at:
            oi = 89_000.0
        rows.append(
            {
                "create_time": pd.to_datetime(BASE_TS + minute * BAR_MS, unit="ms", utc=True),
                "symbol": "BTCUSDT",
                "sum_open_interest": oi,
                "sum_open_interest_value": oi * 100_000,
                "count_toptrader_long_short_ratio": 2.0,
                "sum_toptrader_long_short_ratio": 1.9,
                "count_long_short_ratio": 2.1,
                "sum_taker_long_short_vol_ratio": 0.6,
            }
        )
    return pd.DataFrame(rows)


def make_depth(minutes: int = 400, *, level_bid: float = 100.0, level_ask: float = 100.0) -> pd.DataFrame:
    rows = []
    for minute in range(minutes):
        for offset in (7, 53):  # two snapshots per minute, as in the real archive
            stamp = BASE_TS + minute * BAR_MS + offset * 1000
            for percentage in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):
                notional = level_bid if percentage < 0 else level_ask
                if percentage == -1 and minute == 300:
                    notional = level_bid * 0.5  # bids thin out during the flush
                rows.append(
                    {"timestamp": stamp, "percentage": percentage, "depth": notional / 100_000, "notional": notional}
                )
    return pd.DataFrame(rows)


def make_trades(minutes: int = 400, *, drop_at: int = 300) -> pd.DataFrame:
    rows = []
    for minute in range(minutes):
        for step in range(4):
            seller = minute == drop_at
            rows.append(
                {
                    "agg_trade_id": minute * 10 + step,
                    "price": 100_000.0,
                    "quantity": 0.25 if seller else 0.1,
                    "first_trade_id": 0,
                    "last_trade_id": 0,
                    "transact_time": BASE_TS + minute * BAR_MS + step * 10_000,
                    "is_buyer_maker": seller,
                }
            )
    return pd.DataFrame(rows)


def make_liquidations(
    minutes: int = 400, *, burst_at: int = 300, burst_side: str = "long"
) -> pd.DataFrame:
    rows = []
    for minute in range(minutes):
        notional = 1_000.0
        if minute % 7 == 0:
            notional = 20_000.0
        if minute == burst_at:
            notional = 5_000_000.0
        rows.append(
            {
                "date": BASE_TS + minute * BAR_MS + 1_000,
                "side": burst_side if minute == burst_at else ("long" if minute % 3 else "short"),
                "notional": notional,
            }
        )
    return pd.DataFrame(rows)


def test_feature_file_naming(tmp_path) -> None:
    assert feature_file_name("BTC/USDT:USDT") == "BTC_USDT_USDT-1m-cascade.csv.gz"
    assert feature_path(tmp_path, "ETH/USDT:USDT").name == "ETH_USDT_USDT-1m-cascade.csv.gz"
    assert feature_path(tmp_path, "ETH/USDT:USDT").parent.name == "liquidation"


def test_requires_klines() -> None:
    with pytest.raises(CascadeFeatureError):
        build_features(pd.DataFrame())
    with pytest.raises(CascadeFeatureError):
        build_features(pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]}))


def test_klines_only_still_yields_scores() -> None:
    features = build_features(make_klines())
    assert "cx_ret_1m" in features and "cx_flush_long_score" in features
    assert features["cx_has_liquidations"].max() == 0.0
    # Proxy-only scores must renormalise instead of collapsing to NaN.
    assert features["cx_flush_long_score"].notna().sum() > 300
    assert features["cx_flush_long_score"].max() > 1.0


def test_depth_is_point_in_time_and_imbalance_signed() -> None:
    features = build_features(make_klines(), depth=make_depth())
    # Bar 0 close is 00:00:59; the last snapshot inside the bar is 00:00:53.
    assert features.loc[0, "cx_bid_depth_usd_1pct"] == pytest.approx(100.0)
    assert features.loc[0, "cx_depth_imbalance_1pct"] == pytest.approx(0.0)
    # Thin bids during the flush push the imbalance negative.
    flush_bar = 300
    assert features.loc[flush_bar, "cx_bid_depth_usd_1pct"] == pytest.approx(50.0)
    assert features.loc[flush_bar, "cx_depth_imbalance_1pct"] < -0.3
    assert features.loc[flush_bar, "cx_bid_depth_change_1m"] < 0


def test_trades_refine_taker_imbalance() -> None:
    klines = make_klines()
    features = build_features(klines, trades=make_trades())
    flush_bar = 300
    # 4 seller-aggressor trades of 0.25 vs 3 buyer trades of 0.1 elsewhere.
    assert features.loc[flush_bar, "cx_taker_imbalance"] < -0.9
    assert features.loc[flush_bar - 1, "cx_taker_imbalance"] > 0.9
    assert features.loc[flush_bar, "cx_cvd_1m"] < 0
    # The synthetic ticks all print at 100k while the bar closed lower.
    expected_gap = 100_000.0 / float(klines.loc[flush_bar, "close"]) - 1.0
    assert features.loc[flush_bar, "cx_trade_vwap_gap_pct"] == pytest.approx(expected_gap, rel=1e-6)


def test_liquidation_percentile_marks_the_cascade_bar() -> None:
    features = build_features(
        make_klines(),
        metrics=make_metrics(),
        depth=make_depth(),
        liquidations=make_liquidations(),
    )
    flush_bar = 300
    assert features["cx_has_liquidations"].max() == 1.0
    assert features.loc[flush_bar, "cx_liq_long_usd"] > 0
    assert features.loc[flush_bar, "cx_liq_ratio_1h"] > 1.0
    assert features.loc[flush_bar, "cx_liq_z_1h"] > 1.0
    # A quiet bar stays below its own trailing 95th percentile.
    assert features.loc[flush_bar - 1, "cx_liq_ratio_1h"] < 1.0


def test_features_are_causal() -> None:
    """Recomputing on a prefix must not change the last row."""
    klines, metrics, depth, trades, liquidations = (
        make_klines(),
        make_metrics(),
        make_depth(),
        make_trades(),
        make_liquidations(),
    )
    full = build_features(
        klines, metrics=metrics, depth=depth, trades=trades, liquidations=liquidations
    )
    for cut in (40, 41, 120, 299, 301, 399):
        partial = build_features(
            klines.head(cut),
            metrics=metrics,
            depth=depth,
            trades=trades,
            liquidations=liquidations,
        )
        left = full.iloc[cut - 1].drop(labels=["date"])
        right = partial.iloc[-1].drop(labels=["date"])
        for column in left.index:
            a, b = left[column], right[column]
            if pd.isna(a) and pd.isna(b):
                continue
            assert a == pytest.approx(b, rel=1e-9, abs=1e-12), f"{column} changed at cut={cut}"


def test_round_trip_and_event_reporting(tmp_path) -> None:
    features = build_features(
        make_klines(),
        metrics=make_metrics(),
        depth=make_depth(),
        trades=make_trades(),
        liquidations=make_liquidations(),
    )
    path = write_features(features, tmp_path / feature_file_name("BTC/USDT:USDT"))
    restored = load_features(path)
    assert list(restored.columns) == list(features.columns)
    assert len(restored) == len(features)
    assert restored["cx_flush_long_score"].iloc[300] == pytest.approx(
        features["cx_flush_long_score"].iloc[300], rel=1e-8
    )

    events = cascade_events(restored, side="long", move_pct=0.002, flush_score=1.0)
    assert len(events) >= 1
    assert int(events["date"].iloc[0]) >= BASE_TS + 300 * BAR_MS


def test_load_missing_file_raises(tmp_path) -> None:
    with pytest.raises(CascadeFeatureError):
        load_features(tmp_path / "nope.csv.gz")
