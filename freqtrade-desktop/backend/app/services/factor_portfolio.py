"""Cross-sectional portfolio simulation with an explicit cost model (ticket 05).

The book is dollar-neutral: long the top-K composite names, short the bottom-K,
risked to a target volatility. Costs are charged on realised turnover, funding is
charged only at settlement bars, and the capacity estimate reports the capital at
which the ADV participation cap starts binding.

Normalisation: leg weights sum to 0.5 each (gross exposure 1.0) before the
volatility scaling; the returned ``returns`` series is already net of costs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .factor_lib import cs_zscore
from .factor_screen import forward_returns, rank_ic


@dataclass
class PortfolioConfig:
    k: int = 5
    target_vol: float = 0.15
    max_leverage: float = 2.0
    rebalance_bars: int = 24
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    min_adv_usd: float = 1e6
    max_adv_share: float = 0.005
    vol_window: int = 30
    periods_per_year: float = 365.0
    legs: str = "both"  # both | long | short (for decomposition)

    @property
    def cost_rate(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4


def build_composite(
    factors: dict[str, pd.DataFrame],
    selected: list[str],
    *,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Average cross-sectional z-scores of the selected (direction-signed) factors."""
    total: pd.DataFrame | None = None
    weight_sum = 0.0
    for name in selected:
        if name not in factors:
            continue
        weight = 1.0 if weights is None else float(weights.get(name, 0.0))
        if weight == 0.0:
            continue
        scaled = cs_zscore(factors[name])
        total = scaled * weight if total is None else total.add(scaled * weight, fill_value=0.0)
        weight_sum += weight
    if total is None or weight_sum == 0:
        raise ValueError("组合打分为空：没有可用的因子")
    return total / weight_sum


def walk_forward_composite(
    close: pd.DataFrame,
    factors: dict[str, pd.DataFrame],
    selected: list[str],
    *,
    horizon_bars: int = 24,
    window_obs: int = 40,
    min_obs: int = 10,
    min_pairs: int = 5,
) -> pd.DataFrame:
    """Composite score whose factor orientation is estimated causally.

    A factor's economic ``direction`` is a prior guess; when the data disagrees the
    prior would point the book the wrong way. Here each factor is oriented by the
    sign of its own trailing RankIC. The IC measured at observation ``s`` is only
    known once the forward window has elapsed, so the orientation is shifted by one
    observation before being used — the composite at ``t`` never sees data from ``t``
    or later.
    """
    fwd = forward_returns(close, horizon_bars)
    grid = close.index[::horizon_bars]
    total: pd.DataFrame | None = None
    weight: pd.DataFrame | None = None
    for name in selected:
        frame = factors.get(name)
        if frame is None:
            continue
        ic = rank_ic(frame, fwd, min_pairs)
        ic = ic[ic.index.isin(grid)]
        known = ic.shift(1)  # only ICs whose forward window already closed
        orientation = (known.rolling(window_obs, min_periods=min_obs).mean()
                       .apply(np.sign).replace(0.0, np.nan))
        z = cs_zscore(frame).reindex(grid).mul(orientation, axis=0)
        mask = z.notna().astype(float)
        total = z if total is None else total.add(z, fill_value=0.0)
        weight = mask if weight is None else weight.add(mask, fill_value=0.0)
    if total is None or weight is None:
        raise ValueError("组合打分为空：没有可用的因子")
    return (total / weight.replace(0.0, np.nan)).reindex(close.index)


