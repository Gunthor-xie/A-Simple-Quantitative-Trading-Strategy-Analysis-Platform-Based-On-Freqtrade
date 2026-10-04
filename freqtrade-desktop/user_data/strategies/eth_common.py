"""Shared pandas indicators for ETH_* strategies (no TA-Lib required)."""
import numpy as np
import pandas as pd


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1 / n, adjust=False).mean()
    al = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd_series(close, fast=12, slow=26, signal=9):
    dif = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    dea = dif.ewm(span=signal, adjust=False).mean()
    return {"dif": dif, "dea": dea, "hist": dif - dea}


def atr_series(high, low, close, n=14):
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx_di(high, low, close, n=14):
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)
    plus_dm[(up > down) & (up > 0)] = up
    minus_dm[(down > up) & (down > 0)] = down
    tr = atr_series(high, low, close, n)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), plus_di, minus_di


def mfi(high, low, close, vol, n=14):
    tp = (high + low + close) / 3
    raw = tp * vol
    up = raw.where(tp > tp.shift(1), 0.0)
    dn = raw.where(tp < tp.shift(1), 0.0)
    mr = up.rolling(n).sum() / dn.rolling(n).sum().replace(0, np.nan)
    return 100 - 100 / (1 + mr)


def add_indicators(df):
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    for n in (5, 10, 20, 60, 120):
        df[f"sma{n}"] = close.rolling(n).mean()
    df["rsi14"] = rsi(close, 14)
    df["rsi6"] = rsi(close, 6)
    macd = macd_series(close)
    df["dif"] = macd["dif"]
    df["dea"] = macd["dea"]
    df["hist"] = macd["hist"]
    df["atr"] = atr_series(high, low, close, 14)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    df["bb_mid"] = mid
    df["bb_up"] = mid + 2 * std
    df["bb_low"] = mid - 2 * std
    df["bb_width"] = (df["bb_up"] - df["bb_low"]) / mid.replace(0, np.nan)
    df["volma20"] = vol.rolling(20).mean()
    adx, dip, dim = adx_di(high, low, close)
    df["adx"] = adx
    df["di+"] = dip
    df["di-"] = dim
    df["mfi"] = mfi(high, low, close, vol, 14)
    direction = (close > close.shift(1)).astype(int) - (close < close.shift(1)).astype(int)
    df["obv"] = (direction * vol).cumsum()
    tp = (high + low + close) / 3
    cum_vp = (tp * vol).rolling(24).sum()
    cum_v = vol.rolling(24).sum()
    df["vwap"] = cum_vp / cum_v.replace(0, np.nan)
    return df


def _to_dt(series):
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, unit="ms", utc=True)


def merge_1h(df):
    """Append 1-hour indicator snapshots (suffix _1h) to a 15m dataframe.

    Keeps the original 'date' column untouched (datetime or ms-int) so the
    dataframe stays compatible with freqtrade internals.
    """
    out = df.copy()
    dt = _to_dt(out["date"])
    out["_dt1h"] = dt.dt.floor("1h")
    h = (out.resample("1h", on="_dt1h")
         .agg({"open": "first", "high": "max", "low": "min",
               "close": "last", "volume": "sum"}).dropna().reset_index())
    add_indicators(h)
    h = h.drop(columns=["open"], errors="ignore")
    h = h.rename(columns={"volume": "volume_1h"})
    h = h.rename(columns={c: f"{c}_1h" for c in h.columns if c not in ("_dt1h", "volume_1h")})
    # 因果对齐：把 1h 桶整体后移一小时，使当前 15m K 线只能引用上一根
    # 已完成的 1h K 线。否则回测在整段 DataFrame 上重采样时，会提前把本小时
    # 尚未发生的 15m 数据（未来数据）并入 close_1h/high_1h/low_1h/volume_1h。
    h["_dt1h"] = h["_dt1h"] + pd.Timedelta(hours=1)
    out = out.merge(h, left_on="_dt1h", right_on="_dt1h", how="left")
    return out.drop(columns=["_dt1h"])
