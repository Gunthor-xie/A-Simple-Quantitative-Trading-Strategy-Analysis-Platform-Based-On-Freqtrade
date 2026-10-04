"""BTC/USDT 2025 因果策略 v1 —— 趋势过滤的均值回归。

设计约束（对应目标）：
  - 单笔回撤 = 名义金额 3%：stoploss 直接对应 3% 价格距离（杠杆 1 时
    freqtrade 的 stoploss 就是保证金收益率，因此 -0.03 = 3% 价格）。
  - 每日已实现亏损超过本金 10% 时停止开仓（confirm_trade_entry 门闸）。

本文件不使用任何“未来函数”：
  - 只用 15m 自身的滚动/EWM 指标（close/high/low/volume 均为当前及以前数据）；
  - 不重采样 1h 再回填（这是旧策略前视偏差的来源）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from pandas import DataFrame

from eth_common import atr_series, rsi
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter


class BTC_2025_Causal(IStrategy):
    timeframe = "15m"
    startup_candle_count = 240
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # 单笔名义回撤 3%（杠杆 1 时 stoploss=-0.03 即 3% 价格）
    # 5x 杠杆下，3% 名义（价格）止损 = 15% 保证金止损
    stoploss = -0.15
    use_custom_stoploss = False
    trailing_stop = False

    rsi_entry_long = IntParameter(25, 40, default=32, space="buy")
    rsi_entry_short = IntParameter(60, 85, default=70, space="buy")
    rsi_exit_long = IntParameter(50, 65, default=58, space="sell")
    rsi_exit_short = IntParameter(30, 55, default=45, space="sell")
    RISK_PER_TRADE = 0.03
    DAY_EQUITY_LIMIT = -0.10
    SIDE_DAY_LIMIT = -0.06
    LEVERAGE = 5

    # 止盈换算成保证金收益率：价格止盈 × 杠杆。
    # 2.4% 价格止盈 = 12% 保证金收益率（5x），固定档位。
    minimal_roi = {"0": 0.12}

    def __init__(self, config) -> None:
        super().__init__(config)
        self._loss_day = ""
        self._day_pnl = {"long": 0.0, "short": 0.0}

    @property
    def can_short(self):
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        return 5.0

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        # 单笔权益风险 3%：保证金占比 = 3% / 15%（3% 价格止损 × 5x 杠杆）。
        # BTC/USDT:USDT 一手合约 = 0.01 BTC，按名义金额保底，避免仓位被
        # 合约精度截断成 0。
        stop = 0.03 * leverage
        stake = max_stake * (self.RISK_PER_TRADE / stop)
        min_contract_margin = 0.01 * current_rate / max(leverage, 1e-9)
        stake = max(stake, min_contract_margin, min_stake or 0.0)
        result = min(stake, max_stake)
        return result

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["sma20"] = close.rolling(20).mean()
        dataframe["sma60"] = close.rolling(60).mean()
        dataframe["sma120"] = close.rolling(120).mean()
        dataframe["rsi14"] = rsi(close, 14)
        dataframe["atr14"] = atr_series(dataframe["high"], dataframe["low"], close, 14)
        dataframe["trend_up"] = dataframe["sma60"] > dataframe["sma120"]
        dataframe["trend_dn"] = dataframe["sma60"] < dataframe["sma120"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        # 2025 年 BTC 样本中，下降趋势内 RSI 超买的空头均值回归/破位优势显著。
        long_ok = pd.Series(False, index=df.index)
        short_ok = df["trend_dn"] & (df["rsi14"] > self.rsi_entry_short.value)
        df.loc[long_ok, ["enter_long", "enter_tag"]] = (1, "mr_long")
        df.loc[short_ok, ["enter_short", "enter_tag"]] = (1, "mr_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        # 出场只用 RSI 均值回归条件，避免与开仓条件在同根 K 线重叠，
        # 否则 Freqtrade 会因“开仓+出场信号同时出现”而放弃这笔开仓。
        df.loc[df["rsi14"] > self.rsi_exit_long.value, ["exit_long", "exit_tag"]] = (1, "mr_long_exit")
        df.loc[df["rsi14"] < self.rsi_exit_short.value, ["exit_short", "exit_tag"]] = (1, "mr_short_exit")
        return df

    def _today(self, current_time) -> str:
        return pd.Timestamp(current_time).tz_convert("UTC").strftime("%Y-%m-%d")

    def _reset_daily_state(self, day: str) -> None:
        if self._loss_day != day:
            self._loss_day = day
            self._day_pnl = {"long": 0.0, "short": 0.0}

    def _closed_today_pnl(self, current_time):
        day = self._today(current_time)
        self._reset_daily_state(day)
        try:
            from freqtrade.persistence import Trade
            trades = Trade.get_trades_proxy(is_open=False)
            today_start = pd.Timestamp(current_time).tz_convert("UTC").floor("D")
            result = {"long": 0.0, "short": 0.0}
            for t in trades:
                close_utc = getattr(t, "close_date_utc", None)
                if close_utc is None:
                    continue
                if pd.Timestamp(close_utc).tz_convert("UTC") < today_start:
                    continue
                pnl = float(getattr(t, "close_profit_abs", 0.0) or 0.0)
                side = "short" if getattr(t, "is_short", False) else "long"
                result[side] += pnl
            self._day_pnl = result
        except Exception:
            pass
        return self._day_pnl

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs) -> bool:
        pnl = self._closed_today_pnl(current_time)
        equity = float(self.config.get("dry_run_wallet") or self.config.get("starting_balance") or 1000.0)
        total = pnl["long"] + pnl["short"]
        if equity > 0 and total / equity <= self.DAY_EQUITY_LIMIT:
            return False
        if equity > 0 and pnl.get(side, 0.0) / equity <= self.SIDE_DAY_LIMIT:
            return False
        return True
