"""Factor library v1 (ticket 03).

Every factor is a pure function of the *wide* panel (``ts x pair``), so it can be
evaluated on any pool and any timeframe without touching the screening engine.
``direction`` encodes the economically expected sign: ``+1`` means a higher factor
value should predict a higher forward return.

Causality: factors only use information available at (or before) their own bar
timestamp. Forward returns are computed by the screening engine with an explicit
``shift(-horizon)``, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .factor_panel import pivot

# Session windows in UTC hours (US cash equity session).
US_SESSION_START = 13
US_SESSION_END = 20  # exclusive

DAY = 24
WEEK = 168


@dataclass(frozen=True)
class Factor:
    name: str
    family: str
    direction: int
    lookback: int
    requires: tuple[str, ...] = ()
    equity_only: bool = False
    note: str = ""


@dataclass
class Wide:
    """Wide (ts x pair) view of a panel plus the calendar helpers factors need."""

    close: pd.DataFrame
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    funding: pd.DataFrame
    index: pd.DataFrame
    ret: pd.DataFrame
    hour: pd.Index
    dow: pd.Index

    @property
    def pairs(self) -> list[str]:
        return list(self.close.columns)

    @property
    def market_ret(self) -> pd.Series:
        """Equal-weight universe return (the cross-sectional market factor)."""
        return self.ret.mean(axis=1)


def make_wide(panel: pd.DataFrame) -> Wide:
    close = pivot(panel, "close")
    return Wide(
        close=close,
        open=pivot(panel, "open").reindex_like(close),
        high=pivot(panel, "high").reindex_like(close),
        low=pivot(panel, "low").reindex_like(close),
        volume=pivot(panel, "volume").reindex_like(close),
        funding=pivot(panel, "funding_rate").reindex_like(close),
        index=pivot(panel, "index_close").reindex_like(close),
        ret=np.log(close).diff(),
        hour=pd.Index(panel.groupby("ts")["hour"].last().reindex(close.index).to_numpy()),
        dow=pd.Index(panel.groupby("ts")["dow"].last().reindex(close.index).to_numpy()),
    )


def _rolling_mean(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    return frame.rolling(window, min_periods=window).mean()


def _rolling_std(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    return frame.rolling(window, min_periods=window).std()


def _session_mask(hour: pd.Index) -> np.ndarray:
    values = np.asarray(hour, dtype="float64")
    return (values >= US_SESSION_START) & (values < US_SESSION_END)


def _mask_like(frame: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    """Broadcast a 1-D boolean row mask to the shape of ``frame``."""
    return pd.DataFrame(
        np.broadcast_to(np.asarray(mask, dtype=bool)[:, None], frame.shape),
        index=frame.index,
        columns=frame.columns,
    )


def _market_beta(wide: Wide, window: int) -> pd.DataFrame:
    market = wide.market_ret
    cov = wide.ret.rolling(window, min_periods=window).cov(market)
    var = market.rolling(window, min_periods=window).var()
    return cov.div(var, axis=0)


# --------------------------------------------------------------- definitions

def _factor_momentum(horizon: int) -> Callable[[Wide], pd.DataFrame]:
    def factor(wide: Wide) -> pd.DataFrame:
        return wide.close.pct_change(horizon, fill_method=None)

    return factor


def _factor_reversal(horizon: int) -> Callable[[Wide], pd.DataFrame]:
    def factor(wide: Wide) -> pd.DataFrame:
        return wide.ret.rolling(horizon, min_periods=horizon).sum()

    return factor


def _factor_vol(window: int) -> Callable[[Wide], pd.DataFrame]:
    return lambda wide: _rolling_std(wide.ret, window)


def _vol_ratio(wide: Wide) -> pd.DataFrame:
    return _rolling_std(wide.ret, DAY) / _rolling_std(wide.ret, WEEK)


def _atr_pct(wide: Wide) -> pd.DataFrame:
    span = (wide.high - wide.low) / wide.close
    return _rolling_mean(span, DAY)


def _volume_z(wide: Wide) -> pd.DataFrame:
    mean = _rolling_mean(wide.volume, DAY)
    std = _rolling_std(wide.volume, DAY)
    return (wide.volume - mean) / std.replace(0.0, np.nan)


def _volume_trend(wide: Wide) -> pd.DataFrame:
    short = _rolling_mean(wide.volume, DAY)
    long = _rolling_mean(wide.volume, WEEK)
    return short / long.replace(0.0, np.nan)


def _amihud(wide: Wide) -> pd.DataFrame:
    dollar = (wide.volume * wide.close).replace(0.0, np.nan)
    illiq = wide.ret.abs() / dollar
    return _rolling_mean(illiq, DAY) * 1e9


def _funding_level(wide: Wide) -> pd.DataFrame:
    return wide.funding


def _funding_z(wide: Wide) -> pd.DataFrame:
    mean = _rolling_mean(wide.funding, WEEK)
    std = _rolling_std(wide.funding, WEEK)
    return (wide.funding - mean) / std.replace(0.0, np.nan)


def _funding_trend(wide: Wide) -> pd.DataFrame:
    return _rolling_mean(wide.funding, DAY) - _rolling_mean(wide.funding, WEEK)


def _basis(wide: Wide) -> pd.DataFrame:
    index = wide.index.replace(0.0, np.nan)
    return (wide.close - index) / index


def _basis_z(wide: Wide) -> pd.DataFrame:
    basis = _basis(wide)
    mean = _rolling_mean(basis, WEEK)
    std = _rolling_std(basis, WEEK)
    return (basis - mean) / std.replace(0.0, np.nan)


def _beta(wide: Wide) -> pd.DataFrame:
    return _market_beta(wide, DAY * 30)


def _residual_momentum(wide: Wide) -> pd.DataFrame:
    beta = _market_beta(wide, DAY * 30)
    market_mom = wide.close.mean(axis=1).pct_change(WEEK, fill_method=None)
    own_mom = wide.close.pct_change(WEEK, fill_method=None)
    return own_mom.sub(beta.mul(market_mom, axis=0))


def _us_momentum(wide: Wide) -> pd.DataFrame:
    session_ret = wide.ret.where(_mask_like(wide.ret, _session_mask(wide.hour)), 0.0)
    return session_ret.rolling(DAY, min_periods=DAY).sum()


def _offus_momentum(wide: Wide) -> pd.DataFrame:
    total = wide.ret.rolling(DAY, min_periods=DAY).sum()
    return total - _us_momentum(wide)


def _offhour_vol_ratio(wide: Wide) -> pd.DataFrame:
    mask = _mask_like(wide.ret, _session_mask(wide.hour))
    inside = wide.ret.where(mask)
    outside = wide.ret.where(~mask)
    # Session hours only occur 7 bars per day, so the two legs need different
    # minimum observation counts rather than a full 168-bar window.
    inside_std = inside.rolling(WEEK, min_periods=3 * 7).std()
    outside_std = outside.rolling(WEEK, min_periods=3 * 17).std()
    return outside_std / inside_std.replace(0.0, np.nan)


def _weekend_gap(wide: Wide) -> pd.DataFrame:
    """Monday 00:00 UTC: return since Friday 00:00 UTC (the weekend gap)."""
    gap = wide.close / wide.close.shift(2 * DAY) - 1.0
    mask = (np.asarray(wide.dow) == 0) & (np.asarray(wide.hour) == 0)
    return gap.where(_mask_like(gap, mask))


FACTORS: dict[str, Factor] = {
    # --- momentum --------------------------------------------------------
    "mom_1h": Factor("mom_1h", "momentum", +1, 1, note="1 小时动量"),
    "mom_6h": Factor("mom_6h", "momentum", +1, 6, note="6 小时动量"),
    "mom_1d": Factor("mom_1d", "momentum", +1, DAY, note="1 日动量"),
    "mom_3d": Factor("mom_3d", "momentum", +1, 3 * DAY, note="3 日动量"),
    "mom_7d": Factor("mom_7d", "momentum", +1, WEEK, note="1 周动量"),
    "mom_30d": Factor("mom_30d", "momentum", +1, 30 * DAY, note="1 月动量"),
    # --- short-term reversal --------------------------------------------
    "rev_1h": Factor("rev_1h", "reversal", -1, 1, note="1 小时反转"),
    "rev_4h": Factor("rev_4h", "reversal", -1, 4, note="4 小时反转"),
    "rev_1d": Factor("rev_1d", "reversal", -1, DAY, note="1 日反转"),
    # --- volatility ------------------------------------------------------
    "vol_1d": Factor("vol_1d", "volatility", +1, DAY, note="1 日已实现波动"),
    "vol_7d": Factor("vol_7d", "volatility", +1, WEEK, note="1 周已实现波动"),
    "vol_ratio": Factor("vol_ratio", "volatility", +1, WEEK, note="短/长波动比"),
    "atr_pct": Factor("atr_pct", "volatility", +1, DAY, note="ATR 占价格比"),
    # --- volume / liquidity ---------------------------------------------
    "volume_z": Factor("volume_z", "volume", +1, DAY, note="成交量 z-score"),
    "volume_trend": Factor("volume_trend", "volume", +1, WEEK, note="量能 1 日/1 周比"),
    "amihud": Factor("amihud", "volume", -1, DAY, note="Amihud 非流动性"),
    # --- carry -----------------------------------------------------------
    "funding_level": Factor("funding_level", "carry", -1, 1, requires=("funding",),
                            note="资金费水平（多头付费→做多不利）"),
    "funding_z": Factor("funding_z", "carry", -1, WEEK, requires=("funding",),
                        note="资金费 z-score"),
    "funding_trend": Factor("funding_trend", "carry", -1, WEEK, requires=("funding",),
                            note="资金费均值变化"),
    # --- basis -----------------------------------------------------------
    "basis": Factor("basis", "basis", -1, 1, requires=("index",), note="永续−指数 溢价"),
    "basis_z": Factor("basis_z", "basis", -1, WEEK, requires=("index",), note="溢价 z-score"),
    # --- risk / residual ------------------------------------------------
    "beta_30d": Factor("beta_30d", "risk", -1, 30 * DAY, note="对等权宇宙的 beta"),
    "resid_mom_7d": Factor("resid_mom_7d", "risk", +1, 30 * DAY, note="剔除 beta 的残差动量"),
    # --- equity session structure (equity pool only) ---------------------
    "us_mom_1d": Factor("us_mom_1d", "session", +1, DAY, equity_only=True,
                        note="美国现金时段 1 日动量"),
    "offus_mom_1d": Factor("offus_mom_1d", "session", +1, DAY, equity_only=True,
                           note="非现金时段 1 日动量"),
    "offhour_vol_ratio": Factor("offhour_vol_ratio", "session", +1, WEEK, equity_only=True,
                                note="非时段/时段 波动比"),
    "weekend_gap": Factor("weekend_gap", "session", -1, 2 * DAY, equity_only=True,
                          note="周末跳空（周一 00:00 UTC 可用）"),
}


_IMPLEMENTATIONS: dict[str, Callable[[Wide], pd.DataFrame]] = {
    "mom_1h": _factor_momentum(1),
    "mom_6h": _factor_momentum(6),
    "mom_1d": _factor_momentum(DAY),
    "mom_3d": _factor_momentum(3 * DAY),
    "mom_7d": _factor_momentum(WEEK),
    "mom_30d": _factor_momentum(30 * DAY),
    "rev_1h": _factor_reversal(1),
    "rev_4h": _factor_reversal(4),
    "rev_1d": _factor_reversal(DAY),
    "vol_1d": _factor_vol(DAY),
    "vol_7d": _factor_vol(WEEK),
    "vol_ratio": _vol_ratio,
    "atr_pct": _atr_pct,
    "volume_z": _volume_z,
    "volume_trend": _volume_trend,
    "amihud": _amihud,
    "funding_level": _funding_level,
    "funding_z": _funding_z,
    "funding_trend": _funding_trend,
    "basis": _basis,
    "basis_z": _basis_z,
    "beta_30d": _beta,
    "resid_mom_7d": _residual_momentum,
    "us_mom_1d": _us_momentum,
    "offus_mom_1d": _offus_momentum,
    "offhour_vol_ratio": _offhour_vol_ratio,
    "weekend_gap": _weekend_gap,
}


def compute_factors(
    wide: Wide,
    names: list[str] | None = None,
    *,
    equity_pool: bool = False,
) -> dict[str, pd.DataFrame]:
    """Compute the requested factors (default: all applicable ones)."""
    selected = names or list(FACTORS)
    result: dict[str, pd.DataFrame] = {}
    for name in selected:
        definition = FACTORS.get(name)
        if definition is None:
            raise KeyError(f"未定义的因子：{name}")
        if definition.equity_only and not equity_pool:
            continue
        values = _IMPLEMENTATIONS[name](wide)
        if isinstance(values, pd.DataFrame):
            result[name] = values.reindex_like(wide.close)
        else:  # pragma: no cover - defensive
            result[name] = values.to_frame().reindex_like(wide.close)
    return result


def cs_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score per timestamp (used for composite scoring)."""
    mean = frame.mean(axis=1)
    std = frame.std(axis=1).replace(0.0, np.nan)
    return frame.sub(mean, axis=0).div(std, axis=0)


def usable_ratio(frame: pd.DataFrame, min_pairs: int) -> float:
    """Fraction of timestamps with at least ``min_pairs`` finite values."""
    counts = frame.notna().sum(axis=1)
    return float((counts >= min_pairs).mean()) if len(counts) else 0.0
