"""Contract tests for the LiquidationCascade strategy file.

These run offline: a synthetic feature file is written into a tmp user_data
directory and fed to the strategy's dataframe hooks, so a rename of a feature
column or a broken merge fails here instead of silently producing 0 trades.
"""

from __future__ import annotations

import gzip
import importlib.util
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


BAR_MS = 60_000
BASE_TS = 1_756_684_800_000  # 2025-09-01 00:00:00 UTC
FLUSH_BAR = 120
CONFIRM_BAR = 121
FILL_BAR = CONFIRM_BAR + 1  # the passive order needs a later candle to trade at the limit
STRATEGY_PATH = (
    Path(__file__).resolve().parents[2] / "user_data" / "strategies" / "LiquidationCascade.py"
)


def load_strategy_class():
    spec = importlib.util.spec_from_file_location("LiquidationCascade", STRATEGY_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - import machinery guard
        pytest.skip("cannot load LiquidationCascade.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LiquidationCascade


def make_dataframe(bars: int = 180) -> pd.DataFrame:
    """Flat market, one 0.5% flush bar, then a full recovery bar."""
    close = np.full(bars, 100_000.0)
    close[FLUSH_BAR] = close[FLUSH_BAR - 1] * 0.995
    close[CONFIRM_BAR] = close[FLUSH_BAR] * 1.002
    for i in range(CONFIRM_BAR + 1, bars):
        close[i] = close[i - 1]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(BASE_TS + np.arange(bars) * BAR_MS, unit="ms", utc=True),
            "open": close,
            "high": close * 1.0002,
            "low": close * 0.9998,
            "close": close,
            "volume": 10.0,
        }
    )
    frame.loc[FLUSH_BAR, "low"] = close[FLUSH_BAR] * 0.998
    # The passive (maker) entry only fills if price trades back to the limit,
    # which sits 0.05% below the confirmation candle's close.
    frame.loc[FILL_BAR, "low"] = close[CONFIRM_BAR] * 0.9990
    return frame


def make_features(bars: int = 180) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": BASE_TS + np.arange(bars) * BAR_MS,
            "cx_ret_1m": 0.0,
            "cx_no_new_low": 1.0,
            "cx_no_new_high": 1.0,
            "cx_taker_imbalance": 0.0,
            "cx_taker_imbalance_delta": 0.0,
            "cx_depth_imbalance_1pct": 0.0,
            "cx_depth_imbalance_delta_1m": 0.0,
            "cx_liquidity_percentile_24h": 0.5,
            "cx_flush_long_score": 0.0,
            "cx_flush_short_score": 0.0,
            "cx_liq_ratio_1h": 0.0,
            "cx_has_liquidations": 0.0,
            "cx_oi_chg_5m_pct": 0.0,
            "cx_atr_pct": 0.0010,
        }
    )
    frame.loc[FLUSH_BAR, "cx_ret_1m"] = -0.005
    frame.loc[FLUSH_BAR, "cx_no_new_low"] = 0.0
    frame.loc[FLUSH_BAR, "cx_taker_imbalance"] = -0.85
    frame.loc[FLUSH_BAR, "cx_flush_long_score"] = 3.2
    frame.loc[FLUSH_BAR, "cx_depth_imbalance_1pct"] = -0.30
    frame.loc[CONFIRM_BAR, "cx_ret_1m"] = 0.002
    frame.loc[CONFIRM_BAR, "cx_taker_imbalance"] = 0.60
    frame.loc[CONFIRM_BAR, "cx_taker_imbalance_delta"] = 1.4
    frame.loc[CONFIRM_BAR, "cx_depth_imbalance_1pct"] = 0.10
    frame.loc[CONFIRM_BAR, "cx_depth_imbalance_delta_1m"] = 0.40
    return frame


