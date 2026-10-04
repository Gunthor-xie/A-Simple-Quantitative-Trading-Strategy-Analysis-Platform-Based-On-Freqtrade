from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..storage import db
from .api import _run_to_model


router = APIRouter()


@router.websocket("/api/ws")
async def snapshot_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            snapshot: dict[str, Any] = {
                "type": "snapshot",
                "backtests": [
                    _run_to_model(row).model_dump(mode="json")
                    for row in db.list_backtests(20)
                ],
                "signals_count": len(db.list_signals(limit=500)),
                "jobs": db.recent_jobs(20),
                "connections": db.list_connections(),
            }
            await websocket.send_json(snapshot)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
