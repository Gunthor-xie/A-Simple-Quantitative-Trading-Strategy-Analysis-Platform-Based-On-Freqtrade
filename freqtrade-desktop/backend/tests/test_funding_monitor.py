from __future__ import annotations

import pytest

from app.services.funding_monitor import (
    FundingMonitor,
    FundingTimeout,
    inst_to_pair,
    max_daily_amplitude,
    pair_to_inst,
    pair_to_symbol,
    spot_inst,
    suggest_leverage,
    symbol_to_inst,
    symbol_to_pair,
)


HOUR = 3_600_000
BASE = 1_767_225_600_000  # 2026-01-01 00:00 UTC


class _Resp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _router(routes: dict):
    """Build an injected ``http_get`` that answers by OKX path.

    A route value may be a payload dict, or a callable ``(params) -> payload``
    when the answer depends on the instrument.
    """

    def fake_get(url, params=None, timeout=None, proxies=None):
        for path, payload in routes.items():
            if url.endswith(path):
                return _Resp(payload(params or {}) if callable(payload) else payload)
        raise AssertionError(f"unexpected url {url}")

    return fake_get


def _okx_routes(**overrides) -> dict:
    routes = {
        "/api/v5/public/time": {"code": "0", "data": [{"ts": str(BASE)}]},
        # The same path serves both instTypes, so answer by params.
        "/api/v5/public/instruments": lambda params: {
            "code": "0",
            "data": (
                [{"instId": "BTC-USDT", "state": "live"}]
                if params.get("instType") == "SPOT"
                else [
                    {"instId": "BTC-USDT-SWAP", "settleCcy": "USDT", "state": "live"},
                    {"instId": "ETH-USDT-SWAP", "settleCcy": "USDT", "state": "live"},
                    {"instId": "ZERO-USDT-SWAP", "settleCcy": "USDT", "state": "live"},
                    # liquid, non-zero funding, but NO spot pair on OKX
                    {"instId": "STOCK-USDT-SWAP", "settleCcy": "USDT", "state": "live"},
                ]
            ),
        },
        "/api/v5/market/tickers": {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "last": "100", "volCcy24h": "20000"},  # $2M
                {"instId": "ETH-USDT-SWAP", "last": "10", "volCcy24h": "1000"},  # $10k -> dropped
                {"instId": "ZERO-USDT-SWAP", "last": "1", "volCcy24h": "5000000"},  # $5M, zero funding
                {"instId": "STOCK-USDT-SWAP", "last": "1", "volCcy24h": "5000000"},  # $5M, no spot
            ],
        },
        "/api/v5/market/index-tickers": {
            "code": "0",
            "data": [{"instId": "BTC-USDT", "idxPx": "99"}],
        },
        "/api/v5/public/funding-rate": lambda params: {
            "code": "0",
            "data": [
                {
                    "instId": params.get("instId"),
                    "fundingRate": "0" if params.get("instId") == "ZERO-USDT-SWAP" else "0.0001",
                    "fundingTime": str(BASE + 8 * HOUR),
                    "nextFundingTime": str(BASE + 16 * HOUR),
                    "nextFundingRate": "0.00012",
                    "minFundingRate": "-0.00375",
                    "maxFundingRate": "0.00375",
                    "premium": "-0.0004",
                    "interestRate": "0.0001",
                    "ts": str(BASE),
                }
            ],
        },
        "/api/v5/public/funding-rate-history": lambda params: {
            "code": "0",
            "data": [
                {"fundingTime": str(BASE - i * 8 * HOUR), "fundingRate": "0.0001"}
                for i in range(10)
            ],
        },
    }
    routes.update(overrides)
    return routes


def test_naming_helpers() -> None:
    assert symbol_to_pair("BTC_USDT_USDT") == "BTC/USDT:USDT"
    assert pair_to_symbol("BTC/USDT:USDT") == "BTC_USDT_USDT"
    assert symbol_to_inst("BTC_USDT_USDT") == "BTC-USDT-SWAP"
    assert pair_to_inst("BTC/USDT:USDT") == "BTC-USDT-SWAP"
    assert inst_to_pair("BTC-USDT-SWAP") == "BTC/USDT:USDT"
    assert spot_inst("BTC-USDT-SWAP") == "BTC-USDT"
    assert symbol_to_pair("BTC/USDT") == "BTC/USDT"


def test_amplitude_and_suggested_leverage() -> None:
    rows = [
        [BASE, 100, 105, 95, 100, 1],        # 10%
        [BASE + 86_400_000, 100, 130, 70, 100, 1],  # 60%  <- worst
    ]
    amplitude, ts = max_daily_amplitude(rows)
    assert amplitude == pytest.approx(0.6)
    assert ts == BASE + 86_400_000
    assert suggest_leverage(0.6) == 1
    assert suggest_leverage(0.15) == 3
    assert suggest_leverage(0.05) == 5
    assert suggest_leverage(0.0) == 5  # no data -> permissive cap


