"""BTC/USDT 2025 因果趋势跟踪策略。

约束（放宽后）：
  - 单笔名义回撤 5%~8%（本版 6% 价格止损）。
  - 单日已实现亏损 <= 本金 10% 时停止开仓。
  - 优先年化收益，胜率为次要目标。
  - 无未来函数：只用当前及以前的滚动均线/收盘数据。

思路：1h 级别双均线趋势 + 移动止损让利润奔跑，反向信号离场。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter


class BTC_2025_Trend(IStrategy):
    timeframe = "1h"
    startup_candle_count = 300
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = True

    # 5x 杠杆下：5% 名义（价格）止损 = 25% 保证金止损
    stoploss = -0.25
    trailing_stop = True
    trailing_stop_positive = 0.05     # 1% 价格移动止损距离
    trailing_stop_positive_offset = 0.10  # 盈利 2% 价格后启动移动止损
    trailing_only_offset_is_reached = True

    don = IntParameter(20, 80, default=55, space="buy")

    RISK_PER_TRADE = 0.04
    DAY_EQUITY_LIMIT = -0.10
    LEVERAGE = 5

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
        return float(self.LEVERAGE)

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        # 目标每笔权益风险 1.5%：6% 价格止损 × 5x 杠杆。
        stop = 0.06 * leverage
        stake = max_stake * (self.RISK_PER_TRADE / stop)
        min_contract_margin = 0.01 * current_rate / max(leverage, 1e-9)
        stake = max(stake, min_contract_margin, min_stake or 0.0)
        return min(stake, max_stake)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["don_high"] = dataframe["high"].rolling(self.don.value).max().shift(1)
        dataframe["don_low"] = dataframe["low"].rolling(self.don.value).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        long_ok = (
            df["close"] > df["don_high"]
        )
        short_ok = (
            df["close"] < df["don_low"]
        )
        df.loc[long_ok, ["enter_long", "enter_tag"]] = (1, "trend_long")
        df.loc[short_ok, ["enter_short", "enter_tag"]] = (1, "trend_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        df.loc[df["close"] < df["don_low"], ["exit_long", "exit_tag"]] = (1, "don_flip")
        df.loc[df["close"] > df["don_high"], ["exit_short", "exit_tag"]] = (1, "don_flip")
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
        return True
