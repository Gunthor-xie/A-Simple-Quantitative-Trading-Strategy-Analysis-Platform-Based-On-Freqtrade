"""Smoke-test harness: LiquidationCascade with thresholds fitted to one quiet day.

Not a trading strategy. 2025-09-01 on BTCUSDT had **no** 1-minute move above the
0.35% default trigger (max |ret_1m| = 0.27%), so a backtest with strategy
defaults correctly produces 0 trades. This subclass relaxes the thresholds just
enough to prove the trigger -> confirmation -> entry chain fires on real market
data through the real engine:

    python scripts/freqtrade_offline.py backtesting --userdir ..\\user_data \\
        --config ..\\user_data\\config.json \\
        --strategy-path ..\\..\\.scratch\\liquidation-reversal\\smoke \\
        --strategy LiquidationCascadeLoose --timerange 20250901-20250902 \\
        --timeframe 1m --data-format-ohlcv jsongz
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[3] / "freqtrade-desktop" / "user_data" / "strategies"),
)

from LiquidationCascade import LiquidationCascade as _Base  # noqa: E402
from freqtrade.strategy import DecimalParameter  # noqa: E402


class LiquidationCascadeLoose(_Base):
    move_pct = DecimalParameter(0.0005, 0.0120, default=0.0015, decimals=4, space="buy")
    move_atr_mult = DecimalParameter(0.0, 4.0, default=1.0, decimals=1, space="buy")
    flush_score_min = DecimalParameter(0.5, 3.5, default=1.0, decimals=2, space="buy")
    depth_delta_min = DecimalParameter(-0.20, 0.20, default=-0.05, decimals=2, space="buy")
    taker_delta_min = DecimalParameter(-0.20, 0.40, default=-0.10, decimals=2, space="buy")
    max_holding_minutes = _Base.max_holding_minutes
