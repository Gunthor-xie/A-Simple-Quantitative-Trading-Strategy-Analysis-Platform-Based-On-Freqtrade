"""Background loop that marks open arb positions and runs the risk unwind.

Kept deliberately thin: it only calls into :class:`ArbitrageEngine` on a timer,
and it does nothing unless ``arb_trade_enabled`` is on. The heavy lifting
(sizing, orders, risk triggers) lives in ``arbitrage_engine`` so the loop and
the HTTP API share exactly one implementation.
"""

from __future__ import annotations

import time
from typing import Callable

from ..storage import db as default_db
from .arbitrage_engine import ArbError, ArbitrageEngine, build_trade_client, trade_enabled


class FundingScheduler:
    def __init__(
        self,
        store=default_db,
        *,
        interval: float = 60.0,
        progress: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.db = store
        self.interval = max(5.0, interval)
        self._progress = progress or (lambda _msg: None)
        self._sleep = sleep or time.sleep

    def tick_once(self) -> dict:
        summary = {"refreshed": 0, "unwound": 0, "skipped": False, "error": ""}
        if not trade_enabled(self.db):
            summary["skipped"] = True
            return summary
        open_positions = self.db.list_arb_positions(status="open")
        if not open_positions:
            return summary
        try:
            client = build_trade_client(self.db)
        except ArbError as exc:
            summary["error"] = str(exc)
            return summary
        try:
            engine = ArbitrageEngine(client, self.db)
            # maybe_unwind refreshes every open position before checking triggers.
            unwound = engine.maybe_unwind()
            summary["refreshed"] = len(open_positions)
            summary["unwound"] = len(unwound)
            for item in unwound:
                self._progress(f"auto-unwound #{item['id']} {item['pair']}: {item['reason']}")
        finally:
            client.close()
        return summary

    def run_forever(self, *, max_iterations: int | None = None) -> None:
        self._progress(f"arb scheduler started (interval={self.interval:g}s)")
        iterations = 0
        while True:
            started = time.time()
            try:
                summary = self.tick_once()
                if not summary["skipped"]:
                    message = (
                        f"tick: refreshed={summary['refreshed']} unwound={summary['unwound']}"
                    )
                    if summary["error"]:
                        message += f" error={summary['error']}"
                    self._progress(message)
            except Exception as exc:  # keep the loop alive across hiccups
                self._progress(f"tick failed: {type(exc).__name__}: {exc}")
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            elapsed = time.time() - started
            self._sleep(max(1.0, self.interval - elapsed))