def test_live_scan_filters_and_ranks() -> None:
    routes = _okx_routes()
    monitor = FundingMonitor(http_get=_router(routes))
    # BTC (2M, positive, has spot) kept; ETH (<1M) dropped; ZERO (zero funding)
    # dropped; STOCK (no spot pair -> cannot hedge) dropped by require_spot.
    result = monitor.live_scan()
    assert result.source == "okx-live"
    assert result.count == 1
    row = result.items[0]
    assert row.pair == "BTC/USDT:USDT"
    assert row.funding_rate == pytest.approx(0.0001)
    assert row.funding_annualized == pytest.approx(0.1095)
    assert row.settlements_per_day == pytest.approx(3.0)
    assert row.basis_pct == pytest.approx((100 - 99) / 99)
    assert row.adv_usd == pytest.approx(2_000_000)
    assert row.has_spot is True
    assert row.spot_inst == "BTC-USDT"
    # cheap decision factors from the same funding-rate call
    assert row.next_settlement_ms == BASE + 8 * HOUR
    assert row.next_funding_rate == pytest.approx(0.00012)
    assert row.min_funding_rate == pytest.approx(-0.00375)
    assert row.max_funding_rate == pytest.approx(0.00375)
    assert row.premium == pytest.approx(-0.0004)
    assert row.interest_rate == pytest.approx(0.0001)
    # history-derived persistence factors
    assert row.history_count == 10
    assert row.funding_mean == pytest.approx(0.0001)
    assert row.funding_std == pytest.approx(0.0)
    assert row.streak == 10  # 10 consecutive positive settlements
    assert row.funding_mean_annualized == pytest.approx(0.1095)


def test_series_stats_mean_std_streak_reversal() -> None:
    from app.services.funding_monitor import series_stats

    stats = series_stats([0.001, 0.002, 0.003])
    assert stats["count"] == 3
    assert stats["mean"] == pytest.approx(0.002)
    assert stats["std"] == pytest.approx(0.00081649658, rel=1e-6)
    assert stats["streak"] == 3
    assert stats["reversal_freq"] == pytest.approx(0.0)

    mixed = series_stats([0.001, -0.001, 0.001, -0.001])
    assert mixed["streak"] == -1
    assert mixed["reversal_freq"] == pytest.approx(1.0)

    assert series_stats([])["count"] == 0


def test_ar1_half_life_detects_reversion() -> None:
    import random

    from app.services.funding_monitor import _ar1_half_life

    # Seeded AR(1): x[t] = 0.6*x[t-1] + noise -> persistent but mean-reverting.
    # (A noiseless geometric decay would sit on a straight line, phi = 1.)
    rng = random.Random(7)
    series = [0.001]
    for _ in range(80):
        series.append(0.6 * series[-1] + rng.gauss(0, 0.0015))
    half_life = _ar1_half_life(series)
    assert half_life is not None and half_life > 0

    # perfectly alternating -> anti-correlated, no persistence
    assert _ar1_half_life([0.01 if i % 2 == 0 else -0.01 for i in range(12)]) is None
    # monotone trend -> no reversion
    assert _ar1_half_life([0.001 * i for i in range(12)]) is None
    assert _ar1_half_life([0.001] * 12) is None  # no variance


def test_basis_series_and_stats() -> None:
    from app.services.funding_monitor import basis_series, basis_stats

    perp = [[BASE, 1, 1, 1, 101, 0], [BASE + 86_400_000, 1, 1, 1, 100, 0]]
    index = [[BASE, 1, 1, 1, 100, 0], [BASE + 86_400_000, 1, 1, 1, 100, 0]]
    basis = basis_series(perp, index)
    assert basis == pytest.approx([0.01, 0.0])

    stats = basis_stats(basis)
    assert stats["count"] == 2
    assert stats["current"] == pytest.approx(0.0)
    # percentile = share of history whose |basis| is <= |current| -> 1 of 2
    assert stats["percentile"] == pytest.approx(0.5)
    assert stats["max_abs"] == pytest.approx(0.01)

    assert basis_stats([])["count"] == 0


def test_scan_can_skip_history() -> None:
    monitor = FundingMonitor(http_get=_router(_okx_routes()))
    row = monitor.live_scan(with_history=False).items[0]
    assert row.history_count is None
    assert row.funding_std is None


def test_basis_stats_for() -> None:
    rows = [[BASE - 86_400_000, 1, 1, 1, 101, 0], [BASE, 1, 1, 1, 102, 0]]
    index = [[BASE - 86_400_000, 1, 1, 1, 100, 0], [BASE, 1, 1, 1, 100, 0]]
    routes = _okx_routes(**{
        "/api/v5/market/candles": {"code": "0", "data": rows},
        "/api/v5/market/index-candles": {"code": "0", "data": index},
    })
    stats = FundingMonitor(http_get=_router(routes)).basis_stats_for("BTC/USDT:USDT")
    assert stats["count"] == 2
    assert stats["current"] == pytest.approx(0.02)
    assert stats["inst_index"] == "BTC-USDT"


