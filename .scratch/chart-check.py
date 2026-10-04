"""Throwaway check for the new chart indicators / trade markers (delete after use)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "freqtrade-desktop"
sys.path.insert(0, str(ROOT / "backend"))

from app.services.chart_service import ChartService  # noqa: E402
from app.services.parser import parse_backtest_file  # noqa: E402

service = ChartService(ROOT / "user_data", None)  # storage unused by these calls

candles = service.load_candles(
    "okx", "BTC/USDT:USDT", "15m", trading_mode="futures", limit=2000
)
print("candles:", len(candles))

names = ["ema144", "ema169", "vwap24", "boll", "rsi", "macd"]
ind = service.compute_indicators(candles, names)
print("keys:", sorted(ind))
print("lengths match:", all(len(v) == len(candles) for v in ind.values()))

last = len(candles) - 1
for key in ("ema144", "ema169", "vwap24"):
    print(f"  {key} last = {None if ind[key][last] is None else round(ind[key][last], 3)}")

window = candles[-96:]  # 96 * 15m = 24h
low = min(c.low for c in window)
high = max(c.high for c in window)
vwap_last = ind["vwap24"][last]
print(f"  24h low/high = {low}/{high}, vwap inside band: {low <= vwap_last <= high}")

closes = [c.close for c in candles]
alpha = 2 / (144 + 1)
ema = closes[0]
for price in closes[1:]:
    ema = alpha * price + (1 - alpha) * ema
print("  ema144 manual diff:", abs(ema - ind["ema144"][last]))

results = sorted(
    (ROOT / "user_data" / "backtest_results").glob("*.zip"), key=lambda p: p.stat().st_size
)
result = parse_backtest_file(results[-1])
print("result:", results[-1].name, "trades:", len(result.trades))
pair = str(result.trades[0].get("pair")) if result.trades else "BTC/USDT"
markers = service.markers_from_trades(result, pair)
print("markers:", len(markers), "pair:", pair)
for marker in markers[:6]:
    print("   ", marker.time, marker.position, marker.shape, marker.color, repr(marker.text))
overlays = service.overlays_from_trades(result, pair)
print("overlays:", len(overlays))
for overlay in overlays[:4]:
    print("   ", overlay.trade_id, overlay.pnl, overlay.color)
wins = sum(1 for m in markers if m.color == "#26a69a")
print("green markers:", wins, "red markers:", len(markers) - wins)
