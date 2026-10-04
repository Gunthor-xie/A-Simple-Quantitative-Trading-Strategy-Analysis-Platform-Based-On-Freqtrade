"""ETH futures - Bollinger squeeze breakout (idea 2)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from pandas import DataFrame
from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_BollingerSqueeze(IStrategy):
    timeframe = "15m"
    startup_candle_count = 480
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.010
    trailing_stop = False
    minimal_roi = {"0": 0.05, "30": 0.02, "180": 0}
    leverage_ratio = IntParameter(5, 20, default=5, space="buy")

    @property
    def can_short(self):
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        return float(min(self.leverage_ratio.value, max_leverage))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = merge_1h(dataframe)
        dataframe = add_indicators(dataframe)
        dataframe["width_percentile"] = dataframe["bb_width_1h"].rolling(100).rank(pct=True)
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volma20"].shift(1).replace(0, np.nan)
        dataframe["hist15"] = dataframe["dif"] - dataframe["dea"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        squeezed = (df["width_percentile"] < 0.20)
        up = (df["close_1h"] > df["bb_up_1h"].shift(1)) & (df["volume_1h"] > df["volma20_1h"] * 1.5) & \
             (df["sma20_1h"] > df["sma60_1h"]) & (df["rsi14_1h"] > 55) & (df["rsi14_1h"] < 85) & (df["close"] > df["sma5"]) & (df["hist15"] > 0)
        dn = (df["close_1h"] < df["bb_low_1h"].shift(1)) & (df["volume_1h"] > df["volma20_1h"] * 1.5) & \
             (df["sma20_1h"] < df["sma60_1h"]) & (df["rsi14_1h"] < 45) & (df["rsi14_1h"] > 15) & (df["close"] < df["sma5"]) & (df["hist15"] < 0)
        df.loc[squeezed & up, ["enter_long", "enter_tag"]] = (1, "squeeze_break_up")
        df.loc[squeezed & dn, ["enter_short", "enter_tag"]] = (1, "squeeze_break_down")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["close"] < df["sma10"]) | (df["rsi14"] > 82), ["exit_long", "exit_tag"]] = (1, "exit_up")
        df.loc[(df["close"] > df["sma10"]) | (df["rsi14"] < 18), ["exit_short", "exit_tag"]] = (1, "exit_down")
        return df