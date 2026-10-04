"""BTC/USDT 动量突破策略（15m 信号 / 5m 明细执行）—— 详细中文注释版。

本文件是「唐奇安通道突破 + ATR 吊灯止损」的趋势跟踪策略。下面按模块说明它的
交易思路，并坦白列出它的缺陷（注释只描述现状，不代表这些设计合理）。

===============================================================================
一、整体交易思路
===============================================================================
    1. 入场：纯价格突破。收盘价创出前 N 根 15m K 线的新高就做多，创出新低就
       做空，没有任何成交量 / 趋势 / 波动率过滤。
    2. 离场：不做主动止盈信号，而是用「吊灯式移动止损」——
       止损挂在持仓期间的最有利价格往回 k×ATR 的位置，价格一旦回撤到那里就
       离场。理论上让盈利单尽量奔跑，代价是回吐大。
    3. 仓位：按「单笔打止损约亏本金 RISK_PER_TRADE」反推保证金，使每笔风险
       大致固定。
    4. 日内风控：当天已平仓亏损达到本金 10% 时，当天不再开新仓。
    5. 另有一套「分段止盈」代码（先平一部分锁定利润），但默认关闭。

===============================================================================
二、数据口径与执行方式
===============================================================================
    - timeframe = "15m"：信号只按 15m K 线收盘确认。
    - process_only_new_candles = True：同一根未走完的 K 线内不重复判断信号。
    - 回测用 --timeframe-detail 5m：15m 只负责产生信号，5m 明细负责模拟成交价
      与止损触发时点，比纯 15m 更接近真实成交。
    - 所有指标都是滚动窗口计算：唐奇安通道 forward 位移用 shift(1) 排除当前根，
      ATR 只用当前及以前的数据，因此不含未来函数。

===============================================================================
三、入场规则（populate_entry_trend）
===============================================================================
    don_high = 前 don 根 15m 的最高价（shift(1) 后移，不含当前根）
    don_low  = 前 don 根 15m 的最低价（shift(1) 后移，不含当前根）

    做多：当前收盘价 > don_high，即向上突破前 don 根的新高。
    做空：当前收盘价 < don_low， 即向下跌破前 don 根的新低。

    没有成交量确认、没有趋势过滤、没有波动率过滤。只要突破就下单，因此在震荡
    区间会反复在"假突破"处开仓，这是它产生大量小额亏损单的直接原因。

===============================================================================
四、止损规则（custom_stoploss：吊灯止损 / chandelier stop）
===============================================================================
    做多：止损价 = 持仓期间最高价 trade.max_rate - k × ATR(14, 15m)
    做空：止损价 = 持仓期间最低价 trade.min_rate + k × ATR(14, 15m)

    再把「相对入场价的最大亏损」用 MAX_STOP_PRICE 硬限制在 7.5% 价格以内
    （stoploss = -0.40 只是 5x 杠杆下的兜底值，对应 8% 价格）。

    因为 k 默认 15（15 倍 ATR）非常宽，所以实际表现是：
      - 止损通常发生在价格已经从最有利位置大幅回撤之后；
      - 一笔曾经明显浮盈的单子，可能一路回吐到接近入场价才被止损，最终只赚
        一点点，甚至被手续费吃掉变成小额亏损。
    这正是"放跑收益、止损没意义"这种观感的来源。

===============================================================================
五、仓位规则（custom_stake_amount）
===============================================================================
    先根据当前 ATR 算出止损距离 stop_pct（被限制在 1%~7.5% 之间），然后按
        保证金 = 可用保证金 × (RISK_PER_TRADE / (stop_pct × 杠杆))
    反推仓位，使「打一次止损约等于亏掉本金的 RISK_PER_TRADE（默认 4%）」。

    额外约束：BTC/USDT:USDT 一手合约是 0.01 BTC（名义约 850~1150 USDT），
    小资金（如 1000 USDT 本金）下按风险算出的仓位常常不足一手，会被抬到最小
    合约，于是实际单笔风险和手续费占比都会偏离设计值（手续费按名义金额的
    0.1%/边收取，很容易吃掉幅度很小的有利波动）。

===============================================================================
六、分段止盈（adjust_trade_position）—— 默认关闭
===============================================================================
    逻辑：持仓期间价格相对入场价有利幅度达到 tp1_price（默认 2.5%）时，平掉
    tp_exit_frac（默认 60%）的仓位锁定收益，剩下的仓位继续用 ATR 吊灯止损去
    博突破行情的超额收益。判断用的是 trade.max_rate / trade.min_rate（持仓期间
    的最高 / 最低价），和移动止损口径一致。

    但本文件 position_adjustment_enable = False，所以这段代码当前不会执行，
    仅作为可选功能保留（实测在该配置下开启分段止盈会让总收益下降）。

===============================================================================
七、日内风控（confirm_trade_entry）
===============================================================================
    每次准备开仓前，统计"当天已平仓交易"的已实现盈亏之和；若当天亏损达到本金
    的 10%（DAY_EQUITY_LIMIT），则拒绝当天后续所有新开仓，隔天自动重置。
    统计通过 Freqtrade 的 Trade.get_trades_proxy() 完成，回测时会走 LocalTrade
    代理，实盘则查数据库。

===============================================================================
八、已知缺陷（客观陈述）
===============================================================================
    1. 入场完全不做过滤，震荡市里假突破频繁开仓 → 大量小额亏损；
    2. k=15 的 ATR 止损过宽，盈利回吐严重，止损位离入场价很远；
    3. 没有趋势 / 量能 / 波动率确认，也没有"突破失败就快速离场"的机制；
    4. 分段止盈默认关闭，所以实际上没有"及时止盈"动作；
    5. 小资金 + 最小合约导致仓位与手续费口径失真，微小有利波动常被手续费吃掉。
"""