def trailing_adv(volume: pd.DataFrame, close: pd.DataFrame, window: int = 168,
                 bars_per_day: int = 24) -> pd.DataFrame:
    """Trailing median **daily** dollar volume (past information only).

    The panel stores per-bar volume, so the median is annualised to a daily figure
    before the liquidity filter compares it against ``min_adv_usd``.
    """
    per_bar = (volume * close).rolling(window, min_periods=window // 2).median()
    return per_bar * bars_per_day


def _rebalance_positions(count: int, step: int) -> list[int]:
    positions = list(range(0, count, step))
    if positions and positions[-1] != count - 1:
        positions.append(count - 1)
    return positions


def simulate(
    close: pd.DataFrame,
    composite: pd.DataFrame,
    *,
    funding: pd.DataFrame | None = None,
    funding_settled: pd.DataFrame | None = None,
    adv: pd.DataFrame | None = None,
    cfg: PortfolioConfig | None = None,
) -> dict:
    """Simulate the dollar-neutral book and return per-period net returns and diagnostics."""
    cfg = cfg or PortfolioConfig()
    composite = composite.reindex_like(close)
    positions = _rebalance_positions(len(close.index), cfg.rebalance_bars)

    periods: list[dict] = []
    previous_weights: pd.Series | None = None
    for idx, start in enumerate(positions[:-1]):
        end = positions[idx + 1]
        row = composite.iloc[start]
        eligible = row.dropna()
        if adv is not None:
            liquidity = adv.iloc[start]
            eligible = eligible[eligible.index.isin(
                liquidity[liquidity >= cfg.min_adv_usd].index)]
        if len(eligible) < 2 * cfg.k:
            continue
        ranked = eligible.sort_values()
        shorts = ranked.index[: cfg.k]
        longs = ranked.index[-cfg.k:]
        weights = pd.Series(0.0, index=close.columns)
        if cfg.legs == "long":
            weights[longs] = 1.0 / cfg.k
        elif cfg.legs == "short":
            weights[shorts] = -1.0 / cfg.k
        else:
            weights[longs] = 0.5 / cfg.k
            weights[shorts] = -0.5 / cfg.k

        entry = close.iloc[start]
        exit_ = close.iloc[end]
        gross = float(((exit_ / entry - 1.0) * weights).sum(skipna=True))

        traded = weights.copy()
        if previous_weights is not None:
            traded = (weights - previous_weights).abs()
        cost = float(traded.sum()) * cfg.cost_rate

        funding_cost = 0.0
        if funding is not None and cfg.rebalance_bars > 0:
            window = funding.iloc[start + 1:end + 1]
            if len(window):
                if funding_settled is not None:
                    # Charge only at real settlement bars (the funding series is
                    # forward-filled, so a "changed value" test would miss repeats).
                    flags = funding_settled.iloc[start + 1:end + 1].reindex_like(window).fillna(0)
                else:  # fallback: treat value changes as settlements
                    flags = (window.diff().abs() > 0).astype(float)
                charges = (window * (flags > 0)) @ weights
                funding_cost = float(charges.fillna(0.0).sum())

        periods.append({
            "start": int(close.index[start]),
            "end": int(close.index[end]),
            "gross": gross,
            "cost": cost,
            "funding": funding_cost,
            "net": gross - cost - funding_cost,
            "turnover": float(traded.sum()),
            "longs": list(longs),
            "shorts": list(shorts),
        })
        previous_weights = weights

    frame = pd.DataFrame(periods)
    if frame.empty:
        raise ValueError("模拟为空：可交易标的不足或评分全为空")

    gross_returns = frame.set_index("start")["net"]
    realized = gross_returns.rolling(cfg.vol_window, min_periods=max(5, cfg.vol_window // 3)).std()
    periods_per_year = cfg.periods_per_year
    scale = (cfg.target_vol / (realized * math.sqrt(periods_per_year))).shift(1)
    scale = scale.clip(upper=cfg.max_leverage).fillna(0.0)
    net_returns = gross_returns * scale

    capacity = _capacity(frame, adv, cfg)
    stats = performance(net_returns.reindex(frame["start"]).fillna(0.0), periods_per_year)
    return {
        "config": cfg.__dict__.copy(),
        "periods": frame.drop(columns=["longs", "shorts"]).to_dict("records"),
        "returns": net_returns,
        "gross_returns": gross_returns,
        "leverage": scale,
        "stats": stats,
        "mean_turnover": float(frame["turnover"].mean()),
        "cost_total": float(frame["cost"].sum()),
        "funding_total": float(frame["funding"].sum()),
        "capacity_usd": capacity,
    }


def _capacity(frame: pd.DataFrame, adv: pd.DataFrame | None, cfg: PortfolioConfig) -> float | None:
    """Capital at which the ADV participation cap binds (min across held names)."""
    if adv is None or frame.empty:
        return None
    limits: list[float] = []
    for _, row in frame.iterrows():
        liquidity = adv.loc[row["start"]] if row["start"] in adv.index else None
        if liquidity is None:
            continue
        for name in row["longs"] + row["shorts"]:
            value = liquidity.get(name, np.nan)
            if not value or math.isnan(value):
                continue
            weight = (0.5 / cfg.k) * cfg.max_leverage
            limits.append(cfg.max_adv_share * float(value) / weight)
    return float(min(limits)) if limits else None


def performance(returns: pd.Series, periods_per_year: float = 365.0) -> dict:
    """Annualised performance summary of a per-period net return series."""
    values = returns.dropna()
    if values.empty:
        return {"periods": 0}
    equity = (1.0 + values).cumprod()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    periods = len(values)
    years = periods / periods_per_year
    ann_return = float(equity.iloc[-1] ** (1 / years) - 1) if years > 0 and equity.iloc[-1] > 0 else float("nan")
    ann_vol = float(values.std() * math.sqrt(periods_per_year))
    sharpe = float(values.mean() / values.std() * math.sqrt(periods_per_year)) if values.std() else float("nan")
    return {
        "periods": periods,
        "total_return": float(equity.iloc[-1] - 1.0),
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "calmar": float(ann_return / abs(drawdown.min())) if drawdown.min() < 0 else float("nan"),
        "hit_rate": float((values > 0).mean()),
        "mean_period": float(values.mean()),
    }


def buy_and_hold(close: pd.DataFrame, name: str, periods_per_year: float = 365.0) -> dict:
    """Buy-and-hold benchmark for a single column (e.g. BTC or SPY perp)."""
    series = close[name].dropna() if name in close.columns else pd.Series(dtype="float64")
    if series.empty:
        return {"periods": 0}
    returns = series.pct_change().dropna()
    daily = returns.iloc[::24] if len(returns) > 24 else returns
    return performance(daily, periods_per_year / 24 if len(returns) > 24 else periods_per_year)
