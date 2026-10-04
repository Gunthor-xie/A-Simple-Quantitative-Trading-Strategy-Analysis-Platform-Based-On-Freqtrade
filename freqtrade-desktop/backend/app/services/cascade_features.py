"""Per-minute liquidation-cascade features, computed outside the Freqtrade engine.

Freqtrade has no data channel for forced liquidations, open interest, order-book
depth or tick trades, so a cascade-reversal strategy cannot read them from a
dataframe the engine builds. Instead we pre-compute one *point-in-time* feature
file per pair and let the strategy merge it back on the ``date`` column. The
backtest and the live/dry-run bot read the exact same file, so the signal logic
cannot drift between the two.

Everything here is causal by construction - a value on the bar with open time
``t`` only uses information available at the bar's close (``t + 1min``).
``tests/test_cascade_features.py`` enforces that with a prefix-recompute test.

Output: one row per 1m bar, every generated column prefixed ``cx_`` so it can
never collide with a Freqtrade column.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "cx_"
BAR_MS = 60_000

# Weights for the per-side "flush" score. Components that are missing (e.g.
# real liquidation flow before the collector has ever run) are dropped and the
# remaining weights are renormalised, so a proxy-only score stays comparable.
FLUSH_WEIGHTS = {
    "drop_z": 0.35,     # adverse price velocity
    "sell_z": 0.25,     # aggressive flow against the crowd
    "oi_z": 0.15,       # open interest contracting -> positions closed / killed
    "liq_z": 0.25,      # measured forced-liquidation notional
}

# Canonical column order of a feature file (prefix added on write).
FEATURE_COLUMNS = (
    "ret_1m", "ret_3m", "ret_5m", "ret_15m", "range_pct", "close_position_1m",
    "atr_14", "atr_pct", "prior_high_5m", "prior_low_5m", "prior_high_15m",
    "prior_low_15m", "drawdown_from_5m_high_pct", "rally_from_5m_low_pct",
    "no_new_low", "no_new_high",
    "taker_buy_usd", "taker_sell_usd", "taker_imbalance", "taker_imbalance_ema15",
    "taker_imbalance_delta", "cvd_1m", "cvd_60m", "trade_volume_usd",
    "trade_volume_z", "trade_count", "trade_vwap", "trade_vwap_gap_pct",
    "oi", "oi_notional", "oi_chg_5m_pct", "funding_rate", "funding_annualized",
    "taker_ls_ratio", "top_trader_ls_ratio",
    "bid_depth_usd_1pct", "ask_depth_usd_1pct", "depth_imbalance_1pct",
    "bid_depth_usd_2pct", "ask_depth_usd_2pct", "depth_imbalance_2pct",
    "bid_depth_usd_5pct", "ask_depth_usd_5pct", "depth_imbalance_5pct",
    "bid_depth_change_1m", "ask_depth_change_1m", "depth_imbalance_delta_1m",
    "depth_total_usd_1pct", "liquidity_percentile_24h",
    "liq_long_usd", "liq_short_usd", "liq_total_usd", "liq_count",
    "liq_imbalance", "liq_p95_1h", "liq_ratio_1h", "liq_z_1h",
    "flush_long_score", "flush_short_score", "has_liquidations",
)


class CascadeFeatureError(Exception):
    """Raised when inputs cannot be turned into a feature frame."""


def feature_file_name(pair: str, timeframe: str = "1m") -> str:
    """``BTC/USDT:USDT`` -> ``BTC_USDT_USDT-1m-cascade.csv.gz``."""
    slug = pair.replace("/", "_").replace(":", "_")
    return f"{slug}-{timeframe}-cascade.csv.gz"


def feature_path(user_data: str | Path, pair: str, timeframe: str = "1m") -> Path:
    return Path(user_data) / "liquidation" / feature_file_name(pair, timeframe)


def write_features(frame: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = frame.to_csv(index=False, float_format="%.10g")
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(payload)
    return path


def load_features(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise CascadeFeatureError(f"feature file not found: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        frame = pd.read_csv(fh)
    if "date" not in frame.columns:
        raise CascadeFeatureError(f"{path.name} is missing the 'date' column")
    return frame


# ---------------------------------------------------------------------- utils
def _to_ts_ms(values: pd.Series) -> pd.Series:
    """Accept epoch seconds, epoch ms, or datetime-ish values -> epoch ms."""
    if pd.api.types.is_numeric_dtype(values):
        numeric = pd.to_numeric(values, errors="coerce")
        return (numeric.where(numeric >= 1e11, numeric * 1000.0)).astype("int64")
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    return (parsed.astype("int64") // 1_000_000)


def _zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Causal z-score: the current value against the trailing window, excluding itself."""
    prior = series.shift(1)
    floor = min_periods or max(5, window // 4)
    mean = prior.rolling(window, min_periods=floor).mean()
    std = prior.rolling(window, min_periods=floor).std(ddof=0)
    return (series - mean) / std.replace(0.0, np.nan)


def _weighted_score(components: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    weight = pd.Series(weights, dtype="float64")
    present = components.notna()
    numerator = components.fillna(0.0).mul(weight, axis=1).sum(axis=1)
    denominator = present.mul(weight, axis=1).sum(axis=1)
    return numerator / denominator.replace(0.0, np.nan)


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(frame: pd.DataFrame, window: int = 14) -> pd.Series:
    return _true_range(frame).ewm(alpha=1 / window, min_periods=window, adjust=False).mean()


def _asof_merge(left: pd.DataFrame, right: pd.DataFrame, on: str) -> pd.DataFrame:
    """Point-in-time join: only rows of ``right`` at or before ``left[on]``."""
    right = right.sort_values(on).drop_duplicates(on, keep="last")
    return pd.merge_asof(
        left.sort_values(on), right, on=on, direction="backward", allow_exact_matches=True
    )


def _groupby_vwap(frame: pd.DataFrame) -> pd.Series:
    """Volume-weighted trade price per minute bucket."""
    weighted = frame["notional"].groupby(frame["minute"]).sum()
    priced = (frame["notional"] * frame["price"]).groupby(frame["minute"]).sum()
    return priced / weighted.replace(0.0, np.nan)


# ---------------------------------------------------------------- sub-builds
def _base_features(klines: pd.DataFrame) -> pd.DataFrame:
    frame = (
        klines.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    close = frame["close"]
    out = pd.DataFrame({"date": frame["date"].astype("int64"), "close": close})
    for minutes in (1, 3, 5, 15):
        out[f"ret_{minutes}m"] = close.pct_change(minutes)
    out["range_pct"] = (frame["high"] - frame["low"]) / close.replace(0.0, np.nan)
    span = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    out["close_position_1m"] = (close - frame["low"]) / span
    atr = _atr(frame, 14)
    out["atr_14"] = atr
    out["atr_pct"] = atr / close.replace(0.0, np.nan)

    prior_high_5 = frame["high"].shift(1).rolling(5, min_periods=5).max()
    prior_low_5 = frame["low"].shift(1).rolling(5, min_periods=5).min()
    out["prior_high_5m"] = prior_high_5
    out["prior_low_5m"] = prior_low_5
    out["prior_high_15m"] = frame["high"].shift(1).rolling(15, min_periods=15).max()
    out["prior_low_15m"] = frame["low"].shift(1).rolling(15, min_periods=15).min()
    out["drawdown_from_5m_high_pct"] = close / prior_high_5.replace(0.0, np.nan) - 1.0
    out["rally_from_5m_low_pct"] = close / prior_low_5.replace(0.0, np.nan) - 1.0

    rolling_low_3 = frame["low"].shift(1).rolling(3, min_periods=3).min()
    rolling_high_3 = frame["high"].shift(1).rolling(3, min_periods=3).max()
    out["no_new_low"] = np.where(
        rolling_low_3.isna(), np.nan, (frame["low"] >= rolling_low_3).astype(float)
    )
    out["no_new_high"] = np.where(
        rolling_high_3.isna(), np.nan, (frame["high"] <= rolling_high_3).astype(float)
    )

    # Klines already carry the taker split, so flow features also work without
    # the (heavy) tick archive; aggTrades later refines them.
    volume = pd.to_numeric(frame.get("volume"), errors="coerce")
    buy_volume = pd.to_numeric(frame.get("taker_buy_volume"), errors="coerce")
    if "taker_buy_quote_volume" in frame and "quote_volume" in frame:
        buy_usd = pd.to_numeric(frame["taker_buy_quote_volume"], errors="coerce")
        total_usd = pd.to_numeric(frame["quote_volume"], errors="coerce")
    else:
        buy_usd = buy_volume * close
        total_usd = volume * close
    sell_usd = total_usd - buy_usd
    out["taker_buy_usd"] = buy_usd
    out["taker_sell_usd"] = sell_usd
    out["trade_volume_usd"] = total_usd
    out["trade_count"] = pd.to_numeric(frame.get("count"), errors="coerce")
    imbalance = (buy_usd - sell_usd) / (buy_usd + sell_usd).replace(0.0, np.nan)
    out["taker_imbalance"] = imbalance
    out["taker_imbalance_ema15"] = imbalance.ewm(span=15, min_periods=5, adjust=False).mean()
    out["taker_imbalance_delta"] = imbalance - imbalance.shift(1)
    out["cvd_1m"] = buy_usd - sell_usd
    out["cvd_60m"] = out["cvd_1m"].rolling(60, min_periods=10).sum()
    out["trade_volume_z"] = _zscore(total_usd, 60)
    return out


def _merge_metrics(features: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    required = {"create_time", "sum_open_interest", "sum_taker_long_short_vol_ratio"}
    missing = required - set(metrics.columns)
    if missing:
        raise CascadeFeatureError(f"metrics frame is missing columns: {sorted(missing)}")
    frame = metrics.copy()
    frame["ts"] = _to_ts_ms(frame["create_time"])
    frame["sum_open_interest"] = pd.to_numeric(frame["sum_open_interest"], errors="coerce")
    frame["oi_chg_5m_pct"] = frame["sum_open_interest"].pct_change()
    rename = {
        "sum_open_interest": "oi",
        "sum_open_interest_value": "oi_notional",
        "oi_chg_5m_pct": "oi_chg_5m_pct",
        "sum_taker_long_short_vol_ratio": "taker_ls_ratio",
        "sum_toptrader_long_short_ratio": "top_trader_ls_ratio",
    }
    keep = ["ts"] + [column for column in rename if column in frame.columns]
    merged = _asof_merge(
        features.assign(ts=features["date"]), frame[keep].rename(columns=rename), "ts"
    )
    return merged.drop(columns=["ts"])


def _merge_funding(features: pd.DataFrame, funding: pd.DataFrame) -> pd.DataFrame:
    if "calc_time" not in funding.columns or "last_funding_rate" not in funding.columns:
        raise CascadeFeatureError("funding frame is missing calc_time/last_funding_rate")
    frame = funding.copy()
    frame["ts"] = _to_ts_ms(frame["calc_time"])
    frame["funding_rate"] = pd.to_numeric(frame["last_funding_rate"], errors="coerce")
    frame["funding_annualized"] = frame["funding_rate"] * 3.0 * 365.0
    merged = _asof_merge(
        features.assign(ts=features["date"]),
        frame[["ts", "funding_rate", "funding_annualized"]],
        "ts",
    )
    return merged.drop(columns=["ts"])


def _merge_depth(features: pd.DataFrame, depth: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "percentage", "notional"}
    missing = required - set(depth.columns)
    if missing:
        raise CascadeFeatureError(f"depth frame is missing columns: {sorted(missing)}")
    frame = depth.copy()
    frame["ts"] = _to_ts_ms(frame["timestamp"])
    frame["percentage"] = pd.to_numeric(frame["percentage"], errors="coerce")
    frame["notional"] = pd.to_numeric(frame["notional"], errors="coerce")
    frame = frame.dropna(subset=["ts", "percentage"])
    level_columns = sorted(frame["percentage"].unique().tolist())
    frame["level"] = frame["percentage"].map(lambda value: f"L{int(value)}")
    pivot = (
        frame.pivot_table(index="ts", columns="level", values="notional", aggfunc="last")
        .sort_index()
        .reset_index()
    )

    # Bar close = open time + 60s; the last snapshot published inside the bar is
    # already known by that close, so joining on the close stays causal.
    merged = _asof_merge(features.assign(ts=features["date"] + BAR_MS), pivot, "ts")
    merged = merged.drop(columns=["ts"]).sort_values("date").reset_index(drop=True)

    for level in (1, 2, 5):
        bid = merged.get(f"L-{level}")
        ask = merged.get(f"L{level}")
        if bid is None and ask is None:
            continue
        merged[f"bid_depth_usd_{level}pct"] = bid
        merged[f"ask_depth_usd_{level}pct"] = ask
        merged[f"depth_imbalance_{level}pct"] = (bid - ask) / (bid + ask).replace(0.0, np.nan)
    if "bid_depth_usd_1pct" in merged:
        merged["depth_total_usd_1pct"] = merged["bid_depth_usd_1pct"] + merged["ask_depth_usd_1pct"]
        merged["bid_depth_change_1m"] = (
            merged["bid_depth_usd_1pct"] - merged["bid_depth_usd_1pct"].shift(1)
        )
        merged["ask_depth_change_1m"] = (
            merged["ask_depth_usd_1pct"] - merged["ask_depth_usd_1pct"].shift(1)
        )
        merged["depth_imbalance_delta_1m"] = (
            merged["depth_imbalance_1pct"] - merged["depth_imbalance_1pct"].shift(1)
        )
        merged["liquidity_percentile_24h"] = (
            merged["depth_total_usd_1pct"].rolling(1440, min_periods=120).rank(pct=True)
        )
    return merged.drop(columns=[f"L{int(c)}" for c in level_columns if f"L{int(c)}" in merged.columns])


def _merge_trades(features: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    required = {"price", "quantity", "transact_time", "is_buyer_maker"}
    missing = required - set(trades.columns)
    if missing:
        raise CascadeFeatureError(f"aggTrades frame is missing columns: {sorted(missing)}")
    frame = trades.copy()
    frame["ts"] = _to_ts_ms(frame["transact_time"])
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
    frame["notional"] = frame["price"] * frame["quantity"]
    maker = frame["is_buyer_maker"]
    if maker.dtype != bool:
        maker = maker.astype(str).str.lower().isin({"true", "1"})
    # is_buyer_maker=True means the aggressor was a seller.
    frame["sell_usd"] = frame["notional"].where(maker, 0.0)
    frame["buy_usd"] = frame["notional"].where(~maker, 0.0)
    frame["minute"] = (frame["ts"] // BAR_MS) * BAR_MS
    grouped = frame.groupby("minute").agg(
        tick_buy_usd=("buy_usd", "sum"),
        tick_sell_usd=("sell_usd", "sum"),
        tick_count=("notional", "size"),
    )
    grouped["tick_vwap"] = _groupby_vwap(frame)
    merged = _asof_merge(
        features.assign(ts=features["date"]),
        grouped.reset_index().rename(columns={"minute": "ts"}),
        "ts",
    ).drop(columns=["ts"])

    merged["taker_buy_usd"] = merged["tick_buy_usd"].fillna(merged["taker_buy_usd"])
    merged["taker_sell_usd"] = merged["tick_sell_usd"].fillna(merged["taker_sell_usd"])
    merged["trade_volume_usd"] = merged["taker_buy_usd"] + merged["taker_sell_usd"]
    merged["trade_count"] = merged["tick_count"].fillna(merged["trade_count"])
    imbalance = (merged["taker_buy_usd"] - merged["taker_sell_usd"]) / merged[
        "trade_volume_usd"
    ].replace(0.0, np.nan)
    merged["taker_imbalance"] = imbalance.fillna(merged["taker_imbalance"])
    merged["taker_imbalance_ema15"] = merged["taker_imbalance"].ewm(
        span=15, min_periods=5, adjust=False
    ).mean()
    merged["taker_imbalance_delta"] = merged["taker_imbalance"] - merged["taker_imbalance"].shift(1)
    merged["cvd_1m"] = merged["taker_buy_usd"] - merged["taker_sell_usd"]
    merged["cvd_60m"] = merged["cvd_1m"].rolling(60, min_periods=10).sum()
    merged["trade_vwap"] = merged["tick_vwap"]
    merged["trade_vwap_gap_pct"] = merged["tick_vwap"] / merged["close"].replace(0.0, np.nan) - 1.0
    return merged.drop(
        columns=["tick_buy_usd", "tick_sell_usd", "tick_count", "tick_vwap"]
    )


def _merge_liquidations(
    features: pd.DataFrame,
    liquidations: pd.DataFrame,
    *,
    window: int,
    quantile: float,
) -> pd.DataFrame:
    frame = liquidations.copy()
    if "side" not in frame.columns:
        raise CascadeFeatureError("liquidation frame is missing the 'side' column")
    time_column = "date" if "date" in frame.columns else "transact_time"
    if time_column not in frame.columns:
        raise CascadeFeatureError("liquidation frame needs a date/transact_time column")
    frame["ts"] = _to_ts_ms(frame[time_column])
    if "notional" in frame.columns:
        frame["notional"] = pd.to_numeric(frame["notional"], errors="coerce")
    else:
        quantity = frame["qty"] if "qty" in frame.columns else frame["quantity"]
        frame["notional"] = pd.to_numeric(frame["price"], errors="coerce") * pd.to_numeric(
            quantity, errors="coerce"
        )
    frame["side"] = frame["side"].astype(str).str.lower()
    frame["minute"] = (frame["ts"] // BAR_MS) * BAR_MS
    split = frame.assign(
        long_usd=frame["notional"].where(frame["side"].str.startswith("l"), 0.0),
        short_usd=frame["notional"].where(frame["side"].str.startswith("s"), 0.0),
    )
    grouped = split.groupby("minute").agg(
        liq_long_usd=("long_usd", "sum"),
        liq_short_usd=("short_usd", "sum"),
        liq_count=("notional", "size"),
    )
    merged = _asof_merge(
        features.assign(ts=features["date"]),
        grouped.reset_index().rename(columns={"minute": "ts"}),
        "ts",
    ).drop(columns=["ts"])
    for column in ("liq_long_usd", "liq_short_usd", "liq_count"):
        merged[column] = merged[column].fillna(0.0)
    merged["liq_total_usd"] = merged["liq_long_usd"] + merged["liq_short_usd"]
    merged["liq_imbalance"] = (merged["liq_short_usd"] - merged["liq_long_usd"]) / merged[
        "liq_total_usd"
    ].replace(0.0, np.nan)
    merged["has_liquidations"] = 1.0
    prior = merged["liq_total_usd"].shift(1)
    merged["liq_p95_1h"] = prior.rolling(window, min_periods=max(10, window // 6)).quantile(quantile)
    merged["liq_ratio_1h"] = merged["liq_total_usd"] / merged["liq_p95_1h"].replace(0.0, np.nan)
    merged["liq_z_1h"] = _zscore(merged["liq_total_usd"], window)
    return merged


def _merge_okx_derivatives(
    features: pd.DataFrame,
    *,
    oi: pd.DataFrame | None = None,
    taker: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Merge the venue-consistent OKX OI / taker streams collected from Rubik.

    Both are 5-minute series, so they are forward-filled point-in-time onto the
    1m grid. The taker columns override the kline-derived ones (which OKX candles
    cannot provide) so the flush score uses real venue flow when available.
    """
    out = features
    if oi is not None and not oi.empty:
        frame = oi.copy()
        frame["ts"] = pd.to_numeric(frame["ts"], errors="coerce")
        frame = frame.dropna(subset=["ts"]).sort_values("ts")
        frame["oi"] = pd.to_numeric(frame.get("oi"), errors="coerce")
        frame["oi_notional"] = pd.to_numeric(frame.get("oi_notional"), errors="coerce")
        # Change in *coin* OI, so price moves alone do not look like position changes.
        frame["oi_chg_5m_pct"] = frame["oi"].pct_change()
        out = _asof_merge(
            out.assign(ts=out["date"]),
            frame[["ts", "oi", "oi_notional", "oi_chg_5m_pct"]],
            "ts",
        ).drop(columns=["ts"])
    if taker is not None and not taker.empty:
        frame = taker.copy()
        frame["ts"] = pd.to_numeric(frame["ts"], errors="coerce")
        frame = frame.dropna(subset=["ts"]).sort_values("ts")
        frame["okx_buy"] = pd.to_numeric(frame.get("taker_buy_usd"), errors="coerce")
        frame["okx_sell"] = pd.to_numeric(frame.get("taker_sell_usd"), errors="coerce")
        merged = _asof_merge(
            out.assign(ts=out["date"]), frame[["ts", "okx_buy", "okx_sell"]], "ts"
        ).drop(columns=["ts"])
        merged["taker_buy_usd"] = merged["okx_buy"].fillna(merged.get("taker_buy_usd"))
        merged["taker_sell_usd"] = merged["okx_sell"].fillna(merged.get("taker_sell_usd"))
        merged["trade_volume_usd"] = merged["taker_buy_usd"] + merged["taker_sell_usd"]
        imbalance = (merged["taker_buy_usd"] - merged["taker_sell_usd"]) / merged[
            "trade_volume_usd"
        ].replace(0.0, np.nan)
        merged["taker_imbalance"] = imbalance
        merged["taker_imbalance_ema15"] = imbalance.ewm(span=15, min_periods=5, adjust=False).mean()
        merged["taker_imbalance_delta"] = imbalance - imbalance.shift(1)
        merged["cvd_1m"] = merged["taker_buy_usd"] - merged["taker_sell_usd"]
        merged["cvd_60m"] = merged["cvd_1m"].rolling(60, min_periods=10).sum()
        merged["trade_volume_z"] = _zscore(merged["trade_volume_usd"], 60)
        out = merged.drop(columns=["okx_buy", "okx_sell"])
    return out


def _flow_scores(features: pd.DataFrame, *, window: int) -> pd.DataFrame:
    empty = pd.Series(np.nan, index=features.index, dtype="float64")
    oi_change = features["oi_chg_5m_pct"] if "oi_chg_5m_pct" in features else empty
    long_liq = features["liq_long_usd"] if "liq_long_usd" in features else empty
    short_liq = features["liq_short_usd"] if "liq_short_usd" in features else empty
    long_components = pd.DataFrame(
        {
            "drop_z": _zscore(-features["ret_1m"], window),
            "sell_z": _zscore(-features["taker_imbalance"], window),
            "oi_z": _zscore(-oi_change, window),
            "liq_z": _zscore(long_liq, window),
        }
    )
    short_components = pd.DataFrame(
        {
            "drop_z": _zscore(features["ret_1m"], window),
            "sell_z": _zscore(features["taker_imbalance"], window),
            "oi_z": _zscore(-oi_change, window),
            "liq_z": _zscore(short_liq, window),
        }
    )
    out = features.copy()
    out["flush_long_score"] = _weighted_score(long_components, FLUSH_WEIGHTS)
    out["flush_short_score"] = _weighted_score(short_components, FLUSH_WEIGHTS)
    return out


# ----------------------------------------------------------------- public API
def build_features(
    klines: pd.DataFrame,
    *,
    metrics: pd.DataFrame | None = None,
    depth: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    funding: pd.DataFrame | None = None,
    liquidations: pd.DataFrame | None = None,
    okx_oi: pd.DataFrame | None = None,
    okx_taker: pd.DataFrame | None = None,
    window: int = 60,
    quantile: float = 0.95,
) -> pd.DataFrame:
    """Build the causal 1m cascade feature frame.

    ``klines`` must carry Binance futures 1m columns (``open_time`` plus the
    OHLCV set). Every other input is optional: a missing input simply leaves the
    matching feature columns empty, and the flush score renormalises over
    whatever is available.
    """
    if klines is None or klines.empty:
        raise CascadeFeatureError("klines frame is empty")
    if "open_time" not in klines.columns:
        raise CascadeFeatureError("klines frame is missing 'open_time'")
    frame = klines.copy()
    frame["date"] = _to_ts_ms(frame["open_time"])
    for column in ("open", "high", "low", "close"):
        if column not in frame.columns:
            raise CascadeFeatureError(f"klines frame is missing '{column}'")
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    features = _base_features(frame)
    if metrics is not None and not metrics.empty:
        features = _merge_metrics(features, metrics)
    if funding is not None and not funding.empty:
        features = _merge_funding(features, funding)
    if depth is not None and not depth.empty:
        features = _merge_depth(features, depth)
    if trades is not None and not trades.empty:
        features = _merge_trades(features, trades)
    if (okx_oi is not None and not okx_oi.empty) or (okx_taker is not None and not okx_taker.empty):
        features = _merge_okx_derivatives(features, oi=okx_oi, taker=okx_taker)
    if liquidations is not None and not liquidations.empty:
        features = _merge_liquidations(features, liquidations, window=window, quantile=quantile)
    else:
        for column in ("liq_long_usd", "liq_short_usd", "liq_total_usd", "liq_count"):
            features[column] = np.nan
        features["has_liquidations"] = 0.0

    features = features.drop(columns=["close"]).sort_values("date").reset_index(drop=True)
    features = _flow_scores(features, window=window)

    renamed = features.rename(
        columns={c: f"{PREFIX}{c}" for c in features.columns if c != "date"}
    )
    ordered = ["date"] + [
        f"{PREFIX}{name}" for name in FEATURE_COLUMNS if f"{PREFIX}{name}" in renamed
    ]
    leftovers = [c for c in renamed.columns if c not in ordered]
    return renamed[ordered + leftovers]


def cascade_events(
    features: pd.DataFrame,
    *,
    side: str = "long",
    move_pct: float = 0.005,
    flush_score: float = 1.5,
    liq_ratio: float = 1.0,
    require_liquidations: bool = False,
) -> pd.DataFrame:
    """Rows that satisfy the cascade trigger - used for reporting and tuning."""
    if side not in ("long", "short"):
        raise CascadeFeatureError("side must be 'long' or 'short'")
    direction = -1.0 if side == "long" else 1.0
    mask = features["cx_ret_1m"] * direction >= move_pct
    mask &= features[f"cx_flush_{side}_score"].fillna(-np.inf) >= flush_score
    if require_liquidations and "cx_liq_ratio_1h" in features:
        mask &= features["cx_liq_ratio_1h"].fillna(0.0) >= liq_ratio
    selected = features[mask]
    keep = [
        column
        for column in (
            "date", "cx_ret_1m", "cx_drawdown_from_5m_high_pct", "cx_rally_from_5m_low_pct",
            "cx_taker_imbalance", "cx_oi_chg_5m_pct", "cx_liq_long_usd", "cx_liq_short_usd",
            "cx_liq_ratio_1h", "cx_flush_long_score", "cx_flush_short_score",
            "cx_depth_imbalance_1pct", "cx_liquidity_percentile_24h",
        )
        if column in selected.columns
    ]
    return selected[keep].reset_index(drop=True)
