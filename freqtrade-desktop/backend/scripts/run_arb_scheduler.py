"""Run the delta-neutral arbitrage position scheduler (mark + risk unwind).

Usage (from ``freqtrade-desktop/backend``):

    python scripts/run_arb_scheduler.py --status     # open positions + events
    python scripts/run_arb_scheduler.py --once       # one pass (cron friendly)
    python scripts/run_arb_scheduler.py --loop       # keep running (default)

It is a no-op unless OKX trade keys are configured *and* ``arb_trade_enabled``
is on - both toggled from the desktop "套利机会" page. The background launcher
is ``freqtrade-desktop/start-arb.ps1``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.arbitrage_engine import trade_demo, trade_enabled  # noqa: E402
from app.services.funding_scheduler import FundingScheduler  # noqa: E402
from app.storage import db  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delta-neutral arbitrage scheduler")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between passes")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loop", action="store_true", help="keep running (default)")
    mode.add_argument("--once", action="store_true", help="run one pass and exit")
    mode.add_argument("--status", action="store_true", help="print positions and events")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.status:
        report = {
            "trade_enabled": trade_enabled(db),
            "demo": trade_demo(db),
            "open_positions": db.list_arb_positions(status="open"),
            "recent_positions": db.list_arb_positions(limit=10),
            "recent_events": db.list_arb_events(limit=20),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0

    scheduler = FundingScheduler(
        db, interval=args.interval, progress=lambda message: print(message, flush=True)
    )
    if args.once:
        print(json.dumps(scheduler.tick_once(), indent=2, ensure_ascii=False))
        return 0

    scheduler.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
