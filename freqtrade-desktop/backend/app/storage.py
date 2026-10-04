from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .schemas import utcnow_iso


def _now() -> str:
    return utcnow_iso()


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or settings.db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _init_schema(self) -> None:
        with self.conn() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS connections (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'local',
                    url TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT 'Freqtrader',
                    ws_token TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS backtests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    params_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT,
                    result_json TEXT,
                    result_file TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS score_weights (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    weights_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    time TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    price REAL,
                    created_at TEXT NOT NULL,
                    UNIQUE (strategy, pair, time, side, reason)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                """
            )

    # ---- connections ----

    def list_connections(self) -> list[dict[str, Any]]:
        with self.conn() as db:
            rows = db.execute("SELECT * FROM connections ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def get_connection(self, conn_id: str) -> dict[str, Any] | None:
        with self.conn() as db:
            row = db.execute(
                "SELECT * FROM connections WHERE id = ?", (conn_id,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_connection(self, data: dict[str, Any]) -> dict[str, Any]:
        conn_id = data.get("id") or str(uuid.uuid4())
        with self.conn() as db:
            db.execute(
                """
                INSERT INTO connections (id, name, kind, url, username, ws_token, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, kind=excluded.kind, url=excluded.url,
                    username=excluded.username, ws_token=excluded.ws_token,
                    enabled=excluded.enabled
                """,
                (
                    conn_id,
                    data["name"],
                    data.get("kind", "local"),
                    data["url"],
                    data.get("username", "Freqtrader"),
                    data.get("ws_token"),
                    1 if data.get("enabled", True) else 0,
                    data.get("created_at") or _now(),
                ),
            )
        return {**data, "id": conn_id}

    def delete_connection(self, conn_id: str) -> None:
        with self.conn() as db:
            db.execute("DELETE FROM connections WHERE id = ?", (conn_id,))

    # ---- backtests ----

    def create_backtest(self, params: dict[str, Any]) -> int:
        with self.conn() as db:
            cur = db.execute(
                "INSERT INTO backtests (params_json, status, created_at) VALUES (?, 'queued', ?)",
                (json.dumps(params, ensure_ascii=False), _now()),
            )
            return int(cur.lastrowid)

    def list_backtests(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn() as db:
            rows = db.execute(
                "SELECT * FROM backtests ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["params_json"] = json.loads(item["params_json"])
            item["result_json"] = (
                json.loads(item["result_json"]) if item["result_json"] else None
            )
            out.append(item)
        return out

    def get_backtest(self, run_id: int) -> dict[str, Any] | None:
        with self.conn() as db:
            row = db.execute(
                "SELECT * FROM backtests WHERE id = ?", (run_id,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["params_json"] = json.loads(item["params_json"])
        item["result_json"] = (
            json.loads(item["result_json"]) if item["result_json"] else None
        )
        return item

    def update_backtest(
        self, run_id: int, status: str | None = None, result: dict | None = None,
        result_file: str | None = None, error: str | None = None,
    ) -> None:
        with self.conn() as db:
            sets, vals = [], []
            if status is not None:
                sets.append("status = ?")
                vals.append(status)
            if result is not None:
                sets.append("result_json = ?")
                vals.append(json.dumps(result, ensure_ascii=False))
            if result_file is not None:
                sets.append("result_file = ?")
                vals.append(result_file)
            if error is not None:
                sets.append("error = ?")
                vals.append(error)
            if status in ("done", "error"):
                sets.append("finished_at = ?")
                vals.append(_now())
            if not sets:
                return
            vals.append(run_id)
            db.execute(f"UPDATE backtests SET {', '.join(sets)} WHERE id = ?", vals)

    def delete_backtest(self, run_id: int) -> dict[str, Any] | None:
        """Delete one backtest row and return the removed row (None if missing).

        The caller is responsible for removing ``result_file`` from disk; we
        return the whole row so the API layer still knows the file path.
        """
        row = self.get_backtest(run_id)
        if row is None:
            return None
        with self.conn() as db:
            db.execute("DELETE FROM backtests WHERE id = ?", (run_id,))
        return row

    def best_metrics_for_strategy(self, strategy: str) -> dict[str, float]:
        """Best observed metric values across the strategy's finished backtests."""
        best: dict[str, float] = {}
        with self.conn() as db:
            rows = db.execute(
                "SELECT result_json FROM backtests WHERE status='done' AND result_json IS NOT NULL"
            ).fetchall()
        for row in rows:
            try:
                result = json.loads(row["result_json"])
            except Exception:
                continue
            if result.get("strategy") != strategy:
                continue
            for key in ("sharpe", "sortino", "calmar", "profit_factor", "winrate", "expectancy"):
                value = result.get(key)
                if isinstance(value, (int, float)) and value == value:
                    best[key] = max(best.get(key, float("-inf")), float(value))
            dd = result.get("max_drawdown_account")
            if isinstance(dd, (int, float)) and dd == dd:
                best["max_drawdown"] = min(best.get("max_drawdown", float("inf")), float(dd))
        return {k: v for k, v in best.items() if v not in (float("-inf"), float("inf"))}

    # ---- score weights ----

    def get_weights(self) -> dict[str, float] | None:
        with self.conn() as db:
            row = db.execute(
                "SELECT weights_json FROM score_weights WHERE id = 1"
            ).fetchone()
        return json.loads(row["weights_json"]) if row else None

    def set_weights(self, weights: dict[str, float]) -> None:
        with self.conn() as db:
            db.execute(
                """
                INSERT INTO score_weights (id, weights_json) VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET weights_json = excluded.weights_json
                """,
                (json.dumps(weights, ensure_ascii=False),),
            )

    # ---- app settings ----

    def get_setting(self, key: str) -> str | None:
        with self.conn() as db:
            row = db.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.conn() as db:
            db.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def get_all_settings(self) -> dict[str, str]:
        with self.conn() as db:
            rows = db.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---- signals ----

    def insert_signals(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new_events: list[dict[str, Any]] = []
        with self.conn() as db:
            for event in events:
                try:
                    db.execute(
                        """
                        INSERT INTO signals (strategy, time, pair, side, reason, price, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event["strategy"],
                            event["time"],
                            event["pair"],
                            event["side"],
                            event["reason"],
                            event.get("price"),
                            _now(),
                        ),
                    )
                    new_events.append(event)
                except sqlite3.IntegrityError:
                    continue
        return new_events

    def list_signals(self, strategy: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self.conn() as db:
            if strategy:
                rows = db.execute(
                    "SELECT * FROM signals WHERE strategy = ? ORDER BY id DESC LIMIT ?",
                    (strategy, limit),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    # ---- jobs ----

    def create_job(self, kind: str) -> str:
        job_id = str(uuid.uuid4())
        with self.conn() as db:
            db.execute(
                "INSERT INTO jobs (id, kind, status, created_at) VALUES (?, ?, 'queued', ?)",
                (job_id, kind, _now()),
            )
        return job_id

    def update_job(self, job_id: str, status: str, message: str = "") -> None:
        with self.conn() as db:
            finished = _now() if status in ("done", "error") else None
            db.execute(
                "UPDATE jobs SET status=?, message=?, finished_at=? WHERE id=?",
                (status, message, finished, job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.conn() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def recent_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.conn() as db:
            rows = db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


db = Database()
