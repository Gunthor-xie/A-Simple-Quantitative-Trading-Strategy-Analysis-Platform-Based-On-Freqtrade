from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import api, okx, ws


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("freqtrade-desktop")


@asynccontextmanager
async def lifespan(_: FastAPI):
    for sub in ("strategies", "backtest_results", "data", "logs", "hyperopt_results"):
        (settings.user_data / sub).mkdir(parents=True, exist_ok=True)
    logger.info("Freqtrade Desktop backend started (user_data=%s)", settings.user_data)
    yield


app = FastAPI(title="Freqtrade Desktop Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)
app.include_router(okx.router)
app.include_router(ws.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
