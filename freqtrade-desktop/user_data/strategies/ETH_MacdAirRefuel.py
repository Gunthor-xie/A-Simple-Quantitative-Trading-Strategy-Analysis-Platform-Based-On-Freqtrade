"""ETH futures - MACD above-zero second golden cross (idea 5)."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
from pandas import DataFrame
from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_MacdAirRefuel(IStrategy):
    timeframe = "15m"
    startup_candle_count = 400
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    stoploss = -0.008
    trailing_stop = False
    minimal_roi = {"0": 0.06, "30": 0.03, "180": 0}
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
        above_zero = (df["dif_1h"] > 0) & (df["dea_1h"] > 0)
        crossed = (df["dif_1h"] > df["dea_1h"]) & (df["dif_1h"].shift(1) <= df["dea_1h"].shift(1))
        hist_turn = df["hist_1h"] >= 0
        uptrend = (df["sma20_1h"] > df["sma60_1h"]) & (df["close_1h"] >= df["sma20_1h"]) & (df["rsi14_1h"] > 50)
        volume = df["volume_1h"] > df["volma20_1h"] * 1.0
        below_zero = (df["dif_1h"] < 0) & (df["dea_1h"] < 0)
        crossed_dn = (df["dif_1h"] < df["dea_1h"]) & (df["dif_1h"].shift(1) >= df["dea_1h"].shift(1))
        downtrend = (df["sma20_1h"] < df["sma60_1h"]) & (df["close_1h"] <= df["sma20_1h"]) & (df["rsi14_1h"] < 50)
        base_ok_up = df["hist15"] >= 0
        base_ok_dn = df["hist15"] <= 0
        df.loc[above_zero & crossed & hist_turn & uptrend & volume & base_ok_up,
               ["enter_long", "enter_tag"]] = (1, "air_refuel_long")
        df.loc[below_zero & crossed_dn & (df["hist_1h"] <= 0) & downtrend & volume & base_ok_dn,
               ["enter_short", "enter_tag"]] = (1, "air_refuel_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[(df["close_1h"] < df["sma20_1h"]) | (df["rsi14"] > 78), ["exit_long", "exit_tag"]] = (1, "exit_long")
        df.loc[(df["close_1h"] > df["sma20_1h"]) | (df["rsi14"] < 22), ["exit_short", "exit_tag"]] = (1, "exit_short")
        return df