"""ETH futures - oversold reversal with bottom confirmation (idea 6)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from pandas import DataFrame
from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_OversoldReversal(IStrategy):
    timeframe = "15m"
    startup_candle_count = 400
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.010
    trailing_stop = False
    minimal_roi = {"0": 0.06, "30": 0.02, "240": 0}
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
        dataframe["hist15"] = dataframe["dif"] - dataframe["dea"]
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volma20"].shift(1).replace(0, np.nan)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        oversold = (df["rsi6_1h"] < 30) & (df["rsi14_1h"] < 45) & (df["close_1h"] <= df["bb_low_1h"] * 1.005)
        overbought = (df["rsi6_1h"] > 75) & (df["rsi14_1h"] > 58) & (df["close_1h"] >= df["bb_up_1h"])
        bull = (df["close"] > df["open"]) & (df["vol_ratio"] > 1.2) & (df["close"] > df["sma5"]) & \
               (df["rsi6"] >= 28) & (df["rsi6"] <= 60) & (True)
        bear = (df["close"] < df["open"]) & (df["vol_ratio"] > 1.2) & (df["close"] < df["sma5"]) & \
               (df["rsi6"] <= 72) & (df["rsi6"] >= 40) & (df["hist15"] <= df["hist15"].shift(1))
        df.loc[oversold & bull, ["enter_long", "enter_tag"]] = (1, "oversold_reversal")
        df.loc[overbought & bear, ["enter_short", "enter_tag"]] = (1, "overbought_reversal")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["close"] < df["sma20"]) | (df["rsi14"] > 72), ["exit_long", "exit_tag"]] = (1, "target_hit")
        df.loc[(df["close"] > df["sma20"]) | (df["rsi14"] < 28), ["exit_short", "exit_tag"]] = (1, "target_hit_short")
        return df