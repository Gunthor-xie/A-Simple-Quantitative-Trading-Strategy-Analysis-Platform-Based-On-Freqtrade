"""Collect OKX liquidation / open-interest / taker-flow streams into JSONL.

Usage (from ``freqtrade-desktop/backend``):

    python scripts/collect_liquidations.py --status          # coverage so far
    python scripts/collect_liquidations.py --once            # one poll (cron friendly)
    python scripts/collect_liquidations.py --loop            # keep running (default)

Files land in ``user_data/liquidation/``:
    <PAIR>-liq-raw.jsonl      individual liquidation orders (USD notional)
    <PAIR>-okx-oi.jsonl       open interest, 5m (USD + coin)
    <PAIR>-okx-taker.jsonl    taker sell/buy volume, 5m (USD)

The background launcher is ``freqtrade-desktop/start-collector.ps1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.liquidation_collector import (  # noqa: E402
    LiquidationCollector,
    aggregate_liquidations,
)


def default_user_data() -> Path:
    return BACKEND_DIR.parent / "user_data"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OKX liquidation collector")
    parser.add_argument("--pair", default="BTC/USDT:USDT")
    parser.add_argument("--user-data", default=str(default_user_data()))
    parser.add_argument("--proxy", default="", help="HTTP proxy (default: auto-detect)")
    parser.add_argument("--poll-seconds", type=float, default=30.0,
                        help="liquidation poll interval (default 30s)")
    parser.add_argument("--derivatives-seconds", type=float, default=300.0,
                        help="OI/taker poll interval (default 300s = 5m)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loop", action="store_true", help="keep running (default)")
    mode.add_argument("--once", action="store_true", help="poll once and exit")
    mode.add_argument("--status", action="store_true", help="print collected coverage")
    mode.add_argument("--compact", action="store_true",
                      help="dedupe the JSONL files (run while the loop is stopped)")
    parser.add_argument("--minutes", type=int, default=0,
                        help="with --status: also aggregate the last N minutes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    collector = LiquidationCollector(
        args.user_data,
        args.pair,
        proxy=args.proxy or None,
        poll_seconds=args.poll_seconds,
        derivatives_seconds=args.derivatives_seconds,
        progress=lambda message: print(message, flush=True),
    )

    if args.status:
        report = collector.status()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        if args.minutes:
            import time as _time

            end = int(_time.time() * 1000)
            start = end - args.minutes * 60_000
            frame = aggregate_liquidations(collector.raw_path, start, end)
            if frame.empty:
                print(f"no liquidation records in the last {args.minutes} minutes")
            else:
                frame["minute"] = (frame["date"] // 60_000) * 60_000
                grouped = frame.groupby(["minute", "side"])["notional"].sum().unstack(fill_value=0.0)
                print(grouped.tail(30).to_string())
        return 0

    if args.once:
        print(json.dumps(collector.collect_once(), indent=2, ensure_ascii=False))
        return 0

    if args.compact:
        print(json.dumps(collector.compact(), indent=2, ensure_ascii=False))
        return 0

    collector.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
