"""Offline-market launcher for freqtrade.

Backtesting normally starts by fetching exchange markets over the network
(ccxt/aiohttp). When OKX is unreachable through that stack, this launcher
patches ccxt to build markets from locally cached OKX ``instruments``
responses (user_data/data/okx_instruments_SPOT.json / _SWAP.json), then calls
the regular freqtrade main(). Data files are fetched once via ``requests``
(which is more reliable in restricted networks) and reused afterwards.

Usage (from the executor):  python freqtrade_offline.py <freqtrade args...>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _user_data() -> Path:
    env = os.environ.get("FTDESK_USER_DATA")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "user_data"


def _instruments(inst_type: str) -> list[dict]:
    path = _user_data() / "data" / f"okx_instruments_{inst_type}.json"
    if not path.exists():
        try:
            import requests
            resp = requests.get(
                "https://www.okx.com/api/v5/public/instruments",
                params={"instType": inst_type}, timeout=40,
            )
            resp.raise_for_status()
            payload = resp.json()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:
            raise FileNotFoundError(f"Missing market cache {path}: {exc}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("data", [])


def _build_markets() -> tuple[dict, dict]:
    """Parse cached OKX instruments into ccxt-shaped markets (no network)."""
    import ccxt

    parser = ccxt.okx({"enableRateLimit": False})
    markets: dict[str, dict] = {}
    for inst_type in ("SPOT", "SWAP"):
        for instrument in _instruments(inst_type):
            try:
                market = parser.parse_market(instrument)
            except Exception:
                continue
            if market.get("symbol"):
                markets[market["symbol"]] = market
    currencies: dict[str, dict] = {}
    for market in markets.values():
        for code in (market.get("base"), market.get("quote"), market.get("settle")):
            if code and code not in currencies:
                currencies[code] = {"id": code, "code": code, "active": True}
    return markets, currencies


def _install_patch() -> None:
    import ccxt.async_support as ccxt_async
    import ccxt as ccxt_sync

    markets, currencies = _build_markets()

    async def async_load_markets(self, reload: bool = False, params: dict | None = None) -> dict:
        if self.markets and not reload:
            return self.markets
        self.markets = markets
        self.markets_by_id = {m.get("id"): m for m in markets.values() if m.get("id")}
        self.currencies = currencies
        self.symbols = list(markets)
        return self.markets

    def sync_load_markets(self, reload: bool = False, params: dict | None = None) -> dict:
        if self.markets and not reload:
            return self.markets
        self.markets = markets
        self.markets_by_id = {m.get("id"): m for m in markets.values() if m.get("id")}
        self.currencies = currencies
        self.symbols = list(markets)
        return self.markets

    setattr(ccxt_async.okx, "load_markets", async_load_markets)
    setattr(ccxt_sync.okx, "load_markets", sync_load_markets)


def main() -> int:
    _install_patch()
    from freqtrade.main import main as freqtrade_main

    return freqtrade_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
