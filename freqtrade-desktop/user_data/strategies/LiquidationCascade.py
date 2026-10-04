"""BTC/ETH 永续 —— 清算瀑布反转策略（1 分钟）。

策略逻辑（与 `.scratch/liquidation-reversal/spec.md` 对应）
----------------------------------------------------------
1. 触发：1 分钟出现瀑布式单边行情（默认跌幅 ≥ 0.35%），且"清算/抛压强度分"
   `cx_flush_long_score` ≥ 阈值（该分数由跌幅、主动买卖失衡、OI 收缩、真实强平
   金额四部分组成；缺少强平数据时自动降级为前三项的代理分数）。
2. 确认：价格不再创新低（`cx_no_new_low`）、主动买盘回升（`cx_taker_imbalance_delta`
   由负转正，OFI 的 1 分钟近似）、盘口买盘回补（`cx_depth_imbalance_delta_1m`）、
   并且收盘价突破前一根 K 线高点（短周期高低点突破 / microprice 反向突破的代理）。
3. 入场：确认成立的那根 1 分钟 K 线收盘时市价入场（freqtrade 在收盘后下单）。
4. 出场：目标 0.3%–0.8%（minimal_roi，按价格换算成保证金收益率）、
   止损 0.2%–0.5%（stoploss，同样按价格换算）、时间止损 5–15 分钟（custom_exit）。
5. 过滤：流动性分位过低不入场；可用 `cascade_blackout_windows` 配置宏观事件
   静默窗口（freqtrade 没有经济日历，需要外部维护）。

数据来源（关键约束）
--------------------
Freqtrade 引擎没有强平流 / 盘口 / OI / 逐笔成交的数据通道，因此这些微观结构
特征由桌面端在引擎之外预先算好，写成一份按分钟对齐的特征文件：

    user_data/liquidation/<PAIR>-1m-cascade.csv.gz

生成方式（在 freqtrade-desktop/backend 下执行）：

    python scripts/build_cascade_features.py --pair BTC/USDT:USDT \\
        --start 2025-09-01 --end 2025-09-30 --trades --funding

回测、dry-run、实盘读取的是同一份文件（实盘中由清算采集器持续追加），
因此不存在"回测一套逻辑、实盘另一套逻辑"的漂移问题。文件缺失时策略不会开仓，
并在日志里给出提示。

stoploss / minimal_roi 口径（已核对 freqtrade 2025.5 源码）
----------------------------------------------------------
`Trade.adjust_stop_loss` 用 `current_price * (1 - abs(stoploss) / leverage)` 计算
止损价，`backtesting` 的 ROI 也用 `open_rate * roi / leverage`，也就是两者都是
**保证金（持仓）收益率**，不是价格涨跌幅。本策略用价格口径的参数
（`PRICE_STOP_DEFAULT` / `PRICE_TARGET_DEFAULT`）乘以杠杆换算，避免把 0.35%
的价格止损误写成 0.35% 保证金止损（5 倍杠杆下会差 5 倍）。
"""

from __future__ import annotations

import gzip
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter, IStrategy


logger = logging.getLogger(__name__)

# 静默窗口写法："2026-09-17 18:00-2026-09-17 20:00"（两个日期时间，分隔符任意）。
_BLACKOUT_TOKEN = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")


