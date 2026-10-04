from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from ..schemas import BacktestResult, PairResult, TagResult


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _s(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def parse_backtest_file(path: str | Path) -> BacktestResult:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"回测结果文件不存在: {path}")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if name.endswith(".json") and not name.endswith("_config.json")
            ]
            if not candidates:
                raise ValueError(f"回测归档中未找到结果 JSON: {path}")
            name = sorted(candidates, key=len)[0]
            with archive.open(name) as fh:
                data = json.load(fh)
    else:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    return parse_backtest_dict(data)


def parse_backtest_dict(data: dict[str, Any]) -> BacktestResult:
    """Parse a freqtrade backtest JSON export into a normalized result.

    Tolerates both current exports and older releases (missing fields fall back
    to defaults instead of raising).
    """
    # 2025.x archives nest the full result under {"strategy": {name: {...}}}.
    if isinstance(data.get("strategy"), dict):
        strategy_name = next(iter(data["strategy"]), "")
        inner = data["strategy"][strategy_name] if strategy_name else {}
        merged: dict[str, Any] = dict(inner)
        merged["strategy"] = inner.get("strategy_name") or strategy_name
        for new_key, old_key in (("win", "wins"), ("loss", "losses"), ("draw", "draws")):
            if merged.get(old_key) is not None:
                merged[new_key] = merged[old_key]
        comparison = (data.get("strategy_comparison") or [{}])[0]
        if isinstance(comparison, dict):
            for key in (
                "duration_avg", "expectancy",
                "expectancy_ratio", "sortino", "sharpe", "calmar",
                "profit_factor", "winrate", "max_drawdown_account",
                "max_drawdown_abs", "timerange", "backtest_start",
                "backtest_end", "backtest_days",
            ):
                merged.setdefault(key, comparison.get(key))
            if merged.get("profit_total_percent") is None:
                merged["profit_total_percent"] = comparison.get("profit_total_pct")
        if merged.get("profit_total_percent") is None and merged.get("profit_total_pct") is not None:
            merged["profit_total_percent"] = merged["profit_total_pct"]
        data = merged

    total_trades = _i(data.get("total_trades"))
    win = _i(data.get("win"))
    loss = _i(data.get("loss"))
    draw = _i(data.get("draw"))
    if not total_trades and data.get("strategy_comparison"):
        first = data["strategy_comparison"][0] if isinstance(data["strategy_comparison"], list) else {}
        total_trades = _i(first.get("total_trades"), _i(data.get("trade_count")))
        win = _i(first.get("win"))
        loss = _i(first.get("loss"))
        draw = _i(first.get("draw"))

    strategy = _s(data.get("strategy"), _s(data.get("strategy_name"), ""))

    def tag_items(key: str) -> list[TagResult]:
        items: list[TagResult] = []
        for entry in data.get(key, []) or []:
            if not isinstance(entry, dict):
                continue
            items.append(
                TagResult(
                    key=_s(entry.get("key"), _s(entry.get("enter_tag"), _s(entry.get("exit_reason")))),
                    trades=_i(entry.get("trades"), _i(entry.get("count"))),
                    profit_total_pct=_f(entry.get("profit_total_pct")),
                    profit_total_abs=_f(entry.get("profit_total_abs")),
                )
            )
        return items

    pairs: list[PairResult] = []
    for entry in data.get("results_per_pair", []) or []:
        if not isinstance(entry, dict):
            continue
        pairs.append(
            PairResult(
                pair=_s(entry.get("pair") or entry.get("key")),
                trades=_i(entry.get("trades")),
                avg_profit_pct=_f(entry.get("avg_profit_pct")),
                total_profit_abs=_f(entry.get("total_profit_abs")),
                total_profit_pct=_f(entry.get("total_profit_pct")),
                avg_duration=_s(entry.get("avg_duration")),
                win=_i(entry.get("win")),
                draw=_i(entry.get("draw")),
                loss=_i(entry.get("loss")),
                win_pct=_f(entry.get("win_pct")),
            )
        )

    trades = data.get("trades", []) or []
    if isinstance(trades, dict):
        trades = trades.get("trades", []) or []
    trades = [t for t in trades if isinstance(t, dict)]

    return BacktestResult(
        strategy=strategy,
        timerange=_s(data.get("timerange")),
        backtest_start=_s(data.get("backtest_start")),
        backtest_end=_s(data.get("backtest_end")),
        backtest_days=_i(data.get("backtest_days")),
        total_trades=total_trades,
        trade_count_long=_i(data.get("trade_count_long")),
        trade_count_short=_i(data.get("trade_count_short")),
        win=win,
        draw=draw,
        loss=loss,
        winrate=_f(data.get("winrate")),
        profit_total=_f(data.get("profit_total")),
        profit_total_abs=_f(data.get("profit_total_abs")),
        profit_total_percent=_f(data.get("profit_total_percent")),
        profit_factor=data.get("profit_factor") if data.get("profit_factor") is not None else None,
        expectancy=_f(data.get("expectancy")),
        expectancy_ratio=_f(data.get("expectancy_ratio")),
        sharpe=data.get("sharpe") if data.get("sharpe") is not None else None,
        sortino=data.get("sortino") if data.get("sortino") is not None else None,
        calmar=data.get("calmar") if data.get("calmar") is not None else None,
        max_drawdown_account=_f(data.get("max_drawdown_account")),
        max_drawdown_abs=_f(data.get("max_drawdown_abs")),
        duration_avg=_s(data.get("duration_avg")),
        market_change=_f(data.get("market_change")),
        results_per_pair=pairs,
        results_per_enter_tag=tag_items("results_per_enter_tag"),
        results_per_exit_reason=tag_items("results_per_exit_reason"),
        trades=trades,
    )


def list_result_files(directory: str | Path) -> list[Path]:
    directory = Path(directory)
    if not directory.exists():
        return []
    files = []
    for path in sorted(directory.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        files.append(path)
    return files
