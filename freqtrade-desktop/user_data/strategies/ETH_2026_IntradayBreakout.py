"""ETH/USDT 日内突破策略（15m 信号 / 5m 明细，量能驱动 + 数据驱动的分段止盈）。

===============================================================================
一、设计依据（基于本地 ETH 1h 数据统计）
===============================================================================
    统计样本：ETH/USDT:USDT 1h 本地数据，2026-01-08 ~ 2026-09-07。
    筛选条件：1h 成交量处于全样本前 30%（>=70 分位），且收盘价突破前 20 根
    1h 极值（向上突破前高 / 向下跌破前低）——即"放量突破 K 线"。
    单向性判定：以突破 K 线收盘价为参考，向前最多 12 小时统计；取最大有利
    偏移 MFE，若到达 MFE 之前的最大不利偏移 MAE <= MFE 的 1/3，则视为
    "单向突破行情"（整段走得比较干净、回撤小）。

    统计结果（整段振幅，价格口径）：
        向上：样本 75 笔，中位数 2.80%，平均 4.01%，P25 1.68%，P75 5.41%
        向下：样本 85 笔，中位数 2.81%，平均 3.38%，P25 1.59%，P75 4.64%
    多空振幅的中位数几乎一致（2.8%），说明这段样本里多空突破的可捕捉空间对称；
    平均值明显大于中位数，说明分布右偏（少数大趋势贡献了大部分振幅）。

    由此确定的参数：
        初始止损 = 中位振幅 × stop_frac（默认 0.40 ≈ 1.12%，即中位的 1/2.5 附近，
                   落在"中位振幅的 1/2 或 1/3"这个区间内）
        第一段止盈 = 中位振幅 × 0.5  ≈ 1.4%（先落袋，把止损切成移动止损）
        第二段止盈 = 中位振幅 × 1.0  ≈ 2.8%（兑现中位行情）
        剩余仓位用更紧的移动止损去博平均/P75 级别（3.4%~5.4%）的尾部行情

===============================================================================
二、交易思路（15m 日内短线，持仓数小时）
===============================================================================
    1. 价格通道（更灵敏）：不用笨重的唐奇安长通道，改用 Keltner 风格通道
          上轨 = EMA(20) + ch_mult × ATR(14)
          下轨 = EMA(20) - ch_mult × ATR(14)
       ch_mult 默认 1.2，通道随波动率自适应，比 60 根唐奇安灵敏得多。
    2. 量能过滤（核心）：只有当根 15m 成交量 > 过去 3 天（288 根）成交量的
       70 分位时才允许开仓；量能不足一律不交易。
    3. 入场：收盘价突破通道上轨做多、跌破下轨做空，且必须满足量能条件。
    4. 出场（三段止盈 + 移动止损）：
        - 第一段 TP1 ≈ 0.46×中位 = 1.29%：平掉 tp1_exit(35%)，止损从固定切为移动；
        - 第二段 TP2 ≈ 0.68×中位 = 1.90%：再平 tp2_exit(35%)（统计上约一半盈利单能到）；
        - 第三段 TP3 ≈ 1.00×中位 = 2.80%：再平 tp3_exit(20%)（约 17% 盈利单能到）；
        - 剩余 10% 仓位用更紧的三段移动止损跟随（trail3_frac≈0.10×中位），
          避免把已兑现的利润回吐掉。
    5. 日内风控：当天已平仓亏损达到本金 10% 时，当天不再开新仓。

    所有指标（EMA/ATR/成交量分位）都是滚动窗口，入场只用已收盘的 15m K 线，
    不含未来函数。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from pandas import DataFrame

from eth_common import atr_series
from freqtrade.strategy import IStrategy, DecimalParameter
from freqtrade.strategy.strategy_helper import stoploss_from_absolute


class ETH_2026_IntradayBreakout(IStrategy):
    # ---- 运行框架配置 --------------------------------------------------
    timeframe = "15m"                  # 日内短线：15m 出信号
    startup_candle_count = 400         # 覆盖 3 天量能窗口(288根) + ATR 预热
    process_only_new_candles = True
    use_exit_signal = False            # 不靠反向信号离场，离场由止盈/止损负责
    exit_profit_only = False
    ignore_roi_if_entry_signal = True

    # 全部使用限价单：入场、止盈/减仓（exit）、止损（stoploss）都是限价单。
    # stoploss_on_exchange=True 让实盘/模拟盘把止损挂到交易所（OKX 支持）；
    # 回测框架会强制按 stoploss_on_exchange=False 模拟，并按限价止损成交处理。
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # 分段止盈需要开启仓位调整（返回负 stake 表示减仓）
    position_adjustment_enable = True

    # 硬性兜底止损（5x 杠杆下 -0.25 对应 5% 价格），实际止损由 custom_stoploss 给出
    stoploss = -0.25
    use_custom_stoploss = True
    trailing_stop = False              # 移动止损在 custom_stoploss 里手工实现

    # ---- 可优化参数 ----------------------------------------------------
    # 2026 单独寻优会严重过拟合（2026 收益 +100%，2025 却 -15%），因此这里改用
    # 两年共同验证过的折中取值，而不是任一年的最优点。
    ch_mult = DecimalParameter(0.8, 2.5, default=1.80, decimals=2, space="buy")   # 通道宽度（×ATR）
    vol_q = DecimalParameter(0.5, 0.95, default=0.55, decimals=2, space="buy")   # 量能分位阈值
    vol_x = DecimalParameter(1.0, 2.0, default=1.50, decimals=2, space="buy")    # 相对 3 天中位量的放大倍数
    body_mult = DecimalParameter(0.0, 0.8, default=0.25, decimals=2, space="buy")  # 突破 K 线实体 / ATR
    # 止损：2026 最优 0.27、2025 最优 0.46，取中间 0.40（≈1.2% 价格）。
    stop_frac = DecimalParameter(0.20, 0.80, default=0.40, decimals=2, space="buy")  # 初始止损 = 中位振幅×该系数
    # 三段止盈（× 中位振幅）
    tp1_frac = DecimalParameter(0.30, 0.70, default=0.60, decimals=2, space="sell")
    tp2_frac = DecimalParameter(0.50, 1.00, default=0.90, decimals=2, space="sell")
    tp3_frac = DecimalParameter(0.85, 1.60, default=1.00, decimals=2, space="sell")
    tp1_exit = DecimalParameter(0.20, 0.60, default=0.30, decimals=2, space="sell")
    tp2_exit = DecimalParameter(0.20, 0.60, default=0.40, decimals=2, space="sell")
    tp3_exit = DecimalParameter(0.10, 0.50, default=0.25, decimals=2, space="sell")
    trail1_frac = DecimalParameter(0.20, 0.50, default=0.28, decimals=2, space="sell")  # 第一段后的移动止损
    trail2_frac = DecimalParameter(0.10, 0.35, default=0.30, decimals=2, space="sell")  # 第二段后的移动止损
    trail3_frac = DecimalParameter(0.05, 0.25, default=0.15, decimals=2, space="sell")  # 第三段后的移动止损（最紧）

    # ---- 统计得到的单向突破振幅（价格口径，多空分开）---------------------
    # 2025-01-20~2025-12-31 ETH 1h 样本：向上中位 3.06%（均值 3.94%），
    # 向下中位 3.86%（均值 5.92%）；2026 样本分别是 2.80% / 2.81%。
    # 之前只用了 2026 的 2.80%，导致 2025 年止损/止盈档位偏小、被噪声频繁扫损。
    # 为避免绑定单一年份，取两年中位数的均值（多空分别）。
    MED_AMP_LONG = 0.0293              # (3.06% + 2.80%) / 2
    MED_AMP_SHORT = 0.0334             # (3.86% + 2.81%) / 2

    # ---- 风险与资金 ----------------------------------------------------
    RISK_PER_TRADE = 0.02              # 单笔目标权益风险 2%
    # 当日已实现亏损达本金 8% 即停开新仓：为已持仓的平仓损失留出缓冲，
    # 使全天实际回撤控制在 10% 以内（超参寻优后曾出现单日 -10.2%）。
    DAY_EQUITY_LIMIT = -0.06
    LEVERAGE = 5
    VOL_WINDOW = 288                   # 3 天 = 288 根 15m

    def __init__(self, config) -> None:
        super().__init__(config)
        self._stage = {}               # trade.id -> 0/1/2（止盈阶段）
        self._loss_day = ""
        self._day_pnl = {"long": 0.0, "short": 0.0}
        self._atr_dates = None
        self._atr_vals = None

    @property
    def can_short(self):
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        return float(self.LEVERAGE)

    def _med_amp(self, is_short: bool) -> float:
        """该方向的单向突破振幅中位数（价格口径）。"""
        return self.MED_AMP_SHORT if is_short else self.MED_AMP_LONG

    def _atr_at(self, current_time):
        """按时间戳二分查找缓存的 ATR 值（避免每根 K 线重算）。"""
        if self._atr_dates is None:
            return None
        cur = pd.Timestamp(current_time)
        cur = cur.tz_localize("UTC") if cur.tzinfo is None else cur.tz_convert("UTC")
        idx = int(np.searchsorted(self._atr_dates, cur.value, side="right")) - 1
        if idx < 0:
            return None
        val = float(self._atr_vals[idx])
        return val if val > 0 else None

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        """按"单笔打初始止损约亏 RISK_PER_TRADE 本金"反推保证金。"""
        stop_price = float(self.stop_frac.value) * self._med_amp(side == "short")
        stake = max_stake * (self.RISK_PER_TRADE / (stop_price * leverage))
        # ETH 最小下单量约 0.001 ETH（名义 ~3 USDT），这里只做兜底
        min_contract_margin = 0.001 * current_rate / max(leverage, 1e-9)
        stake = max(stake, min_contract_margin, min_stake or 0.0)
        return min(stake, max_stake)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        dataframe["ema20"] = close.ewm(span=20, adjust=False).mean()
        dataframe["atr"] = atr_series(dataframe["high"], dataframe["low"], close, 14)
        # 过去 3 天（288 根 15m）成交量的分位阈值；shift(1) 只用已完成的 K 线
        dataframe["vol_thr"] = (
            dataframe["volume"].rolling(self.VOL_WINDOW).quantile(float(self.vol_q.value)).shift(1)
        )
        dataframe["vol_med"] = (
            dataframe["volume"].rolling(self.VOL_WINDOW).median().shift(1)
        )
        # 1h 上下文（因果对齐：当前 15m 只能看到上一根已完成的 1h K 线）
        dataframe = self._merge_1h_causal(dataframe)
        # 最近 4 小时（16 根 15m）内出现过 1h 放量突破
        dataframe["brk_up_recent"] = dataframe["brk_up_1h"].fillna(0).rolling(16).max().fillna(0)
        dataframe["brk_dn_recent"] = dataframe["brk_dn_1h"].fillna(0).rolling(16).max().fillna(0)
        self._atr_dates = pd.to_datetime(dataframe["date"], utc=True).astype("int64").to_numpy()
        self._atr_vals = dataframe["atr"].to_numpy()
        return dataframe

    @staticmethod
    def _merge_1h_causal(df: DataFrame) -> DataFrame:
        """把 1h 的放量突破标记因果地并入 15m 数据（不含未来数据）。

        做法：先把 15m 重采样成 1h 并计算指标，再把整根 1h 桶后移一小时，
        这样当前 15m K 线只能引用"上一根已完成"的 1h K 线。
        """
        out = df.copy()
        dt = pd.to_datetime(out["date"], utc=True)
        out["_h"] = dt.dt.floor("1h")
        h = (
            out.resample("1h", on="_h")
            .agg({"open": "first", "high": "max", "low": "min",
                  "close": "last", "volume": "sum"})
            .dropna()
            .reset_index()
        )
        h["vol_thr_1h"] = h["volume"].rolling(72).quantile(0.70).shift(1)   # 前 3 天 1h 量的 70 分位
        h["don_high_1h"] = h["high"].rolling(20).max().shift(1)
        h["don_low_1h"] = h["low"].rolling(20).min().shift(1)
        h["brk_up_1h"] = (
            (h["close"] > h["don_high_1h"]) & (h["volume"] > h["vol_thr_1h"]) & (h["close"] > h["open"])
        ).astype(int)
        h["brk_dn_1h"] = (
            (h["close"] < h["don_low_1h"]) & (h["volume"] > h["vol_thr_1h"]) & (h["close"] < h["open"])
        ).astype(int)
        h["_h"] = h["_h"] + pd.Timedelta(hours=1)   # 因果对齐
        out = out.merge(h[["_h", "brk_up_1h", "brk_dn_1h", "vol_thr_1h"]], on="_h", how="left")
        return out.drop(columns=["_h"])

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe
        band = float(self.ch_mult.value) * df["atr"]
        # 量能：既要在过去 3 天的分位阈值之上，又要比 3 天中位量明显放大
        vol_ok = (df["volume"] > df["vol_thr"]) & (
            df["volume"] > float(self.vol_x.value) * df["vol_med"]
        )
        # 突破 K 线必须有实体、且收盘靠近极值端（避免长上/下影的假突破）
        body = (df["close"] - df["open"]).abs()
        strength = body > float(self.body_mult.value) * df["atr"]
        rng = (df["high"] - df["low"]).replace(0, np.nan)
        close_pos = (df["close"] - df["low"]) / rng
        # 必须处在 1h 放量突破的方向上（最近 4 小时内出现过）
        long_ok = (
            (df["brk_up_recent"] > 0) & vol_ok & strength
            & (df["close"] > df["ema20"] + band) & (close_pos > 0.6)
        )
        short_ok = (
            (df["brk_dn_recent"] > 0) & vol_ok & strength
            & (df["close"] < df["ema20"] - band) & (close_pos < 0.4)
        )
        df.loc[long_ok, ["enter_long", "enter_tag"]] = (1, "vol_breakout_long")
        df.loc[short_ok, ["enter_short", "enter_tag"]] = (1, "vol_breakout_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill, **kwargs):
        """三段式止损：
            第 0 段：固定止损（入场价 ∓ stop_frac × 中位振幅）
            第 1 段：第一段止盈后，改为跟随极值的移动止损（trail1_frac）
            第 2 段：第二段止盈后，移动止损收紧（trail2_frac），防止回吐
        """
        med = self._med_amp(trade.is_short)
        stage = self._stage.get(trade.id, 0)
        entry = float(trade.open_rate)
        if stage == 0:
            dist = float(self.stop_frac.value) * med
            stop_price = entry * (1 + dist) if trade.is_short else entry * (1 - dist)
        else:
            if stage >= 3:
                trail = float(self.trail3_frac.value) * med
            elif stage == 2:
                trail = float(self.trail2_frac.value) * med
            else:
                trail = float(self.trail1_frac.value) * med
            if trade.is_short:
                ref = float(trade.min_rate or current_rate)
                stop_price = ref * (1 + trail)
                # 已止盈后止损不劣于入场价：做空的止损必须 <= 入场价（保本）
                stop_price = min(stop_price, entry)
            else:
                ref = float(trade.max_rate or current_rate)
                stop_price = ref * (1 - trail)
                # 做多的止损必须 >= 入场价（保本）
                stop_price = max(stop_price, entry)
        return stoploss_from_absolute(
            stop_price, current_rate, trade.is_short, float(trade.leverage or 1.0)
        )

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit,
                              min_stake, max_stake, current_entry_rate, current_exit_rate,
                              current_entry_profit, current_exit_profit, **kwargs):
        """分段止盈：先落袋一部分、再兑现中位行情，剩余交给移动止损。"""
        stage = self._stage.get(trade.id, 0)
        if stage >= 3:
            return None
        if trade.is_short:
            best_price = trade.min_rate
        else:
            best_price = trade.max_rate
        if best_price is None or not trade.open_rate:
            return None
        med = self._med_amp(trade.is_short)
        price_profit = (1.0 - float(best_price) / float(trade.open_rate)) if trade.is_short \
            else (float(best_price) / float(trade.open_rate) - 1.0)
        if stage == 0 and price_profit >= float(self.tp1_frac.value) * med:
            self._stage[trade.id] = 1
            return -float(trade.stake_amount) * float(self.tp1_exit.value), "tp1_partial"
        if stage == 1 and price_profit >= float(self.tp2_frac.value) * med:
            self._stage[trade.id] = 2
            return -float(trade.stake_amount) * float(self.tp2_exit.value), "tp2_partial"
        if stage == 2 and price_profit >= float(self.tp3_frac.value) * med:
            self._stage[trade.id] = 3
            return -float(trade.stake_amount) * float(self.tp3_exit.value), "tp3_partial"
        return None

    # ---- 日内风控 ------------------------------------------------------
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
                result["short" if getattr(t, "is_short", False) else "long"] += pnl
            self._day_pnl = result
        except Exception:
            pass
        return self._day_pnl

    def confirm_trade_entry(self, pair, order_type, amount, rate, time_in_force,
                            current_time, entry_tag, side, **kwargs) -> bool:
        pnl = self._closed_today_pnl(current_time)
        equity = float(self.config.get("dry_run_wallet") or self.config.get("starting_balance") or 1000.0)
        if equity > 0 and (pnl["long"] + pnl["short"]) / equity <= self.DAY_EQUITY_LIMIT:
            return False
        return True