class LiquidationCascade(IStrategy):
    INTERFACE_VERSION = 3

    # 1 分钟是 freqtrade 支持的最小周期，也是清算瀑布策略能拿到的最高频率。
    timeframe = "1m"
    process_only_new_candles = True
    # 特征文件自身已经处理了滚动窗口的预热，这里只留出 ATR/分位数所需的最短长度。
    startup_candle_count = 70

    # ---- 资金与杠杆 ------------------------------------------------------
    LEVERAGE = 5.0
    RISK_PER_TRADE = 0.01          # 单笔权益风险上限 1%
    MAX_STAKE_FRACTION = 0.35      # 单笔保证金占可用余额上限

    # ---- 价格口径的风控参数（会换算成 freqtrade 的保证金口径） -----------
    PRICE_STOP_DEFAULT = 0.0035    # 0.35% 价格止损（策略描述：0.2%–0.5%）
    PRICE_TARGET_DEFAULT = 0.005   # 0.5% 价格止盈（策略描述：0.3%–0.8%）

    # freqtrade 的 stoploss / minimal_roi 都按保证金收益率计，故乘以杠杆。
    stoploss = -PRICE_STOP_DEFAULT * LEVERAGE
    minimal_roi = {"0": PRICE_TARGET_DEFAULT * LEVERAGE}
    use_custom_stoploss = False    # 保留 freqtrade 原生 stoploss 超参搜索空间
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False
    # OKX 支持交易所侧止损（exchange/okx.py 的 _ft_has），回测会自动忽略该开关。
    stoploss_on_exchange = True

    # ---- 超参（space=buy 用于入场，space=sell 用于出场） ------------------
    move_pct = DecimalParameter(0.0005, 0.0060, default=0.0010, decimals=4, space="buy",
                                optimize=True)
    # BTC 单分钟很少出现 0.5% 以上的波动（实测：1m 收益标准差 ≈0.05%，
    # 0.5% ≈ 10σ），所以触发阈值按波动率自适应：
    #     阈值 = max(move_pct, move_atr_mult × ATR%_1m(14))
    # 默认 max(0.10%, 2.5×ATR%) 在典型 ATR%≈0.06% 时约 0.15%（≈3σ）。
    move_atr_mult = DecimalParameter(1.0, 4.0, default=2.5, decimals=1, space="buy",
                                     optimize=True)
    flush_score_min = DecimalParameter(1.0, 3.5, default=1.8, decimals=2, space="buy",
                                       optimize=True)
    liq_ratio_min = DecimalParameter(0.5, 3.0, default=1.0, decimals=2, space="buy",
                                     optimize=True)
    require_liquidations = CategoricalParameter([True, False], default=False, space="buy",
                                                optimize=False)
    confirm_window = IntParameter(1, 6, default=3, space="buy", optimize=True)
    depth_delta_min = DecimalParameter(-0.05, 0.20, default=0.02, decimals=2, space="buy",
                                       optimize=True)
    taker_delta_min = DecimalParameter(-0.05, 0.40, default=0.05, decimals=2, space="buy",
                                       optimize=True)
    liquidity_pct_min = DecimalParameter(0.0, 0.60, default=0.05, decimals=2, space="buy",
                                         optimize=True)
    max_holding_minutes = IntParameter(3, 90, default=30, space="sell", optimize=True)
    # 被动（maker）入场：在触发 K 线收盘价下方 entry_offset_pct 挂限价单，
    # 只有后续 entry_valid_minutes 分钟内价格真的回到该价位才成交；没回到就不交易。
    # 回测里成交价用挂单价、且要求当根 K 线 low/high 真的触及该价——因此不会
    # 假设"挂单必然成交"。
    entry_offset_pct = DecimalParameter(0.0, 0.0020, default=0.0005, decimals=4, space="buy",
                                        optimize=True)
    entry_valid_minutes = IntParameter(1, 5, default=2, space="buy", optimize=True)
    # 波动率门槛：目标 0.6% 价格在 1 分钟 ATR 过低时不可能在持有窗口内达到，
    # 达不到门槛就不交易（少交易、单笔毛期望更大，才付得起手续费）。
    min_atr_pct = DecimalParameter(0.0, 0.0030, default=0.0006, decimals=4, space="buy",
                                   optimize=True)
    exit_on_flow_flip = CategoricalParameter([True, False], default=True, space="sell",
                                             optimize=False)
    # 反向瀑布出现时是否必须已有浮盈才允许离场。默认 True：否则刚入场就被
    # 反向分数扫出场，来回付手续费（实测 1 天 1000+ 笔的"churn"就来自这里）。
    flow_flip_requires_profit = CategoricalParameter([True, False], default=True, space="sell",
                                                     optimize=False)
    # 只做多 / 只做空的研究开关（默认双向）。
    trade_side = CategoricalParameter(["both", "long", "short"], default="both", space="buy",
                                      optimize=False)
    # 交易的是"反转"还是"延续"：
    #   fade   —— 急跌后做多、急涨后做空（策略原始假设）
    #   follow —— 急跌后做空、急涨后做多（顺着急动的方向跟进）
    # 两者共用同一套触发/确认构件，只是把方向对调。
    entry_direction = CategoricalParameter(["fade", "follow"], default="fade", space="buy",
                                           optimize=False)

    FEATURE_COLUMNS = (
        "cx_ret_1m", "cx_no_new_low", "cx_no_new_high", "cx_taker_imbalance",
        "cx_taker_imbalance_delta", "cx_depth_imbalance_1pct", "cx_depth_imbalance_delta_1m",
        "cx_liquidity_percentile_24h", "cx_flush_long_score", "cx_flush_short_score",
        "cx_liq_ratio_1h", "cx_has_liquidations", "cx_oi_chg_5m_pct", "cx_atr_pct",
    )

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config or {})
        self._feature_cache: dict[str, tuple[float, DataFrame]] = {}
        self._pending_entry_prices: dict[tuple[str, int], float] = {}
        self._warned_pairs: set[str] = set()
        self._blackouts = self._parse_blackouts(
            (self.config or {}).get("cascade_blackout_windows") or []
        )

    # ------------------------------------------------------------ helpers
    @property
    def can_short(self) -> bool:
        try:
            return (self.config or {}).get("trading_mode", "spot") != "spot"
        except Exception:
            return False

    @staticmethod
    def _parse_blackouts(raw: Any) -> list[tuple[datetime, datetime]]:
        """``["2026-09-17 18:00-2026-09-17 20:00", ...]`` -> tz-aware ranges."""
        parsed: list[tuple[datetime, datetime]] = []
        for item in raw if isinstance(raw, (list, tuple)) else []:
            try:
                tokens = _BLACKOUT_TOKEN.findall(str(item))
                if len(tokens) < 2:
                    raise ValueError(f"expected two timestamps, got {tokens!r}")
                start = datetime.fromisoformat(tokens[0].replace(" ", "T"))
                end = datetime.fromisoformat(tokens[1].replace(" ", "T"))
            except (ValueError, AttributeError) as exc:
                logger.warning("LiquidationCascade: 无法解析静默窗口 %r（%s）", item, exc)
                continue
            start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
            end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
            parsed.append((start, end))
        return parsed

    def _in_blackout(self, moment: datetime) -> bool:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return any(start <= moment <= end for start, end in self._blackouts)

    def _features_for(self, pair: str) -> DataFrame | None:
        """Load (and cache by mtime) the pre-computed feature file for ``pair``."""
        user_data = Path((self.config or {}).get("user_data_dir") or "user_data")
        slug = pair.replace("/", "_").replace(":", "_")
        path = user_data / "liquidation" / f"{slug}-{self.timeframe}-cascade.csv.gz"
        if not path.exists():
            if pair not in self._warned_pairs:
                self._warned_pairs.add(pair)
                logger.warning(
                    "LiquidationCascade: 缺少特征文件 %s —— 该币对不会开仓。"
                    "请先运行 backend/scripts/build_cascade_features.py。",
                    path,
                )
            return None
        stamp = path.stat().st_mtime
        cached = self._feature_cache.get(pair)
        if cached and cached[0] == stamp:
            return cached[1]
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            frame = pd.read_csv(handle)
        if "date" not in frame.columns:
            logger.error("LiquidationCascade: %s 缺少 date 列，忽略该文件", path)
            return None
        self._feature_cache[pair] = (stamp, frame)
        return frame

    def _cached_frame(self, pair: str) -> DataFrame | None:
        """The already-loaded feature frame for ``pair`` (None if never loaded)."""
        entry = self._feature_cache.get(pair)
        return entry[1] if entry else None

    def _merge_features(self, dataframe: DataFrame, pair: str) -> DataFrame:
        frame = self._features_for(pair)
        if frame is None:
            for column in self.FEATURE_COLUMNS:
                if column not in dataframe.columns:
                    dataframe[column] = np.nan
            dataframe["cx_features_available"] = False
            return dataframe
        minutes = (dataframe["date"].astype("int64") // 1_000_000).astype("int64")
        merged = dataframe.merge(
            frame.assign(date=frame["date"].astype("int64")),
            left_on=minutes,
            right_on="date",
            how="left",
            suffixes=("", "_cx"),
        )
        merged.index = dataframe.index
        merged["cx_features_available"] = merged.get("cx_ret_1m").notna() if "cx_ret_1m" in merged else False
        for column in self.FEATURE_COLUMNS:
            if column not in merged.columns:
                merged[column] = np.nan
        return merged.drop(columns=[c for c in merged.columns if c.endswith("_cx")])

    @staticmethod
    def _usable(dataframe: DataFrame, column: str) -> bool:
        return column in dataframe.columns and dataframe[column].notna().any()

    # ------------------------------------------------------- indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self._merge_features(dataframe, metadata["pair"])

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        if "cx_flush_long_score" not in dataframe.columns:
            return dataframe

        window = max(1, int(self.confirm_window.value))
        drop = dataframe["cx_ret_1m"]
        atr_floor = (
            self.move_atr_mult.value * dataframe["cx_atr_pct"]
            if self._usable(dataframe, "cx_atr_pct")
            else 0.0
        )
        move_threshold = np.maximum(self.move_pct.value, atr_floor)

        # --- 触发：单边瀑布 + 抛压/清算强度分 -----------------------------
        # flush_down = 急跌（下方向瀑布）；flush_up = 急涨（上方向挤压）
        flush_down = (drop <= -move_threshold) & (
            dataframe["cx_flush_long_score"] >= self.flush_score_min.value
        )
        flush_up = (drop >= move_threshold) & (
            dataframe["cx_flush_short_score"] >= self.flush_score_min.value
        )
        if bool(self.require_liquidations.value) and self._usable(dataframe, "cx_liq_ratio_1h"):
            liquidated = dataframe["cx_liq_ratio_1h"] >= self.liq_ratio_min.value
            flush_down &= liquidated
            flush_up &= liquidated

        recent_down = flush_down.rolling(window, min_periods=1).max().fillna(0).astype(bool)
        recent_up = flush_up.rolling(window, min_periods=1).max().fillna(0).astype(bool)

        # --- 确认：不再创新低/新高 + 主动买卖回升 + 盘口回补 --------------
        confirm_depth = (
            dataframe["cx_depth_imbalance_delta_1m"] >= self.depth_delta_min.value
            if self._usable(dataframe, "cx_depth_imbalance_delta_1m")
            else True
        )
        confirm_taker = (
            dataframe["cx_taker_imbalance_delta"] >= self.taker_delta_min.value
            if self._usable(dataframe, "cx_taker_imbalance_delta")
            else True
        )
        # 入场确认：收盘价突破前一根 K 线的高/低点（短周期高低点突破）。
        prior_high = dataframe["high"].shift(1)
        prior_low = dataframe["low"].shift(1)
        breakout_long = dataframe["close"] > prior_high
        breakout_short = dataframe["close"] < prior_low

        liquidity_ok = (
            dataframe["cx_liquidity_percentile_24h"] >= self.liquidity_pct_min.value
            if self._usable(dataframe, "cx_liquidity_percentile_24h")
            else True
        )

        # 反转确认（价格不再创新低 + 买盘回补 + 向上突破）
        setup_reversal_up = (
            recent_down
            & (dataframe["cx_no_new_low"].fillna(0) > 0)
            & confirm_taker
            & confirm_depth
            & breakout_long
            & liquidity_ok
        )
        # 反转确认（价格不再创新高 + 卖盘回补 + 向下突破）
        setup_reversal_down = (
            recent_up
            & (dataframe["cx_no_new_high"].fillna(0) > 0)
            & confirm_taker
            & confirm_depth
            & breakout_short
            & liquidity_ok
        )
        # 延续确认：急跌之后继续向下突破 / 急涨之后继续向上突破
        setup_follow_down = (
            recent_down
            & (dataframe["cx_no_new_high"].fillna(0) > 0)
            & breakout_short
            & liquidity_ok
        )
        setup_follow_up = (
            recent_up
            & (dataframe["cx_no_new_low"].fillna(0) > 0)
            & breakout_long
            & liquidity_ok
        )
        if str(self.entry_direction.value) == "follow":
            long_signal, short_signal = setup_follow_up, setup_follow_down
        else:
            long_signal, short_signal = setup_reversal_up, setup_reversal_down
        side_mode = str(self.trade_side.value)
        if side_mode == "long":
            short_signal &= False
        elif side_mode == "short":
            long_signal &= False

        # 波动率门槛：ATR% 太低时 0.6% 级别的目标在持有窗口内不可达，直接不交易。
        if self._usable(dataframe, "cx_atr_pct"):
            vol_ok = dataframe["cx_atr_pct"] >= float(self.min_atr_pct.value)
            long_signal &= vol_ok
            short_signal &= vol_ok
        long_signal = pd.Series(np.asarray(long_signal, dtype=bool), index=dataframe.index)
        short_signal = pd.Series(np.asarray(short_signal, dtype=bool), index=dataframe.index)

        # 被动挂单：触发后把限价挂在触发 K 线收盘价 ±offset，等价格回来才成交。
        offset = float(self.entry_offset_pct.value)
        valid = max(1, int(self.entry_valid_minutes.value))
        close = dataframe["close"]
        follow = str(self.entry_direction.value) == "follow"
        long_fill = pd.Series(False, index=dataframe.index)
        short_fill = pd.Series(False, index=dataframe.index)
        long_price = pd.Series(np.nan, index=dataframe.index, dtype="float64")
        short_price = pd.Series(np.nan, index=dataframe.index, dtype="float64")
        for step in range(1, valid + 1):
            trigger_long = long_signal.shift(step, fill_value=False)
            trigger_short = short_signal.shift(step, fill_value=False)
            if follow:
                # 延续：等价格朝急动方向再走 offset 才成交（突破入场）
                limit_long = close.shift(step) * (1 + offset)
                limit_short = close.shift(step) * (1 - offset)
                hit_long = trigger_long & (dataframe["high"] >= limit_long) & ~long_fill
                hit_short = trigger_short & (dataframe["low"] <= limit_short) & ~short_fill
            else:
                # 反转：等价格回踩 offset 才成交（挂单入场）
                limit_long = close.shift(step) * (1 - offset)
                limit_short = close.shift(step) * (1 + offset)
                hit_long = trigger_long & (dataframe["low"] <= limit_long) & ~long_fill
                hit_short = trigger_short & (dataframe["high"] >= limit_short) & ~short_fill
            long_fill |= hit_long
            short_fill |= hit_short
            long_price = long_price.where(~hit_long, limit_long)
            short_price = short_price.where(~hit_short, limit_short)

        dataframe.loc[long_fill, "enter_long"] = 1
        dataframe.loc[short_fill, "enter_short"] = 1
        if "enter_tag" not in dataframe.columns:
            dataframe["enter_tag"] = ""
        prefix = "follow" if str(self.entry_direction.value) == "follow" else "cascade"
        dataframe.loc[long_fill, "enter_tag"] = f"{prefix}_long_limit"
        dataframe.loc[short_fill & ~long_fill, "enter_tag"] = f"{prefix}_short_limit"
        self._remember_entry_prices(metadata["pair"], dataframe, long_fill, long_price, short_fill,
                                    short_price)
        return dataframe

    def _remember_entry_prices(
        self,
        pair: str,
        dataframe: DataFrame,
        long_fill: pd.Series,
        long_price: pd.Series,
        short_fill: pd.Series,
        short_price: pd.Series,
    ) -> None:
        """Record the passive fill price per candle so ``custom_entry_price`` can use it."""
        minutes = (dataframe["date"].astype("int64") // 1_000_000).astype("int64")
        for mask, prices in ((long_fill, long_price), (short_fill, short_price)):
            for index in dataframe.index[mask]:
                value = prices.at[index]
                if np.isfinite(value):
                    self._pending_entry_prices[(pair, int(minutes.at[index]))] = float(value)
        if len(self._pending_entry_prices) > 20_000:
            for key in list(self._pending_entry_prices)[:10_000]:
                self._pending_entry_prices.pop(key, None)

    def custom_entry_price(self, pair: str, trade: Trade | None, current_time: datetime,
                           proposed_rate: float, entry_tag: str | None, side: str,
                           **kwargs: Any) -> float:
        """Return the passive limit price recorded when the fill candle closed."""
        minutes = int(pd.Timestamp(current_time).value // 1_000_000)
        price = self._pending_entry_prices.get((pair, minutes))
        return float(price) if price is not None else proposed_rate

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        if "cx_flush_short_score" not in dataframe.columns:
            return dataframe
        # 反向清算瀑布出现时离场（目标/止损/时间止损由 freqtrade 处理）。
        dataframe.loc[
            (dataframe["cx_flush_short_score"] >= self.flush_score_min.value)
            & (dataframe["cx_ret_1m"] >= self.move_pct.value),
            "exit_long",
        ] = 1
        dataframe.loc[
            (dataframe["cx_flush_long_score"] >= self.flush_score_min.value)
            & (dataframe["cx_ret_1m"] <= -self.move_pct.value),
            "exit_short",
        ] = 1
        return dataframe

    # ------------------------------------------------------ order handling
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None,
                 side: str, **kwargs: Any) -> float:
        return min(self.LEVERAGE, max_leverage)

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float | None, max_stake: float,
                            leverage: float, entry_tag: str | None, side: str,
                            **kwargs: Any) -> float:
        """按"价格止损距离 × 杠杆"反推仓位，使单笔权益风险≈RISK_PER_TRADE。"""
        stop_rate = max(self.PRICE_STOP_DEFAULT * leverage, 1e-9)
        stake = max_stake * min(1.0, self.RISK_PER_TRADE / stop_rate)
        stake = min(stake, max_stake * self.MAX_STAKE_FRACTION)
        if min_stake:
            stake = max(stake, min_stake)
        return float(min(stake, max_stake))

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: str | None,
                            side: str, **kwargs: Any) -> bool:
        if self._in_blackout(current_time):
            return False
        # 数据缺失（没有特征文件或该分钟无特征）时不允许开仓。
        frame = self._cached_frame(pair)
        if frame is None:
            return False
        minutes = int(pd.Timestamp(current_time).value // 1_000_000)
        row = frame.loc[frame["date"] == minutes]
        if row.empty or not np.isfinite(row["cx_flush_long_score"].iloc[0]
                                         if side == "long" else row["cx_flush_short_score"].iloc[0]):
            return False
        return True

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float,
                    current_profit: float, **kwargs: Any) -> str | bool | None:
        held_minutes = (current_time - trade.open_date_utc).total_seconds() / 60.0
        if held_minutes >= self.max_holding_minutes.value:
            return "time_stop"
        if bool(self.exit_on_flow_flip.value):
            frame = self._cached_frame(pair)
            if frame is not None:
                minutes = int(pd.Timestamp(current_time).value // 1_000_000)
                row = frame.loc[frame["date"] == minutes]
                if not row.empty:
                    score = float(
                        row["cx_flush_short_score"].iloc[0]
                        if trade.is_short is False
                        else row["cx_flush_long_score"].iloc[0]
                    )
                    if np.isfinite(score) and score >= self.flush_score_min.value * 1.5:
                        if bool(self.flow_flip_requires_profit.value) and current_profit <= 0:
                            return None
                        return "flow_flip"
        return None
