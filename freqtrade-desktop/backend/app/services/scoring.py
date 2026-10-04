from __future__ import annotations

from typing import Any

from ..schemas import BacktestResult, MetricScore, ScoreReport, ScoreWeights


METRIC_LABELS = {
    "sharpe": "Sharpe",
    "sortino": "Sortino",
    "calmar": "Calmar",
    "profit_factor": "利润因子",
    "winrate": "胜率",
    "max_drawdown": "最大回撤",
    "expectancy": "期望",
}

# Fallback baselines used when the strategy has no historical best to compare against.
DEFAULT_BASELINES: dict[str, float] = {
    "sharpe": 1.0,
    "sortino": 1.0,
    "calmar": 1.0,
    "profit_factor": 1.5,
    "winrate": 0.5,
    "max_drawdown": 0.20,
    "expectancy": 0.01,
}

HIGHER_IS_BETTER = ("sharpe", "sortino", "calmar", "profit_factor", "winrate", "expectancy")
LOWER_IS_BETTER = ("max_drawdown",)


def _is_valid(value: Any) -> bool:
    if value is None:
        return False
    try:
        return float(value) == float(value)  # NaN check
    except (TypeError, ValueError):
        return False


def compute_score(
    result: BacktestResult,
    weights: ScoreWeights,
    baselines: dict[str, float] | None = None,
    baseline_source: str = "default",
) -> ScoreReport:
    baselines = baselines or {}
    warnings: list[str] = []

    if result.total_trades <= 0:
        warnings.append("无成交记录，综合评分记为 0（请先确认回测区间与交易对数据）")
        metrics = [
            MetricScore(
                name=name,
                label=METRIC_LABELS.get(name, name),
                value=None,
                baseline=DEFAULT_BASELINES.get(name),
                score=0.0,
                weight=weights.as_dict()[name],
                missing=True,
                note="无成交",
            )
            for name in weights.as_dict()
        ]
        return ScoreReport(composite=0.0, metrics=metrics, baseline_source=baseline_source, warnings=warnings)

    if result.total_trades < 30:
        warnings.append(f"交易样本不足（{result.total_trades} < 30），综合评分仅供参考")
    if result.sortino is None and result.loss == 0 and result.total_trades > 0:
        warnings.append("无亏损交易，Sortino 未定义，按 0 分计")
    if result.winrate == 0 and result.total_trades > 0:
        warnings.append("胜率为 0，策略可能无交易或全亏")

    weights_map = weights.as_dict()
    metrics: list[MetricScore] = []
    weighted_sum = 0.0

    for name in weights_map:
        value = getattr(result, name, None)
        if name == "max_drawdown":
            value = result.max_drawdown_account
        weight = weights_map[name]
        label = METRIC_LABELS.get(name, name)

        if not _is_valid(value):
            metrics.append(
                MetricScore(
                    name=name, label=label, value=None,
                    baseline=baselines.get(name) if baselines.get(name) is not None else DEFAULT_BASELINES.get(name),
                    score=0.0, weight=weight, missing=True,
                    note="指标缺失或不可计算，按 0 分计",
                )
            )
            continue

        value_f = float(value)
        baseline = baselines.get(name, DEFAULT_BASELINES.get(name, 1.0))
        if baseline is None or baseline == 0 or baseline != baseline:
            baseline = DEFAULT_BASELINES.get(name, 1.0)

        if name in LOWER_IS_BETTER:
            raw = 1.0 - min(abs(value_f) / abs(float(baseline)), 1.0) if float(baseline) else 0.0
            note = None
        else:
            if value_f <= 0:
                raw = 0.0
                note = "数值 ≤ 0，按 0 分计"
            else:
                raw = min(value_f / float(baseline), 2.0)
                note = None
        score = max(0.0, min(raw, 1.0))
        metrics.append(
            MetricScore(
                name=name, label=label, value=round(value_f, 4),
                baseline=round(float(baseline), 4), score=round(score, 4),
                weight=weight, missing=False, note=note,
            )
        )
        weighted_sum += weight * score

    composite = round(min(max(weighted_sum, 0.0), 1.0) * 100, 1)
    return ScoreReport(
        composite=composite,
        metrics=metrics,
        baseline_source=baseline_source,
        warnings=warnings,
    )


def build_baselines(history: dict[str, float] | None) -> tuple[dict[str, float], str]:
    """Merge historical bests (if any) over built-in defaults."""
    if not history:
        return dict(DEFAULT_BASELINES), "default"
    merged: dict[str, float] = {}
    for key, default in DEFAULT_BASELINES.items():
        merged[key] = history.get(key, default)
    return merged, "history-best"