import sys
from pathlib import Path

# 把策略目录加入 sys.path，保证可以 import 同目录的 eth_common
# （超参寻优在子进程里反序列化策略时也需要这一行）。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np
from pandas import DataFrame

from eth_common import atr_series
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from freqtrade.strategy.strategy_helper import stoploss_from_absolute


class BTC_2025_Breakout(IStrategy):
    # ---- 运行框架配置 --------------------------------------------------
    timeframe = "15m"                 # 信号周期：15m 收盘确认突破
    startup_candle_count = 400        # 预热 K 线数量，保证 don/ATR 有足够历史
    process_only_new_candles = True    # 未收盘的 K 线不重复触发信号
    use_exit_signal = False           # 不使用 exit_long/exit_short 信号离场
    exit_profit_only = False          # （配合上一条）允许多种离场原因
    ignore_roi_if_entry_signal = True  # 有入场信号时不因 ROI 平仓（本策略无 ROI）

    # 是否允许加仓/减仓。分段止盈依赖它为 True，但当前默认 False，
    # 因此 adjust_trade_position() 不会被调用（见上文第六节）。
    position_adjustment_enable = False

    # ---- 止损配置 ------------------------------------------------------
    # stoploss 是"保证金收益率"口径：5x 杠杆下 -0.40 对应 8% 价格跌幅。
    # 这里只作为硬性兜底（最坏情况），实际止损点位由 custom_stoploss 动态给出。
    stoploss = -0.40
    use_custom_stoploss = True        # 启用自定义止损（ATR 吊灯止损）
    trailing_stop = False             # 不用内置固定比例移动止损，避免与自定义冲突

    # ---- 可优化参数（buy 空间，供 hyperopt 搜索）------------------------
    don = IntParameter(40, 240, default=60, space="buy")            # 突破回看根数
    atr_mult = DecimalParameter(8.0, 20.0, default=15.0, decimals=1, space="buy")  # ATR 倍数 k
    tp1_price = DecimalParameter(0.015, 0.040, default=0.025, decimals=3, space="buy")  # 分段止盈触发（价格口径）
    tp_exit_frac = DecimalParameter(0.4, 0.8, default=0.6, decimals=2, space="buy")    # 分段止盈平仓比例

    # ---- 风险与资金参数 -------------------------------------------------
    RISK_PER_TRADE = 0.04             # 单笔目标权益风险 4%
    DAY_EQUITY_LIMIT = -0.10          # 当日已实现亏损达到本金 -10% 时停止开仓
    LEVERAGE = 5                      # 固定 5x 杠杆
    MAX_STOP_PRICE = 0.075            # 单笔最大价格止损距离 7.5%（名义回撤上限）

    def __init__(self, config) -> None:
        super().__init__(config)
        self._loss_day = ""                       # 日内风控：当前统计的日期
        self._day_pnl = {"long": 0.0, "short": 0.0}  # 当日已实现盈亏（按方向）
        self._tp_stage = {}                       # 分段止盈状态：trade.id -> 已执行阶段
        self._atr_dates = None                    # ATR 时间戳数组（纳秒，升序）
        self._atr_vals = None                     # 与时间戳对应的 ATR 数值数组

    @property
    def can_short(self):
        # 只有合约模式才允许做空；现货返回 False。
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    def leverage(self, pair, current_time, current_rate, proposed_leverage,
                 max_leverage, entry_tag, side, **kwargs):
        # 固定 5x 杠杆（不超过交易所允许的上限由框架兜底处理）。
        return float(self.LEVERAGE)

    def _atr_at(self, current_time):
        """取 current_time 时点（含该时点）最近的 ATR 值。

        ATR 在 populate_indicators 里预先算好并缓存成两个 numpy 数组，
        这里用二分查找定位，避免每根 K 线都重新计算 / 重建 Series。
        """
        if self._atr_dates is None:
            return None
        cur = pd.Timestamp(current_time)
        if cur.tzinfo is None:
            cur = cur.tz_localize("UTC")
        else:
            cur = cur.tz_convert("UTC")
        cur_ns = cur.value  # 转成自 epoch 起的纳秒整数，与缓存数组同口径比较
        idx = int(np.searchsorted(self._atr_dates, cur_ns, side="right")) - 1
        if idx < 0:
            return None
        val = float(self._atr_vals[idx])
        return val if val > 0 else None

    def _stop_pct(self, current_time, current_rate):
        """把 ATR 换算成"价格止损距离百分比"，并夹在 1%~7.5% 之间。

        没有可用 ATR 时退化为固定 5%（仅作为异常兜底）。
        """
        atr = self._atr_at(current_time)
        if atr and current_rate:
            pct = float(self.atr_mult.value) * atr / float(current_rate)
            return min(max(pct, 0.01), self.MAX_STOP_PRICE)
        return 0.05

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake,
                            min_stake, max_stake, leverage, entry_tag, side, **kwargs):
        """按"单笔止损约亏 RISK_PER_TRADE 本金"反推保证金。

        公式：保证金 = 可用保证金 × RISK_PER_TRADE / (止损距离% × 杠杆)
        再保证不低于交易所最小仓位；最后不超过可用保证金。
        """
        stop_pct = self._stop_pct(current_time, current_rate)
        stake = max_stake * (self.RISK_PER_TRADE / (stop_pct * leverage))
        # BTC/USDT:USDT 一手 = 0.01 BTC，按名义金额换算成所需保证金，避免仓位被
        # 合约精度截断成 0（小资金下经常触发）。
        min_contract_margin = 0.01 * current_rate / max(leverage, 1e-9)
        stake = max(stake, min_contract_margin, min_stake or 0.0)
        return min(stake, max_stake)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算指标：唐奇安通道 + ATR，并缓存 ATR 供回调函数按时间查询。"""
        n = int(self.don.value)
        # 用 shift(1) 后移一根：通道只包含"当前根之前"的 K 线，避免用当前收盘价
        # 与自己比较，也避免未来函数。
        dataframe["don_high"] = dataframe["high"].rolling(n).max().shift(1)
        dataframe["don_low"] = dataframe["low"].rolling(n).min().shift(1)
        dataframe["atr"] = atr_series(dataframe["high"], dataframe["low"], dataframe["close"], 14)
        # 缓存成 numpy 数组（纳秒时间戳 + ATR 值），供 _atr_at() 二分查找。
        self._atr_dates = pd.to_datetime(dataframe["date"], utc=True).astype("int64").to_numpy()
        self._atr_vals = dataframe["atr"].to_numpy()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """入场信号：收盘价突破唐奇安通道上/下轨。"""
        df = dataframe
        long_ok = df["close"] > df["don_high"]    # 向上突破前 don 根最高价
        short_ok = df["close"] < df["don_low"]    # 向下跌破前 don 根最低价
        df.loc[long_ok, ["enter_long", "enter_tag"]] = (1, "breakout_long")
        df.loc[short_ok, ["enter_short", "enter_tag"]] = (1, "breakout_short")
        return df

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 本策略不使用信号离场（use_exit_signal = False），这里原样返回。
        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill, **kwargs):
        """ATR 吊灯止损：把止损挂在持仓期间极值往回 k×ATR 的位置。

        返回的是"相对当前价的止损比例"（stoploss_from_absolute 负责换算），
        Freqtrade 内部的 adjust_stop_loss 只会让止损单向收紧，所以整体表现为
        一条跟随价格新高/新低移动、且不会反向放松的止损线。
        """
        atr = self._atr_at(current_time)
        if atr is None:
            return None  # 没有 ATR 时交回框架用 stoploss 兜底
        k = float(self.atr_mult.value)
        if trade.is_short:
            # 做空：以持仓期间最低价为基准，止损放在其上方 k×ATR
            ref = float(trade.min_rate or current_rate)
            stop_price = ref + k * atr
            # 硬上限：相对入场价最多亏 MAX_STOP_PRICE（7.5%）
            cap = float(trade.open_rate) * (1 + self.MAX_STOP_PRICE)
            stop_price = min(stop_price, cap)
        else:
            # 做多：以持仓期间最高价为基准，止损放在其下方 k×ATR
            ref = float(trade.max_rate or current_rate)
            stop_price = ref - k * atr
            cap = float(trade.open_rate) * (1 - self.MAX_STOP_PRICE)
            stop_price = max(stop_price, cap)
        return stoploss_from_absolute(
            stop_price, current_rate, trade.is_short, float(trade.leverage or 1.0)
        )

    def adjust_trade_position(self, trade, current_time, current_rate, current_profit,
                              min_stake, max_stake, current_entry_rate, current_exit_rate,
                              current_entry_profit, current_exit_profit, **kwargs):
        """分段止盈（默认不启用，position_adjustment_enable = False）。

        逻辑：价格相对入场价的有利幅度首次达到 tp1_price 时，平掉 tp_exit_frac
        比例的仓位锁定收益；每笔交易只执行一次（用 _tp_stage 记录）。返回负的
        stake 表示减仓。
        """
        stage = self._tp_stage.get(trade.id, 0)
        if stage >= 1:
            return None  # 该笔已经做过一次分段止盈
        # 用持仓期间的极值判断（与吊灯止损同口径），而不是只看当前开盘价
        if trade.is_short:
            best_price = trade.min_rate
        else:
            best_price = trade.max_rate
        if best_price is None or not trade.open_rate:
            return None
        if trade.is_short:
            price_profit = 1.0 - float(best_price) / float(trade.open_rate)
        else:
            price_profit = float(best_price) / float(trade.open_rate) - 1.0
        if price_profit >= float(self.tp1_price.value):
            self._tp_stage[trade.id] = 1
            reduce_stake = float(trade.stake_amount) * float(self.tp_exit_frac.value)
            return -reduce_stake, "tp1_partial"
        return None

    # ---- 日内风控 ------------------------------------------------------

    def _today(self, current_time) -> str:
        """把当前时间转换成 UTC 日期字符串，作为当日统计的 key。"""
        return pd.Timestamp(current_time).tz_convert("UTC").strftime("%Y-%m-%d")

    def _reset_daily_state(self, day: str) -> None:
        """跨交易日时重置当日累计盈亏。"""
        if self._loss_day != day:
            self._loss_day = day
            self._day_pnl = {"long": 0.0, "short": 0.0}

    def _closed_today_pnl(self, current_time):
        """统计当日已平仓交易的已实现盈亏（按多/空分别累加）。

        回测时 Trade.get_trades_proxy() 走 LocalTrade 代理，实盘则查数据库。
        出错时静默返回上一次的统计值，避免中断策略。
        """
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
        """开仓前检查：当日已实现亏损达到本金 DAY_EQUITY_LIMIT 时拒绝开仓。"""
        pnl = self._closed_today_pnl(current_time)
        equity = float(self.config.get("dry_run_wallet") or self.config.get("starting_balance") or 1000.0)
        total = pnl["long"] + pnl["short"]
        if equity > 0 and total / equity <= self.DAY_EQUITY_LIMIT:
            return False
        return True
