"""CLI for the factor-research pipeline (``.scratch/factor-screening``).

Usage (from ``freqtrade-desktop/backend``)::

    python scripts/factor_research.py universe
    python scripts/factor_research.py download --pool equity_liquid --timerange 20260225-20260926
    python scripts/factor_research.py panel    --pool equity_liquid --timeframe 1h
    python scripts/factor_research.py screen   --pool equity_liquid --timeframe 1h
    python scripts/factor_research.py portfolio --pool equity_liquid --timeframe 1h
    python scripts/factor_research.py report   --pool equity_liquid --timeframe 1h
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import factor_panel as fp  # noqa: E402
from app.services import factor_portfolio as fport  # noqa: E402
from app.services import factor_screen as fs  # noqa: E402
from app.services.factor_lib import FACTORS, compute_factors, make_wide  # noqa: E402


def user_data_dir() -> Path:
    return BACKEND.parent / "user_data"


def repo_root() -> Path:
    return BACKEND.parent.parent


def _pairs(pool: str) -> list[str]:
    config = fp.load_universe(user_data_dir())
    return fp.pool_pairs(config, pool)


def cmd_universe(args: argparse.Namespace) -> int:
    config = fp.build_universe(
        user_data_dir(),
        crypto_min_days=args.crypto_min_days,
        crypto_min_adv=args.crypto_min_adv,
        equity_min_days=args.equity_min_days,
        equity_min_adv=args.equity_min_adv,
        max_per_pool=args.max_per_pool,
    )
    target = fp.save_universe(config, user_data_dir())
    print(f"标的池已写入 {target}")
    for name, entries in config["pools"].items():
        print(f"\n[{name}] {len(entries)} 个")
        for entry in entries[:8]:
            print(f"  {entry['instId']:<24} ADV {entry['adv_usd'] / 1e6:>8.1f} MUSD  "
                  f"上市 {entry['days_listed']:>6.1f} 天")
        if len(entries) > 8:
            print(f"  ... 另外 {len(entries) - 8} 个")
    print(f"\n未入池（历史/流动性不足）：{config['excluded_count']} 个")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    pairs = _pairs(args.pool)
    if not pairs:
        print(f"标的池 {args.pool} 为空")
        return 1
    print(f"下载 {args.pool}：{len(pairs)} 个标的，周期 {args.timeframes}")
    result = fp.download_pool(
        user_data_dir(), pairs,
        timeframes=tuple(args.timeframes.split(",")),
        timerange=args.timerange,
        candle_types=tuple(args.candle_types.split(",")),
        progress=lambda message: print(message, flush=True),
    )
    for item in result["files"]:
        print(f"  {item['pair']:<20} {item['timeframe']:>3} {item['kind']:<12} {item['rows']} 行")
    for error in result["errors"]:
        print(f"  FAILED {error['pair']} {error['timeframe']} {error['kind']}: {error['error']}")
    return 0


def cmd_panel(args: argparse.Namespace) -> int:
    pairs = _pairs(args.pool)
    if not pairs:
        return 1
    panel = fp.build_panel(user_data_dir(), pairs, args.timeframe,
                           progress=lambda message: print(message, flush=True))
    target = fp.write_panel(panel, user_data_dir(), args.pool, args.timeframe)
    span = pd.to_datetime(panel["ts"], unit="ms", utc=True)
    print(f"\n面板 {panel.shape} -> {target}")
    print(f"标的 {panel['pair'].nunique()} 个，时间 {span.min()} → {span.max()}")
    missing = panel.groupby("pair")["funding_rate"].apply(lambda s: float(s.isna().mean()))
    print(f"资金费缺失率：中位 {missing.median():.1%}，最大 {missing.max():.1%}")
    return 0


def _load_wide(pool: str, timeframe: str):
    panel = fp.read_panel(user_data_dir(), pool, timeframe)
    wide = make_wide(panel)
    equity_pool = pool.startswith("equity")
    factors = compute_factors(wide, equity_pool=equity_pool)
    return panel, wide, factors, equity_pool


def cmd_screen(args: argparse.Namespace) -> int:
    panel, wide, factors, _ = _load_wide(args.pool, args.timeframe)
    cfg = fs.ScreenConfig(
        horizon_bars=args.horizon,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        min_pairs=args.min_pairs,
    )
    report = fs.screen_all(factors, wide.close, cfg)
    target = user_data_dir() / fp.FACTOR_DIR / args.pool / f"screen-{_stamp()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"评估 {report['trials']} 个因子（{args.pool} {args.timeframe}，"
          f"h={cfg.horizon_bars}，费率 {cfg.fee_bps}+{cfg.slippage_bps} bps）")
    print(f"{'因子':<20}{'族':<11}{'IC':>8}{'t':>7}{'q':>7}{'净bps':>9}{'换手':>7}{'正窗口':>8}  判定")
    for name, record in list(report["results"].items())[: args.top]:
        ic = record["ic_mean"]
        t_stat = record["ic_t_nw"]
        q_value = record["fdr_q"]
        net = record["spread_net_bps"]
        print(f"{name:<20}{record['family']:<11}{_num(ic, 4):>8}{_num(t_stat, 2):>7}"
              f"{_num(q_value, 3):>7}{_num(net, 1):>9}{_num(record['turnover'], 2):>7}"
              f"{_num(record['window_positive_frac'], 2):>8}  {record['verdict']}")
    print(f"\n通过闸门：{report['promising'] or '无'}")
    print(f"完整结果：{target}")
    return 0


def _candidate_factors(report: dict, min_coverage: float = 0.3) -> tuple[list[str], str]:
    """Pick candidates: gate-passers, else FDR-significant, else the strongest tails."""
    promising = list(report["promising"])
    if promising:
        return promising, "通过四条闸门"
    significant = [name for name, record in report["results"].items()
                   if record.get("fdr_q") is not None and record["fdr_q"] < 0.10
                   and record["coverage"] >= min_coverage
                   and not np.isnan(record.get("ic_t_nw") or np.nan)]
    if significant:
        return significant, "FDR 显著（未通过全部闸门）"
    ranked = [name for name, record in report["results"].items()
              if not np.isnan(record.get("spread_net_bps") or np.nan)]
    return ranked[:5], "按成本后净价差排序（统计上不显著）"


def _dedupe(names: list[str], factors: dict, max_factors: int,
            report: dict, threshold: float = 0.7) -> list[str]:
    """Collapse |corr| > threshold clusters to the strongest member (spec section 7)."""
    available = {name: factors[name] for name in names if name in factors}
    if len(available) < 2:
        return list(available)[:max_factors]
    correlation = fs.factor_correlation(available)
    clusters = fs.cluster_factors(correlation, threshold=threshold)
    chosen: list[str] = []
    for cluster in clusters:
        best = max(cluster, key=lambda name: abs(report["results"].get(name, {})
                                                 .get("ic_t_nw") or 0.0))
        chosen.append(best)
    chosen.sort(key=lambda name: -(abs(report["results"].get(name, {}).get("ic_t_nw") or 0.0)))
    return chosen[:max_factors]


def _sensitivity(wide, composite, settled, adv, args, cfg) -> list[dict]:
    """Re-run the book across K, fee and leg combinations to expose fragile results."""
    runs: list[tuple[str, dict]] = []
    for k in (3, 5, 8):
        runs.append((f"K={k}", {"k": k}))
    for fee in (2.0, 5.0, 10.0):
        runs.append((f"费率={fee}bps", {"fee_bps": fee, "slippage_bps": 0.0}))
    runs.append(("仅多头", {"legs": "long"}))
    runs.append(("仅空头", {"legs": "short"}))

    out: list[dict] = []
    for label, override in runs:
        params = dict(k=cfg.k, fee_bps=cfg.fee_bps, slippage_bps=cfg.slippage_bps,
                      rebalance_bars=args.horizon, min_adv_usd=args.min_adv,
                      target_vol=cfg.target_vol, max_leverage=cfg.max_leverage)
        params.update(override)
        try:
            run = fport.simulate(wide.close, composite, funding=wide.funding,
                                 funding_settled=settled, adv=adv,
                                 cfg=fport.PortfolioConfig(**params))
        except ValueError:
            continue
        stats = run["stats"]
        out.append({
            "label": label,
            "total_return": stats["total_return"],
            "sharpe": stats["sharpe"],
            "max_drawdown": stats["max_drawdown"],
            "turnover": run["mean_turnover"],
        })
    return out


def cmd_portfolio(args: argparse.Namespace) -> int:
    screen_path = _latest(user_data_dir() / fp.FACTOR_DIR / args.pool, "screen-*.json")
    if screen_path is None:
        print("先运行 screen 子命令")
        return 1
    report = json.loads(screen_path.read_text(encoding="utf-8"))
    panel, wide, factors, _ = _load_wide(args.pool, args.timeframe)
    candidates, basis = _candidate_factors(report)
    selected = _dedupe(candidates, factors, args.max_factors, report)
    if args.orientation == "walkforward":
        composite = fport.walk_forward_composite(
            wide.close, factors, selected, horizon_bars=args.horizon,
            window_obs=args.orientation_window)
    else:
        composite = fport.build_composite(factors, selected)
    adv = fport.trailing_adv(wide.volume, wide.close)
    settled = fp.pivot(panel, "funding_settled") if "funding_settled" in panel.columns else None
    cfg = fport.PortfolioConfig(
        k=args.k, fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
        rebalance_bars=args.horizon, min_adv_usd=args.min_adv,
    )
    result = fport.simulate(wide.close, composite, funding=wide.funding,
                            funding_settled=settled, adv=adv, cfg=cfg)
    sensitivity = _sensitivity(wide, composite, settled, adv, args, cfg)
    payload = {
        "pool": args.pool, "timeframe": args.timeframe,
        "selected_factors": selected,
        "selected_basis": basis,
        "candidates": candidates,
        "orientation": args.orientation,
        "config": {k: v for k, v in result["config"].items()},
        "stats": result["stats"],
        "mean_turnover": result["mean_turnover"],
        "cost_total": result["cost_total"],
        "funding_total": result["funding_total"],
        "capacity_usd": result["capacity_usd"],
        "sensitivity": sensitivity,
        "returns": {str(int(k)): float(v) for k, v in result["returns"].items()},
    }
    target = user_data_dir() / fp.FACTOR_DIR / args.pool / f"portfolio-{_stamp()}.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    stats = result["stats"]
    print(f"组合（{args.pool} {args.timeframe}，K={cfg.k}，因子 {len(selected)} 个，选取依据：{basis}）")
    print(f"  入选因子：{', '.join(selected)}")
    print(f"  区间数 {stats['periods']}，累计 {_pct(stats['total_return'])}，"
          f"年化 {_pct(stats['ann_return'])}，波动 {_pct(stats['ann_vol'])}")
    print(f"  Sharpe {_num(stats['sharpe'], 2)}，最大回撤 {_pct(stats['max_drawdown'])}，"
          f"Calmar {_num(stats['calmar'], 2)}，胜率 {_pct(stats['hit_rate'])}")
    print(f"  平均换手 {result['mean_turnover']:.2f}，成本合计 {_pct(result['cost_total'])}，"
          f"资金费合计 {_pct(result['funding_total'])}")
    if result["capacity_usd"]:
        print(f"  容量估算（ADV 0.5% 约束）：约 {result['capacity_usd'] / 1e4:,.0f} 万美元")
    print(f"完整结果：{target}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    screen_path = _latest(user_data_dir() / fp.FACTOR_DIR / args.pool, "screen-*.json")
    portfolio_path = _latest(user_data_dir() / fp.FACTOR_DIR / args.pool, "portfolio-*.json")
    if screen_path is None or portfolio_path is None:
        print("先运行 screen 与 portfolio 子命令")
        return 1
    report = json.loads(screen_path.read_text(encoding="utf-8"))
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    panel = fp.read_panel(user_data_dir(), args.pool, args.timeframe)

    results_dir = repo_root() / ".scratch" / "factor-screening" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    target = results_dir / f"{_stamp()}-{args.pool}.md"
    target.write_text(_render_report(args, report, portfolio, panel), encoding="utf-8")
    print(f"报告已写入 {target}")
    return 0


def _render_report(args: argparse.Namespace, report: dict, portfolio: dict,
                   panel: pd.DataFrame) -> str:
    cfg = report["config"]
    stats = portfolio["stats"]
    span = pd.to_datetime(panel["ts"], unit="ms", utc=True)
    lines: list[str] = []
    lines.append(f"# 因子筛选结果：{args.pool}（{args.timeframe}）")
    lines.append("")
    lines.append(f"日期：{_stamp()}　标的数：{panel['pair'].nunique()}　"
                 f"区间：{span.min():%Y-%m-%d} → {span.max():%Y-%m-%d}　"
                 f"面板规模：{len(panel):,} 行")
    lines.append("")
    lines.append("## 口径")
    lines.append("")
    lines.append(f"- 预测跨度：{cfg['horizon_bars']} 根（非重叠采样），分位组数 {cfg['quantiles']}")
    lines.append(f"- 成本：taker {cfg['fee_bps']} bps + 滑点 {cfg['slippage_bps']} bps（每边），"
                 f"另有资金费")
    lines.append(f"- 滚动窗口：训练 {cfg['train_obs']} / 测试 {cfg['test_obs']} 个非重叠观测；"
                 f"多重检验 FDR q < {cfg['fdr_q']}")
    lines.append("")
    lines.append("## 因子筛选（按成本后净价差排序）")
    lines.append("")
    lines.append("| 因子 | 族 | 定向 | 样本外 IC | NW t | FDR q | 毛价差 bps | 净价差 bps | 换手 | 正窗口占比 | 判定 |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for name, record in report["results"].items():
        lines.append(
            f"| `{name}` | {record['family']} | {record.get('orientation', 1):+d} | "
            f"{_num(record['ic_mean'], 4)} | "
            f"{_num(record['ic_t_nw'], 2)} | {_num(record['fdr_q'], 3)} | "
            f"{_num(record['spread_gross'] * 1e4, 1)} | {_num(record['spread_net_bps'], 1)} | "
            f"{_num(record['turnover'], 2)} | {_num(record['window_positive_frac'], 2)} | "
            f"{record['verdict']} |")
    lines.append("")
    lines.append(f"通过闸门的因子：{', '.join(report['promising']) if report['promising'] else '**无**'}")
    lines.append("")
    lines.append("被否决的原因（前 10 条）：")
    lines.append("")
    rejected = [(name, record) for name, record in report["results"].items()
                if record["verdict"] != "promising"][:10]
    if not rejected:
        lines.append("- 无")
    for name, record in rejected:
        lines.append(f"- `{name}`：{'；'.join(record.get('reasons', []))}")
    lines.append("")
    lines.append("## 组合模拟")
    lines.append("")
    lines.append(f"- 因子组合：{', '.join(portfolio['selected_factors'])}")
    lines.append(f"- K={portfolio['config']['k']}，目标波动 {portfolio['config']['target_vol']:.0%}，"
                 f"杠杆上限 {portfolio['config']['max_leverage']}x，"
                 f"调仓 {portfolio['config']['rebalance_bars']} 根")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("| --- | ---: |")
    lines.append(f"| 区间数 | {stats['periods']} |")
    lines.append(f"| 累计收益 | {_pct(stats['total_return'])} |")
    lines.append(f"| 年化收益 | {_pct(stats['ann_return'])} |")
    lines.append(f"| 年化波动 | {_pct(stats['ann_vol'])} |")
    lines.append(f"| Sharpe | {_num(stats['sharpe'], 2)} |")
    lines.append(f"| 最大回撤 | {_pct(stats['max_drawdown'])} |")
    lines.append(f"| 胜率 | {_pct(stats['hit_rate'])} |")
    lines.append(f"| 平均换手 | {portfolio['mean_turnover']:.2f} |")
    lines.append(f"| 成本合计 | {_pct(portfolio['cost_total'])} |")
    lines.append(f"| 资金费合计 | {_pct(portfolio['funding_total'])} |")
    if portfolio.get("capacity_usd"):
        lines.append(f"| 容量估算 | {portfolio['capacity_usd'] / 1e4:,.0f} 万美元 |")
    lines.append("")
    sensitivity = portfolio.get("sensitivity") or []
    if sensitivity:
        lines.append("### 敏感性（同一组合，改动单一条件）")
        lines.append("")
        lines.append("| 变体 | 累计收益 | Sharpe | 最大回撤 | 换手 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for run in sensitivity:
            lines.append(f"| {run['label']} | {_pct(run['total_return'])} | "
                         f"{_num(run['sharpe'], 2)} | {_pct(run['max_drawdown'])} | "
                         f"{_num(run['turnover'], 2)} |")
        lines.append("")
    lines.append("## 结论")
    lines.append("")
    if report["promising"]:
        lines.append("存在通过四条闸门的因子，可按组合结果进入下一步（更长期样本复核 + dry-run）。")
    else:
        lines.append("**本样本内没有任何因子通过四条闸门。** 结论是「该池该口径下未发现可交易因子」，"
                     "而不是「加密/美股代币没有因子」——样本长度、成本假设与因子集合都是边界条件。")
    lines.append("")
    lines.append("风险与边界：")
    lines.append("")
    lines.append("- 股票池历史 ≤7 个月，任何结论都是暂定的；")
    lines.append("- 回测未建模点差冲击与被动成交概率，实盘预期劣于此处结果；")
    lines.append("- 因子网格本身存在过拟合风险，FDR 只是下限保护。")
    lines.append("")
    return "\n".join(lines)


def _latest(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    files = sorted(directory.glob(pattern))
    return files[-1] if files else None


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _num(value, digits: int) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if np.isnan(number):
        return "-"
    return f"{number:.{digits}f}"


def _pct(value) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if np.isnan(number):
        return "-"
    return f"{number * 100:.2f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OKX 因子研究与多因子组合管线")
    sub = parser.add_subparsers(dest="command", required=True)

    universe = sub.add_parser("universe", help="构建标的池配置")
    universe.add_argument("--crypto-min-days", type=float, default=730)
    universe.add_argument("--crypto-min-adv", type=float, default=2e7)
    universe.add_argument("--equity-min-days", type=float, default=90)
    universe.add_argument("--equity-min-adv", type=float, default=5e6)
    universe.add_argument("--max-per-pool", type=int, default=30)
    universe.set_defaults(func=cmd_universe)

    download = sub.add_parser("download", help="下载标的池行情")
    download.add_argument("--pool", required=True)
    download.add_argument("--timeframes", default="1h,1d")
    download.add_argument("--timerange", default=None)
    download.add_argument("--candle-types", default="futures,funding_rate")
    download.set_defaults(func=cmd_download)

    panel = sub.add_parser("panel", help="构建研究面板")
    panel.add_argument("--pool", required=True)
    panel.add_argument("--timeframe", default="1h")
    panel.set_defaults(func=cmd_panel)

    screen = sub.add_parser("screen", help="因子筛选")
    screen.add_argument("--pool", required=True)
    screen.add_argument("--timeframe", default="1h")
    screen.add_argument("--horizon", type=int, default=24)
    screen.add_argument("--fee-bps", type=float, default=5.0)
    screen.add_argument("--slippage-bps", type=float, default=2.0)
    screen.add_argument("--min-pairs", type=int, default=5)
    screen.add_argument("--top", type=int, default=20)
    screen.set_defaults(func=cmd_screen)

    portfolio = sub.add_parser("portfolio", help="组合模拟")
    portfolio.add_argument("--pool", required=True)
    portfolio.add_argument("--timeframe", default="1h")
    portfolio.add_argument("--horizon", type=int, default=24)
    portfolio.add_argument("--k", type=int, default=5)
    portfolio.add_argument("--max-factors", type=int, default=5)
    portfolio.add_argument("--fee-bps", type=float, default=5.0)
    portfolio.add_argument("--slippage-bps", type=float, default=2.0)
    portfolio.add_argument("--min-adv", type=float, default=1e6)
    portfolio.add_argument("--orientation", choices=("walkforward", "prior"), default="walkforward",
                           help="因子定向方式：walkforward=用滚动 IC 估计，prior=用经济先验")
    portfolio.add_argument("--orientation-window", type=int, default=40)
    portfolio.set_defaults(func=cmd_portfolio)

    report = sub.add_parser("report", help="生成结论文档")
    report.add_argument("--pool", required=True)
    report.add_argument("--timeframe", default="1h")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
