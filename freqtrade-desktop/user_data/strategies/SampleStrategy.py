"""演示策略：均线交叉 + RSI 过滤 + 布林带边界退出。

纯 pandas 实现（不依赖 TA-Lib），可直接用于回测、dry-run 与实盘。
包含两个可超参优化的参数（buy_rsi_low / sell_rsi_high）。
"""

from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter


class SampleStrategy(IStrategy):
    timeframe = "5m"

    stoploss = -0.05
    trailing_stop = False

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    minimal_roi = {
        "0": 0.08,
        "60": 0.04,
        "240": 0.0,
    }

    process_only_new_candles = True
    startup_candle_count = 60

    @property
    def can_short(self) -> bool:
        # Allow shorting on futures, disable on spot (freqtrade rejects short
        # strategies on spot markets). Short signals are ignored on spot.
        try:
            return (self.config or {}).get("trading_mode") != "spot"
        except Exception:
            return False

    # 可超参优化（hyperopt --spaces buy sell）
    buy_rsi_low = IntParameter(25, 45, default=40, space="buy")
    sell_rsi_high = IntParameter(65, 85, default=75, space="sell")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma_fast"] = dataframe["close"].rolling(10).mean()
        dataframe["sma_slow"] = dataframe["close"].rolling(30).mean()
        dataframe["ema_fast"] = dataframe["close"].ewm(span=10, adjust=False).mean()
        dataframe["ema_slow"] = dataframe["close"].ewm(span=30, adjust=False).mean()

        delta = dataframe["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        dataframe["rsi"] = 100 - (100 / (1 + rs))

        macd = dataframe["close"].ewm(span=12, adjust=False).mean() - dataframe[
            "close"
        ].ewm(span=26, adjust=False).mean()
        dataframe["macd"] = macd
        dataframe["macdsignal"] = macd.ewm(span=9, adjust=False).mean()
        dataframe["macdhist"] = macd - dataframe["macdsignal"]

        mid = dataframe["close"].rolling(20).mean()
        std = dataframe["close"].rolling(20).std()
        dataframe["bb_lowerband"] = mid - 2 * std
        dataframe["bb_middleband"] = mid
        dataframe["bb_upperband"] = mid + 2 * std
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Uptrend pullback long: fast MA above slow MA while RSI dips.
        dataframe.loc[
            (
                (dataframe["sma_fast"] > dataframe["sma_slow"])
                & (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["rsi"] < self.buy_rsi_low.value)
            ),
            ["enter_long", "enter_tag"],
        ] = (1, "ma_cross_rsi_dip")

        # Downtrend bounce short (futures only; ignored on spot).
        dataframe.loc[
            (
                (dataframe["sma_fast"] < dataframe["sma_slow"])
                & (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["rsi"] > self.sell_rsi_high.value)
            ),
            ["enter_short", "enter_tag"],
        ] = (1, "ma_cross_rsi_top")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["rsi"] > self.sell_rsi_high.value)
            | (dataframe["close"] >= dataframe["bb_upperband"]),
            ["exit_long", "exit_tag"],
        ] = (1, "rsi_overbought")

        dataframe.loc[
            (dataframe["rsi"] < self.buy_rsi_low.value)
            | (dataframe["close"] < dataframe["bb_lowerband"]),
            ["exit_short", "exit_tag"],
        ] = (1, "rsi_oversold")
        return dataframe

    @property
    def plot_config(self) -> dict:
        return {
            "main_plot": {
                "sma_fast": {"color": "#4f8cff"},
                "sma_slow": {"color": "#ffb74d"},
                "ema_fast": {"color": "#26a69a"},
                "bb_upperband": {"color": "rgba(255,255,255,0.3)"},
                "bb_lowerband": {"color": "rgba(255,255,255,0.3)"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "#7e57c2"}},
                "MACD": {
                    "macd": {"color": "#4f8cff"},
                    "macdsignal": {"color": "#ffb74d"},
                    "macdhist": {"type": "bar"},
                },
            },
        }
