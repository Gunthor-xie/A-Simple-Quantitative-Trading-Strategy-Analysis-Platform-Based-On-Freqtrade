from __future__ import annotations

import gzip
import json

from app.services.coverage import scan
from app.services.excel_export import parse_catalog
from app.services.okx_client import OkxClient


def test_sign_is_deterministic() -> None:
    client = OkxClient("key", "secret", "pass")
    a = client._sign("GET", "/api/v5/account/balance", "", "123")
    b = client._sign("GET", "/api/v5/account/balance", "", "123")
    assert a == b
    assert len(a) > 20


def test_catalog_parses_11_sections(tmp_path) -> None:
    from app.config import APP_DIR

    path = APP_DIR / "回测指标需求.txt"
    if not path.exists():
        return
    sections = parse_catalog(path)
    assert len(sections) == 11
    assert sum(len(s["fields"]) for s in sections) > 150


def test_coverage_scan(tmp_path) -> None:
    data = tmp_path / "data" / "okx"
    (data / "futures").mkdir(parents=True)
    rows = [
        [1700000000000 + i * 900000, 1, 2, 1, 1.5, 10] for i in range(10)
    ]
    with gzip.open(data / "BTC_USDT-15m.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)
    inventory = scan(tmp_path, write_file=True)
    pair = inventory["okx"]["BTC_USDT"]["15m"]["spot"]
    assert pair["count"] == 10
    assert (tmp_path / "data" / ".coverage.json").exists()
