"""OKX **live** funding-rate / basis monitor (no local files).

Every number is fetched from OKX public REST endpoints on each scan; nothing is
read from disk. A scan enforces a hard deadline (default 10s): if OKX does not
answer in time the monitor raises :class:`FundingTimeout`, so the API can
report a network timeout instead of returning stale data.

Filtering applied to the scan (per product requirements):
* drop instruments whose 24h notional is below ``min_volume_usd`` (default $1M);
* drop instruments whose current funding rate is exactly zero.
"""

from __future__ import annotations

import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

import requests
from requests.adapters import HTTPAdapter

from ..schemas import FundingHistory, FundingOpportunity, FundingPoint, FundingScanResult
from .proxy import resolve_proxy


OKX_BASE = "https://www.okx.com"
DEFAULT_TIMEOUT = 10.0
DEFAULT_INTERVAL_HOURS = 8.0
# Settlements fetched per instrument for the persistence statistics (30 as the
# product spec asks, plus headroom so the streak/half-life have context).
HISTORY_ROWS = 60


class FundingTimeout(Exception):
    """OKX did not answer within the deadline."""


class FundingError(Exception):
    """OKX answered but rejected the request."""


# ------------------------------------------------------------- naming helpers
def symbol_to_pair(symbol: str) -> str:
    """``BTC_USDT_USDT`` -> ``BTC/USDT:USDT`` (falls back to ``BASE/USDT``)."""
    parts = symbol.split("_")
    if len(parts) >= 3:
        return f"{parts[0]}/{parts[1]}:{parts[2]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    return symbol


def pair_to_symbol(pair: str) -> str:
    """``BTC/USDT:USDT`` -> ``BTC_USDT_USDT``."""
    return pair.replace("/", "_").replace(":", "_")


def symbol_to_inst(symbol: str) -> str:
    """``BTC_USDT_USDT`` -> ``BTC-USDT-SWAP``."""
    parts = symbol.split("_")
    if len(parts) >= 3:
        return f"{parts[0]}-{parts[1]}-SWAP"
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return symbol


def pair_to_inst(pair: str) -> str:
    """``BTC/USDT:USDT`` -> ``BTC-USDT-SWAP`` (perp instrument id)."""
    return symbol_to_inst(pair_to_symbol(pair))


def inst_to_pair(inst_id: str) -> str:
    """``BTC-USDT-SWAP`` -> ``BTC/USDT:USDT``."""
    parts = inst_id.split("-")
    if len(parts) >= 3 and parts[2] == "SWAP":
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return inst_id


def spot_inst(inst_perp: str) -> str:
    """``BTC-USDT-SWAP`` -> ``BTC-USDT``."""
    return inst_perp[:-5] if inst_perp.endswith("-SWAP") else inst_perp


