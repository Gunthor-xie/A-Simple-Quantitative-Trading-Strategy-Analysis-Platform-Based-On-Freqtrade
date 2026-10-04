from __future__ import annotations

import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_USER_DATA = APP_DIR / "user_data"
DEFAULT_DB = APP_DIR / "backend" / "data" / "freqtrade_desktop.db"


class Settings:
    def __init__(self) -> None:
        self.host: str = os.environ.get("FTDESK_HOST", "127.0.0.1")
        self.port: int = int(os.environ.get("FTDESK_PORT", "8765"))
        self.user_data: Path = Path(os.environ.get("FTDESK_USER_DATA", str(DEFAULT_USER_DATA)))
        self.db_path: Path = Path(os.environ.get("FTDESK_DB", str(DEFAULT_DB)))
        self.freqtrade_bin: str = os.environ.get("FTDESK_FREQTRADE_BIN", "freqtrade")
        self.cors_origins: list[str] = [
            o.strip()
            for o in os.environ.get(
                "FTDESK_CORS",
                "http://localhost:5173,http://127.0.0.1:5173,file://",
            ).split(",")
            if o.strip()
        ]


settings = Settings()
