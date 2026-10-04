import type {
  BacktestRun,
  AppSettings,
  BackendHealth,
  ChartData,
  ConnectionOut,
  ConnectionTestResult,
  JobState,
  ScoreReport,
  ScoreWeights,
  SettingsStatus,
  SignalEvent,
  StrategyInfo,
  StrategyValidateResult,
} from "./types";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const FALLBACK_BASE = "http://127.0.0.1:8766";

export function getBaseUrl(): string {
  return window.desktop?.backendUrl || FALLBACK_BASE;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  let response: Response;
  try {
    response = await fetch(getBaseUrl() + path, { ...options, headers });
  } catch {
    let reason = "无法连接本地后端，请确认已启动（python -m uvicorn app.main:app --port 8765）";
    try {
      const probe = await fetch(getBaseUrl() + "/api/health");
      if (probe.ok) {
        reason = "后端可达但请求失败（接口可能报错或已重启），请刷新后重试";
      }
    } catch {
      /* backend unreachable */
    }
    throw new ApiError(reason, 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      const text = await response.text().catch(() => "");
      if (text) detail = text.slice(0, 400);
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) });
export const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export interface SnapshotMessage {
  type: "snapshot";
  backtests: BacktestRun[];
  signals_count: number;
  jobs: JobState[];
  connections: ConnectionOut[];
}

export function connectSnapshot(onMessage: (snapshot: SnapshotMessage) => void): WebSocket {
  const url = getBaseUrl().replace(/^http/, "ws") + "/api/ws";
  const ws = new WebSocket(url);
  ws.onmessage = (event) => {
    try {
      onMessage(JSON.parse(event.data) as SnapshotMessage);
    } catch {
      /* ignore malformed frames */
    }
  };
  return ws;
}

export const api = {
  getSettings: () => get<AppSettings>("/api/settings"),
  putSettings: (body: AppSettings) => put<AppSettings>("/api/settings", body),
  dataCoverage: () => get<Record<string, unknown>>("/api/data/coverage"),
  networkDiagnostics: (proxy?: string) =>
    get<Record<string, unknown>>(
      `/api/diagnostics/network${proxy ? `?proxy=${encodeURIComponent(proxy)}` : ""}`,
    ),
  localChart: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => qs.set(k, String(v)));
    return get<ChartData>(`/api/charts/local?${qs.toString()}`);
  },
  exportBacktest: (runId: number) =>
    post<JobState>(`/api/backtests/${runId}/export`),
  okxStatus: () => get<{ configured: boolean }>("/api/okx/status"),
  okxCredentials: (body: unknown) => post<{ ok: boolean; configured: boolean }>("/api/okx/credentials", body),
  okxSummary: () => get<Record<string, unknown>>("/api/okx/summary"),
  okxReconcile: (payload: unknown) => post<Record<string, unknown>>("/api/okx/reconcile", payload),
  settingsStatus: () => get<SettingsStatus>("/api/settings/status"),
  health: () => get<BackendHealth>("/api/health"),
  strategies: () => get<StrategyInfo[]>("/api/strategies"),
  validateStrategy: (name: string) => post<StrategyValidateResult>("/api/strategies/validate", { name }),
  backtests: () => get<BacktestRun[]>("/api/backtests"),
  createBacktest: (params: unknown) => post<BacktestRun>("/api/backtests", params),
  backtest: (id: number) => get<BacktestRun>(`/api/backtests/${id}`),
  deleteBacktest: (id: number) =>
    del<{ ok: boolean; id: number; deleted_files: string[]; warnings: string[] }>(
      `/api/backtests/${id}`,
    ),
  backtestScore: (id: number) => get<ScoreReport>(`/api/backtests/${id}/score`),
  compareBacktests: (ids: number[]) =>
    post<Record<string, unknown>[]>("/api/backtests/compare", ids),
  backtestChart: (id: number, params: Record<string, string | number>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => qs.set(k, String(v)));
    return get<ChartData>(`/api/backtests/${id}/chart?${qs.toString()}`);
  },
  liveChart: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => qs.set(k, String(v)));
    return get<ChartData>(`/api/charts/live?${qs.toString()}`);
  },
  connections: () => get<ConnectionOut[]>("/api/connections"),
  saveConnection: (body: unknown) => post<ConnectionOut>("/api/connections", body),
  deleteConnection: (id: string) => del<{ ok: boolean }>(`/api/connections/${id}`),
  testConnection: (id: string) => post<ConnectionTestResult>(`/api/connections/${id}/test`),
  botRead: <T>(connectionId: string, endpoint: string) =>
    get<T>(`/api/bot/${connectionId}/read/${endpoint}`),
  botAction: (connectionId: string, action: string, payload?: unknown) =>
    post<unknown>(`/api/bot/${connectionId}/action/${action}`, payload || {}),
  refreshSignals: (payload: unknown) => post<SignalEvent[]>("/api/signals/refresh", payload),
  signalsFromBacktest: (runId: number) =>
    post<SignalEvent[]>("/api/signals/from-backtest", { run_id: runId }),
  signals: (strategy?: string) =>
    get<SignalEvent[]>(`/api/signals${strategy ? `?strategy=${encodeURIComponent(strategy)}` : ""}`),
  getWeights: () => get<ScoreWeights>("/api/score/weights"),
  putWeights: (weights: ScoreWeights) => put<ScoreWeights>("/api/score/weights", weights),
  downloadData: (params: unknown) => post<JobState>("/api/data/download", params),
  jobs: () => get<JobState[]>("/api/jobs"),
  job: (id: string) => get<JobState>(`/api/jobs/${id}`),
  hyperopt: (params: unknown, epochs = 100) =>
    post<JobState>(`/api/hyperopt?epochs=${epochs}`, params),
  lookahead: (strategy: string, timerange: string, tradingMode: string) =>
    post<JobState>(
      `/api/analysis/lookahead?strategy=${encodeURIComponent(strategy)}&timerange=${encodeURIComponent(timerange)}&trading_mode=${tradingMode}`,
    ),
  buildConfig: (params: unknown) => post<{ ok: boolean; path: string; hint: string }>(
    "/api/settings/build-config",
    params,
  ),
  dataAvailable: () => get<Record<string, Record<string, string>>>("/api/data/available"),
};
