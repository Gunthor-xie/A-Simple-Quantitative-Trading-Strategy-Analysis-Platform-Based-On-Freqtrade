from __future__ import annotations

import pytest

from app.schemas import BacktestResult, ScoreWeights
from app.services.scoring import DEFAULT_BASELINES, build_baselines, compute_score


def _result(**overrides) -> BacktestResult:
    data = dict(
        strategy="DemoStrategy",
        total_trades=120,
        win=80,
        loss=40,
        draw=0,
        winrate=0.667,
        profit_total=0.05,
        profit_total_abs=50.0,
        profit_total_percent=5.0,
        profit_factor=1.9,
        expectancy=0.008,
        expectancy_ratio=1.4,
        sharpe=2.1,
        sortino=2.4,
        calmar=3.2,
        max_drawdown_account=0.12,
    )
    data.update(overrides)
    return BacktestResult(**data)


def test_default_weights_sum_to_one() -> None:
    weights = ScoreWeights()
    assert abs(sum(weights.as_dict().values()) - 1.0) < 1e-6


def test_invalid_weights_rejected() -> None:
    with pytest.raises(ValueError):
        ScoreWeights(sharpe=0.5, sortino=0.5)  # 其他默认值使总和 > 1


def test_composite_with_healthy_strategy() -> None:
    report = compute_score(_result(), ScoreWeights())
    assert 50 <= report.composite <= 100
    assert report.baseline_source == "default"
    assert len(report.metrics) == 7


def test_zero_trades_warns_and_scores_low() -> None:
    report = compute_score(_result(total_trades=0, win=0, loss=0, winrate=0), ScoreWeights())
    assert any("无成交记录" in w for w in report.warnings)
    assert report.composite == 0.0


def test_sortino_undefined_when_no_losses() -> None:
    report = compute_score(_result(sortino=None, loss=0), ScoreWeights())
    sortino_metric = next(m for m in report.metrics if m.name == "sortino")
    assert sortino_metric.missing
    assert sortino_metric.score == 0.0
    assert any("Sortino" in w for w in report.warnings)


def test_negative_sharpe_scores_zero() -> None:
    report = compute_score(_result(sharpe=-0.5), ScoreWeights())
    sharpe_metric = next(m for m in report.metrics if m.name == "sharpe")
    assert sharpe_metric.score == 0.0
    assert sharpe_metric.note


def test_drawdown_direction_lower_is_better() -> None:
    good = compute_score(_result(max_drawdown_account=0.02), ScoreWeights())
    bad = compute_score(_result(max_drawdown_account=0.9), ScoreWeights())
    good_dd = next(m for m in good.metrics if m.name == "max_drawdown").score
    bad_dd = next(m for m in bad.metrics if m.name == "max_drawdown").score
    assert good_dd > bad_dd


def test_history_baselines_override_defaults() -> None:
    baselines, source = build_baselines({"sharpe": 3.0})
    assert source == "history-best"
    assert baselines["sharpe"] == 3.0
    assert baselines["winrate"] == DEFAULT_BASELINES["winrate"]


def test_nan_metric_treated_as_missing() -> None:
    report = compute_score(_result(calmar=float("nan")), ScoreWeights())
    calmar_metric = next(m for m in report.metrics if m.name == "calmar")
    assert calmar_metric.missing
