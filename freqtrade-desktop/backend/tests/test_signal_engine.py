from __future__ import annotations

from app.schemas import BacktestResult, SignalEvent
from app.services.signal_engine import SignalEngine
from app.storage import Database


def test_analyzed_rows_to_signals(tmp_path) -> None:
    engine = SignalEngine(Database(tmp_path / "signal-test.db"))
    rows = [
        {"date": 1704067200000, "close": 40000.0, "enter_long": True},
        {"date": "2024-01-02 00:00:00", "close": 40500.0, "exit_long": True},
    ]
    events = engine.from_analyzed_rows("Demo", "BTC/USDT", rows)
    assert len(events) == 2
    assert events[0].side == "long"
    assert events[1].side == "exit"


def test_dedupe_stores_only_new(tmp_path) -> None:
    storage = Database(tmp_path / "signals.db")
    engine = SignalEngine(storage)
    events = [
        SignalEvent(
            strategy="Demo",
            time="2024-01-02T00:00:00+00:00",
            pair="BTC/USDT",
            side="long",
            reason="ma_cross",
            price=40000.0,
        )
    ]
    first = engine.dedupe(events)
    second = engine.dedupe(events)
    assert len(first) == 1
    assert second == []


def test_from_backtest_builds_events(tmp_path) -> None:
    engine = SignalEngine(Database(tmp_path / "signal-bt.db"))
    result = BacktestResult(
        strategy="Demo",
        trades=[
            {
                "pair": "BTC/USDT",
                "open_date": "2024-01-02 00:00:00",
                "close_date": "2024-01-03 00:00:00",
                "open_rate": 40000.0,
                "close_rate": 41000.0,
                "enter_reason": "ma_cross",
                "exit_reason": "roi",
                "is_short": False,
            }
        ],
    )
    events = engine.from_backtest(result)
    assert [e.side for e in events] == ["long", "exit"]
