from __future__ import annotations

import gzip
import json
import math
import re
from pathlib import Path


TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "8h": 28800, "12h": 43200, "1d": 86400,
}


def _tf_from_name(name: str) -> str | None:
    match = re.search(r"-(\d+[mhd])(?:-|\.)", name)
    return match.group(1) if match else None


def _kind_from_name(name: str) -> str:
    low = name.lower()
    if "funding" in low:
        return "funding_rate"
    if "mark" in low:
        return "mark"
    if "index" in low:
        return "index"
    if "futures" in low:
        return "futures"
    return "spot"


def _file_stats(path: Path) -> dict:
    tf = _tf_from_name(path.name)
    kind = _kind_from_name(path.name)
    result = {"timeframe": tf or "", "type": kind, "count": 0, "start": 0, "end": 0}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        if isinstance(rows, dict):
            rows = rows.get("data", [])
        times = [int(r[0]) for r in rows if isinstance(r, (list, tuple)) and len(r) >= 1]
        if not times:
            return result
        result["count"] = len(times)
        result["start"] = min(times)
        result["end"] = max(times)
        if tf and tf in TF_SECONDS and result["end"] > result["start"]:
            expected = math.floor((result["end"] - result["start"]) / (TF_SECONDS[tf] * 1000)) + 1
            result["expected"] = expected
            result["fill_ratio"] = round(min(1.0, result["count"] / expected), 4)
        else:
            result["expected"] = result["count"]
            result["fill_ratio"] = 1.0
    except Exception:
        result["count"] = -1
    return result


def scan(user_data: Path, write_file: bool = True) -> dict:
    """Inventory downloaded candles: {exchange: {pair: {timeframe: {type: stats}}}}."""
    root = Path(user_data) / "data"
    inventory: dict = {}
    if not root.exists():
        return inventory
    for exchange_dir in sorted(root.iterdir()):
        if not exchange_dir.is_dir() or exchange_dir.name.startswith("."):
            continue
        exchange_key = exchange_dir.name
        mode_dirs: list[tuple[str, Path]] = []
        for sub in sorted(exchange_dir.iterdir()):
            if sub.is_dir() and sub.name == "futures":
                mode_dirs.append(("futures", sub))
            elif sub.is_file() and sub.suffix in (".gz", ".json"):
                mode_dirs.append(("root", exchange_dir))
        if exchange_dir.name == "futures":
            mode_dirs = [("futures", exchange_dir)]
        exchange_out: dict = inventory.setdefault(exchange_key, {})
        seen_pairs: set[tuple] = set()
        for mode, folder in mode_dirs:
            files = list(folder.glob("*.json.gz"))
            for path in files:
                stats = _file_stats(path)
                stem = path.stem.replace(".json", "")
                pair_key = stem.split("-")[0]
                tf = stats["timeframe"]
                if not tf:
                    continue
                key = (pair_key, tf, stats["type"])
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                pair_out = exchange_out.setdefault(pair_key, {})
                pair_out.setdefault(tf, {})[stats["type"]] = {
                    k: stats[k]
                    for k in ("count", "start", "end", "expected", "fill_ratio", "type")
                }
    if write_file:
        out_path = root / ".coverage.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    return inventory
