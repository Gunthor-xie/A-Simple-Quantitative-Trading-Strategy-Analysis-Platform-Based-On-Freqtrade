from __future__ import annotations

import os
from pathlib import Path

from .config import settings as base_settings
from .storage import db


def current_user_data() -> Path:
    env = os.environ.get("FTDESK_USER_DATA")
    if env:
        return Path(env)
    row = db.get_setting("data_root")
    return Path(row) if row else Path(base_settings.user_data)


def current_export_dir() -> Path:
    row = db.get_setting("export_dir")
    if row:
        return Path(row)
    return current_user_data() / "backtest_exports"


def z_thresholds() -> tuple[float, float]:
    def _val(key: str, default: float) -> float:
        try:
            return float(db.get_setting(key) or default)
        except (TypeError, ValueError):
            return default

    return _val("z_soft", 2.0), _val("z_hard", 3.0)
