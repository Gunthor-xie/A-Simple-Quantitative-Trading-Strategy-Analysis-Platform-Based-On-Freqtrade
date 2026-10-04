from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..schemas import BacktestResult, BotConnection, SignalEvent, utcnow_iso
from ..storage import Database
from .bot_client import BotClient


def _to_iso(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


class SignalEngine:
    """Generate and deduplicate trade signals.

    Sources:
    - live/dry-run bot analyzed frames (``pair_history``), detecting
      ``enter_long/enter_short/exit_long/exit_short`` columns;
    - backtest exports (entries and exits from closed trades).
    """

    def __init__(self, storage: Database) -> None:
        self.storage = storage

    def from_analyzed_rows(
        self, strategy: str, pair: str, rows: list[dict[str, Any]]
    ) -> list[SignalEvent]:
        events: list[SignalEvent] = []
        for row in rows:
            timestamp = _to_iso(row.get("date") or row.get("timestamp"))
            price = row.get("close")
            for column, side in (
                ("enter_long", "long"),
                ("enter_short", "short"),
                ("exit_long", "exit"),
                ("exit_short", "exit"),
            ):
                if row.get(column) is True or str(row.get(column, "")).lower() in ("1", "true"):
                    events.append(
                        SignalEvent(
                            strategy=strategy,
                            time=timestamp,
                            pair=pair,
                            side=side,
                            reason=f"signal:{column}",
                            price=float(price) if isinstance(price, (int, float)) else None,
                            created_at=utcnow_iso(),
                        )
                    )
        return events

    def from_backtest(self, result: BacktestResult, strategy: str = "") -> list[SignalEvent]:
        strategy = strategy or result.strategy
        events: list[SignalEvent] = []
        for trade in result.trades:
            pair = str(trade.get("pair", ""))
            is_short = bool(trade.get("is_short"))
            entry_reason = str(trade.get("enter_reason", "") or "entry")
            exit_reason = str(trade.get("exit_reason", "") or "exit")
            events.append(
                SignalEvent(
                    strategy=strategy,
                    time=_to_iso(trade.get("open_date")),
                    pair=pair,
                    side="short" if is_short else "long",
                    reason=entry_reason,
                    price=trade.get("open_rate"),
                    created_at=utcnow_iso(),
                )
            )
            if trade.get("close_date"):
                events.append(
                    SignalEvent(
                        strategy=strategy,
                        time=_to_iso(trade.get("close_date")),
                        pair=pair,
                        side="exit",
                        reason=exit_reason,
                        price=trade.get("close_rate"),
                        created_at=utcnow_iso(),
                    )
                )
        return events

    def dedupe(self, events: list[SignalEvent]) -> list[SignalEvent]:
        payload = [
            {
                "strategy": e.strategy,
                "time": e.time,
                "pair": e.pair,
                "side": e.side,
                "reason": e.reason,
                "price": e.price,
            }
            for e in events
        ]
        stored = self.storage.insert_signals(payload)
        return [SignalEvent(**item) for item in stored]

    def live_signals(
        self,
        client: BotClient,
        strategy: str,
        pairs: list[str],
        timeframe: str,
    ) -> list[SignalEvent]:
        all_events: list[SignalEvent] = []
        for pair in pairs:
            rows = client.pair_history(pair, timeframe, strategy)
            all_events.extend(self.from_analyzed_rows(strategy, pair, rows))
        return self.dedupe(all_events)

    def backtest_signals(self, result: BacktestResult, strategy: str = "") -> list[SignalEvent]:
        return self.dedupe(self.from_backtest(result, strategy))
