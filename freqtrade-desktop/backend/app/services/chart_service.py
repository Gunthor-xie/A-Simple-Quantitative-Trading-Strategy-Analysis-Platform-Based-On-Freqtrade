from __future__ import annotations

import gzip
import json
import math
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas import (
    BacktestResult,
    BotConnection,
    ChartCandle,
    ChartData,
    ChartCoverage,
    ChartMarker,
    SignalEvent,
    TradeOverlay,
    TradePoint,
)
from ..storage import Database
from .bot_client import BotClient


def _epoch_seconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        ts = float(value)
        return int(ts / 1000 if ts > 10_000_000_000 else ts)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def _trade_id(trade: dict[str, Any], fallback: int) -> int:
    """Freqtrade only ships ``trade_id`` for live trades; fall back to the 1-based order."""
    raw = trade.get("trade_id")
    if raw is None:
        raw = trade.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


class ChartService:
    def __init__(self, user_data: Path, storage: Database) -> None:
        self.user_data = Path(user_data)
        self.storage = storage

    # ---- data loading ----

    def load_candles(
        self,
        exchange: str,
        pair: str,
        timeframe: str,
        trading_mode: str = "spot",
        limit: int = 750,
        offset: int = 0,
        timerange: tuple[int, int] | None = None,
        meta: dict | None = None,
        full_range: bool = False,
        hard_cap: int = 200_000,
    ) -> list[ChartCandle]:
        path = self._find_candle_file(exchange, pair, timeframe, trading_mode)
        if path is None:
            hints = self._available_hints(exchange, pair, trading_mode)
            hint_text = f"；该交易对现有文件：{', '.join(hints)}" if hints else ""
            raise FileNotFoundError(
                f"未找到 {exchange} {pair} {timeframe} 的本地数据"
                f"（请先在「设置 → 下载历史数据」中下载，格式为 jsongz）{hint_text}"
            )
        rows = self._read_ohlcv(path)
        if timerange:
            start, end = timerange
            rows = [
                r for r in rows
                if (start is None or r[0] >= start) and (end is None or r[0] <= end)
            ]
        rows.sort(key=lambda r: r[0])
        deduped: list[list[float]] = []
        last_ts: float | None = None
        for row in rows:
            ts = row[0]
            if last_ts is not None and ts <= last_ts:
                continue
            deduped.append(row)
            last_ts = ts
        rows = deduped
        total = len(rows)
        if meta is not None and total:
            tf_seconds = {
                "1m": 60, "3m": 180, "5m": 300, "15m": 900,
                "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
            }.get(timeframe)
            expected = 1
            if tf_seconds:
                expected = math.floor((rows[-1][0] - rows[0][0]) / (tf_seconds * 1000)) + 1
            meta.update(
                count=total,
                start=int(rows[0][0]),
                end=int(rows[-1][0]),
                expected=expected,
            )
        if full_range:
            # Backtest charts must cover the whole timerange; paginating by a
            # fixed limit silently dropped the tail of long backtests.
            window = rows[:hard_cap]
        else:
            window = rows[offset : offset + limit]
        candles = [
            ChartCandle(time=_epoch_seconds(r[0]), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in window
            if len(r) >= 6
        ]
        if not candles:
            raise FileNotFoundError(f"{path} 中没有可用的 K 线数据")
        return candles

    def _find_candle_file(
        self, exchange: str, pair: str, timeframe: str, trading_mode: str
    ) -> Path | None:
        """Locate local OHLCV files for both flat (2025.x) and nested layouts."""
        root = Path(self.user_data) / "data"
        safe = pair.replace("/", "_").replace(":", "_")
        safe_names = [safe]
        # Futures symbols on OKX are written BASE/QUOTE:SETTLE (e.g. ETH/USDT:USDT).
        # Accept a query without the settle suffix by trying the USDT-perp name.
        if trading_mode == "futures" and ":" not in pair:
            base_quote = pair.replace("/", "_")
            safe_names.append(f"{base_quote}_USDT")
            safe_names.append(f"{base_quote}:USDT".replace(":", "_"))
        candidates: list[Path] = []
        search_dirs = [root / exchange, root / exchange / "futures"]
        for mode_dir in search_dirs:
            if not mode_dir.exists():
                continue
            for safe in safe_names:
                nested = mode_dir / safe
                if nested.exists():
                    candidates += sorted(nested.glob(f"{timeframe}.*"))
                candidates += sorted(mode_dir.glob(f"{safe}-{timeframe}*"))
        if trading_mode == "spot":
            candidates = [c for c in candidates if "-futures" not in c.name and "futures" not in c.parts] or candidates
        else:
            futures_named = [c for c in candidates if "-futures" in c.name or "futures" in c.parts]
            if futures_named:
                candidates = futures_named
        seen: set[str] = set()
        unique: list[Path] = []
        for cand in candidates:
            if cand.is_file() and cand.name not in seen:
                seen.add(cand.name)
                unique.append(cand)
        return unique[0] if unique else None

    def _available_hints(self, exchange: str, pair: str, trading_mode: str,
                         limit: int = 6) -> list[str]:
        """List existing files for a pair so the UI error is actionable."""
        root = Path(self.user_data) / "data" / exchange
        dirs = [root / "futures", root]
        base_spot = pair.split(":")[0].replace("/", "_")
        base_fut = pair.replace("/", "_").replace(":", "_")
        if trading_mode != "futures":
            base_fut = f"{base_spot}_USDT"
        names: list[str] = []
        for directory in dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.json.gz")):
                if path.name.startswith(base_spot) or path.name.startswith(base_fut):
                    names.append(path.name)
        return names[:limit]

    def _read_ohlcv(self, path: Path) -> list[list[float]]:
        suffix = path.suffix.lower()
        if suffix == ".gz" or path.name.endswith(".json.gz"):
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
            return self._normalize_ohlcv(payload)
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return self._normalize_ohlcv(payload)
        if suffix in (".feather", ".parquet"):
            try:
                import pandas as pd

                frame = pd.read_feather(path) if suffix == ".feather" else pd.read_parquet(path)
                out: list[list[float]] = []
                for _, row in frame.iterrows():
                    out.append(
                        [
                            float(row.get("date") or row.get("timestamp")),
                            float(row["open"]),
                            float(row["high"]),
                            float(row["low"]),
                            float(row["close"]),
                            float(row.get("volume", 0.0)),
                        ]
                    )
                return out
            except Exception as exc:
                raise FileNotFoundError(f"无法读取 {path}：{exc}（可能需要 pyarrow/pandas）") from exc
        raise FileNotFoundError(f"不支持的数据格式：{suffix}")

    @staticmethod
    def _normalize_ohlcv(payload: Any) -> list[list[float]]:
        if isinstance(payload, dict):
            data = payload.get("data") or payload.get("ohlcv") or []
        else:
            data = payload
        rows: list[list[float]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(
                    [
                        float(item.get("date") or item.get("timestamp") or 0),
                        float(item.get("open", 0)),
                        float(item.get("high", 0)),
                        float(item.get("low", 0)),
                        float(item.get("close", 0)),
                        float(item.get("volume", 0)),
                    ]
                )
            elif isinstance(item, (list, tuple)) and len(item) >= 6:
                rows.append([float(v) for v in item[:6]])
        return rows

    # ---- indicators ----

    def compute_indicators(
        self, candles: list[ChartCandle], names: list[str]
    ) -> dict[str, list[float | None]]:
        try:
            import pandas as pd
        except ImportError:
            raise FileNotFoundError("计算指标需要 pandas，请安装后端依赖")
        frame = pd.DataFrame(
            {
                "close": [c.close for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "volume": [c.volume for c in candles],
            }
        )
        out: dict[str, list[float | None]] = {}
        for name in names:
            key = name.strip().lower()
            if key in ("sma", "sma20", "ma", "ma20"):
                out[key] = self._series(frame["close"].rolling(20).mean())
            elif key in ("ema", "ema20"):
                out[key] = self._series(frame["close"].ewm(span=20, adjust=False).mean())
            elif key in ("ema144",):
                out[key] = self._series(frame["close"].ewm(span=144, adjust=False).mean())
            elif key in ("ema169",):
                out[key] = self._series(frame["close"].ewm(span=169, adjust=False).mean())
            elif key in ("vwap", "vwap24", "vwap_24h", "vwap_24"):
                out["vwap24"] = self._vwap24(candles)
            elif key in ("rsi", "rsi14"):
                out[key] = self._series(self._rsi(frame["close"], 14))
            elif key in ("macd",):
                macd = frame["close"].ewm(span=12, adjust=False).mean() - frame["close"].ewm(
                    span=26, adjust=False
                ).mean()
                signal = macd.ewm(span=9, adjust=False).mean()
                out["macd"] = self._series(macd)
                out["macdsignal"] = self._series(signal)
                out["macdhist"] = self._series(macd - signal)
            elif key in ("boll", "bollinger"):
                mid = frame["close"].rolling(20).mean()
                std = frame["close"].rolling(20).std()
                out["boll_upper"] = self._series(mid + 2 * std)
                out["boll_mid"] = self._series(mid)
                out["boll_lower"] = self._series(mid - 2 * std)
        return out

    @staticmethod
    def _series(series: Any) -> list[float | None]:
        return [None if pd.isna(v) else float(v) for v in series]

    @staticmethod
    def _rsi(close: Any, period: int = 14) -> Any:
        import pandas as pd

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        return rsi.where(avg_loss.notna(), pd.NA)

    @staticmethod
    def _vwap24(candles: list[ChartCandle], window: str = "24h") -> list[float | None]:
        """Rolling VWAP over `window` (24h by default), volume weighted on typical price.

        The window is time based, so 5m/15m/1h/4h candles all end up with a 24h VWAP.
        """
        import pandas as pd

        out: list[float | None] = [None] * len(candles)
        if not candles:
            return out
        index = pd.to_datetime([int(c.time) for c in candles], unit="s", utc=True)
        typical = pd.Series(
            [(float(c.high) + float(c.low) + float(c.close)) / 3.0 for c in candles],
            index=index,
            dtype="float64",
        )
        volume = pd.Series(
            [float(c.volume or 0.0) for c in candles], index=index, dtype="float64"
        )
        frame = pd.DataFrame(
            {"pv": (typical * volume).to_numpy(), "vol": volume.to_numpy()}, index=index
        )
        # duplicates/unsorted rows would make a time based rolling window raise
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        total_pv = frame["pv"].rolling(window, min_periods=1).sum()
        total_vol = frame["vol"].rolling(window, min_periods=1).sum()
        vwap = total_pv / total_vol.replace(0, pd.NA)
        # map back by timestamp so duplicate rows cannot shift the series
        by_time = {int(ts.timestamp()): value for ts, value in vwap.items()}
        for position, candle in enumerate(candles):
            value = by_time.get(int(candle.time))
            out[position] = None if value is None or pd.isna(value) else float(value)
        return out

    # ---- markers & signals ----

    def markers_from_trades(
        self, result: BacktestResult, pair: str
    ) -> list[ChartMarker]:
        markers: list[ChartMarker] = []
        for position, trade in enumerate(result.trades, start=1):
            if trade.get("pair") != pair:
                continue
            is_short = bool(trade.get("is_short"))
            try:
                profit = float(trade.get("profit_ratio") or 0.0)
            except (TypeError, ValueError):
                profit = 0.0
            # green = winning trade, red = losing trade
            color = "#26a69a" if profit >= 0 else "#ef5350"
            label = f"#{_trade_id(trade, position)}"
            if trade.get("open_date"):
                markers.append(
                    ChartMarker(
                        time=_epoch_seconds(trade.get("open_date")),
                        position="aboveBar" if is_short else "belowBar",
                        color=color,
                        shape="arrowDown" if is_short else "arrowUp",
                        text=label,
                    )
                )
            if trade.get("close_date"):
                markers.append(
                    ChartMarker(
                        time=_epoch_seconds(trade.get("close_date")),
                        position="belowBar" if is_short else "aboveBar",
                        color=color,
                        shape="circle",
                        text=f"{label} {profit * 100:+.2f}%",
                    )
                )
        return markers

    def overlays_from_trades(
        self, result: BacktestResult, pair: str
    ) -> list[TradeOverlay]:
        overlays: list[TradeOverlay] = []
        for index, trade in enumerate(result.trades, start=1):
            if trade.get("pair") != pair:
                continue
            is_short = bool(trade.get("is_short"))
            pnl = trade.get("profit_abs")
            if pnl is None:
                pnl = trade.get("profit")
            entry = TradePoint(
                time=_epoch_seconds(trade.get("open_date")),
                price=float(trade.get("open_rate") or 0.0),
                side="short" if is_short else "long",
                kind="entry",
                reason=str(trade.get("enter_reason", "")),
            )
            exit_point: TradePoint | None = None
            if trade.get("close_date"):
                exit_point = TradePoint(
                    time=_epoch_seconds(trade.get("close_date")),
                    price=float(trade.get("close_rate") or 0.0),
                    side="short" if is_short else "long",
                    kind="exit",
                    pnl=float(pnl) if pnl is not None else None,
                    reason=str(trade.get("exit_reason", "")),
                )
            try:
                pnl_f = float(pnl) if pnl is not None else None
            except (TypeError, ValueError):
                pnl_f = None
            overlays.append(
                TradeOverlay(
                    trade_id=_trade_id(trade, index),
                    entry=entry,
                    exit=exit_point,
                    pnl=pnl_f,
                    # The entry/exit connector encodes trade direction, not PnL:
                    # short = red, long = green. PnL colouring stays on the
                    # markers/number labels.
                    color="#ef5350" if is_short else "#26a69a",
                )
            )
        return overlays[-500:]

    def signals_from_trades(self, result: BacktestResult, strategy: str = "") -> list[SignalEvent]:
        events: list[SignalEvent] = []
        strategy = strategy or result.strategy
        for trade in result.trades:
            pair = str(trade.get("pair", ""))
            events.append(
                SignalEvent(
                    strategy=strategy,
                    time=str(trade.get("open_date", "")),
                    pair=pair,
                    side="short" if trade.get("is_short") else "long",
                    reason=str(trade.get("enter_reason", "entry")),
                    price=trade.get("open_rate"),
                )
            )
            if trade.get("close_date"):
                events.append(
                    SignalEvent(
                        strategy=strategy,
                        time=str(trade.get("close_date", "")),
                        pair=pair,
                        side="exit",
                        reason=str(trade.get("exit_reason", "exit")),
                        price=trade.get("close_rate"),
                    )
                )
        return events

    # ---- chart builders ----

    def backtest_chart(
        self,
        result: BacktestResult,
        exchange: str,
        pair: str,
        timeframe: str,
        trading_mode: str,
        indicators: list[str],
        limit: int = 750,
        offset: int = 0,
        timerange: tuple[int, int] | None = None,
    ) -> ChartData:
        meta: dict = {}
        candles = self.load_candles(
            exchange, pair, timeframe, trading_mode=trading_mode, limit=limit,
            offset=offset, timerange=timerange, meta=meta, full_range=True,
        )
        indicator_map = self.compute_indicators(candles, indicators)
        coverage = None
        if meta.get("count"):
            fill = min(1.0, meta["count"] / max(meta.get("expected", 1), 1))
            coverage = ChartCoverage(
                start=meta["start"], end=meta["end"], count=meta["count"],
                expected=meta.get("expected", meta["count"]),
                fill_ratio=round(fill, 4), has_gap=fill < 0.995,
            )
        return ChartData(
            candles=candles,
            indicators=indicator_map,
            markers=self.markers_from_trades(result, pair),
            signals=self.signals_from_trades(result),
            total=len(candles),
            coverage=coverage,
            overlays=self.overlays_from_trades(result, pair),
        )

    def live_chart(
        self,
        client: BotClient,
        strategy: str,
        pair: str,
        timeframe: str,
        indicators: list[str],
        limit: int = 750,
    ) -> ChartData:
        rows = client.pair_history(pair, timeframe, strategy)
        candles: list[ChartCandle] = []
        for row in rows[-limit:]:
            candles.append(
                ChartCandle(
                    time=_epoch_seconds(row.get("date") or row.get("timestamp")),
                    open=float(row.get("open", 0)),
                    high=float(row.get("high", 0)),
                    low=float(row.get("low", 0)),
                    close=float(row.get("close", 0)),
                    volume=float(row.get("volume", 0)),
                )
            )
        indicator_map = self.compute_indicators(candles, indicators)
        from .signal_engine import SignalEngine

        engine = SignalEngine(self.storage)
        signals = engine.from_analyzed_rows(strategy, pair, rows[-limit:])
        markers = []
        for signal in signals:
            markers.append(
                ChartMarker(
                    time=_epoch_seconds(signal.time),
                    position="belowBar" if signal.side != "exit" else "aboveBar",
                    color="#2962ff" if signal.side == "long" else ("#ef5350" if signal.side == "short" else "#26a69a"),
                    shape="arrowUp" if signal.side != "exit" else "arrowDown",
                    text=signal.reason[:24],
                )
            )
        return ChartData(
            candles=candles,
            indicators=indicator_map,
            markers=markers,
            signals=signals,
            total=len(candles),
        )
