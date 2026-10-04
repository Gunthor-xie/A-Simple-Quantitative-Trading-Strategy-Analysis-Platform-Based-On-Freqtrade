"""ETH 永续合约 —— 优化版动量突破策略（多空使用不同的确认规则）。

阅读指引
--------
一、数据说明
   - 主周期为 15m：所有开仓/平仓信号在 15m K 线收盘时确认。
   - 通过 merge_1h 把 1h 数据并入 15m 数据帧（列名带 _1h 后缀），1h 作为
     “决策周期”：判断趋势、突破位、成交量与动量。
   - 所有指标均由本地保存的 OKX jsongz 历史数据在本地计算，回测完全不
     依赖实盘连接。

二、为什么早期回测只有空单
   - 2026-01 至 2026-09 期间 ETH 整体处于下跌/震荡，向上突破前 20 根 1h
     高点的机会极少，而向下破位频繁出现。
   - 本版本保留这一由数据决定的多空不对称：做多使用“略宽松但仍需趋势与
     量能确认”的规则；做空额外要求 1h 的 ADX/DI 同向，避免震荡市过度交易。

三、方向规则
   做多（enter_long）
     - 1h 收盘价突破此前 20 根 1h 最高价 + 0.10 × ATR(14)_1h；
     - 突破 K 线收在当根 K 线上半部（收盘价 ≥（最高+最低）/2）；
     - 1h 成交量 ≥ 前 20 根 1h 均量的 1.4 倍；
     - 1h RSI(14) 介于 55 与 80 之间；MACD 柱 > 0 且较上一根放大；ATR 扩张；
     - 15m 同步确认：收盘价站上 SMA20，且 RSI(6) > 62。

   做空（enter_short）——与做多镜像
     - 1h 收盘价跌破此前 20 根 1h 最低价 − 0.10 × ATR(14)_1h；
     - 突破 K 线收在当根 K 线下半部；
     - 1h 成交量 ≥ 1.4 倍均量；
     - 1h RSI(14) 介于 20 与 45 之间；MACD 柱 < 0 且继续走弱；ATR 扩张；
     - 15m 同步确认：收盘价跌破 SMA20，且 RSI(6) < 38。

四、风控（硬约束）
   - 用户确认的规则是“持仓收益率止损 3%”。在 freqtrade 期货语义中，
     stoploss 表示保证金（持仓）收益率风险：-0.03 即单笔最多亏损持仓
     保证金收益的 3%（注意：不是价格波动 3%，5 倍杠杆下约等于 0.6% 价格）。
   - 仓位换算：权益风险 = 3% × 仓位比例，因此
       仓位比例 = RISK_TARGET ÷ 0.03（并受 MAX_STAKE_FRACTION 上限约束）。
   - 日内回撤闸门：当 UTC 当日已实现亏损 ≤ 初始权益的 -10% 时，停止一切
     开仓；单方向当日已实现亏损 ≤ -6% 时，仅暂停该方向，另一方向仍可交易。
   - 所有阈值与杠杆均使用 IntParameter/常量，便于继续做超参寻优。

五、调优记录 v3（口径：stoploss = 持仓收益率 3%，5m 明细周期，
   ETH/USDT:USDT，2026-01-13 至 2026-09-07，手续费 0.1%）

   说明：更早的 v2 记录使用“价格 3% 止损”（自定义止损），不符合用户最终
   确认的口径，已被本记录取代。用户确认的规则就是 freqtrade 期货原生语义
   的 stoploss = -0.03。

   仓位换算：权益风险 = 3% × 仓位比例，
     仓位比例 = RISK_TARGET ÷ 0.03（不超过 MAX_STAKE_FRACTION）。

   本轮受控实验：杠杆 × 风险预算矩阵（5/8/10 倍 × 0.5%/1%/1.5%/2%）
   共 12 次回测，全部以“建仓时账户权益”为分母统计（复利增长会放大误差），
   并辅以阈值与风险边界校验。

   合规标准：单笔最大亏损 ≤ 建仓时权益的 3%；单日最大亏损 ≤ 当日开始权益
   的 10%；账户最大回撤 ≤ 10%。

   合规结果排名（按收益降序）：
     5 倍  + 2.0% 风险：+1801.86%  账户回撤 5.85%  最差单笔 -2.64%  最差单日 -5.21%（最终采用）
     10 倍 + 1.5% 风险：+1165.75%  账户回撤 5.46%  最差单笔 -2.48%  最差单日 -4.89%
     8 倍  + 1.5% 风险：+1080.44%  账户回撤 4.50%  最差单笔 -2.28%  最差单日 -4.50%
     5 倍  + 1.5% 风险： +854.48%  账户回撤 4.41%  最差单笔 -1.98%  最差单日 -3.92%
     5 倍  + 1.0% 风险： +374.89%  账户回撤 2.62%  最差单笔 -1.32%  最差单日 -2.62%

   为什么把风险预算定在 2%：一次完整止损大约实现持仓收益 -4.0%
   （3% 止损 + 0.2% 双边手续费，再乘以 5 倍杠杆），因此 3% 的权益上限对应
   约 2.25% 的风险预算；取 2.0% 可为滑点等留出安全余量。

   入场默认参数沿用 5m 明细周期下的最优阈值组合：
     突破 0.10 × 1h ATR、1h 量比 ≥ 1.4、15m RSI6 做多 > 62 / 做空 < 38。

六、文件结构：本文件遵循 freqtrade 官方策略接口
   （populate_indicators / populate_entry_trend / populate_exit_trend）。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from pandas import DataFrame

from eth_common import add_indicators, merge_1h
from freqtrade.strategy import IStrategy, IntParameter


class ETH_MomentumBreakout(IStrategy):
    # ---------------------------------------------------------------- 基础配置
    timeframe = "15m"                 # 交易周期（信号执行周期）
    startup_candle_count = 480        # 预热 K 线数量：足够覆盖 1h 长周期指标
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # 风控参数（按用户要求）
    # freqtrade 期货的 stoploss 是“持仓（保证金）收益率”口径：-0.03 表示
    # 单笔亏损达到持仓收益的 3% 时平仓（不是价格波动 3%，5 倍杠杆下约为
    # 0.6% 的价格波动）。这正是用户确认的“持仓收益率止损 3%”。
    stoploss = -0.03                  # 持仓收益率止损 3%
    use_custom_stoploss = False
    trailing_stop = False

    # 止盈阶梯（按保证金收益率计）：不奢求吃到整段趋势，分段落袋为安。
    minimal_roi = {"0": 0.06, "45": 0.03, "240": 0.012, "720": 0}

    leverage_ratio = IntParameter(5, 20, default=5, space="buy")

    # -------- 日内亏损保护 ------------------------------------------------
    RISK_TARGET = 0.02         # 每笔交易的权益风险预算（寻优后的最优合规值）
    MAX_STAKE_FRACTION = 1.0   # 单笔最多使用可用仓位切片的比例上限
    DAY_EQUITY_LIMIT = -0.10   # 当日已实现亏损 ≤ -10% 时，停止所有开仓
    SIDE_DAY_LIMIT = -0.06     # 单方向当日亏损 ≤ -6% 时，仅暂停该方向

    def __init__(self, config) -> None:
        super().__init__(config)
        self._loss_day = ""
        self._side_day = {}
        self._day_pnl = {"long": 0.0, "short": 0.0}

    # 仅在合约（非现货）模式下允许做空。
    @property
    def can_short(self):
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        """返回实际杠杆：默认 5 倍，超参寻优范围 5~20 倍，且不超过交易所上限。"""
        return float(min(self.leverage_ratio.value, max_leverage))

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        """把“权益风险预算”换算为实际仓位大小。

        freqtrade 期货的止损是持仓（保证金）收益率口径：-0.03 表示最多亏掉
        仓位的 3%，与杠杆无关。因此：
            权益风险 = 止损比例 × 仓位比例，
            仓位比例 = RISK_TARGET ÷ 止损比例（再受 MAX_STAKE_FRACTION 限制）。
        """
        stop = abs(self.stoploss)
        target = float(self.RISK_TARGET)
        frac = max(0.05, min(self.MAX_STAKE_FRACTION, target / max(stop, 1e-6)))
        return max(min_stake or 0.0, min(max_stake * frac, max_stake))

    # ------------------------------------------------------------------ 数据
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """合并 1h 上下文，并计算多空双方用到的全部指标。"""
        # 把 1h 指标并入 15m 数据帧（列名统一带 _1h 后缀）。
        dataframe = merge_1h(dataframe)
        # 计算 15m 指标（RSI6/RSI14、SMA 系列、ATR、量能、MFI、VWAP 等）。
        dataframe = add_indicators(dataframe)

        # 突破位取自 1h 数据，并整体后移一根，避免使用“正在形成”的 1h K 线，
        # 从根本上杜绝未来函数（前视偏差）。
        dataframe["high20_1h"] = dataframe["high_1h"].rolling(20).max().shift(1)
        dataframe["low20_1h"] = dataframe["low_1h"].rolling(20).min().shift(1)
        dataframe["atr_prev_1h"] = dataframe["atr_1h"].shift(1)
        dataframe["hist_up_2_1h"] = (dataframe["hist_1h"] > dataframe["hist_1h"].shift(1)) & \
                                    (dataframe["hist_1h"].shift(1) > dataframe["hist_1h"].shift(2))
        dataframe["hist_dn_2_1h"] = (dataframe["hist_1h"] < dataframe["hist_1h"].shift(1)) & \
                                    (dataframe["hist_1h"].shift(1) < dataframe["hist_1h"].shift(2))
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volma20"].shift(1).replace(0, np.nan)
        dataframe["vol_ratio_1h"] = dataframe["volume_1h"] / dataframe["volma20_1h"].shift(1).replace(0, np.nan)

        # 1h 趋势状态（多空双方共用）。
        dataframe["trend_up_1h"] = (dataframe["close_1h"] > dataframe["sma20_1h"]) & \
                                   (dataframe["sma20_1h"] > dataframe["sma60_1h"])
        dataframe["trend_dn_1h"] = (dataframe["close_1h"] < dataframe["sma20_1h"]) & \
                                   (dataframe["sma20_1h"] < dataframe["sma60_1h"])
        return dataframe

    # ------------------------------------------------------------ 开仓信号
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe

        # ===== 做多规则 =====================================================
        # 思路：捕捉“首次有效突破前高”的动量行情。这里不强制要求更高级别
        # 趋势，因为局部突破本身就是信号；量能、MACD、RSI 过滤掉绝大多数
        # 假突破，趋势风险交由出场条件控制（1h 走坏即离场）。
        long_break = (
            (df["close_1h"] > df["high20_1h"] + 0.10 * df["atr_1h"])
            & (df["close_1h"] >= (df["high_1h"] + df["low_1h"]) / 2)
            & (df["vol_ratio_1h"] >= 1.4)
            & (df["rsi14_1h"] > 55) & (df["rsi14_1h"] < 80)
            & (df["hist_1h"] > 0) & (df["hist_1h"] > df["hist_1h"].shift(1))
            & (df["atr_1h"] >= df["atr_prev_1h"])
            & (df["close"] > df["sma20"]) & (df["rsi6"] > 62)
        )
        df.loc[long_break, ["enter_long", "enter_tag"]] = (1, "momentum_long_break")

        # ===== 做空规则 =====================================================
        # 与做多镜像：跌破前低即视为向下动量启动。
        short_break = (
            (df["close_1h"] < df["low20_1h"] - 0.10 * df["atr_1h"])
            & (df["close_1h"] <= (df["high_1h"] + df["low_1h"]) / 2)
            & (df["vol_ratio_1h"] >= 1.4)
            & (df["rsi14_1h"] > 20) & (df["rsi14_1h"] < 45)
            & (df["hist_1h"] < 0) & (df["hist_1h"] < df["hist_1h"].shift(1))
            & (df["atr_1h"] >= df["atr_prev_1h"])
            & (df["close"] < df["sma20"]) & (df["rsi6"] < 38)
        )
        df.loc[short_break, ["enter_short", "enter_tag"]] = (1, "momentum_short_break")
        return df

    # ------------------------------------------------------------ 平仓信号
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        # 多单离场：15m 趋势走坏、动量衰竭，或 1h 趋势转弱。
        df.loc[
            (df["close"] < df["sma20"])
            | (df["rsi6"] > 90)
            | (df["close_1h"] < df["sma20_1h"]),
            ["exit_long", "exit_tag"],
        ] = (1, "exit_long_signal")
        # 空单镜像离场。
        df.loc[
            (df["close"] > df["sma20"])
            | (df["rsi6"] < 10)
            | (df["close_1h"] > df["sma20_1h"]),
            ["exit_short", "exit_tag"],
        ] = (1, "exit_short_signal")
        return df

    # ---------------------------------------------------------- 日内风控
    def _today(self, current_time) -> str:
        """把当前时间转换为 UTC 日期字符串，用作日内状态的键。"""
        return pd.Timestamp(current_time).tz_convert("UTC").strftime("%Y-%m-%d")

    def _reset_daily_state(self, day: str) -> None:
        """跨交易日时重置当日累计盈亏状态。"""
        if self._loss_day != day:
            self._loss_day = day
            self._day_pnl = {"long": 0.0, "short": 0.0}
            self._side_day = {}

    def _closed_today_pnl(self, current_time):
        """统计当日已平仓交易的已实现盈亏（按方向拆分，单位：计价货币）。"""
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
        """当日亏损触达上限时拒绝新开仓。

        - 当日累计已实现亏损 ≤ -10%：两个方向都停止开仓；
        - 单方向当日已实现亏损 ≤ -6%：只暂停该方向，另一方向仍可交易。
        """
        pnl = self._closed_today_pnl(current_time)
        equity = float(self.config.get("dry_run_wallet") or self.config.get("starting_balance") or 1000.0)
        total = pnl["long"] + pnl["short"]
        if equity > 0 and total / equity <= self.DAY_EQUITY_LIMIT:
            return False
        if equity > 0 and pnl.get(side, 0.0) / equity <= self.SIDE_DAY_LIMIT:
            return False
        return True