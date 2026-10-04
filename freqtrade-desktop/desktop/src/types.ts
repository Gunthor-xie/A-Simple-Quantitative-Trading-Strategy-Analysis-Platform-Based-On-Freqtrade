export interface BotConnection {
  id?: string;
  name: string;
  kind: "local" | "remote";
  url: string;
  username: string;
  password?: string | null;
  ws_token?: string | null;
  enabled: boolean;
  created_at?: string;
}

export interface ConnectionOut {
  id: string;
  name: string;
  kind: "local" | "remote";
  url: string;
  username: string;
  has_password: boolean;
  enabled: boolean;
  created_at: string;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  version?: string | null;
}

export interface BacktestParams {
  strategy: string;
  exchange: string;
  pairs: string[];
  timerange: string;
  timeframe: string;
  trading_mode: "spot" | "futures";
  margin_mode: "isolated" | "cross";
  dry_run_wallet: number;
  stake_amount: string;
  max_open_trades: number;
  fee?: number | null;
  enable_protections: boolean;
  notes?: string;
}

export interface PairResult {
  pair: string;
  trades: number;
  avg_profit_pct: number;
  total_profit_abs: number;
  total_profit_pct: number;
  avg_duration: string;
  win: number;
  draw: number;
  loss: number;
  win_pct: number;
}

export interface TagResult {
  key: string;
  trades: number;
  profit_total_pct: number;
  profit_total_abs: number;
}

export interface BacktestResult {
  strategy: string;
  timerange: string;
  backtest_start: string;
  backtest_end: string;
  backtest_days: number;
  total_trades: number;
  trade_count_long: number;
  trade_count_short: number;
  win: number;
  draw: number;
  loss: number;
  winrate: number;
  profit_total: number;
  profit_total_abs: number;
  profit_total_percent: number;
  profit_factor: number | null;
  expectancy: number;
  expectancy_ratio: number;
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  max_drawdown_account: number;
  max_drawdown_abs: number;
  duration_avg: string;
  market_change: number;
  results_per_pair: PairResult[];
  results_per_enter_tag: TagResult[];
  results_per_exit_reason: TagResult[];
  trades: Record<string, unknown>[];
}

export interface BacktestRun {
  id: number;
  params: BacktestParams;
  status: "queued" | "running" | "done" | "error";
  error?: string | null;
  result?: BacktestResult | null;
  result_file?: string | null;
  created_at: string;
  finished_at?: string | null;
}

export interface ScoreWeights {
  sharpe: number;
  sortino: number;
  calmar: number;
  profit_factor: number;
  winrate: number;
  max_drawdown: number;
  expectancy: number;
}

export interface MetricScore {
  name: string;
  label: string;
  value: number | null;
  baseline: number | null;
  score: number;
  weight: number;
  missing: boolean;
  note?: string | null;
}

export interface ScoreReport {
  composite: number;
  metrics: MetricScore[];
  baseline_source: string;
  warnings: string[];
}

export interface ChartCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartMarker {
  time: number;
  position: string;
  color: string;
  shape: string;
  text: string;
}

export interface SignalEvent {
  strategy: string;
  time: string;
  pair: string;
  side: "long" | "short" | "exit";
  reason: string;
  price?: number | null;
  created_at?: string;
}

export interface ChartData {
  candles: ChartCandle[];
  indicators: Record<string, (number | null)[]>;
  markers: ChartMarker[];
  signals: SignalEvent[];
  total: number;
  coverage?: {
    start: number;
    end: number;
    count: number;
    expected: number;
    fill_ratio: number;
    has_gap: boolean;
  } | null;
  overlays?: TradeOverlay[];
}

export interface TradePoint {
  time: number;
  price: number;
  side: string;
  kind: string;
  pnl?: number | null;
  reason?: string;
}

export interface TradeOverlay {
  trade_id: number;
  entry: TradePoint | null;
  exit: TradePoint | null;
  pnl?: number | null;
  color: string;
}

export interface AppSettings {
  data_root: string;
  export_dir: string;
  z_soft: number;
  z_hard: number;
  http_proxy?: string;
}

export interface StrategyInfo {
  name: string;
  file: string;
  path: string;
}

export interface StrategyValidateResult {
  ok: boolean;
  name: string;
  errors: string[];
  warnings: string[];
}

export interface JobState {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "error";
  message: string;
  created_at: string;
  finished_at?: string | null;
}

export interface SettingsStatus {
  freqtrade_available: boolean;
  freqtrade_version: string;
  freqtrade_error?: string;
  user_data: string;
  keyring_available: boolean;
  default_db: string;
}

export interface BackendHealth {
  status: string;
  version: string;
  features: string[];
}
