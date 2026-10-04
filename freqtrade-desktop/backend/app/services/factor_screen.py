"""Factor screening engine (ticket 04).

Implements the protocol in ``.scratch/factor-screening/spec.md`` section 7:
walk-forward windows, RankIC with Newey-West t-statistics, quantile spreads,
turnover, an explicit cost model and Benjamini-Hochberg FDR across the factor grid.

Design notes:
  * Observations are **non-overlapping**: for a 1-day horizon on an hourly panel the
    series is sampled every 24 bars, so the t-statistics are not inflated by overlap.
  * A factor's ``direction`` is applied before evaluation, so a positive IC always
    means "the factor behaved as economically expected".
  * Costs are charged at the evaluation frequency, not retro-fitted afterwards.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .factor_lib import FACTORS

TIMEFRAME_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "1d": 86_400_000,
}


@dataclass
class ScreenConfig:
    horizon_bars: int = 24          # forward-return horizon = rebalance frequency
    quantiles: int = 5
    fee_bps: float = 5.0            # 0.05% per side (OKX taker)
    slippage_bps: float = 2.0
    train_obs: int = 40             # 8 weeks of daily observations
    test_obs: int = 10              # 2 weeks of daily observations
    nw_lag: int = 5
    min_pairs: int = 5
    min_coverage: float = 0.3       # required share of evaluable observations
    positive_window_frac: float = 0.70
    t_threshold: float = 2.0
    fdr_q: float = 0.10
    max_drawdown: float = 0.20

    @property
    def round_trip_cost(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 1e4


def forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Forward simple return over ``horizon`` bars (explicitly look-ahead, by design)."""
    return close.shift(-horizon) / close - 1.0


