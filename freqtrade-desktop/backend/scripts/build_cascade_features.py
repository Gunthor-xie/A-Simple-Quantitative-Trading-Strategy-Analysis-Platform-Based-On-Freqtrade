"""Build the per-minute cascade feature file a strategy merges back in.

Example (from ``freqtrade-desktop/backend``):

    python scripts/build_cascade_features.py \\
        --pair BTC/USDT:USDT --start 2025-09-01 --end 2025-09-30 --trades

Writes ``user_data/liquidation/<PAIR>-1m-cascade.csv.gz``. The strategy
``LiquidationCascade`` reads exactly that file in backtest, dry-run and live, so
there is a single source of truth for the microstructure features.

Data comes from the Binance USD-M public archives (``data.binance.vision``):
1m klines, 5m OI/funding metrics, ~30s order-book depth, optional tick trades
and the funding-rate history. See ``app/services/binance_archive.py`` for the
dataset list and for why liquidations themselves cannot be archived.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.binance_archive import (  # noqa: E402
    BinanceArchive,
    BinanceArchiveError,
    days_between,
    month_of,
    parse_day,
    to_binance_symbol,
)
from app.services.cascade_features import (  # noqa: E402
    build_features,
    cascade_events,
    feature_path,
    write_features,
)


def default_user_data() -> Path:
    return BACKEND_DIR.parent / "user_data"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build 1m liquidation-cascade features")
    parser.add_argument("--pair", default="BTC/USDT:USDT", help="freqtrade pair")
    parser.add_argument("--start", required=True, help="UTC start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="UTC end date, YYYY-MM-DD")
    parser.add_argument(
        "--klines-source",
        choices=("binance", "okx"),
        default="binance",
        help="price/volume base: Binance archive (has taker split) or the local OKX json.gz "
             "(same venue as execution, no taker split)",
    )
    parser.add_argument(
        "--no-derivatives",
        action="store_true",
        help="skip the Binance OI/depth archives (price + volume features only)",
    )
    parser.add_argument("--user-data", default=str(default_user_data()))
    parser.add_argument("--cache", default="", help="raw archive cache (default: <user_data>/liquidation/raw_binance)")
    parser.add_argument("--trades", action="store_true", help="include aggTrades (slow: ~90MB/day/pair)")
    parser.add_argument("--funding", action="store_true", help="include the funding-rate history")
    parser.add_argument(
        "--liquidations",
        action="store_true",
        help="merge the liquidation flow collected by scripts/collect_liquidations.py",
    )
    parser.add_argument(
        "--okx-derivatives",
        action="store_true",
        help="merge the collected OKX open interest + taker volume (Rubik, 5m)",
    )
    parser.add_argument(
        "--klines-period",
        choices=("monthly", "daily"),
        default="monthly",
        help="fetch klines per month (1 file/month) or per day (default: monthly)",
    )
    parser.add_argument("--window", type=int, default=60, help="liquidation percentile window in minutes")
    parser.add_argument("--quantile", type=float, default=0.95, help="liquidation percentile")
    parser.add_argument("--report", type=int, default=8, help="how many trigger rows to print")
    parser.add_argument("--pause", type=float, default=0.8, help="seconds between archive downloads")
    parser.add_argument("--retries", type=int, default=5, help="archive download retries")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    user_data = Path(args.user_data)
    cache = Path(args.cache) if args.cache else user_data / "liquidation" / "raw_binance"
    symbol = to_binance_symbol(args.pair)
    start, end = parse_day(args.start), parse_day(args.end)
    days = days_between(start, end)
    progress = (lambda _msg: None) if args.quiet else (lambda msg: print(f"  {msg}", flush=True))
    archive = BinanceArchive(cache, progress=progress, pause=args.pause, retries=args.retries)

    print(f"[1/3] building feature inputs for {args.pair}: {start} .. {end} ({len(days)} days)")
    klines_parts: list[pd.DataFrame] = []
    metrics_parts: list[pd.DataFrame] = []
    depth_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    skipped: dict[str, int] = {}
    if args.klines_source == "okx":
        klines_parts.append(load_okx_klines(user_data, args.pair, start, end, progress))
    elif args.klines_period == "monthly":
        for month in sorted({month_of(day) for day in days}):
            frame = _load_month(archive, "klines", symbol, month, progress)
            if frame.empty:
                skipped["klines"] = skipped.get("klines", 0) + 1
            klines_parts.append(frame)
    for day in days:
        if args.klines_source == "binance" and args.klines_period == "daily":
            frame = _load_day(archive, "klines", symbol, day, progress)
            if frame.empty:
                skipped["klines"] = skipped.get("klines", 0) + 1
            klines_parts.append(frame)
        if args.no_derivatives:
            continue
        for dataset, bucket in (("metrics", metrics_parts), ("bookDepth", depth_parts)):
            frame = _load_day(archive, dataset, symbol, day, progress)
            if frame.empty:
                skipped[dataset] = skipped.get(dataset, 0) + 1
            bucket.append(frame)
        if args.trades:
            frame = _load_day(archive, "aggTrades", symbol, day, progress)
            if frame.empty:
                skipped["aggTrades"] = skipped.get("aggTrades", 0) + 1
            trade_parts.append(frame)
            if not args.quiet:
                print(f"  {day}: trades={len(trade_parts[-1]):,}", flush=True)

    klines = _concat(klines_parts)
    metrics = _concat(metrics_parts)
    depth = _concat(depth_parts)
    trades = _concat(trade_parts) if trade_parts else None
    funding = None
    if args.funding:
        months = sorted({month_of(day) for day in days})
        funding = _concat(
            [_load_month(archive, "fundingRate", symbol, month, progress) for month in months]
        )

    liquidations = None
    okx_oi = None
    okx_taker = None
    if args.liquidations or args.okx_derivatives:
        from app.services.liquidation_collector import (  # noqa: PLC0415
            aggregate_liquidations,
            pair_slug,
            read_jsonl_frame,
        )

        slug = pair_slug(args.pair)
        base = Path(args.user_data) / "liquidation"
        start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) + 86_400_000
        if args.liquidations:
            liquidations = aggregate_liquidations(base / f"{slug}-liq-raw.jsonl", start_ms, end_ms)
            print(f"      collected liquidations: {len(liquidations):,} records")
        if args.okx_derivatives:
            oi_frame = read_jsonl_frame(base / f"{slug}-okx-oi.jsonl")
            taker_frame = read_jsonl_frame(base / f"{slug}-okx-taker.jsonl")
            if not oi_frame.empty:
                oi_frame = oi_frame[
                    (oi_frame["ts"] >= start_ms) & (oi_frame["ts"] < end_ms)
                ].copy()
            if not taker_frame.empty:
                taker_frame = taker_frame[
                    (taker_frame["ts"] >= start_ms) & (taker_frame["ts"] < end_ms)
                ].copy()
            okx_oi = oi_frame if not oi_frame.empty else None
            okx_taker = taker_frame if not taker_frame.empty else None
            print(
                f"      collected OKX derivatives: oi={0 if okx_oi is None else len(okx_oi):,} "
                f"taker={0 if okx_taker is None else len(okx_taker):,}"
            )

    print(
        f"[2/3] building features: klines={len(klines):,} metrics={len(metrics):,} "
        f"depth={len(depth):,} trades={0 if trades is None else len(trades):,}"
    )
    if skipped:
        print(f"      skipped (unavailable/missing): {skipped}")
    features = build_features(
        klines,
        metrics=metrics,
        depth=depth,
        trades=trades,
        funding=funding,
        liquidations=liquidations,
        okx_oi=okx_oi,
        okx_taker=okx_taker,
        window=args.window,
        quantile=args.quantile,
    )
    target = feature_path(user_data, args.pair)
    write_features(features, target)

    first = pd.to_datetime(int(features["date"].iloc[0]), unit="ms", utc=True)
    last = pd.to_datetime(int(features["date"].iloc[-1]), unit="ms", utc=True)
    print(f"[3/3] wrote {target}")
    print(f"      rows={len(features):,}  {first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M} UTC")
    print(f"      liquidations measured: {bool(features['cx_has_liquidations'].max())}")
    if args.report:
        for side in ("long", "short"):
            events = cascade_events(features, side=side, move_pct=0.005, flush_score=1.5)
            print(f"      {side} flush candidates at >=0.5% 1m move: {len(events):,}")
            if not events.empty:
                top = events.reindex(
                    events[f"cx_flush_{side}_score"].abs().sort_values(ascending=False).index
                ).head(args.report)
                top = top.assign(time=pd.to_datetime(top["date"], unit="ms", utc=True))
                columns = [
                    c
                    for c in ("time", "cx_ret_1m", "cx_taker_imbalance", "cx_oi_chg_5m_pct",
                              "cx_depth_imbalance_1pct", "cx_flush_long_score", "cx_flush_short_score")
                    if c in top.columns
                ]
                with pd.option_context("display.width", 200, "display.max_columns", 50):
                    print(top[columns].to_string(index=False))
    return 0


def _load_day(
    archive: BinanceArchive, dataset: str, symbol: str, day: date, progress
) -> pd.DataFrame:
    try:
        return archive.load(dataset, symbol, day=day, interval="1m")
    except BinanceArchiveError as exc:
        progress(f"{dataset} unavailable for {day}: {exc}")
        return pd.DataFrame()


def _concat(parts: list[pd.DataFrame]) -> pd.DataFrame:
    usable = [frame for frame in parts if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame()
    return pd.concat(usable, ignore_index=True)


def _load_month(archive: BinanceArchive, dataset: str, symbol: str, month: str, progress) -> pd.DataFrame:
    try:
        return archive.load(dataset, symbol, month=month, interval="1m")
    except BinanceArchiveError as exc:
        progress(f"{dataset} unavailable for {month}: {exc}")
        return pd.DataFrame()


def load_okx_klines(
    user_data: Path, pair: str, start, end, progress
) -> pd.DataFrame:
    """Read the locally downloaded OKX 1m candles and normalise them.

    ``PublicDataDownloader`` stores ``[ts, o, h, l, c, vol]`` where ``vol`` is in
    contracts for swaps, so contract value is used to derive base/quote volume.
    OKX candles carry no taker split - the flow columns stay empty and the flush
    score simply renormalises over the components it does have.
    """
    slug = pair.replace("/", "_").replace(":", "_")
    path = Path(user_data) / "data" / "okx" / "futures" / f"{slug}-1m-futures.json.gz"
    if not path.exists():
        raise SystemExit(f"missing OKX 1m data: {path} (download it first)")
    import gzip as _gzip
    import json as _json

    rows = _json.loads(_gzip.decompress(path.read_bytes()).decode())
    frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000) + 86_400_000
    frame = frame[(frame["open_time"] >= start_ms) & (frame["open_time"] < end_ms)].reset_index(drop=True)

    ct_val = _okx_contract_value(user_data, pair)
    base_volume = frame["volume"] * ct_val
    frame["quote_volume"] = base_volume * frame["close"]
    frame["taker_buy_volume"] = float("nan")
    frame["taker_buy_quote_volume"] = float("nan")
    frame["count"] = float("nan")
    progress(
        f"okx klines: {len(frame):,} rows ({path.name}), ctVal={ct_val}, "
        f"no taker split available"
    )
    return frame


def _okx_contract_value(user_data: Path, pair: str) -> float:
    """Contract value (base currency per contract) for the swap, defaulting to 0.01."""
    path = Path(user_data) / "data" / "okx_instruments_SWAP.json"
    inst_id = pair.split(":")[0].replace("/", "-") + "-SWAP"
    try:
        import json as _json

        payload = _json.loads(path.read_text(encoding="utf-8"))
        for instrument in payload.get("data", []):
            if instrument.get("instId") == inst_id:
                return float(instrument.get("ctVal") or 0.01)
    except Exception:
        pass
    return 0.01


if __name__ == "__main__":
    raise SystemExit(main())
