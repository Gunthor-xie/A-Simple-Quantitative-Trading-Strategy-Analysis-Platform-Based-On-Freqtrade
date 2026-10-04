"""ETH futures - VWAP + volume pullback (idea 3)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from pandas import DataFrame
from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_VwapPullback(IStrategy):
    timeframe = "15m"
    startup_candle_count = 400
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.012
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
        dataframe["vwap_slope_1h"] = dataframe["vwap_1h"] - dataframe["vwap_1h"].shift(4)
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volma20"].shift(1).replace(0, np.nan)
        dataframe["hist15"] = dataframe["dif"] - dataframe["dea"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        long_regime = (df["sma20_1h"] > df["sma60_1h"]) & (df["close_1h"] > df["vwap_1h"]) & \
                      (df["vwap_slope_1h"] > 0) & (df["mfi_1h"] > 50) & (df["hist_1h"] > 0)
        near_vwap = (df["close"] / df["vwap"].replace(0, np.nan) - 1).abs() < 0.004
        prev_low_vol = df["volume"].shift(1) < df["volma20"].shift(1)
        long_rsi = (df["rsi14"] >= 35) & (df["rsi14"] <= 60)
        bounce_up = (df["close"] > df["open"]) & (df["close"] > df["vwap"]) & (df["vol_ratio"] > 1.3)
        df.loc[long_regime & near_vwap & prev_low_vol & long_rsi & bounce_up, ["enter_long", "enter_tag"]] = (1, "vwap_hold")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["close"] < df["sma20"]) | (df["rsi14"] > 78), ["exit_long", "exit_tag"]] = (1, "vwap_lost")
        df.loc[(df["close"] > df["sma20"]) | (df["rsi14"] < 22), ["exit_short", "exit_tag"]] = (1, "vwap_lost_short")
        return df