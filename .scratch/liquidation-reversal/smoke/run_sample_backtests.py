"""Run a LiquidationCascade parameter sweep on a sample window and collect results.

Writes ``user_data/strategies/LiquidationCascade.json`` for each parameter set
(freqtrade's standard parameter-file mechanism), runs the real backtester through
``backend/scripts/freqtrade_offline.py``, then reads the exported result zip and
prints a comparison table - the numbers needed to decide whether the strategy is
worth refining.

Usage (from the repository root):

    python .scratch/liquidation-reversal/smoke/run_sample_backtests.py \
        --window 20260301-20260901

The parameter file is deleted afterwards unless ``--keep-params`` is given, so a
swept set never silently becomes the strategy's permanent configuration.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DESKTOP = ROOT / "freqtrade-desktop"
BACKEND = DESKTOP / "backend"
USER_DATA = DESKTOP / "user_data"
STRATEGY = "LiquidationCascade"
PARAM_FILE = USER_DATA / "strategies" / f"{STRATEGY}.json"
RESULTS_DIR = ROOT / ".scratch" / "liquidation-reversal" / "results"


def buy(move_pct: float, atr_mult: float, flush: float, depth: float, taker: float,
        liquidity: float = 0.0, side: str = "both", offset: float = 0.0005,
        valid_minutes: int = 2, min_atr: float = 0.0006, direction: str = "fade") -> dict:
    return {
        "move_pct": move_pct,
        "move_atr_mult": atr_mult,
        "flush_score_min": flush,
        "depth_delta_min": depth,
        "taker_delta_min": taker,
        "liquidity_pct_min": liquidity,
        "trade_side": side,
        "entry_offset_pct": offset,
        "entry_valid_minutes": valid_minutes,
        "min_atr_pct": min_atr,
        "entry_direction": direction,
    }


# name -> params (buy + optional stoploss/roi overrides, margin ratios)
SETS: dict[str, dict] = {
    "00-baseline": {},
    "01-loose": {"buy": buy(0.0010, 2.0, 1.0, -0.05, -0.10)},
    "02-medium": {"buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00)},
    "03-strict": {"buy": buy(0.0020, 3.0, 2.0, 0.05, 0.10)},
    "04-move-only": {"buy": buy(0.0015, 1.0, 0.5, -0.20, -0.20)},
    "05-breakout-only": {"buy": buy(0.0015, 2.5, 1.0, -0.20, -0.20)},
    "06-liquid": {"buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, liquidity=0.25)},
    "07-tight-stop": {"buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00), "stoploss": {"stoploss": -0.0125}},
    "08-wide-stop": {"buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00), "stoploss": {"stoploss": -0.025}},
    "09-fast-target": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00),
        "roi": {"0": 0.015},
        "sell": {"max_holding_minutes": 6},
    },
    # --- diagnostics: is the raw signal any good, or do costs kill it? ---
    "10-hold-only": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00),
        "roi": {"0": 0.5},               # no practical target
        "stoploss": {"stoploss": -0.5},  # no practical stop
        "sell": {"max_holding_minutes": 15, "exit_on_flow_flip": False},
    },
    "11-long-only": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="long"),
        "sell": {"exit_on_flow_flip": False},
    },
    "12-short-only": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="short"),
        "sell": {"exit_on_flow_flip": False},
    },
    "13-strict-no-flip": {
        "buy": buy(0.0020, 3.0, 2.0, 0.05, 0.10),
        "sell": {"exit_on_flow_flip": False},
    },
    # --- round 4: cost-aware redesign (maker entry, bigger target, longer hold) ---
    "20-target06-hold30": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00),
        "roi": {"0": 0.030},           # 0.6% price target
        "stoploss": {"stoploss": -0.015},  # 0.3% price stop
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "21-target06-hold30-short": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="short"),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "22-target06-hold30-long": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="long"),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "23-target06-hold60": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 60, "exit_on_flow_flip": False},
    },
    "24-target08-hold60-stop04": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00),
        "roi": {"0": 0.040},           # 0.8% price target
        "stoploss": {"stoploss": -0.020},  # 0.4% price stop
        "sell": {"max_holding_minutes": 60, "exit_on_flow_flip": False},
    },
    "25-atr-gate-high": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, min_atr=0.0010),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "26-offset-deep": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0010),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "27-strict-target06-hold45": {
        "buy": buy(0.0020, 3.0, 2.0, 0.05, 0.10, min_atr=0.0008),
        "roi": {"0": 0.030},
        "stoploss": {"stoploss": -0.015},
        "sell": {"max_holding_minutes": 45, "exit_on_flow_flip": False},
    },
    # --- round 5: keep the OLD exit profile (0.5% target / 0.35% stop / 10 min),
    #     which had the best gross edge, and add the passive maker entry ---
    "28-short-old-exits-maker": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="short"),
        "roi": {"0": 0.025},
        "stoploss": {"stoploss": -0.0175},
        "sell": {"max_holding_minutes": 10, "exit_on_flow_flip": False},
    },
    "29-short-old-exits-deep-offset": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="short", offset=0.0010),
        "roi": {"0": 0.025},
        "stoploss": {"stoploss": -0.0175},
        "sell": {"max_holding_minutes": 10, "exit_on_flow_flip": False},
    },
    "30-short-old-exits-atr-gate": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, side="short", min_atr=0.0010),
        "roi": {"0": 0.025},
        "stoploss": {"stoploss": -0.0175},
        "sell": {"max_holding_minutes": 10, "exit_on_flow_flip": False},
    },
    # --- round 6: the inverted hypothesis - trade WITH the cascade (continuation) ---
    "31-follow-quick": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0, direction="follow"),
        "roi": {"0": 0.025},
        "stoploss": {"stoploss": -0.0175},
        "sell": {"max_holding_minutes": 10, "exit_on_flow_flip": False},
    },
    "32-follow-wide": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0, direction="follow"),
        "roi": {"0": 0.040},
        "stoploss": {"stoploss": -0.025},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "33-follow-extension": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0005, direction="follow"),
        "roi": {"0": 0.040},
        "stoploss": {"stoploss": -0.025},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "34-follow-short-only": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0, side="short", direction="follow"),
        "roi": {"0": 0.040},
        "stoploss": {"stoploss": -0.025},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "35-follow-long-only": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0, side="long", direction="follow"),
        "roi": {"0": 0.040},
        "stoploss": {"stoploss": -0.025},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
    "36-follow-ext-atr-gate": {
        "buy": buy(0.0015, 2.5, 1.5, 0.00, 0.00, offset=0.0005, min_atr=0.0010,
                   direction="follow"),
        "roi": {"0": 0.040},
        "stoploss": {"stoploss": -0.025},
        "sell": {"max_holding_minutes": 30, "exit_on_flow_flip": False},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="20260301-20260901", help="freqtrade timerange")
    parser.add_argument("--only", default="", help="comma-separated set names")
    parser.add_argument("--keep-params", action="store_true")
    parser.add_argument(
        "--fee-pct",
        type=float,
        default=None,
        help="override the trading fee in PERCENT per side (e.g. 0.035 = maker entry + "
             "taker exit; 0 for a gross-edge run). freqtrade's config takes a ratio, "
             "so this value is divided by 100.",
    )
    parser.add_argument("--timeout", type=int, default=1800)
    return parser.parse_args()


def write_params(params: dict) -> None:
    payload = {
        "strategy_name": STRATEGY,
        "params": params,
        "ft_stratparam_v": 1,
        "export_time": datetime.now(timezone.utc).isoformat(),
    }
    PARAM_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_backtest(window: str, timeout: int, fee_pct: float | None = None) -> str:
    config = USER_DATA / "config.json"
    if fee_pct is not None:
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["fee"] = fee_pct / 100.0
        config = RESULTS_DIR / f"_runconfig_fee{fee_pct}pct.json"
        config.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    command = [
        sys.executable, str(BACKEND / "scripts" / "freqtrade_offline.py"), "backtesting",
        "--userdir", str(USER_DATA),
        "--config", str(config),
        "--strategy", STRATEGY,
        "--timerange", window,
        "--timeframe", "1m",
        "--data-format-ohlcv", "jsongz",
        "--export", "trades",
        "--cache", "none",
    ]
    proc = subprocess.run(
        command, cwd=BACKEND, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return proc.stdout + proc.stderr


def read_result() -> dict:
    pointer = USER_DATA / "backtest_results" / ".last_result.json"
    if not pointer.exists():
        return {}
    archive = USER_DATA / "backtest_results" / json.loads(pointer.read_text())["latest_backtest"]
    with zipfile.ZipFile(archive) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".json") and "config" not in n)
        payload = json.loads(zf.read(name))
    return payload.get("strategy", {}).get(STRATEGY, {})


def summarize(result: dict) -> dict:
    trades = result.get("trades", []) or []
    wins = [t for t in trades if t.get("profit_ratio", 0) > 0]
    losses = [t for t in trades if t.get("profit_ratio", 0) <= 0]
    gross_win = sum(t["profit_abs"] for t in wins) if trades else 0.0
    gross_loss = -sum(t["profit_abs"] for t in losses) if trades else 0.0
    durations = [t.get("trade_duration", 0) for t in trades]
    exits: dict[str, int] = {}
    for trade in trades:
        exits[trade.get("exit_reason", "?")] = exits.get(trade.get("exit_reason", "?"), 0) + 1
    return {
        "trades": result.get("total_trades", 0),
        "long": result.get("trade_count_long", 0),
        "short": result.get("trade_count_short", 0),
        "profit_pct": round(100 * result.get("profit_total", 0.0), 2),
        "profit_abs": round(result.get("profit_total_abs", 0.0), 2),
        "final_balance": round(result.get("final_balance", 0.0), 2),
        "winrate": round(100 * result.get("winrate", 0.0), 1),
        # profit_mean is the average profit ratio per trade (margin terms).
        "avg_profit_pct": round(100 * result.get("profit_mean", 0.0), 3),
        "expectancy_ratio": (
            round(result["expectancy_ratio"], 2)
            if result.get("expectancy_ratio") is not None
            else None
        ),
        "pf": round(result.get("profit_factor", 0.0), 2) if result.get("profit_factor") else None,
        "max_dd_pct": round(100 * result.get("max_drawdown_account", 0.0), 2),
        "max_dd_abs": round(result.get("max_drawdown_abs", 0.0), 2),
        "sharpe": round(result.get("sharpe", 0.0), 2) if result.get("sharpe") is not None else None,
        "sortino": round(result.get("sortino", 0.0), 2) if result.get("sortino") is not None else None,
        "calmar": round(result.get("calmar", 0.0), 2) if result.get("calmar") is not None else None,
        "avg_duration_min": round(sum(durations) / len(durations), 1) if durations else 0.0,
        "market_change": round(100 * result.get("market_change", 0.0), 2),
        "gross_win": round(gross_win, 2),
        "gross_loss": round(gross_loss, 2),
        "exits": exits,
    }


def main() -> int:
    args = parse_args()
    wanted = [name.strip() for name in args.only.split(",") if name.strip()] or list(SETS)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, dict]] = []

    for name in wanted:
        params = SETS[name]
        if params:
            write_params(params)
        elif PARAM_FILE.exists():
            PARAM_FILE.unlink()
        print(f"--- {name}: {json.dumps(params, ensure_ascii=False)}", flush=True)
        output = run_backtest(args.window, args.timeout, args.fee_pct)
        result = read_result()
        if not result:
            print(output[-2000:])
            print(f"    ! no result parsed for {name}")
            continue
        summary = summarize(result)
        executed = [line for line in output.splitlines() if line.startswith("Backtested")]
        rows.append((name, summary))
        print(f"    {executed[0] if executed else ''}")
        print(
            "    trades={trades} (L{long}/S{short}) profit={profit_pct}% "
            "dd={max_dd_pct}% win={winrate}% pf={pf} avg_profit={avg_profit_pct}% "
            "expectancy_ratio={expectancy_ratio} "
            "sharpe={sharpe} avg_min={avg_duration_min} exits={exits}".format(**summary),
            flush=True,
        )

    if not args.keep_params and PARAM_FILE.exists():
        PARAM_FILE.unlink()

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = RESULTS_DIR / f"sample-backtest-{args.window}-{stamp}.md"
    lines = [
        f"# LiquidationCascade 抽样回测（窗口 {args.window}）",
        "",
        f"- 生成时间：{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        "- 数据：OKX BTC/USDT:USDT 1m futures；特征来自 Binance 公共归档（无真实强平流 → 代理分）",
        "- 成本：交易所默认档位手续费，未建模滑点",
        "",
        "| 参数组 | 交易数 | 多/空 | 收益% | 期末权益 | 最大回撤% | 胜率% | PF | 单笔均值% | 期望比 | Sharpe | 平均持仓(分) | 出场分布 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, s in rows:
        exits = ", ".join(f"{k}:{v}" for k, v in sorted(s["exits"].items()))
        lines.append(
            f"| {name} | {s['trades']} | {s['long']}/{s['short']} | {s['profit_pct']} | "
            f"{s['final_balance']} | {s['max_dd_pct']} | {s['winrate']} | {s['pf']} | "
            f"{s['avg_profit_pct']} | {s['expectancy_ratio']} | {s['sharpe']} | "
            f"{s['avg_duration_min']} | {exits} |"
        )
    lines.append("")
    if rows:
        market = rows[0][1]["market_change"]
        lines.append(f"同期市场变动（BTC 买入持有）：{market}%")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