def test_scan_can_include_symbols_without_spot() -> None:
    monitor = FundingMonitor(http_get=_router(_okx_routes()))
    every = monitor.live_scan(require_spot=False)
    by_pair = {row.pair: row for row in every.items}
    assert set(by_pair) == {"BTC/USDT:USDT", "STOCK/USDT:USDT"}
    # BTC has a spot pair; STOCK is derivatives-only -> cannot be hedged.
    assert by_pair["BTC/USDT:USDT"].has_spot is True
    assert by_pair["STOCK/USDT:USDT"].has_spot is False
    assert by_pair["STOCK/USDT:USDT"].spot_inst is None


def test_live_scan_respects_volume_floor() -> None:
    monitor = FundingMonitor(http_get=_router(_okx_routes()))
    assert monitor.live_scan(min_volume_usd=10_000_000).count == 0


def test_live_scan_timeout_when_unreachable() -> None:
    def boom(url, params=None, timeout=None, proxies=None):
        raise TimeoutError("no route")

    with pytest.raises(FundingTimeout) as excinfo:
        FundingMonitor(http_get=boom).live_scan()
    # The underlying cause must be surfaced, not swallowed.
    assert "TimeoutError" in str(excinfo.value)


def test_explicit_proxy_is_forwarded() -> None:
    seen: list = []
    base = _router(_okx_routes())

    def spy(url, params=None, timeout=None, proxies=None):
        seen.append(proxies)
        return base(url, params=params, timeout=timeout, proxies=proxies)

    monitor = FundingMonitor(proxy="http://127.0.0.1:9999", http_get=spy)
    monitor.live_scan()
    assert seen
    assert all(p == {"http": "http://127.0.0.1:9999", "https": "http://127.0.0.1:9999"}
               for p in seen)


def test_candidate_proxies_prefers_explicit_and_keeps_local_fallback(monkeypatch) -> None:
    from app.services.proxy import LOCAL_PROXY, candidate_proxies

    for key in ("FTDESK_HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY",
                "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(key, raising=False)

    cands = candidate_proxies("http://explicit:1234")
    assert cands[0] == "http://explicit:1234"
    assert LOCAL_PROXY in cands  # the well-known local proxy stays as a fallback


def test_okx_client_skips_proxy_probe_with_transport(monkeypatch) -> None:
    """MockTransport clients must never trigger a real proxy probe."""
    import app.services.okx_client as okx_module
    from app.services.okx_client import OkxClient

    calls: list = []
    monkeypatch.setattr(okx_module, "resolve_proxy", lambda *a, **k: calls.append(1) or None)

    import httpx

    client = OkxClient("k", "s", "p", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    client.close()
    assert calls == []


def test_daily_stats_and_history() -> None:
    rows = [[BASE, 100, 150, 50, 100, 1], [BASE - 86_400_000, 100, 101, 99, 100, 1]]
    routes = _okx_routes(
        **{
            "/api/v5/market/candles": {"code": "0", "data": rows},
            "/api/v5/public/funding-rate-history": {
                "code": "0",
                "data": [
                    {"fundingTime": str(BASE - i * 8 * HOUR), "fundingRate": "0.0001"}
                    for i in range(5)
                ],
            },
        }
    )
    monitor = FundingMonitor(http_get=_router(routes))

    stats = monitor.daily_stats("BTC/USDT:USDT")
    assert stats["max_daily_amplitude"] == pytest.approx(1.0)
    assert stats["suggested_leverage"] == 1

    hist = monitor.history("BTC/USDT:USDT", days=30)
    assert hist.pair == "BTC/USDT:USDT"
    assert len(hist.points) == 5
    assert hist.interval_hours == pytest.approx(8.0)


def test_arb_endpoints_smoke() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert "funding_arb" in health["features"]
        # Risk settings round-trip (paper defaults, no network needed).
        assert client.get("/api/arb/risk").status_code == 200
        updated = client.put(
            "/api/arb/risk",
            json={"warn_liq_distance_pct": 0.2, "max_delta_pct": 0.05, "fee_bps": 7},
        )
        assert updated.status_code == 200
        assert updated.json()["fee_bps"] == 7
        # Out-of-range but positive values are accepted (the UI flags them red).
        assert client.put(
            "/api/arb/risk",
            json={"warn_liq_distance_pct": 0.9, "max_delta_pct": 0.5, "fee_bps": 50},
        ).status_code == 200
        # Restore defaults for other tests sharing the DB.
        client.put(
            "/api/arb/risk",
            json={"warn_liq_distance_pct": 0.12, "max_delta_pct": 0.03, "fee_bps": 5},
        )
        # Non-positive thresholds are refused.
        assert client.put(
            "/api/arb/risk",
            json={"warn_liq_distance_pct": 0, "max_delta_pct": 0.03, "fee_bps": 5},
        ).status_code == 422
