from __future__ import annotations

import json

from app.services.parser import parse_backtest_dict


def _sample_export() -> dict:
    return {
        "strategy": "SampleStrategy",
        "timerange": "20240101-20240301",
        "backtest_start": "2024-01-01 00:00:00",
        "backtest_end": "2024-03-01 00:00:00",
        "backtest_days": 60,
        "total_trades": 42,
        "trade_count_long": 30,
        "trade_count_short": 12,
        "win": 28,
        "draw": 0,
        "loss": 14,
        "winrate": 0.6667,
        "profit_total": 0.0234,
        "profit_total_abs": 23.4,
        "profit_total_percent": 2.34,
        "profit_factor": 1.55,
        "expectancy": 0.0042,
        "expectancy_ratio": 0.9,
        "sharpe": 1.8,
        "sortino": 2.1,
        "calmar": 5.4,
        "max_drawdown_account": 0.083,
        "max_drawdown_abs": 8.3,
        "duration_avg": "6:30:00",
        "market_change": 0.12,
        "results_per_pair": [
            {
                "pair": "BTC/USDT:USDT",
                "trades": 42,
                "avg_profit_pct": 0.56,
                "total_profit_abs": 23.4,
                "total_profit_pct": 2.34,
                "avg_duration": "6:30:00",
                "win": 28,
                "draw": 0,
                "loss": 14,
                "win_pct": 66.7,
            }
        ],
        "results_per_enter_tag": [
            {"key": "ma_cross", "trades": 42, "profit_total_pct": 2.34, "profit_total_abs": 23.4}
        ],
        "results_per_exit_reason": [
            {"key": "roi", "trades": 30, "profit_total_pct": 2.0, "profit_total_abs": 20.0}
        ],
        "trades": [
            {
                "pair": "BTC/USDT:USDT",
                "open_date": "2024-01-02 00:00:00",
                "close_date": "2024-01-03 00:00:00",
                "open_rate": 40000.0,
                "close_rate": 41000.0,
                "profit_ratio": 0.02,
                "profit_abs": 20.0,
                "enter_reason": "ma_cross",
                "exit_reason": "roi",
                "is_short": False,
            }
        ],
    }


def test_parse_full_export() -> None:
    result = parse_backtest_dict(_sample_export())
    assert result.strategy == "SampleStrategy"
    assert result.total_trades == 42
    assert result.sharpe == 1.8
    assert result.profit_factor == 1.55
    assert len(result.results_per_pair) == 1
    assert len(result.trades) == 1
    assert result.trades[0]["enter_reason"] == "ma_cross"


def test_parse_old_format_falls_back_to_comparison() -> None:
    data = {
        "strategy": "Old",
        "strategy_comparison": [
            {"total_trades": 10, "win": 6, "loss": 4, "draw": 0, "winrate": 0.6}
        ],
    }
    result = parse_backtest_dict(data)
    assert result.total_trades == 10
    assert result.win == 6
    assert result.loss == 4
    assert result.sharpe is None


def test_parse_missing_keys_uses_defaults() -> None:
    result = parse_backtest_dict({"strategy": "Bare"})
    assert result.total_trades == 0
    assert result.results_per_pair == []
    assert result.winrate == 0.0


def test_parse_trades_dict_wrapper() -> None:
    data = {"strategy": "Wrapped", "trades": {"trades": [{"pair": "ETH/USDT", "open_date": "x"}]}}
    result = parse_backtest_dict(data)
    assert len(result.trades) == 1


def test_json_roundtrip(tmp_path) -> None:
    path = tmp_path / "SampleStrategy.json"
    path.write_text(json.dumps(_sample_export()), encoding="utf-8")
    from app.services.parser import parse_backtest_file

    result = parse_backtest_file(path)
    assert result.total_trades == 42
