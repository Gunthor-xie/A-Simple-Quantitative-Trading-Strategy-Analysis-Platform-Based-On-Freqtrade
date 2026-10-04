import { useEffect, useState } from "react";
import { api, connectSnapshot, type SnapshotMessage } from "../api";
import type { BacktestRun, ScoreReport, StrategyInfo } from "../types";

interface FormState {
  strategy: string;
  exchange: string;
  pairs: string;
  timerange: string;
  timeframe: string;
  timeframe_detail: string;
  trading_mode: "spot" | "futures";
  margin_mode: "isolated" | "cross";
  dry_run_wallet: string;
  stake_amount: string;
  max_open_trades: string;
  fee: string;
  enable_protections: boolean;
}

const INITIAL_FORM: FormState = {
  strategy: "",
  exchange: "okx",
  pairs: "BTC/USDT",
  timerange: "20240101-",
  timeframe: "5m",
  timeframe_detail: "5m",
  trading_mode: "spot",
  margin_mode: "isolated",
  dry_run_wallet: "1000",
  stake_amount: "unlimited",
  max_open_trades: "3",
  fee: "",
  enable_protections: false,
};

function toDateInput(value: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})/.exec(value);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}

function fromDateInput(value: string): string {
  return value ? value.replace(/-/g, "") : "";
}

function daysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

