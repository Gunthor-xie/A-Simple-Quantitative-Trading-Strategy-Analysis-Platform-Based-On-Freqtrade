from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.services import factor_panel as fp
from app.services import factor_lib as fl

BAR_MS = 3_600_000
BASE_TS = 1_780_000_000_000  # arbitrary fixed UTC hour


def _write(path: Path, rows: list[list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(rows).encode()))


def make_local_files(user_data: Path, pair: str, hours: int = 300, *,
                     seed: int = 3, index_offset: float = 0.0) -> pd.DataFrame:
    """Write candles + funding + index files in the freqtrade layout."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + 0.002 * rng.standard_normal(hours))
    ts = BASE_TS + np.arange(hours) * BAR_MS
    candles = [[int(t), float(c), float(c) * 1.001, float(c) * 0.999, float(c),
                float(100 + i)] for i, (t, c) in enumerate(zip(ts, close))]
    index = [[int(t), float(c) * (1 + index_offset)] for t, c in zip(ts, close)]
    funding = [[int(BASE_TS + 8 * i * BAR_MS), 0.0001 * (i % 3 - 1), 0, 0, 0, 0]
               for i in range(hours // 8 + 1)]
    _write(fp.candle_path(user_data, pair, "1h", "futures"), candles)
    _write(fp.candle_path(user_data, pair, "1h", "index"), index)
    _write(fp.funding_path(user_data, pair), funding)
    return pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])


def test_pair_name_roundtrip():
    assert fp.to_pair("TSLA-USDT-SWAP") == "TSLA/USDT:USDT"
    assert fp.pair_symbol("TSLA/USDT:USDT") == "TSLA_USDT_USDT"
    with pytest.raises(fp.FactorDataError):
        fp.to_pair("WEIRD")


def test_build_panel_is_causal_and_aligned(tmp_path: Path):
    make_local_files(tmp_path, "AAA/USDT:USDT", hours=48, index_offset=0.001)
    panel = fp.build_panel(tmp_path, ["AAA/USDT:USDT"], "1h")

    assert list(panel["ts"]) == sorted(panel["ts"])
    assert len(panel) == 48
    # Index merge is a backward as-of join: the premium is visible on every bar.
    assert panel["index_close"].notna().all()
    assert abs(float(panel["index_close"].iloc[-1] / panel["close"].iloc[-1] - 1.001)) < 1e-9

    # Funding only becomes observable at (and after) each 8h settlement.
    settlements = panel[panel["ts"] % (8 * BAR_MS) == BASE_TS % (8 * BAR_MS)]
    assert len(settlements) == 6
    before_first_settlement = panel[panel["ts"] < BASE_TS + 8 * BAR_MS]
    assert len(before_first_settlement) == 8
    first_known = float(before_first_settlement["funding_rate"].iloc[0])
    assert first_known == pytest.approx(-0.0001)
    # The value must not change until the next settlement arrives.
    assert before_first_settlement["funding_rate"].nunique() == 1


def test_panel_roundtrip(tmp_path: Path):
    make_local_files(tmp_path, "AAA/USDT:USDT", hours=72)
    panel = fp.build_panel(tmp_path, ["AAA/USDT:USDT"], "1h")
    target = fp.write_panel(panel, tmp_path, "test_pool", "1h")
    assert target.exists()
    again = fp.read_panel(tmp_path, "test_pool", "1h")
    pd.testing.assert_frame_equal(panel, again)
    with pytest.raises(fp.FactorDataError):
        fp.read_panel(tmp_path, "missing_pool", "1h")


def test_panel_converts_contract_volume_to_base_units(tmp_path: Path):
    """Crypto SWAP volume is in contracts; ctVal must scale it to base units."""
    make_local_files(tmp_path, "AAA/USDT:USDT", hours=48)
    snapshot = {"code": "0", "data": [
        {"instId": "AAA-USDT-SWAP", "ctVal": "0.01", "ctValCcy": "AAA"},
    ]}
    path = tmp_path / "data" / "okx_instruments_SWAP.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    panel = fp.build_panel(tmp_path, ["AAA/USDT:USDT"], "1h")
    raw = fp.load_candles(tmp_path, "AAA/USDT:USDT", "1h", "futures")
    assert float(panel["volume"].iloc[0]) == pytest.approx(float(raw["volume"].iloc[0]) * 0.01)
    assert fp.contract_values(tmp_path) == {"AAA/USDT:USDT": 0.01}


def test_universe_classification(tmp_path: Path):
    now = BASE_TS
    instruments = [
        {"instId": "BTC-USDT-SWAP", "listTime": str(now - 1000 * 86_400_000),
         "state": "live", "settleCcy": "USDT", "instCategory": "1", "lever": "100",
         "tickSz": "0.1"},
        {"instId": "TSLA-USDT-SWAP", "listTime": str(now - 120 * 86_400_000),
         "state": "live", "settleCcy": "USDT", "instCategory": "3", "lever": "25",
         "tickSz": "0.01"},
        {"instId": "NEW-USDT-SWAP", "listTime": str(now - 10 * 86_400_000),
         "state": "live", "settleCcy": "USDT", "instCategory": "3", "lever": "25",
         "tickSz": "0.01"},
        {"instId": "XAU-USDT-SWAP", "listTime": str(now - 500 * 86_400_000),
         "state": "live", "settleCcy": "USDT", "instCategory": "4", "lever": "25",
         "tickSz": "0.01"},
    ]
    tickers = [
        {"instId": "BTC-USDT-SWAP", "volCcy24h": "50000", "last": "100000"},
        {"instId": "TSLA-USDT-SWAP", "volCcy24h": "2000000", "last": "150"},
        {"instId": "NEW-USDT-SWAP", "volCcy24h": "5000000", "last": "10"},
        {"instId": "XAU-USDT-SWAP", "volCcy24h": "100000", "last": "2500"},
    ]
    config = fp.build_universe(
        tmp_path, crypto_min_days=730, crypto_min_adv=2e7,
        equity_min_days=90, equity_min_adv=5e6, now_ms=now,
        http_get=_fake_get(instruments, tickers),
    )
    assert [e["pair"] for e in config["pools"]["crypto_majors"]] == ["BTC/USDT:USDT"]
    assert [e["pair"] for e in config["pools"]["equity_liquid"]] == ["TSLA/USDT:USDT"]
    assert [e["pair"] for e in config["pools"]["commodity_index"]] == ["XAU/USDT:USDT"]
    assert config["excluded_count"] == 1  # the 10-day-old equity perp


def _fake_get(instruments: list[dict], tickers: list[dict]):
    """Serve cached snapshots so the universe test never touches the network."""
    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def getter(url: str, **kwargs):
        payload = instruments if "instruments" in url else tickers
        return Response({"code": "0", "data": payload})

    return getter


def test_factor_prefix_recomputation_matches(tmp_path: Path):
    """A factor computed on a prefix must equal the same rows of the full sample."""
    make_local_files(tmp_path, "AAA/USDT:USDT", hours=400, seed=11)
    panel = fp.build_panel(tmp_path, ["AAA/USDT:USDT"], "1h")
    cutoff = 300
    full = fl.compute_factors(fl.make_wide(panel), equity_pool=True)
    prefix = fl.compute_factors(fl.make_wide(panel.iloc[:cutoff]), equity_pool=True)
    for name, frame in full.items():
        left = frame.iloc[:cutoff - 1]
        right = prefix[name].iloc[:cutoff - 1]
        pd.testing.assert_frame_equal(left, right, check_names=False, atol=1e-12)


def test_equity_only_factors_skipped_for_crypto(tmp_path: Path):
    make_local_files(tmp_path, "AAA/USDT:USDT", hours=400)
    wide = fl.make_wide(fp.build_panel(tmp_path, ["AAA/USDT:USDT"], "1h"))
    crypto = fl.compute_factors(wide, equity_pool=False)
    assert "weekend_gap" not in crypto
    assert "mom_1d" in crypto
    equity = fl.compute_factors(wide, equity_pool=True)
    assert "weekend_gap" in equity


def test_momentum_factor_detects_autocorrelated_series():
    """A strongly autocorrelated panel must show positive momentum IC."""
    rng = np.random.default_rng(5)
    bars, pairs = 400, 8
    # Persistently trending assets: a slow AR(1) drift plus noise, so a past-window
    # return genuinely predicts the next window (the definition of momentum).
    drift = np.zeros((bars, pairs))
    for t in range(1, bars):
        drift[t] = 0.98 * drift[t - 1] + 0.0006 * rng.standard_normal(pairs)
    returns = drift + 0.004 * rng.standard_normal((bars, pairs))
    close = pd.DataFrame(100 * np.cumprod(1 + returns, axis=0))
    index = pd.Index(np.arange(bars) * BAR_MS)
    close.index = index
    wide = fl.Wide(
        close=close, open=close, high=close, low=close,
        volume=pd.DataFrame(1.0, index=index, columns=close.columns),
        funding=pd.DataFrame(0.0, index=index, columns=close.columns),
        index=close, ret=np.log(close).diff(),
        hour=pd.Index(np.zeros(bars, dtype=int)),
        dow=pd.Index(np.zeros(bars, dtype=int)),
    )
    momentum = fl.compute_factors(wide, ["mom_1d"])["mom_1d"]
    assert momentum.notna().to_numpy().any()
    fwd = close.shift(-24) / close - 1
    ic = factor_ic_helper(momentum, fwd)
    assert ic > 0.25


def factor_ic_helper(factor: pd.DataFrame, fwd: pd.DataFrame) -> float:
    from app.services.factor_screen import rank_ic

    series = rank_ic(factor, fwd, 3)
    return float(series.mean())
