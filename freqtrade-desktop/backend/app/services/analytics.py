"""Per-trade analytics engine for backtest results.

Reads a freqtrade backtest archive plus local 15m/1h/4h OHLCV (jsongz) and
produces the per-trade feature rows described in 回测指标需求.txt.

口径说明
- 快照类字段取交易时刻已收 K 线（时间戳 <= 交易时间）。
- 斜率 = (均线当前值 - 前 N 值) / (N * ATR)，N=20。
- 路径类字段按 15m 逐根重放近似（入场K线至出场K线闭市）。
- 无离线数据源的字段输出 NA，并在备注列说明。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _ts_sec(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(float(value) / 1000 if float(value) > 10_000_000_000 else float(value))
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            return 0
    return 0


def _load_frame(user_data: Path, exchange: str, pair: str, timeframe: str,
                trading_mode: str = "spot") -> pd.DataFrame:
    pair_key = pair.split(":")[0].replace("/", "_")
    if trading_mode == "futures":
        base = Path(user_data) / "data" / exchange / "futures"
        file = base / f"{pair.replace(':', '_')}-{timeframe}-futures.json.gz"
    else:
        base = Path(user_data) / "data" / exchange
        file = base / f"{pair_key}-{timeframe}.json.gz"
    if not file.exists():
        return pd.DataFrame()
    import gzip
    import json

    with gzip.open(file, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    frame = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume"]
    )
    frame["date"] = frame["date"].astype("int64")
    return frame


class TimeframeFrame:
    """Cached indicator-enriched dataframe for one timeframe."""

    def __init__(self, df: pd.DataFrame, label: str) -> None:
        self.label = label
        if df is None:
            df = pd.DataFrame()
        self.raw = df
        # Missing local file for this timeframe -> keep an empty frame so all
        # dependent fields become NA instead of raising KeyError('close').
        self.df = self._enrich(df, label) if not df.empty else pd.DataFrame()

    @staticmethod
    def _atr(close: pd.Series, high: pd.Series, low: pd.Series, n: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return tr.ewm(alpha=1 / n, adjust=False).mean()

    @classmethod
    def _enrich(cls, df: pd.DataFrame, label: str) -> pd.DataFrame:
        out = df.copy()
        close, high, low, vol = out["close"], out["high"], out["low"], out["volume"]
        atr = cls._atr(close, high, low)
        out["atr14"] = atr
        out["atr14_pct"] = atr / close
        for n in (5, 20, 50, 200):
            if len(close) >= n:
                out[f"sma{n}"] = close.rolling(n).mean()
        out["rsi"] = cls._rsi(close)
        macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = macd.ewm(span=9, adjust=False).mean()
        out["macd"] = macd
        out["macdsignal"] = signal
        out["macdhist"] = macd - signal
        mid = close.rolling(20).mean()
        std = close.rolling(20).std()
        out["bb_mid"] = mid
        out["bb_up"] = mid + 2 * std
        out["bb_low"] = mid - 2 * std
        out["bb_pos"] = (close - out["bb_low"]) / (out["bb_up"] - out["bb_low"]).replace(0, float("nan"))
        out["bb_width"] = (out["bb_up"] - out["bb_low"]) / close
        out["vol_ratio"] = vol / vol.rolling(20).mean().shift(1).replace(0, float("nan"))
        logret = pd.Series(close).apply(math.log).diff()
        bars_year = {"15m": 35040, "1h": 8760, "4h": 2190}.get(label, 8760)
        out["hv20"] = logret.rolling(20).std() * math.sqrt(bars_year)
        typical = (high + low + close) / 3
        cum_vp = (typical * vol).rolling(24).sum()
        cum_v = vol.rolling(24).sum()
        out["vwap_dist_pct"] = (close - cum_vp / cum_v.replace(0, pd.NA)) / close
        low20 = low.rolling(20).min()
        high20 = high.rolling(20).max()
        rng = (high20 - low20).replace(0, float("nan"))
        out["pct20"] = ((close - low20) / rng * 100)
        obv = (vol * ((close > close.shift(1)).astype(int) - (close < close.shift(1)).astype(int))).cumsum()
        out["obv_slope"] = (obv - obv.shift(20)) / (atr * vol.rolling(20).mean()).replace(0, float("nan"))
        adx, di_plus, di_minus = cls._adx(high, low, close)
        out["adx"] = adx
        out["di_plus"] = di_plus
        out["di_minus"] = di_minus
        out["di_diff"] = di_plus - di_minus
        return out

    @staticmethod
    def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.ewm(alpha=1 / n, adjust=False).mean()
        al = loss.ewm(alpha=1 / n, adjust=False).mean()
        rs = ag / al.replace(0, float("nan"))
        return 100 - 100 / (1 + rs)

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(0.0, index=high.index)
        minus_dm = pd.Series(0.0, index=high.index)
        plus_dm[(up > down) & (up > 0)] = up
        minus_dm[(down > up) & (down > 0)] = down
        tr = TimeframeFrame._atr(close, high, low, n)
        plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, float("nan"))
        minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, float("nan"))
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
        adx = dx.ewm(alpha=1 / n, adjust=False).mean()
        return adx, plus_di, minus_di

    def index_at(self, ts_sec: int) -> int:
        if self.raw is None or self.raw.empty:
            return 0
        arr = self.raw["date"].to_numpy()
        pos = int(arr.searchsorted(ts_sec * 1000, side="right")) - 1
        return max(pos, 0)

    def row(self, idx: int) -> dict:
        return self.df.iloc[idx].to_dict()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def _slope(frame: TimeframeFrame, row: dict, ma_col: str) -> float | None:
    idx = frame.df.index.get_loc(row["_idx"]) if False else None
    try:
        value = row.get(ma_col)
        atr = row.get("atr14")
        if value is None or atr is None or not atr:
            return None
        pos = int(row.get("_pos", 0))
        df = frame.df
        if pos < 20:
            return None
        past = df[ma_col].iloc[pos - 20] if ma_col in df else None
        if past is None or pd.isna(past):
            return None
        return round((value - past) / (20 * atr), 6)
    except Exception:
        return None


NA_NOTES = {
    "spread_entry_pct": "无历史点差源",
    "spread_exit_pct": "无历史点差源",
    "news_high_impact_flag": "无事件数据源",
    "slippage_total": "回测未建模滑点",
    "trailing_stop_hit_count": "无逐笔路径日志",
    "breakeven_stop_hit_count": "无逐笔路径日志",
    "adverse_signal_count_1h": "近似值（反向排列计数）",
    "adverse_signal_count_15m": "近似值（反向排列计数）",
}


def analyze_trades(
    trades: list[dict],
    user_data: Path,
    exchange: str = "okx",
    trading_mode: str = "spot",
    timeframe: str = "15m",
    strategy_stoploss: float = -0.05,
) -> tuple[list[dict], dict[str, str]]:
    """Returns (rows, column_notes)."""
    pair = trades[0].get("pair") if trades else ""
    funding: list[tuple[int, float]] = []
    if trading_mode == "futures":
        funding = _load_funding(user_data, exchange, pair)
    tfs = {
        tf: TimeframeFrame(
            _load_frame(user_data, exchange, pair, tf, trading_mode), tf
        )
        for tf in ("15m", "1h", "4h")
    }
    notes: dict[str, str] = {}
    rows: list[dict] = []
    for trade in trades:
        rows.append(_analyze_one(trade, tfs, trading_mode, timeframe, strategy_stoploss, notes, funding))
    _postprocess(rows)
    return rows, notes


def _load_funding(user_data: Path, exchange: str, pair: str) -> list[tuple[int, float]]:
    base = Path(user_data) / "data" / exchange / "futures"
    file = base / f"{pair.replace(':', '_')}-8h-funding_rate.json.gz"
    if not file.exists():
        return []
    import gzip
    import json

    with gzip.open(file, "rt", encoding="utf-8") as fh:
        raw = json.load(fh)
    out: list[tuple[int, float]] = []
    for r in raw:
        try:
            out.append((int(r[0]), float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue
    return out


def _postprocess(rows: list[dict]) -> None:
    def series(key: str) -> list[float | None]:
        out: list[float | None] = []
        for r in rows:
            try:
                v = float(r.get(key))
                out.append(v if v == v else None)
            except (TypeError, ValueError):
                out.append(None)
        return out

    vals_net = [v for v in series("net_pnl") if v is not None]
    vals_r = [v for v in series("r_multiple") if v is not None]
    for r in rows:
        net = _num(r.get("net_pnl"))
        if net is not None and len(vals_net) > 1:
            mean = sum(vals_net) / len(vals_net)
            var = sum((v - mean) ** 2 for v in vals_net) / (len(vals_net) - 1)
            std = var ** 0.5
            z = (net - mean) / std if std else None
            r["sample_zscore_net_pnl"] = round(z, 4) if z is not None else None
            r["sample_percentile_net_pnl"] = round(
                sum(1 for v in vals_net if v <= net) / len(vals_net) * 100, 2
            )
        else:
            r["sample_zscore_net_pnl"] = None
            r["sample_percentile_net_pnl"] = None
        rval = _num(r.get("r_multiple"))
        if rval is not None and len(vals_r) > 1:
            r["sample_percentile_r"] = round(
                sum(1 for v in vals_r if v <= rval) / len(vals_r) * 100, 2
            )
        else:
            r["sample_percentile_r"] = None
        z_net = r.get("sample_zscore_net_pnl")
        r["outlier_flag"] = 1 if z_net is not None and abs(z_net) >= 2.0 else 0
    funding_vals = [v for v in series("annualized_funding_rate") if v is not None]
    if len(funding_vals) > 1:
        f_mean = sum(funding_vals) / len(funding_vals)
        f_std = (sum((v - f_mean) ** 2 for v in funding_vals) / (len(funding_vals) - 1)) ** 0.5
        for r in rows:
            value = _num(r.get("annualized_funding_rate"))
            r["funding_rate_z"] = round((value - f_mean) / f_std, 4) if f_std and value is not None else None


def _analyze_one(
    trade: dict, tfs: dict[str, TimeframeFrame], trading_mode: str,
    timeframe: str, strategy_stoploss: float, notes: dict[str, str],
    funding: list[tuple[int, float]],
) -> dict:
    row: dict[str, Any] = {}
    entry_ts = _ts_sec(trade.get("open_timestamp") or trade.get("open_date"))
    exit_ts = _ts_sec(trade.get("close_timestamp") or trade.get("close_date"))
    entry_price = _num(trade.get("open_rate"))
    exit_price = _num(trade.get("close_rate"))
    qty = _num(trade.get("amount"))
    stake = _num(trade.get("stake_amount"))
    pnl = _num(trade.get("profit_abs"))
    # 手续费按“名义金额”（数量 × 价格）收取，而不是按保证金 stake 收取。
    # 合约带杠杆时两者相差 leverage 倍，按 stake 计算会严重低估手续费并抬高毛盈亏。
    fee_open = _num(trade.get("fee_open")) * qty * entry_price
    fee_close = _num(trade.get("fee_close")) * qty * exit_price
    fees_total = fee_open + fee_close
    gross = pnl + fees_total
    side = "short" if trade.get("is_short") else "long"
    duration_min = _num(trade.get("trade_duration"), 0.0)
    stop_abs = trade.get("initial_stop_loss_abs")
    stop_ratio = trade.get("initial_stop_loss_ratio")
    risk_per_unit = abs(entry_price - _num(stop_abs)) if stop_abs else abs(entry_price * _num(stop_ratio, strategy_stoploss))
    risk_amount = risk_per_unit * qty if risk_per_unit else 0.0
    mfe_pct = max(0.0, (_num(trade.get("max_rate")) - entry_price) / entry_price) if side == "long" else max(0.0, (entry_price - _num(trade.get("min_rate"))) / entry_price)
    mae_pct = max(0.0, (entry_price - _num(trade.get("min_rate"))) / entry_price) if side == "long" else max(0.0, (_num(trade.get("max_rate")) - entry_price) / entry_price)
    max_runup = _num(trade.get("max_rate")) / entry_price - 1 if side == "long" else 1 - _num(trade.get("max_rate")) / entry_price
    max_dd = 1 - _num(trade.get("min_rate")) / entry_price if side == "long" else _num(trade.get("min_rate")) / entry_price - 1
    return_pct = pnl / stake if stake else 0.0

    # --- 一、基础信息 ---
    row.update({
        "trade_id": trade.get("trade_id") if trade.get("trade_id") is not None else 0,
        "side": side,
        "exit_reason": str(trade.get("exit_reason", "")),
        "entry_time": str(trade.get("open_date", "")),
        "exit_time": str(trade.get("close_date", "")),
        "holding_minutes": duration_min,
        "holding_1h_bars": round(duration_min / 60, 2),
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "quantity": round(qty, 8),
        "notional_value": round(stake, 2),
        "fee": round(fees_total, 6),
        "slippage_total": pd.NA,
        "entry_trigger_type": str(trade.get("enter_tag", "")),
        "exit_trigger_type": str(trade.get("exit_reason", "")),
        "is_overnight": 1 if entry_ts and exit_ts and (
            datetime.fromtimestamp(exit_ts, tz=timezone.utc).date() >
            datetime.fromtimestamp(entry_ts, tz=timezone.utc).date()) else 0,
        "is_weekend": 1 if entry_ts and datetime.fromtimestamp(entry_ts, tz=timezone.utc).weekday() >= 5 else 0,
    })
    # --- 二、盈亏绩效 ---
    row.update({
        "gross_pnl": round(gross, 6),
        "net_pnl": round(pnl, 6),
        "return_pct": round(return_pct, 8),
        "log_return": round(math.log(1 + return_pct), 8) if return_pct > -1 else pd.NA,
        "r_multiple": round(pnl / risk_amount, 4) if risk_amount else pd.NA,
        "initial_risk_amount": round(risk_amount, 6),
        "initial_risk_pct": round(risk_amount / max(stake, 1e-9), 6),
        "initial_stop_distance_pct": abs(_num(stop_ratio, strategy_stoploss)),
        "mfe_price": round(_num(trade.get("max_rate")), 6) if side == "long" else round(_num(trade.get("min_rate")), 6),
        "mfe_pct": round(mfe_pct, 6),
        "mae_price": round(_num(trade.get("min_rate")), 6) if side == "long" else round(_num(trade.get("max_rate")), 6),
        "mae_pct": round(mae_pct, 6),
        "mfe_mae_ratio": round(mfe_pct / mae_pct, 4) if mae_pct else pd.NA,
        "max_holding_dd_pct": round(max_dd, 6),
        "net_pnl_over_mfe": round(pnl / max(mfe_pct * stake, 1e-9), 6),
        "net_pnl_over_mae": round(pnl / max(mae_pct * stake, 1e-9), 6),
        "net_pnl_per_holding_bar": round(pnl / max(duration_min / 60, 1e-9), 6),
        "fee_pct_of_gross": round(fees_total / max(abs(gross), 1e-9), 6),
        "is_win": 1 if pnl > 0 else 0,
    })
    notes["mfe_atr"] = "使用入场时刻 1H ATR 归一"
    notes["mfe_r"] = "max_rate/min_rate 来自回测记录"
    notes["mae_atr"] = "使用入场时刻 1H ATR 归一"
    # --- 快照与结构字段 ---
    _fill_snapshots(row, tfs, entry_ts, exit_ts, entry_price, exit_price, side, notes)
    _fill_path(row, tfs, entry_ts, exit_ts, entry_price, side, risk_amount, return_pct, mfe_pct, mae_pct, duration_min, notes)
    _fill_tags(row, tfs, entry_ts, entry_price, exit_ts, exit_price, side, max_dd, max_runup, notes)
    if funding and entry_ts and exit_ts:
        holding = [rate for ts, rate in funding if entry_ts * 1000 <= ts <= exit_ts * 1000]
        row["annualized_funding_rate"] = round(sum(holding) / len(holding) * 3 * 365, 6) if holding else None
        row["holding_funding_records"] = len(holding)
        notes["annualized_funding_rate"] = "持仓期 8h 资金费率均值 × 3 × 365"
    _fill_composites(row)
    return row


def _fill_snapshots(row, tfs, entry_ts, exit_ts, entry_price, exit_price, side, notes) -> None:
    map_specs = {
        "1h": {
            "ma": (5, 20, 50, 200),
            "prefix": "entry_1h", "extra": ["rsi", "macd", "bb", "atr", "vol", "pct20"],
        },
        "4h": {"ma": (20, 50), "prefix": "entry_4h", "extra": ["rsi", "macd", "bb", "atr", "vol"]},
        "15m": {"ma": (5, 20, 50), "prefix": "entry_15m", "extra": ["rsi", "macd", "bb", "atr", "vol"]},
    }
    for tf, spec in map_specs.items():
        frame = tfs.get(tf)
        if frame is None or frame.df.empty or not entry_ts:
            continue
        idx = frame.index_at(entry_ts)
        r = frame.row(idx)
        prefix = spec["prefix"]
        close = r.get("close")
        atr = r.get("atr14") or 0
        row[f"{prefix}_ma_arrangement"] = _arrangement(r, spec["ma"])
        for n in spec["ma"]:
            col = f"sma{n}"
            row[f"{prefix}_ma{n}_slope"] = _slope_by_col(frame, idx, col)
            if col in ("sma20", "sma50"):
                if close and close:
                    row[f"{prefix}_price_dist_ma{n}"] = round((entry_price - (r.get(col) or entry_price)) / max(entry_price, 1e-9), 6)
        row[f"{prefix}_adx"] = _round2(r.get("adx"))
        row[f"{prefix}_di_plus"] = _round2(r.get("di_plus"))
        row[f"{prefix}_di_minus"] = _round2(r.get("di_minus"))
        row[f"{prefix}_di_diff"] = _round2(r.get("di_diff"))
        row[f"{prefix}_rsi14"] = _round2(r.get("rsi"))
        row[f"{prefix}_macd_hist"] = _round6(r.get("macdhist"))
        row[f"{prefix}_macd_signal_gap"] = _round6((r.get("macd") or 0) - (r.get("macdsignal") or 0))
        row[f"{prefix}_bb_position"] = _round4(r.get("bb_pos"))
        row[f"{prefix}_bb_width_pct"] = _round6(r.get("bb_width"))
        row[f"{prefix}_atr14"] = _round6(atr)
        row[f"{prefix}_atr14_pct"] = _round6(r.get("atr14_pct"))
        row[f"{prefix}_volume_ratio"] = _round4(r.get("vol_ratio"))
        row[f"{prefix}_hv20"] = _round6(r.get("hv20"))
        row[f"{prefix}_obv_slope"] = _round6(r.get("obv_slope"))
        row[f"{prefix}_vwap_dist_pct"] = _round6(r.get("vwap_dist_pct"))
        row[f"{prefix}_price_percentile_20"] = _round2(r.get("pct20"))
        row[f"{prefix}_bias_ma20"] = _round6((entry_price - (r.get("sma20") or entry_price)) / max(entry_price, 1e-9))
        row[f"{prefix}_trend_strength_score"] = _score(r, spec["ma"])
        if tf == "1h":
            row["entry_1h_rsi_state"] = _rsi_state(r.get("rsi"))
            row["entry_1h_macd_zero_cross"] = "above" if (r.get("macd") or 0) > 0 else "below"
            row["entry_1h_kline_pattern"] = _pattern(r)
            row["entry_1h_price_dist_ma200"] = _round6((entry_price - (r.get("sma200") or entry_price)) / max(entry_price, 1e-9))
            row["entry_support_dist_atr"] = _round4((entry_price - (r.get("_low20") or 0)) / atr) if atr else pd.NA
            row["entry_resistance_dist_atr"] = _round4(((r.get("_high20") or 0) - entry_price) / atr) if atr else pd.NA
            row["entry_high_20_1h"] = _round6(r.get("_high20"))
            row["entry_low_20_1h"] = _round6(r.get("_low20"))
            row["entry_position_in_20b_range"] = _round2(r.get("pct20"))
            row["entry_at_key_level"] = 1 if atr and abs(entry_price - round(entry_price)) < atr else 0
        if tf == "4h":
            row["entry_4h_breakout_dist_atr"] = _round4(((r.get("_high20") or entry_price) - entry_price) / atr) if atr else pd.NA
        if tf == "15m":
            row["entry_15m_trigger_type"] = _trigger(r)
            row["entry_15m_confirmation_bars"] = 0
    _snapshot_extra(row, tfs, entry_ts, entry_price, notes)
    # 出场快照：关键子集
    if exit_ts:
        for tf, prefix in (("1h", "exit_1h"), ("4h", "exit_4h"), ("15m", "exit_15m")):
            frame = tfs.get(tf)
            if frame is None or frame.df.empty:
                continue
            idx = frame.index_at(exit_ts)
            r = frame.row(idx)
            row[f"{prefix}_ma_arrangement"] = _arrangement(r, (5, 20, 50) if tf == "15m" else (5, 20, 50, 200) if tf == "1h" else (20, 50))
            row[f"{prefix}_rsi14"] = _round2(r.get("rsi"))
            row[f"{prefix}_macd_hist"] = _round6(r.get("macdhist"))
            row[f"{prefix}_atr14_pct"] = _round6(r.get("atr14_pct"))
            row[f"{prefix}_bb_position"] = _round4(r.get("bb_pos"))
            row[f"{prefix}_volume_ratio"] = _round4(r.get("vol_ratio"))
            row[f"{prefix}_price_dist_ma20"] = _round6((exit_price - (r.get("sma20") or exit_price)) / max(exit_price, 1e-9))
            row[f"{prefix}_ma20_slope"] = _slope_by_col(frame, idx, "sma20")


def _fill_path(row, tfs, entry_ts, exit_ts, entry_price, side, risk_amount,
               return_pct, mfe_pct, mae_pct, duration_min, notes) -> None:
    if not entry_ts or not exit_ts:
        return
    frame = tfs.get("15m")
    if frame is None or frame.df.empty:
        return
    df = frame.df
    a = frame.index_at(entry_ts)
    b = frame.index_at(exit_ts)
    if b <= a:
        return
    window = df.iloc[a : b + 1]
    direction = 1 if side == "long" else -1
    reached_p, reached_n = set(), set()
    levels_p = {0.5: None, 1: None, 2: None, 3: None}
    levels_n = {0.5: None, 1: None}
    unit_r = max(abs(float(row.get("initial_stop_distance_pct", 0.05))), 0.001) * entry_price
    for _, bar in window.iterrows():
        t = int(bar["date"]) // 1000
        high_r = (bar["high"] - entry_price) / entry_price if direction > 0 else (entry_price - bar["low"]) / entry_price
        low_r = (entry_price - bar["low"]) / entry_price if direction > 0 else (bar["high"] - entry_price) / entry_price
        for mult in levels_p:
            if levels_p[mult] is None and high_r >= mult * unit_r / entry_price:
                levels_p[mult] = (t - entry_ts) / 3600
                reached_p.add(mult)
        for mult in levels_n:
            if levels_n[mult] is None and low_r <= -mult * unit_r / entry_price:
                levels_n[mult] = (t - entry_ts) / 3600
                reached_n.add(mult)
    row["first_plus_0_5r_bars"] = _round2(levels_p.get(0.5))
    row["first_plus_1r_bars"] = _round2(levels_p.get(1))
    row["first_plus_2r_bars"] = _round2(levels_p.get(2))
    row["first_minus_0_5r_bars"] = _round2(levels_n.get(0.5))
    row["first_minus_1r_bars"] = _round2(levels_n.get(1))
    row["reached_plus_1r"] = 1 if 1 in reached_p else 0
    row["reached_plus_2r"] = 1 if 2 in reached_p else 0
    row["reached_plus_3r"] = 1 if 3 in reached_p else 0
    row["reached_minus_1r"] = 1 if 1 in reached_n else 0
    row["holding_1h_range_pct"] = round(float((window["high"].max() - window["low"].min()) / entry_price), 6)
    row["path_efficiency"] = round(return_pct / max(mfe_pct, 1e-9), 6)
    row["time_efficiency"] = round(return_pct / max(duration_min / 60 / 24, 1e-9), 6)
    frame_1h = tfs.get("1h")
    if frame_1h is not None and not frame_1h.df.empty:
        idx = frame_1h.index_at(entry_ts)
        atr1h = float(frame_1h.df["atr14"].iloc[idx] or 0.0)
        row["mfe_atr"] = round(mfe_pct * entry_price / atr1h, 4) if atr1h else pd.NA
        row["mae_atr"] = round(mae_pct * entry_price / atr1h, 4) if atr1h else pd.NA
        row["mfe_r"] = round(mfe_pct / max(abs(float(row.get("initial_stop_distance_pct", 0.05))), 1e-9), 4)
        row["mae_r"] = round(mae_pct / max(abs(float(row.get("initial_stop_distance_pct", 0.05))), 1e-9), 4)
        row["initial_stop_distance_atr"] = round(unit_r / atr1h, 4) if atr1h else pd.NA
        net_pnl = float(row.get("net_pnl") or 0.0)
        row["net_pnl_per_atr"] = round(net_pnl / max(atr1h * max(row.get("quantity") or 0.0, 1e-9), 1e-9), 4) if atr1h else pd.NA


def _fill_tags(row, tfs, entry_ts, entry_price, exit_ts, exit_price, side, max_dd, max_runup, notes) -> None:
    if entry_ts:
        hour = datetime.fromtimestamp(entry_ts, tz=timezone.utc).hour
        row["session_entry"] = "美洲" if hour >= 12 else ("欧洲" if hour >= 6 else "亚洲")
        row["day_of_week_entry"] = datetime.fromtimestamp(entry_ts, tz=timezone.utc).strftime("%A")
        row["month_entry"] = datetime.fromtimestamp(entry_ts, tz=timezone.utc).month
    if exit_ts:
        hour = datetime.fromtimestamp(exit_ts, tz=timezone.utc).hour
        row["session_exit"] = "美洲" if hour >= 12 else ("欧洲" if hour >= 6 else "亚洲")
    frame = tfs.get("1h")
    if frame is not None and not frame.df.empty and entry_ts:
        idx = frame.index_at(entry_ts)
        r = frame.row(idx)
        row["regime_1h"] = "趋势" if (r.get("adx") or 0) >= 20 else "震荡"
        atr = r.get("atr14") or 0
        atr_series = frame.df["atr14"].dropna()
        if len(atr_series):
            pct = float((atr_series <= atr).mean())
            row["volatility_regime"] = "高波" if pct > 0.8 else ("低波" if pct < 0.2 else "中波")
            row["daily_atr_percentile"] = round(pct, 4)
        row["liquidity_regime"] = "高流动性" if (r.get("vol_ratio") or 1) >= 1.2 else "低流动性"
    row["spread_entry_pct"] = pd.NA
    row["spread_exit_pct"] = pd.NA
    row["news_high_impact_flag"] = pd.NA
    row["max_runup_pct"] = round(max_runup, 6)
    row["max_drawdown_pct"] = round(max_dd, 6)
    realized = exit_price / entry_price - 1 if side == "long" else 1 - exit_price / entry_price
    row["giveback_pct"] = round((max_runup - realized) / max(max_runup, 1e-9), 6)
    net = float(row.get("net_pnl") or 0.0)
    notional = max(float(row.get("notional_value") or 0.0), 1e-9)
    row["recovery_from_mae_pct"] = round((net / notional + max(0.0, max_dd)) / max(max(0.0, max_dd), 1e-9), 6)


def _fill_composites(row: dict) -> None:
    def z_row(values: list[float]) -> list[float]:
        return values

    row["entry_score_composite"] = None
    row["exit_score_composite"] = None
    row["signal_quality_score"] = None
    row["multi_timeframe_score"] = None
    row["risk_adjusted_entry_score"] = None
    row["efficiency_score"] = None
    row["outlier_flag"] = 0
    row["sample_percentile_net_pnl"] = None
    row["sample_percentile_r"] = None


def _snapshot_extra(row, tfs, entry_ts, entry_price, notes) -> None:
    frame = tfs.get("1h")
    if frame is None or frame.df.empty:
        return
    df = frame.df
    idx = frame.index_at(entry_ts)
    r = frame.row(idx)
    for col in ("_high20", "_low20"):
        if col not in df:
            df[col] = df["high"].rolling(20).max() if col == "_high20" else df["low"].rolling(20).min()
    r = frame.row(idx)
    row["entry_high_20_1h"] = _round6(r.get("_high20"))
    row["entry_low_20_1h"] = _round6(r.get("_low20"))
    atr = r.get("atr14") or 0
    row["entry_support_dist_atr"] = _round4((entry_price - (r.get("_low20") or entry_price)) / atr) if atr else pd.NA
    row["entry_resistance_dist_atr"] = _round4(((r.get("_high20") or entry_price) - entry_price) / atr) if atr else pd.NA
    row["entry_breakout_retest"] = 0
    row["entry_inside_bar_parent_range"] = pd.NA
    row["entry_nearest_sr_type"] = "前高" if entry_price >= (r.get("_high20") or entry_price) * 0.995 else "前低"


def _arrangement(r: dict, mas: tuple) -> str:
    vals = [r.get(f"sma{n}") for n in mas]
    if any(v is None or pd.isna(v) for v in vals):
        return "NA"
    if all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
        return "多头"
    if all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
        return "空头"
    return "纠缠"


def _rsi_state(value) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return "超卖" if value < 30 else ("超买" if value > 70 else "中性")


def _pattern(r: dict) -> str:
    try:
        o, c, h, l = r.get("open"), r.get("close"), r.get("high"), r.get("low")
        if None in (o, c, h, l):
            return "无"
        body = abs(c - o)
        if body and l <= min(o, c) - 0.6 * (h - l) and c > o:
            return "Pin Bar"
        prev = r.get("_prev")
        if prev and prev.get("close") < prev.get("open") and c > o and c >= prev.get("open"):
            return "吞没"
        return "无"
    except Exception:
        return "无"


def _trigger(r: dict) -> str:
    try:
        if r.get("sma20") and r["close"] > r["close"] and (r.get("pct20") or 50) >= 80 and (r.get("di_diff") or 0) > 0:
            return "突破"
        if (r.get("rsi") or 50) < 35 and (r.get("pct20") or 50) < 40:
            return "回撤"
        return "二次确认" if (r.get("macdhist") or 0) < 0 and (r.get("di_diff") or 0) > 0 else "反转"
    except Exception:
        return "反转"


def _score(r: dict, mas: tuple) -> int:
    score = 0
    if (r.get("adx") or 0) >= 25:
        score += 1
    if _arrangement(r, mas) == "多头" and (r.get("di_diff") or 0) > 0:
        score += 1
    if _arrangement(r, mas) == "空头" and (r.get("di_diff") or 0) < 0:
        score -= 1
    return score


def _round2(v): return round(float(v), 2) if v is not None and not pd.isna(v) else None
def _round4(v): return round(float(v), 4) if v is not None and not pd.isna(v) else None
def _round6(v): return round(float(v), 6) if v is not None and not pd.isna(v) else None


def _slope_by_col(frame: TimeframeFrame, idx: int, col: str):
    df = frame.df
    if df is None or df.empty:
        return None
    try:
        if idx < 20 or col not in df:
            return None
        cur = df[col].iloc[idx]
        past = df[col].iloc[idx - 20]
        atr = df["atr14"].iloc[idx]
        if cur != cur or past != past or not atr:
            return None
        return round(float((cur - past) / (20 * atr)), 6)
    except Exception:
        return None