# ---------------------------------------------------------- amplitude helpers
def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _opt(value: Any) -> float | None:
    """Float or ``None`` (``""`` / missing values are common in OKX payloads)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ar1_half_life(values: list[float], *, min_obs: int = 6) -> float | None:
    """AR(1) half-life in observations; ``None`` when not mean-reverting.

    ``phi`` is the lag-1 autocorrelation: ``half_life = -ln2 / ln(phi)``.
    ``phi <= 0`` means no persistence, ``phi >= 1`` means no reversion.
    """
    if len(values) < min_obs:
        return None
    lagged = values[:-1]
    latest = values[1:]
    mean_x = sum(lagged) / len(lagged)
    mean_y = sum(latest) / len(latest)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(lagged, latest))
    var_x = sum((x - mean_x) ** 2 for x in lagged)
    var_y = sum((y - mean_y) ** 2 for y in latest)
    if var_x <= 0 or var_y <= 0:
        return None
    phi = cov / math.sqrt(var_x * var_y)
    if phi <= 0 or phi >= 1:
        return None
    return round(-math.log(2) / math.log(phi), 2)


def series_stats(rates: list[float]) -> dict[str, Any]:
    """Persistence statistics over a funding-rate series (oldest -> newest)."""
    count = len(rates)
    if count == 0:
        return {"count": 0, "mean": None, "std": None, "streak": None,
                "reversal_freq": None, "half_life": None}
    signs = [0 if r == 0 else (1 if r > 0 else -1) for r in rates]
    nonzero = [s for s in signs if s != 0]
    changes = sum(1 for i in range(1, len(nonzero)) if nonzero[i] != nonzero[i - 1])
    reversal = changes / (len(nonzero) - 1) if len(nonzero) > 1 else None

    # Signed run length at the tail: +3 = last 3 settlements all positive.
    streak = 0
    if nonzero:
        tail = nonzero[-1]
        for sign in reversed(nonzero):
            if sign != tail:
                break
            streak += 1
        streak *= tail

    return {
        "count": count,
        "mean": sum(rates) / count,
        "std": statistics.pstdev(rates) if count > 1 else 0.0,
        "streak": streak,
        "reversal_freq": reversal,
        "half_life": _ar1_half_life(rates),
    }


def basis_series(perp_rows: list, index_rows: list) -> list[float]:
    """``(perp − index)/index`` aligned by timestamp (oldest -> newest)."""
    index_by_ts = {int(row[0]): float(row[4]) for row in index_rows if len(row) >= 5}
    out: list[float] = []
    for row in sorted(perp_rows, key=lambda r: int(r[0])):
        if len(row) < 5:
            continue
        reference = index_by_ts.get(int(row[0]))
        if reference:
            out.append((float(row[4]) - reference) / reference)
    return out


def basis_stats(basis: list[float]) -> dict[str, Any]:
    """Where the current basis sits historically and how fast it converges."""
    count = len(basis)
    if count == 0:
        return {"count": 0, "current": None, "mean": None, "volatility": None,
                "percentile": None, "min": None, "max": None, "max_abs": None,
                "half_life": None}
    current = basis[-1]
    magnitude = abs(current)
    rank = sum(1 for value in basis if abs(value) <= magnitude)
    return {
        "count": count,
        "current": current,
        "mean": sum(basis) / count,
        "volatility": statistics.pstdev(basis) if count > 1 else 0.0,
        "percentile": rank / count,
        "min": min(basis),
        "max": max(basis),
        "max_abs": max(abs(value) for value in basis),
        # convergence speed of the *magnitude* of the basis
        "half_life": _ar1_half_life([abs(value) for value in basis]),
    }


def daily_amplitudes(rows: list) -> list[tuple[int, float]]:
    """``[[ts,o,h,l,c,...], ...]`` -> ``[(ts, (h-l)/o), ...]`` (skips bad rows)."""
    out: list[tuple[int, float]] = []
    for row in rows:
        try:
            ts = int(row[0])
            open_px = float(row[1])
            high = float(row[2])
            low = float(row[3])
        except (TypeError, ValueError, IndexError):
            continue
        if open_px <= 0:
            continue
        out.append((ts, (high - low) / open_px))
    return out


def max_daily_amplitude(rows: list) -> tuple[float, int | None]:
    amps = daily_amplitudes(rows)
    if not amps:
        return 0.0, None
    ts, amp = max(amps, key=lambda item: item[1])
    return amp, ts


def suggest_leverage(max_amplitude: float, *, budget: float = 0.5, cap: int = 5) -> int:
    """Very simple rule of thumb: keep one worst-day swing inside ``budget``.

    ``suggested = clamp(int(budget / max_amplitude), 1, cap)``

    A 5% worst day -> 5x (capped); 15% -> 3x; 30% -> 1x. The intent is only to
    stop obviously oversized leverage, not to model liquidation precisely.
    """
    if max_amplitude <= 0:
        return cap
    return max(1, min(cap, int(budget / max_amplitude)))


def _interval_hours(record: dict) -> float:
    """Funding settlement cadence from ``fundingTime`` -> ``nextFundingTime``."""
    funding_time = _f(record.get("fundingTime"))
    next_time = _f(record.get("nextFundingTime"))
    if funding_time and next_time > funding_time:
        hours = (next_time - funding_time) / 3_600_000
        if 0.5 <= hours <= 24:
            return hours
    return DEFAULT_INTERVAL_HOURS


def _annualize(rate: float, interval_hours: float) -> float:
    return rate * (24.0 / interval_hours) * 365.0


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt_ts(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


class FundingMonitor:
    """Live OKX funding/basis scanner with a hard deadline."""

    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_get: Callable[..., Any] | None = None,
        max_workers: int = 12,
    ) -> None:
        self.timeout = timeout
        self._max_workers = max(1, max_workers)
        self._session = requests.Session()
        self._session.trust_env = False
        # Match the connection pool to the worker count, otherwise urllib3
        # discards connections ("Connection pool is full") under load.
        adapter = HTTPAdapter(pool_connections=self._max_workers, pool_maxsize=self._max_workers)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._get = http_get or self._session.get
        self._custom_get = http_get is not None
        self._explicit_proxy = (proxy or "").strip() or None
        self._attempts: list[dict[str, str] | None] | None = None

    # ------------------------------------------------------------- transport
    def _resolve_proxies(self) -> list[dict[str, str] | None]:
        """Proxy candidates to try, in order; ``None`` = direct connection.

        Tests inject ``http_get`` (which ignores proxies); an explicit proxy is
        still honored so this path stays covered.
        """
        if self._attempts is not None:
            return self._attempts
        if self._custom_get:
            candidates: list[str | None] = (
                [self._explicit_proxy] if self._explicit_proxy else [None]
            )
        else:
            # Probe (memoised) so we do not silently connect direct on networks
            # where OKX is only reachable through a proxy.
            candidates = [resolve_proxy(self._explicit_proxy)]
        self._attempts = [{"http": c, "https": c} if c else None for c in candidates]
        return self._attempts

    def _fetch(self, path: str, params: dict[str, Any] | None, deadline: float) -> list:
        last_error: Exception | None = None
        for proxies in self._resolve_proxies():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            kwargs: dict[str, Any] = {"params": params or {}, "timeout": max(0.5, remaining)}
            if proxies:
                kwargs["proxies"] = proxies
            try:
                response = self._get(f"{OKX_BASE}{path}", **kwargs)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:  # noqa: BLE001 - try the next route
                last_error = exc
                continue
            if str(payload.get("code")) not in ("0",):
                raise FundingError(f"OKX 错误 {payload.get('code')}: {payload.get('msg')}")
            self._attempts = [proxies]  # pin the working route
            return payload.get("data") or []
        detail = f"{type(last_error).__name__}: {str(last_error)[:140]}" if last_error else "无可用通道"
        hint = "" if any(self._attempts or []) else (
            "（直连被阻断且未找到可用代理；请在「设置」填写可用代理后重试，"
            "例如 http://127.0.0.1:17891）"
        )
        raise FundingTimeout(f"网络连接超时：{path} 无实时数据反馈 [{detail}]{hint}")

    @staticmethod
    def _deadline() -> float:
        return time.monotonic() + DEFAULT_TIMEOUT

    def ping(self, deadline: float | None = None) -> None:
        """Connectivity probe; raises :class:`FundingTimeout` when unreachable."""
        self._fetch("/api/v5/public/time", None, deadline or self._deadline())

    # ----------------------------------------------------------------- scan
    def _gather(self, inst_ids: list[str], task, deadline: float, pick) -> dict[str, Any]:
        """Run ``task(inst_id) -> (inst_id, data)`` concurrently, keyed on ``pick``."""
        out: dict[str, Any] = {}
        if not inst_ids:
            return out
        workers = min(self._max_workers, len(inst_ids))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(task, inst_id) for inst_id in inst_ids]
            for future in as_completed(futures):
                if time.monotonic() > deadline:
                    for pending in futures:
                        pending.cancel()
                    break
                try:
                    inst_id, data = future.result()
                except Exception:  # noqa: BLE001 - skip individual failures
                    continue
                value = pick(data)
                if value is not None:
                    out[inst_id] = value
        return out

    def _funding_current(self, inst_ids: list[str], deadline: float) -> dict[str, dict]:
        """Current funding record per instrument (one call each, concurrent)."""

        def task(inst_id: str) -> tuple[str, list]:
            return inst_id, self._fetch(
                "/api/v5/public/funding-rate", {"instId": inst_id}, deadline
            )

        return self._gather(
            inst_ids, task, deadline, lambda data: data[0] if data else None
        )

    def _history_stats(self, inst_ids: list[str], deadline: float) -> dict[str, dict]:
        """Persistence statistics from recent settlements (one call each)."""

        def task(inst_id: str) -> tuple[str, list]:
            return inst_id, self._fetch(
                "/api/v5/public/funding-rate-history",
                {"instId": inst_id, "limit": str(HISTORY_ROWS)},
                deadline,
            )

        def pick(data: list) -> dict | None:
            if not data:
                return None
            ordered = sorted(data, key=lambda item: _f(item.get("fundingTime")))
            rates = [
                value
                for value in (_opt(item.get("fundingRate")) for item in ordered)
                if value is not None
            ]
            return series_stats(rates)

        return self._gather(inst_ids, task, deadline, pick)

    def live_scan(
        self,
        *,
        min_volume_usd: float = 1_000_000.0,
        limit: int = 100,
        quote: str = "USDT",
        require_spot: bool = True,
        with_history: bool = True,
        deadline: float | None = None,
    ) -> FundingScanResult:
        """Live scan.

        Cheap fields (interval, caps, premium, interest, countdown, next rate)
        come from the same funding-rate call already needed for filtering, so
        they are always populated. History-derived statistics cost one extra
        call per instrument, so they are fetched only for the rows that will be
        returned (``with_history``).
        """
        # Resolve the route first (memoised) so the 10s budget covers only the
        # actual OKX calls, not proxy probing.
        self._resolve_proxies()
        deadline = deadline or (time.monotonic() + self.timeout)
        # 1) connectivity first, so a dead network fails fast and clearly.
        self.ping(deadline)

        instruments = {
            item["instId"]: item
            for item in self._fetch(
                "/api/v5/public/instruments", {"instType": "SWAP"}, deadline
            )
        }
        # Many OKX perps (tokenised equities/commodities, pre-IPO) have NO spot
        # market, so a spot+perp hedge is impossible for them. Remember which
        # ones do have spot instead of failing later at plan time.
        spot_ids = {
            item["instId"]
            for item in self._fetch(
                "/api/v5/public/instruments", {"instType": "SPOT"}, deadline
            )
            if item.get("state") == "live"
        }
        tickers = self._fetch("/api/v5/market/tickers", {"instType": "SWAP"}, deadline)
        indexes = {
            item.get("instId"): item
            for item in self._fetch(
                "/api/v5/market/index-tickers", {"quoteCcy": quote}, deadline
            )
        }

        candidates: list[tuple[str, float, float]] = []
        for ticker in tickers:
            inst_id = ticker.get("instId", "")
            meta = instruments.get(inst_id)
            if not meta or meta.get("settleCcy") != quote or meta.get("state") != "live":
                continue
            last = _f(ticker.get("last"))
            # For SWAP, volCcy24h is base-currency volume -> USD notional = x last.
            notional = _f(ticker.get("volCcy24h")) * last
            if notional < min_volume_usd:  # requirement: drop < $1M/day
                continue
            candidates.append((inst_id, last, notional))

        funding = self._funding_current([c[0] for c in candidates], deadline)
        if candidates and not funding:
            raise FundingTimeout("网络连接超时：10 秒内未获取到任何实时资金费数据")

        items: list[FundingOpportunity] = []
        for inst_id, last, notional in candidates:
            record = funding.get(inst_id)
            if not record:
                continue
            rate = _opt(record.get("fundingRate"))
            if rate is None or rate == 0:  # requirement: drop zero funding
                continue
            interval = _interval_hours(record)
            base = inst_id.split("-")[0]
            index_px = _f((indexes.get(f"{base}-{quote}") or {}).get("idxPx"))
            basis = (last - index_px) / index_px if (last and index_px) else None
            annual = _annualize(rate, interval)
            pair = inst_to_pair(inst_id)
            spot_id = spot_inst(inst_id)
            has_spot = spot_id in spot_ids
            if require_spot and not has_spot:
                continue  # cannot build a spot+perp hedge
            items.append(
                FundingOpportunity(
                    pair=pair,
                    symbol=pair_to_symbol(pair),
                    funding_rate=rate,
                    funding_annualized=annual,
                    settlements_per_day=24.0 / interval,
                    funding_interval_hours=interval,
                    basis_pct=basis,
                    adv_usd=notional,
                    last_price=last,
                    updated_ms=int(_f(record.get("ts"))) or None,
                    next_settlement_ms=int(_f(record.get("fundingTime"))) or None,
                    next_funding_rate=_opt(record.get("nextFundingRate")),
                    min_funding_rate=_opt(record.get("minFundingRate")),
                    max_funding_rate=_opt(record.get("maxFundingRate")),
                    premium=_opt(record.get("premium")),
                    interest_rate=_opt(record.get("interestRate")),
                    has_spot=has_spot,
                    spot_inst=spot_id if has_spot else None,
                    source="okx-live",
                    note=_note(annual),
                )
            )

        items.sort(
            key=lambda r: (r.funding_annualized is not None, r.funding_annualized or 0.0),
            reverse=True,
        )
        items = items[:limit]

        # History-derived factors (mean/std/streak/reversal/half-life) cost one
        # extra call per instrument, so only enrich the rows we actually return.
        if with_history and items:
            stats = self._history_stats([pair_to_inst(r.pair) for r in items], deadline)
            for row in items:
                data = stats.get(pair_to_inst(row.pair))
                if not data:
                    continue
                row.history_count = data.get("count")
                row.funding_mean = data.get("mean")
                row.funding_std = data.get("std")
                row.streak = data.get("streak")
                row.reversal_freq = data.get("reversal_freq")
                row.half_life = data.get("half_life")
                if data.get("mean") is not None:
                    row.funding_mean_annualized = _annualize(
                        data["mean"], row.funding_interval_hours
                    )

        return FundingScanResult(
            generated_ms=_now_ms(),
            count=len(items),
            source="okx-live",
            items=items,
        )

    # -------------------------------------------------------------- history
    def history(
        self, pair: str, *, days: int = 90, deadline: float | None = None
    ) -> FundingHistory:
        self._resolve_proxies()
        deadline = deadline or (time.monotonic() + self.timeout)
        inst_id = pair_to_inst(pair)
        want = max(3, min(days * 3, 900))
        records: list[dict] = []
        before: int | None = None
        for _ in range(12):
            params: dict[str, Any] = {"instId": inst_id, "limit": "100"}
            if before:
                params["before"] = str(before)
            page = self._fetch("/api/v5/public/funding-rate-history", params, deadline)
            if not page:
                break
            records.extend(page)
            oldest = min(int(_f(item.get("fundingTime"))) for item in page)
            if len(page) < 100 or oldest <= 0 or (before and oldest >= before):
                break
            before = oldest
            if len(records) >= want or time.monotonic() > deadline:
                break

        records.sort(key=lambda item: int(_f(item.get("fundingTime"))))
        if not records:
            raise FundingTimeout("网络连接超时：未获取到资金费历史")
        interval = _interval_hours(records[-1])
        points = [
            FundingPoint(
                time=int(_f(item.get("fundingTime"))),
                rate=_f(item.get("fundingRate")),
                annualized=_annualize(_f(item.get("fundingRate")), interval),
            )
            for item in records[-want:]
            if _f(item.get("fundingTime"))
        ]
        return FundingHistory(
            pair=inst_to_pair(inst_id),
            interval_hours=interval,
            settlements_per_day=24.0 / interval,
            points=points,
        )

    # ------------------------------------------------------ daily amplitude
    def daily_stats(
        self, pair: str, *, days: int = 730, deadline: float | None = None
    ) -> dict[str, Any]:
        """Max/avg single-day amplitude over ``days`` plus a suggested leverage."""
        self._resolve_proxies()
        deadline = deadline or (time.monotonic() + self.timeout)
        inst_id = pair_to_inst(pair)
        rows = self._daily_candles(inst_id, days, deadline)
        amplitudes = daily_amplitudes(rows)
        if not amplitudes:
            raise FundingTimeout("网络连接超时：未获取到日K数据")
        max_ts, max_amp = max(amplitudes, key=lambda item: item[1])
        avg_amp = sum(amp for _, amp in amplitudes) / len(amplitudes)
        return {
            "pair": pair,
            "inst_id": inst_id,
            "days": len(amplitudes),
            "from": _fmt_ts(min(ts for ts, _ in amplitudes)),
            "to": _fmt_ts(max(ts for ts, _ in amplitudes)),
            "max_daily_amplitude": max_amp,
            "max_amplitude_date": _fmt_ts(max_ts),
            "avg_daily_amplitude": avg_amp,
            "suggested_leverage": suggest_leverage(max_amp),
            "rule": "建议杠杆 = clamp(int(0.5 / 单日最大振幅), 1, 5)",
        }

    def _daily_candles(self, inst_id: str, days: int, deadline: float,
                       path: str = "/api/v5/market/candles") -> list[list]:
        rows: list[list] = []
        after: int | None = None
        pages = max(1, min(10, (days // 100) + 1))
        for _ in range(pages):
            params: dict[str, Any] = {"instId": inst_id, "bar": "1D", "limit": "100"}
            if after:
                params["after"] = str(after)
            page = self._fetch(path, params, deadline)
            if not page:
                break
            rows.extend(page)
            oldest = min(int(_f(item[0])) for item in page)
            if len(page) < 100 or oldest <= 0:
                break
            after = oldest
            if time.monotonic() > deadline:
                break
        return rows

    def basis_stats_for(
        self, pair: str, *, days: int = 365, deadline: float | None = None
    ) -> dict[str, Any]:
        """Per-symbol basis history factors (expensive: 2 paginated candle calls).

        Fetched only after a symbol is picked, never during the scan.
        """
        self._resolve_proxies()
        deadline = deadline or (time.monotonic() + self.timeout)
        inst_perp = pair_to_inst(pair)
        inst_index = spot_inst(inst_perp)
        perp = self._daily_candles(inst_perp, days, deadline)
        index = self._daily_candles(
            inst_index, days, deadline, path="/api/v5/market/index-candles"
        )
        stats = basis_stats(basis_series(perp, index))
        stats.update({"pair": pair, "inst_perp": inst_perp, "inst_index": inst_index})
        return stats


def _note(annualized: float) -> str:
    if annualized > 0:
        return "正资金费：做多现货 / 做空永续，收取资金费"
    if annualized < 0:
        return "负资金费：做多永续 / 做空现货（需借币，成本高）"
    return "资金费为零，无套利空间"