def subsample(frame: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Keep non-overlapping observations for a given horizon."""
    return frame.iloc[::horizon]


def thin(series: pd.Series, horizon: int) -> pd.Series:
    """Thin a series of valid observations to a non-overlapping cadence."""
    return series.iloc[::horizon]


def on_grid(series: pd.Series, full_index: pd.Index, horizon: int) -> pd.Series:
    """Keep only observations that fall on the rebalance grid (time-based thinning).

    Time-based (not rank-based) thinning matters for sparse factors such as a weekly
    weekend-gap signal: sampling every ``horizon``-th *observation* would stretch it
    to a monthly cadence.
    """
    grid = full_index[::horizon]
    return series[series.index.isin(grid)]


def rank_ic(factor: pd.DataFrame, fwd: pd.DataFrame, min_pairs: int) -> pd.Series:
    """Per-timestamp Spearman correlation between factor and forward return."""
    common = factor.index.intersection(fwd.index)
    a, b = factor.loc[common], fwd.loc[common]
    enough = ((a.notna() & b.notna()).sum(axis=1) >= min_pairs).to_numpy()
    ic = a.rank(axis=1).corrwith(b.rank(axis=1), axis=1)
    ic = ic.where(enough)
    return ic.dropna()


def newey_west_t(series: pd.Series, lag: int) -> tuple[float, float]:
    """Newey-West corrected t-statistic and two-sided p-value for the mean."""
    values = series.dropna().to_numpy(dtype="float64")
    n = len(values)
    if n < 3:
        return float("nan"), float("nan")
    demeaned = values - values.mean()
    gamma0 = float(demeaned @ demeaned) / n
    variance = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1)
        gamma = float(demeaned[k:] @ demeaned[:-k]) / n
        variance += 2.0 * weight * gamma
    variance = max(variance, 1e-18)
    t_stat = float(values.mean() / math.sqrt(variance / n))
    p_value = math.erfc(abs(t_stat) / math.sqrt(2.0))
    return t_stat, p_value


def quantile_series(factor: pd.DataFrame, fwd: pd.DataFrame, quantiles: int,
                    min_pairs: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (top leg, bottom leg, universe) mean forward returns per timestamp."""
    common = factor.index.intersection(fwd.index)
    a, b = factor.loc[common], fwd.loc[common]
    enough = ((a.notna() & b.notna()).sum(axis=1) >= min_pairs).to_numpy()
    rank = a.rank(axis=1, pct=True)
    bucket = np.ceil(rank * quantiles)
    top = b.where(bucket == quantiles).mean(axis=1)
    bottom = b.where(bucket == 1).mean(axis=1)
    universe = b.mean(axis=1)
    return top.where(enough), bottom.where(enough), universe.where(enough)


def leg_turnover(membership: pd.DataFrame) -> float:
    """One-sided turnover of a leg (fraction of names replaced per rebalance)."""
    flags = membership.fillna(False).to_numpy(dtype=bool)
    if flags.shape[0] < 2:
        return float("nan")
    changed = np.logical_xor(flags[1:], flags[:-1]).sum(axis=1)
    size = flags[1:].sum(axis=1)
    valid = size > 0
    if not valid.any():
        return float("nan")
    return float((changed[valid] / size[valid]).mean())


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    peak = equity.cummax()
    return float((equity / peak - 1.0).min())


def walk_forward_windows(count: int, cfg: ScreenConfig) -> list[tuple[int, int]]:
    """Rolling test windows over an out-of-sample (already trained) series."""
    windows: list[tuple[int, int]] = []
    start = 0
    while start + cfg.test_obs <= count:
        windows.append((start, start + cfg.test_obs))
        start += cfg.test_obs
    return windows


def bh_fdr(p_values: dict[str, float]) -> dict[str, float]:
    """Benjamini-Hochberg q-values."""
    items = [(name, p) for name, p in p_values.items()
             if p is not None and not math.isnan(p)]
    if not items:
        return {}
    items.sort(key=lambda item: item[1])
    total = len(items)
    q_values: dict[str, float] = {}
    previous = 1.0
    for rank, (name, p) in reversed(list(enumerate(items, start=1))):
        q = min(previous, p * total / rank)
        q_values[name] = float(q)
        previous = q
    return q_values


def evaluate_factor(
    name: str,
    factor: pd.DataFrame,
    close: pd.DataFrame,
    cfg: ScreenConfig,
    *,
    direction: int = 1,
) -> dict:
    """Walk-forward screening record for one factor at the primary horizon.

    Protocol (spec section 7): orientation is estimated on the first ``train_obs``
    observations only, and every reported statistic is computed on the remaining
    out-of-sample observations. A factor whose economic prior points the wrong way
    is therefore *orientable*, not automatically wrong — but the orientation is
    never fitted on the data it is scored on.
    """
    fwd = forward_returns(close, cfg.horizon_bars)
    grid_size = max(1, len(close.index[::cfg.horizon_bars]))

    raw_ic = on_grid(rank_ic(factor, fwd, cfg.min_pairs).dropna(),
                     close.index, cfg.horizon_bars)
    orientation = int(direction)
    train = raw_ic.iloc[: cfg.train_obs]
    if len(train) >= 5:
        train_mean = float(train.mean())
        if not math.isnan(train_mean) and train_mean != 0.0:
            orientation = 1 if train_mean > 0 else -1
    signed = factor * orientation

    ic_oos = on_grid(rank_ic(signed, fwd, cfg.min_pairs).dropna(),
                     close.index, cfg.horizon_bars).iloc[cfg.train_obs:]
    top, bottom, universe = quantile_series(signed, fwd, cfg.quantiles, cfg.min_pairs)
    spread = on_grid((top - bottom).dropna(), close.index, cfg.horizon_bars).reindex(ic_oos.index)
    top_daily = on_grid(top.dropna(), close.index, cfg.horizon_bars).reindex(ic_oos.index)
    universe_daily = on_grid(universe.dropna(), close.index, cfg.horizon_bars).reindex(ic_oos.index)

    rank = signed.rank(axis=1, pct=True)
    long_leg = (rank > 1 - 1 / cfg.quantiles) & signed.notna()
    short_leg = (rank < 1 / cfg.quantiles) & signed.notna()
    valid_index = spread.dropna().index
    turnover_long = leg_turnover(long_leg.loc[valid_index]) if len(valid_index) else float("nan")
    turnover_short = leg_turnover(short_leg.loc[valid_index]) if len(valid_index) else float("nan")
    turnover = float(np.nansum([turnover_long, turnover_short]))
    cost_per_rebalance = cfg.round_trip_cost * (0.0 if math.isnan(turnover) else turnover)
    net_spread = spread.dropna() - cost_per_rebalance

    t_stat, p_value = newey_west_t(ic_oos, cfg.nw_lag)
    decay: dict[int, float] = {}
    for horizon in (1, 4, cfg.horizon_bars, 7 * cfg.horizon_bars):
        decay_ic = on_grid(
            rank_ic(signed, forward_returns(close, horizon), cfg.min_pairs).dropna(),
            close.index, horizon).iloc[cfg.train_obs:]
        decay[horizon] = float(decay_ic.mean()) if len(decay_ic) else float("nan")

    windows = walk_forward_windows(len(ic_oos), cfg)
    window_results: list[dict] = []
    for start, end in windows:
        window_ic = ic_oos.iloc[start:end]
        window_net = net_spread.iloc[start:end]
        window_results.append({
            "start": int(window_ic.index[0]) if len(window_ic) else None,
            "end": int(window_ic.index[-1]) if len(window_ic) else None,
            "ic": float(window_ic.mean()) if len(window_ic) else float("nan"),
            "net": float(window_net.mean()) if len(window_net) else float("nan"),
        })
    usable = [w for w in window_results if not math.isnan(w["net"])]
    positive_frac = (sum(1 for w in usable if w["net"] > 0) / len(usable)) if usable else float("nan")

    return {
        "factor": name,
        "family": FACTORS[name].family if name in FACTORS else "",
        "prior_direction": int(direction),
        "orientation": orientation,
        "coverage": float(len(ic_oos) / max(1, grid_size - cfg.train_obs)),
        "n_obs": int(len(ic_oos)),
        "ic_mean": float(ic_oos.mean()) if len(ic_oos) else float("nan"),
        "ic_ir": float(ic_oos.mean() / ic_oos.std()) if len(ic_oos) and ic_oos.std() else float("nan"),
        "ic_t_nw": t_stat,
        "ic_p": p_value,
        "ic_decay": {int(k): v for k, v in decay.items()},
        "spread_gross": float(spread.mean()) if len(spread) else float("nan"),
        "spread_net": float(net_spread.mean()) if len(net_spread) else float("nan"),
        "spread_net_bps": float(net_spread.mean() * 1e4) if len(net_spread) else float("nan"),
        "top_mean": float(top_daily.mean()) if len(top_daily) else float("nan"),
        "universe_mean": float(universe_daily.mean()) if len(universe_daily) else float("nan"),
        "turnover_long": turnover_long,
        "turnover_short": turnover_short,
        "turnover": turnover,
        "cost_per_rebalance": cost_per_rebalance,
        "max_drawdown": max_drawdown(net_spread) if len(net_spread) else float("nan"),
        "window_count": len(window_results),
        "window_positive_frac": positive_frac,
        "windows": window_results,
        "net_series": net_spread,
    }


def verdict(record: dict, q_value: float | None, cfg: ScreenConfig) -> tuple[str, list[str]]:
    """Apply the four-gate acceptance rule from the spec."""
    reasons: list[str] = []
    positive_frac = record["window_positive_frac"]
    if not positive_frac or math.isnan(positive_frac) or positive_frac < cfg.positive_window_frac:
        shown = "无" if not positive_frac or math.isnan(positive_frac) else f"{positive_frac:.2f}"
        reasons.append(f"OOS 窗口正期望占比 {shown} < {cfg.positive_window_frac}")
    t_stat = record["ic_t_nw"]
    if not t_stat or math.isnan(t_stat) or abs(t_stat) <= cfg.t_threshold:
        shown = "缺失" if not t_stat or math.isnan(t_stat) else f"{t_stat:.2f}"
        reasons.append(f"OOS IC |t| {shown} ≤ {cfg.t_threshold}")
    if q_value is None or q_value >= cfg.fdr_q:
        shown = "缺失" if q_value is None else f"{q_value:.3f}"
        reasons.append(f"FDR q {shown} ≥ {cfg.fdr_q}")
    drawdown = record["max_drawdown"]
    if not drawdown or math.isnan(drawdown) or drawdown <= -cfg.max_drawdown:
        shown = "缺失" if not drawdown or math.isnan(drawdown) else f"{drawdown:.1%}"
        reasons.append(f"回撤 {shown} 超过 {cfg.max_drawdown:.0%}")
    return ("promising" if not reasons else "rejected"), reasons


def screen_all(
    factors: dict[str, pd.DataFrame],
    close: pd.DataFrame,
    cfg: ScreenConfig | None = None,
) -> dict:
    """Evaluate every factor, apply FDR across the grid, and return ranked results."""
    cfg = cfg or ScreenConfig()
    records: dict[str, dict] = {}
    p_values: dict[str, float] = {}
    for name, values in factors.items():
        direction = FACTORS[name].direction if name in FACTORS else 1
        record = evaluate_factor(name, values, close, cfg, direction=direction)
        if record["coverage"] < cfg.min_coverage or record["n_obs"] < cfg.test_obs:
            record["verdict"] = "rejected"
            record["fdr_q"] = None
            record["reasons"] = [
                f"样本不足（OOS 覆盖率 {record['coverage']:.2f}，观测 {record['n_obs']}）"
            ]
        else:
            p_values[name] = record["ic_p"]
        records[name] = record

    q_values = bh_fdr(p_values)
    for name, record in records.items():
        if name in p_values:
            state, reasons = verdict(record, q_values.get(name), cfg)
            record["verdict"] = state
            record["reasons"] = reasons
            record["fdr_q"] = q_values.get(name)

    ordered = dict(sorted(records.items(),
                          key=lambda item: -_finite(item[1].get("spread_net_bps"))))
    promising = [name for name, record in ordered.items() if record["verdict"] == "promising"]
    return {
        "config": {
            "horizon_bars": cfg.horizon_bars, "quantiles": cfg.quantiles,
            "fee_bps": cfg.fee_bps, "slippage_bps": cfg.slippage_bps,
            "train_obs": cfg.train_obs, "test_obs": cfg.test_obs,
            "min_pairs": cfg.min_pairs, "fdr_q": cfg.fdr_q,
        },
        "trials": len(records),
        "promising": promising,
        "results": {name: {k: v for k, v in record.items() if k != "net_series"}
                    for name, record in ordered.items()},
        "net_series": {name: record["net_series"] for name, record in ordered.items()},
    }


def _finite(value: float | None) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return -1e9
    return float(value)


def factor_correlation(factors: dict[str, pd.DataFrame], min_overlap: int = 5) -> pd.DataFrame:
    """Cross-sectional rank correlation between factors, averaged over timestamps."""
    names = [name for name, values in factors.items() if values.notna().to_numpy().any()]
    matrix = pd.DataFrame(np.eye(len(names)), index=names, columns=names)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            a, b = factors[left], factors[right]
            common = a.index.intersection(b.index)
            enough = ((a.loc[common].notna() & b.loc[common].notna()).sum(axis=1)
                      >= min_overlap).to_numpy()
            corr = a.loc[common].rank(axis=1).corrwith(b.loc[common].rank(axis=1), axis=1)
            value = float(corr.where(enough).mean()) if enough.any() else float("nan")
            matrix.loc[left, right] = matrix.loc[right, left] = value
    return matrix


def cluster_factors(correlation: pd.DataFrame, threshold: float = 0.7) -> list[list[str]]:
    """Greedy grouping of factors whose |correlation| exceeds ``threshold``."""
    remaining = list(correlation.index)
    clusters: list[list[str]] = []
    while remaining:
        head = remaining.pop(0)
        group = [head]
        for other in list(remaining):
            value = correlation.loc[head, other]
            if not math.isnan(value) and abs(value) > threshold:
                group.append(other)
                remaining.remove(other)
        clusters.append(group)
    return clusters


def deflated_sharpe(returns: pd.Series, n_trials: int) -> float:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado), normal-skew approximation."""
    values = returns.dropna().to_numpy(dtype="float64")
    if len(values) < 10 or n_trials < 1:
        return float("nan")
    mean, std = float(values.mean()), float(values.std(ddof=1))
    if std == 0:
        return float("nan")
    sharpe = mean / std
    skew = float(((values - mean) ** 3).mean() / std ** 3)
    kurt = float(((values - mean) ** 4).mean() / std ** 4)
    euler = 0.5772156649
    expected_max = ((1 - euler) * _norm_ppf(1 - 1 / n_trials)
                    + euler * _norm_ppf(1 - 1 / (n_trials * math.e)))
    denominator = math.sqrt(max(1e-12, 1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2))
    return float((sharpe - expected_max / math.sqrt(len(values)))
                 * math.sqrt(len(values)) / denominator)


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation)."""
    if not 0.0 < p < 1.0:
        return float("nan")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