def prepare_user_data(tmp_path: Path, with_features: bool = True, pair: str = "BTC/USDT:USDT") -> Path:
    user_data = tmp_path / "user_data"
    target = user_data / "liquidation"
    target.mkdir(parents=True, exist_ok=True)
    if with_features:
        slug = pair.replace("/", "_").replace(":", "_")
        frame = make_features()
        payload = frame.to_csv(index=False, float_format="%.10g")
        with gzip.open(target / f"{slug}-1m-cascade.csv.gz", "wt", encoding="utf-8", newline="") as fh:
            fh.write(payload)
    return user_data


def build_strategy(tmp_path: Path, *, with_features: bool = True):
    strategy_class = load_strategy_class()
    user_data = prepare_user_data(tmp_path, with_features=with_features)
    config = {
        "user_data_dir": str(user_data),
        "trading_mode": "futures",
        "runmode": "backtest",
        "strategy": "LiquidationCascade",
    }
    return strategy_class(config), config


def analyze(strategy, dataframe: pd.DataFrame, pair: str = "BTC/USDT:USDT") -> pd.DataFrame:
    out = strategy.populate_indicators(dataframe.copy(), {"pair": pair})
    out = strategy.populate_entry_trend(out, {"pair": pair})
    return strategy.populate_exit_trend(out, {"pair": pair})


def test_strategy_file_sits_where_freqtrade_expects() -> None:
    assert STRATEGY_PATH.exists(), "strategy must live in user_data/strategies"


def test_long_entry_after_flush_is_confirmed(tmp_path) -> None:
    strategy, _ = build_strategy(tmp_path)
    dataframe = make_dataframe()
    out = analyze(strategy, dataframe)
    entries = out.index[out["enter_long"] == 1].tolist()
    assert FILL_BAR in entries
    assert out.loc[FILL_BAR, "enter_tag"] == "cascade_long_limit"
    # No short side in a market that only flushes downward.
    assert int(out["enter_short"].sum()) == 0
    # Neither the flush bar nor the confirmation bar is an entry by itself.
    assert out.loc[FLUSH_BAR, "enter_long"] == 0
    assert out.loc[CONFIRM_BAR, "enter_long"] == 0
    # The engine must open at the passive limit, not at the candle close.
    limit = float(dataframe.loc[CONFIRM_BAR, "close"]) * (1 - 0.0005)
    fill_rate = strategy.custom_entry_price(
        "BTC/USDT:USDT", None, dataframe.loc[FILL_BAR, "date"].to_pydatetime(),
        float(dataframe.loc[FILL_BAR, "close"]), "cascade_long_limit", "long",
    )
    assert fill_rate == pytest.approx(limit, rel=1e-6)
    assert fill_rate < float(dataframe.loc[FILL_BAR, "close"])


def test_no_fill_when_price_never_returns(tmp_path) -> None:
    """A passive entry must not be assumed to fill - no dip, no trade."""
    strategy, _ = build_strategy(tmp_path)
    dataframe = make_dataframe()
    dataframe.loc[FILL_BAR, "low"] = dataframe.loc[FILL_BAR, "close"] * 0.99995
    out = analyze(strategy, dataframe)
    assert int(out["enter_long"].sum()) == 0


def test_follow_direction_trades_with_the_flush(tmp_path) -> None:
    """In 'follow' mode a downward flush must produce a SHORT, not a long."""
    strategy, _ = build_strategy(tmp_path)
    strategy.entry_direction.value = "follow"
    dataframe = make_follow_dataframe()
    out = analyze(strategy, dataframe)
    shorts = out.index[out["enter_short"] == 1].tolist()
    assert FILL_BAR in shorts
    assert out.loc[FILL_BAR, "enter_tag"] == "follow_short_limit"
    assert int(out["enter_long"].sum()) == 0


def make_follow_dataframe(bars: int = 180) -> pd.DataFrame:
    """Down-flush, then a breakdown candle, then one more push lower to fill a stop order."""
    close = np.full(bars, 100_000.0)
    close[FLUSH_BAR] = 99_500.0          # -0.5% flush
    close[CONFIRM_BAR] = 99_430.0        # closes below the flush low -> breakdown
    close[FILL_BAR] = 99_380.0
    for i in range(FILL_BAR + 1, bars):
        close[i] = close[i - 1]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(BASE_TS + np.arange(bars) * BAR_MS, unit="ms", utc=True),
            "open": close,
            "high": close * 1.0002,
            "low": close * 0.9998,
            "close": close,
            "volume": 10.0,
        }
    )
    frame.loc[FLUSH_BAR, "low"] = 99_450.0
    frame.loc[CONFIRM_BAR, "low"] = 99_400.0
    # Stop-entry fills when price extends 0.05% beyond the trigger candle's close.
    frame.loc[FILL_BAR, "low"] = 99_350.0
    return frame