export default function Backtests() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [selected, setSelected] = useState<number[]>([]);
  const [compare, setCompare] = useState<Record<string, unknown>[]>([]);
  const [score, setScore] = useState<ScoreReport | null>(null);
  const [scoreRun, setScoreRun] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => api.backtests().then(setRuns).catch((e: Error) => setError(e.message));

  useEffect(() => {
    api
      .strategies()
      .then(setStrategies)
      .catch(() => setStrategies([]));
    refresh();
    const ws = connectSnapshot((snapshot: SnapshotMessage) => setRuns(snapshot.backtests));
    return () => ws.close();
  }, []);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const runBacktest = async () => {
    setError("");
    if (!form.strategy.trim()) {
      setError("请选择或输入策略名称");
      return;
    }
    try {
      await api.createBacktest({
        strategy: form.strategy.trim(),
        exchange: form.exchange,
        pairs: form.pairs
          .split(/[,\s]+/)
          .map((p) => p.trim())
          .filter(Boolean),
        timerange: form.timerange,
        timeframe: form.timeframe,
        timeframe_detail: form.timeframe_detail || null,
        trading_mode: form.trading_mode,
        margin_mode: form.margin_mode,
        dry_run_wallet: Number(form.dry_run_wallet),
        stake_amount: form.stake_amount,
        max_open_trades: Number(form.max_open_trades),
        fee: form.fee ? Number(form.fee) : null,
        enable_protections: form.enable_protections,
      });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggleSelect = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const runCompare = async () => {
    setError("");
    if (selected.length < 2) {
      setError("请至少勾选两个已完成回测");
      return;
    }
    try {
      setCompare(await api.compareBacktests(selected));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const deleteRuns = async (ids: number[]) => {
    if (ids.length === 0) return;
    const label = ids.length === 1 ? `回测 #${ids[0]}` : `${ids.length} 条回测`;
    if (!window.confirm(`确认删除 ${label}？关联的本地回测文件也会一并删除，且不可恢复。`)) {
      return;
    }
    setError("");
    setDeleting(true);
    try {
      for (const id of ids) {
        await api.deleteBacktest(id);
      }
      setSelected([]);
      setScore(null);
      setScoreRun(null);
      setCompare([]);
      refresh();
    } catch (e) {
      setError((e as Error).message);
      refresh();
    } finally {
      setDeleting(false);
    }
  };

  // 勾选回测记录后按 Delete 键即可删除（输入框内不触发）
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Delete") return;
      const tag = (event.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (selected.length === 0 || deleting) return;
      event.preventDefault();
      void deleteRuns(selected);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected, deleting]);

  const runExport = async (id: number) => {
    setError("");
    try {
      await api.exportBacktest(id);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const loadScore = async (id: number) => {
    setError("");
    try {
      setScore(await api.backtestScore(id));
      setScoreRun(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <h1 className="page-title">回测中心</h1>
      <p className="page-sub">基于本地数据执行 freqtrade backtesting，解析结果、评分并对比</p>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <h3>新建回测</h3>
        <div className="form-row">
          <label>
            策略
            <input
              list="strategy-options"
              value={form.strategy}
              onChange={(e) => set("strategy", e.target.value)}
              placeholder="SampleStrategy"
            />
            <datalist id="strategy-options">
              {strategies.map((s) => (
                <option key={s.name} value={s.name} />
              ))}
            </datalist>
          </label>
          <label>
            交易所
            <select value={form.exchange} onChange={(e) => set("exchange", e.target.value)}>
              <option value="okx">okx</option>
              <option value="myokx">myokx（OKX EAA）</option>
            </select>
          </label>
          <label>
            交易对（逗号/空格分隔）
            <input value={form.pairs} onChange={(e) => set("pairs", e.target.value)} />
          </label>
          <label>
            开始日期
            <input
              type="date"
              value={toDateInput(form.timerange.split("-")[0] || "")}
              onChange={(e) => {
                const end = form.timerange.includes("-")
                  ? form.timerange.split("-")[1] || ""
                  : "";
                set("timerange", `${fromDateInput(e.target.value)}-${end}`);
              }}
            />
          </label>
          <label>
            结束日期
            <input
              type="date"
              value={toDateInput(form.timerange.split("-")[1] || "")}
              onChange={(e) => {
                const start = form.timerange.split("-")[0] || "";
                set("timerange", `${start}-${fromDateInput(e.target.value)}`);
              }}
            />
          </label>
          <label>
            快捷区间
            <div className="row">
              <button className="btn-sm" onClick={() => set("timerange", `${daysAgo(30)}-${daysAgo(1)}`)}>近30天</button>
              <button className="btn-sm" onClick={() => set("timerange", `${daysAgo(90)}-${daysAgo(1)}`)}>近90天</button>
              <button className="btn-sm" onClick={() => set("timerange", `20260601-${daysAgo(1)}`)}>全部（示例）</button>
            </div>
          </label>
          <label>
            周期
            <input value={form.timeframe} onChange={(e) => set("timeframe", e.target.value)} />
          </label>
          <label>
            明细周期（timeframe-detail）
            <input value={form.timeframe_detail} onChange={(e) => set("timeframe_detail", e.target.value)} placeholder="5m" />
          </label>
          <label>
            模式
            <select
              value={form.trading_mode}
              onChange={(e) => {
                const mode = e.target.value as "spot" | "futures";
                set("trading_mode", mode);
                // Keep pair naming consistent with the selected mode.
                const hasSuffix = form.pairs.split(/[,\s]+/).some((p) => p.includes(":"));
                if (mode === "spot" && hasSuffix) {
                  set(
                    "pairs",
                    form.pairs
                      .split(/[,\s]+/)
                      .map((p) => p.split(":")[0])
                      .join(", "),
                  );
                } else if (mode === "futures" && !hasSuffix) {
                  set(
                    "pairs",
                    form.pairs
                      .split(/[,\s]+/)
                      .map((p) => (p.includes(":") ? p : `${p}:USDT`))
                      .join(", "),
                  );
                }
              }}
            >
              <option value="spot">现货</option>
              <option value="futures">合约</option>
            </select>
          </label>
          <label>
            保证金模式
            <select
              value={form.margin_mode}
              onChange={(e) => set("margin_mode", e.target.value as "isolated" | "cross")}
            >
              <option value="isolated">逐仓（isolated）</option>
              <option value="cross">全仓（cross）</option>
            </select>
          </label>
          <label>
            起始资金
            <input
              type="number"
              value={form.dry_run_wallet}
              onChange={(e) => set("dry_run_wallet", e.target.value)}
            />
          </label>
          <label>
            单笔金额
            <input value={form.stake_amount} onChange={(e) => set("stake_amount", e.target.value)} />
          </label>
          <label>
            最大同时持仓
            <input
              type="number"
              value={form.max_open_trades}
              onChange={(e) => set("max_open_trades", e.target.value)}
            />
          </label>
          <label>
            手续费覆盖（可选，如 0.001）
            <input value={form.fee} onChange={(e) => set("fee", e.target.value)} />
          </label>
          <label>
            启用 Protections
            <input
              type="checkbox"
              checked={form.enable_protections}
              onChange={(e) => set("enable_protections", e.target.checked)}
              style={{ width: 18, height: 18 }}
            />
          </label>
        </div>
        <button className="btn-primary" onClick={runBacktest}>
          开始回测
        </button>
        <p className="hint" style={{ marginTop: 10 }}>
          合约回测早于近 3 个月时，OKX 资金费率数据不足会有偏差；OKX 单次调用仅返回 100 根 K
          线，初次请先在「设置 → 数据」中下载足够历史。
        </p>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>回测记录</h3>
          <div className="row">
            <button className="btn-sm" onClick={runCompare} disabled={selected.length < 2}>
              对比选中（{selected.length}）
            </button>
            <button
              className="btn-sm"
              onClick={() => deleteRuns(selected)}
              disabled={selected.length === 0 || deleting}
            >
              {deleting ? "删除中…" : `删除选中（${selected.length}）`}
            </button>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          勾选左侧复选框选中回测记录，点「删除选中」或直接按 Delete 键即可删除该记录及其本地回测文件。
        </p>
        <div className="table-wrap"><table>
          <thead>
            <tr>
              <th>勾选</th>
              <th>ID</th>
              <th>策略</th>
              <th>状态</th>
              <th>区间</th>
              <th>模式</th>
              <th>交易数</th>
              <th>胜率</th>
              <th>利润%</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.includes(run.id)}
                    onChange={() => toggleSelect(run.id)}
                  />
                </td>
                <td>{run.id}</td>
                <td>{run.params.strategy}</td>
                <td>
                  {run.status === "done" && <span className="badge badge-ok">完成</span>}
                  {run.status === "running" && <span className="badge badge-run">运行中</span>}
                  {run.status === "queued" && <span className="badge badge-run">排队中</span>}
                  {run.status === "error" && <span className="badge badge-err">失败</span>}
                  {run.error && <div className="error mono">{run.error.slice(0, 120)}</div>}
                </td>
                <td className="mono">{run.params.timerange}</td>
                <td>{run.params.trading_mode}</td>
                <td>{run.result?.total_trades ?? "—"}</td>
                <td>{run.result ? (run.result.winrate * 100).toFixed(1) + "%" : "—"}</td>
                <td>{run.result ? run.result.profit_total_percent.toFixed(2) : "—"}</td>
                <td className="mono">{run.created_at.slice(0, 19)}</td>
                <td>
                  {run.status === "done" && (
                    <div className="row">
                      <button className="btn-sm" onClick={() => loadScore(run.id)}>评分</button>
                      <button className="btn-sm" onClick={() => runExport(run.id)}>导出Excel</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>

      {score && scoreRun !== null && (
        <div className="card">
          <h3>
            评分报告 · 回测 #{scoreRun}（基准：{score.baseline_source === "history-best" ? "历史最优" : "内置默认"}）
          </h3>
          <div className="row" style={{ marginBottom: 12 }}>
            <div className="score-big">{score.composite}</div>
            <div>
              {score.warnings.map((w) => (
                <div key={w} className="warn">
                  {w}
                </div>
              ))}
            </div>
          </div>
          <div className="table-wrap"><table>
            <thead>
              <tr>
                <th>指标</th>
                <th>数值</th>
                <th>基准</th>
                <th>得分</th>
                <th>权重</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {score.metrics.map((m) => (
                <tr key={m.name}>
                  <td>{m.label}</td>
                  <td>{m.value ?? "—"}</td>
                  <td>{m.baseline ?? "—"}</td>
                  <td>{m.score}</td>
                  <td>{(m.weight * 100).toFixed(0)}%</td>
                  <td className="muted">{m.missing ? (m.note ?? "缺失") : m.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}

      {compare.length > 0 && (
        <div className="card">
          <h3>对比结果</h3>
          <div className="table-wrap"><table>
            <thead>
              <tr>
                <th>回测</th>
                <th>综合评分</th>
                <th>交易数</th>
                <th>利润%</th>
                <th>胜率</th>
                <th>Sharpe</th>
                <th>Sortino</th>
                <th>Calmar</th>
                <th>利润因子</th>
                <th>最大回撤</th>
                <th>警告</th>
              </tr>
            </thead>
            <tbody>
              {compare.map((item) => {
                const result = item.result as { total_trades?: number; profit_total_percent?: number; winrate?: number; sharpe?: number | null; sortino?: number | null; calmar?: number | null; profit_factor?: number | null; max_drawdown_account?: number } | null;
                const warnings = (item.warnings as string[]) ?? [];
                return (
                  <tr key={item.run_id as number}>
                    <td>#{String(item.run_id)}</td>
                    <td>
                      <strong>{item.score == null ? "—" : Number(item.score).toFixed(1)}</strong>
                    </td>
                    <td>{result?.total_trades ?? "—"}</td>
                    <td>{result?.profit_total_percent != null ? result.profit_total_percent.toFixed(2) : "—"}</td>
                    <td>{result?.winrate != null ? (result.winrate * 100).toFixed(1) + "%" : "—"}</td>
                    <td>{result?.sharpe?.toFixed(2) ?? "—"}</td>
                    <td>{result?.sortino?.toFixed(2) ?? "—"}</td>
                    <td>{result?.calmar?.toFixed(2) ?? "—"}</td>
                    <td>{result?.profit_factor?.toFixed(2) ?? "—"}</td>
                    <td>{result?.max_drawdown_account != null ? (result.max_drawdown_account * 100).toFixed(1) + "%" : "—"}</td>
                    <td className="warn">{warnings.join("；")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
