from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BotConnection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str
    kind: Literal["local", "remote"] = "local"
    url: str = "http://127.0.0.1:8080"
    username: str = "Freqtrader"
    password: str | None = None
    ws_token: str | None = None
    enabled: bool = True
    created_at: str = ""


class ConnectionOut(BaseModel):
    id: str
    name: str
    kind: Literal["local", "remote"]
    url: str
    username: str
    has_password: bool
    enabled: bool
    created_at: str


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    version: str | None = None


class StrategyInfo(BaseModel):
    name: str
    file: str = ""
    path: str = ""


class StrategyValidateResult(BaseModel):
    ok: bool
    name: str
    errors: list[str] = []
    warnings: list[str] = []


class BacktestParams(BaseModel):
    strategy: str
    exchange: str = "okx"
    pairs: list[str] = Field(default_factory=lambda: ["BTC/USDT"])
    timerange: str = "20240101-"
    timeframe: str = "5m"
    timeframe_detail: str | None = None  # finer timeframe for intrabar simulation
    trading_mode: Literal["spot", "futures"] = "spot"
    margin_mode: Literal["isolated", "cross"] = "isolated"
    dry_run_wallet: float = 1000.0
    stake_amount: str = "unlimited"
    max_open_trades: int = 3
    fee: float | None = None
    enable_protections: bool = False
    notes: str = ""


class PairResult(BaseModel):
    pair: str = ""
    trades: int = 0
    avg_profit_pct: float = 0.0
    total_profit_abs: float = 0.0
    total_profit_pct: float = 0.0
    avg_duration: str = ""
    win: int = 0
    draw: int = 0
    loss: int = 0
    win_pct: float = 0.0


class TagResult(BaseModel):
    key: str = ""
    trades: int = 0
    profit_total_pct: float = 0.0
    profit_total_abs: float = 0.0


class BacktestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategy: str = ""
    timerange: str = ""
    backtest_start: str = ""
    backtest_end: str = ""
    backtest_days: int = 0
    total_trades: int = 0
    trade_count_long: int = 0
    trade_count_short: int = 0
    win: int = 0
    draw: int = 0
    loss: int = 0
    winrate: float = 0.0
    profit_total: float = 0.0
    profit_total_abs: float = 0.0
    profit_total_percent: float = 0.0
    profit_factor: float | None = None
    expectancy: float = 0.0
    expectancy_ratio: float = 0.0
    sharpe: float | None = None
    sortino: float | None = None
    calmar: float | None = None
    max_drawdown_account: float = 0.0
    max_drawdown_abs: float = 0.0
    duration_avg: str = ""
    market_change: float = 0.0
    results_per_pair: list[PairResult] = Field(default_factory=list)
    results_per_enter_tag: list[TagResult] = Field(default_factory=list)
    results_per_exit_reason: list[TagResult] = Field(default_factory=list)
    trades: list[dict] = Field(default_factory=list)


class BacktestRun(BaseModel):
    id: int
    params: BacktestParams
    status: Literal["queued", "running", "done", "error"]
    error: str | None = None
    result: BacktestResult | None = None
    result_file: str | None = None
    created_at: str = ""
    finished_at: str | None = None


class BacktestCompareItem(BaseModel):
    run_id: int
    score: float | None = None
    result: BacktestResult | None = None
    warnings: list[str] = []


class ScoreWeights(BaseModel):
    sharpe: float = 0.20
    sortino: float = 0.20
    calmar: float = 0.10
    profit_factor: float = 0.15
    winrate: float = 0.10
    max_drawdown: float = 0.15
    expectancy: float = 0.10

    @model_validator(mode="after")
    def _sum_is_one(self) -> "ScoreWeights":
        total = round(
            self.sharpe
            + self.sortino
            + self.calmar
            + self.profit_factor
            + self.winrate
            + self.max_drawdown
            + self.expectancy,
            4,
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"权重之和必须为 1，当前为 {total}")
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "profit_factor": self.profit_factor,
            "winrate": self.winrate,
            "max_drawdown": self.max_drawdown,
            "expectancy": self.expectancy,
        }


class MetricScore(BaseModel):
    name: str
    label: str = ""
    value: float | None = None
    baseline: float | None = None
    score: float = 0.0
    weight: float = 0.0
    missing: bool = False
    note: str | None = None


class ScoreReport(BaseModel):
    composite: float = 0.0
    metrics: list[MetricScore] = Field(default_factory=list)
    baseline_source: str = "default"
    warnings: list[str] = Field(default_factory=list)


class SignalEvent(BaseModel):
    strategy: str = ""
    time: str = ""
    pair: str = ""
    side: str = "long"
    reason: str = ""
    price: float | None = None
    created_at: str = ""


class ChartCandle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class ChartMarker(BaseModel):
    time: int
    position: str = "aboveBar"
    color: str = "#26a69a"
    shape: str = "arrowUp"
    text: str = ""