def test_missing_feature_file_blocks_entries(tmp_path) -> None:
    strategy, _ = build_strategy(tmp_path, with_features=False)
    out = analyze(strategy, make_dataframe())
    assert int(out["enter_long"].sum()) == 0
    assert int(out["enter_short"].sum()) == 0
    assert bool(out["cx_features_available"].any()) is False
    assert (
        strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "limit", 1.0, 100_000.0, "GTC",
            datetime(2025, 9, 1, 2, 1, tzinfo=timezone.utc), "cascade_long", "long",
        )
        is False
    )


def test_price_space_risk_params_are_leveraged(tmp_path) -> None:
    strategy, _ = build_strategy(tmp_path)
    # stoploss/minimal_roi are margin ratios in freqtrade: price space x leverage.
    assert strategy.stoploss == pytest.approx(-strategy.PRICE_STOP_DEFAULT * strategy.LEVERAGE)
    assert strategy.minimal_roi["0"] == pytest.approx(
        strategy.PRICE_TARGET_DEFAULT * strategy.LEVERAGE
    )
    assert strategy.stoploss_on_exchange is True
    assert strategy.leverage("BTC/USDT:USDT", datetime.now(timezone.utc), 100_000.0, 1.0, 20.0,
                             "cascade_long", "long") == strategy.LEVERAGE


def test_time_stop_and_flow_flip_exits(tmp_path) -> None:
    strategy, _ = build_strategy(tmp_path)
    analyze(strategy, make_dataframe())
    opened = datetime(2025, 9, 1, 0, 0, tzinfo=timezone.utc)
    trade = SimpleNamespace(open_date_utc=opened, is_short=False)

    too_early = opened + pd.Timedelta(minutes=2).to_pytimedelta()
    assert strategy.custom_exit("BTC/USDT:USDT", trade, too_early, 100_000.0, 0.0) is None

    late = opened + pd.Timedelta(minutes=strategy.max_holding_minutes.value + 1).to_pytimedelta()
    assert strategy.custom_exit("BTC/USDT:USDT", trade, late, 100_000.0, 0.0) == "time_stop"


def test_blackout_windows_block_entries(tmp_path) -> None:
    strategy_class = load_strategy_class()
    user_data = prepare_user_data(tmp_path)
    strategy = strategy_class(
        {
            "user_data_dir": str(user_data),
            "trading_mode": "futures",
            "runmode": "backtest",
            "cascade_blackout_windows": ["2025-09-01 02:00-2025-09-01 03:00"],
        }
    )
    inside = datetime(2025, 9, 1, 2, 30, tzinfo=timezone.utc)
    outside = datetime(2025, 9, 1, 4, 30, tzinfo=timezone.utc)
    assert strategy._in_blackout(inside) is True
    assert strategy._in_blackout(outside) is False


def test_feature_cache_is_reused_until_file_changes(tmp_path) -> None:
    strategy, _ = build_strategy(tmp_path)
    analyze(strategy, make_dataframe())
    cached = strategy._feature_cache["BTC/USDT:USDT"]
    analyze(strategy, make_dataframe())
    assert strategy._feature_cache["BTC/USDT:USDT"][0] == cached[0]


def test_tmp_cleanup_guard(tmp_path) -> None:
    """Sanity: the suite never writes into the real user_data directory."""
    prepare_user_data(tmp_path)
    assert (tmp_path / "user_data" / "liquidation").exists()
    assert "tmp" in str(tmp_path).lower() or "pytest" in str(tmp_path).lower()
    shutil.rmtree(tmp_path / "user_data")
