"""ETH futures - Multi-timeframe pullback in uptrend (idea 1)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from pandas import DataFrame
from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_PullbackTrend(IStrategy):
    timeframe = "15m"
    startup_candle_count = 480
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.012
    trailing_stop = False
    minimal_roi = {"0": 0.06, "30": 0.02, "180": 0}
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
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volma20"].shift(1).replace(0, np.nan)
        dataframe["hist15"] = dataframe["dif"] - dataframe["dea"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        uptrend = (df["sma60_1h"] > df["sma120_1h"]) & (df["close_1h"] > df["sma60_1h"]) & \
                  (df["adx_1h"] > 18) & (df["di+_1h"] >= df["di-_1h"]) & (df["dif_1h"] > df["dea_1h"])
        downtrend = (df["sma60_1h"] < df["sma120_1h"]) & (df["close_1h"] < df["sma60_1h"]) & \
                    (df["adx_1h"] > 18) & (df["di+_1h"] <= df["di-_1h"]) & (df["dif_1h"] < df["dea_1h"])
        near_ma = (df["close"] / df["sma20"].replace(0, np.nan) - 1).abs() < 0.02
        pull_rsi = (df["rsi14"] >= 30) & (df["rsi14"] <= 58)
        pull_rsi_s = (df["rsi14"] >= 42) & (df["rsi14"] <= 70)
        recovery = (df["close"] > df["open"]) & (df["close"] > df["sma5"]) & \
                   (df["sma5"] > df["sma20"]) & (df["hist15"] >= 0) & (df["vol_ratio"] > 0.9)
        breakdown = (df["close"] < df["open"]) & (df["close"] < df["sma5"]) & \
                    (df["sma5"] < df["sma20"]) & (df["hist15"] <= 0) & (df["vol_ratio"] > 0.9)
        df.loc[uptrend & near_ma & pull_rsi & recovery, ["enter_long", "enter_tag"]] = (1, "pullback_confirm")
        df.loc[downtrend & near_ma & pull_rsi_s & breakdown, ["enter_short", "enter_tag"]] = (1, "pullback_confirm_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["rsi14"] > 78) | (df["close_1h"] < df["sma20_1h"]), ["exit_long", "exit_tag"]] = (1, "trend_fade")
        df.loc[(df["rsi14"] < 22) | (df["close_1h"] > df["sma20_1h"]), ["exit_short", "exit_tag"]] = (1, "trend_fade_short")
        return df