class ChartData(BaseModel):
    candles: list[ChartCandle] = Field(default_factory=list)
    indicators: dict[str, list[float | None]] = Field(default_factory=dict)
    markers: list[ChartMarker] = Field(default_factory=list)
    signals: list[SignalEvent] = Field(default_factory=list)
    total: int = 0
    coverage: ChartCoverage | None = None
    overlays: list[TradeOverlay] = Field(default_factory=list)


class DownloadParams(BaseModel):
    exchange: str = "okx"
    pairs: list[str] = Field(default_factory=lambda: ["BTC/USDT:USDT"])
    timeframes: list[str] = Field(default_factory=lambda: ["15m", "1h", "4h"])
    timerange: str | None = None
    trading_mode: Literal["spot", "futures"] = "spot"
    data_format: str = "jsongz"
    candle_types: list[str] = Field(default_factory=list)


class AppSettings(BaseModel):
    data_root: str = ""
    export_dir: str = ""
    z_soft: float = 2.0
    z_hard: float = 3.0
    http_proxy: str = ""


class ChartCoverage(BaseModel):
    start: int = 0
    end: int = 0
    count: int = 0
    expected: int = 0
    fill_ratio: float = 1.0
    has_gap: bool = False


class TradePoint(BaseModel):
    time: int = 0
    price: float = 0.0
    side: str = "long"
    kind: str = "entry"  # entry | exit
    pnl: float | None = None
    reason: str = ""


class TradeOverlay(BaseModel):
    trade_id: int = 0
    entry: TradePoint | None = None
    exit: TradePoint | None = None
    pnl: float | None = None
    color: str = ""


class BuildConfigParams(BaseModel):
    exchange: str = "okx"
    trading_mode: Literal["spot", "futures"] = "spot"
    margin_mode: Literal["isolated", "cross"] = "isolated"
    stake_currency: str = "USDT"
    pairs: list[str] = Field(default_factory=lambda: ["BTC/USDT:USDT"])
    timeframe: str = "5m"
    dry_run: bool = True
    dry_run_wallet: float = 1000.0
    stake_amount: str = "unlimited"
    max_open_trades: int = 3
    force_entry_enable: bool = False
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    api_port: int = 8080


class JobState(BaseModel):
    id: str
    kind: str
    status: Literal["queued", "running", "done", "error"]
    message: str = ""
    created_at: str = ""
    finished_at: str | None = None


class FundingOpportunity(BaseModel):
    pair: str
    symbol: str = ""
    # --- current funding (cheap: same call already used for filtering) ---
    funding_rate: float | None = None
    funding_annualized: float | None = None
    funding_interval_hours: float = 8.0
    settlements_per_day: float = 3.0
    next_settlement_ms: int | None = None
    next_funding_rate: float | None = None
    min_funding_rate: float | None = None
    max_funding_rate: float | None = None
    premium: float | None = None
    interest_rate: float | None = None
    # --- basis (current) + liquidity ---
    basis_pct: float | None = None
    adv_usd: float | None = None
    last_price: float | None = None
    updated_ms: int | None = None
    # --- spot availability (a hedge needs a spot leg) ---
    has_spot: bool = False
    spot_inst: str | None = None
    # --- history-derived persistence (one extra call, top rows only) ---
    history_count: int | None = None
    funding_mean: float | None = None
    funding_mean_annualized: float | None = None
    funding_std: float | None = None
    streak: int | None = None
    reversal_freq: float | None = None
    half_life: float | None = None
    source: str = "okx-live"
    note: str = ""


class FundingBasisStats(BaseModel):
    pair: str
    inst_perp: str = ""
    inst_index: str = ""
    count: int = 0
    current: float | None = None
    mean: float | None = None
    volatility: float | None = None
    percentile: float | None = None
    min: float | None = None
    max: float | None = None
    max_abs: float | None = None
    half_life: float | None = None


class FundingPoint(BaseModel):
    time: int
    rate: float
    annualized: float
    basis_pct: float | None = None


class FundingHistory(BaseModel):
    pair: str
    interval_hours: float = 8.0
    settlements_per_day: float = 3.0
    points: list[FundingPoint] = Field(default_factory=list)


class FundingScanResult(BaseModel):
    generated_ms: int = 0
    count: int = 0
    source: str = "okx-live"
    items: list[FundingOpportunity] = Field(default_factory=list)


class ArbRiskSettings(BaseModel):
    """Position risk-check thresholds and the fee assumption (all editable).

    Values are accepted as-is so the UI can flag out-of-range entries in red
    rather than silently rejecting them; only non-positive thresholds - which
    would disable the checks entirely - are refused.
    """

    warn_liq_distance_pct: float = Field(default=0.12, gt=0)
    max_delta_pct: float = Field(default=0.03, gt=0)
    fee_bps: float = Field(default=5.0, ge=0)
