import { useEffect, useState } from "react";
import { api } from "../api";
import type { JobState, StrategyInfo } from "../types";

export default function Strategies() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [validation, setValidation] = useState<Record<string, string>>({});
  const [hyperoptForm, setHyperoptForm] = useState({
    strategy: "",
    timerange: "20240101-",
    timeframe: "5m",
    pairs: "BTC/USDT:USDT",
    epochs: "100",
    loss: "MultiMetricHyperOptLoss",
    trading_mode: "spot",
  });
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .strategies()
      .then(setStrategies)
      .catch((e: Error) => setError(e.message));
    api.jobs().then(setJobs).catch(() => undefined);
  };

  useEffect(refresh, []);

  const validate = async (name: string) => {
    try {
      const result = await api.validateStrategy(name);
      const parts = [...result.errors, ...result.warnings];
      setValidation((prev) => ({ ...prev, [name]: parts.join("；") || "校验通过" }));
    } catch (e) {
      setValidation((prev) => ({ ...prev, [name]: (e as Error).message }));
    }
  };

  const runHyperopt = async () => {
    setError("");
    setMessage("");
    if (!hyperoptForm.strategy) {
      setError("请选择策略");
      return;
    }
    try {
      const job = await api.hyperopt(
        {
          strategy: hyperoptForm.strategy,
          exchange: "okx",
          pairs: hyperoptForm.pairs.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean),
          timerange: hyperoptForm.timerange,
          timeframe: hyperoptForm.timeframe,
          trading_mode: hyperoptForm.trading_mode,
          margin_mode: "isolated",
          dry_run_wallet: 1000,
          stake_amount: "unlimited",
          max_open_trades: 3,
        },
        Number(hyperoptForm.epochs),
      );
      setMessage(`超参任务已创建：${job.id}（损失函数 ${hyperoptForm.loss}）`);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const runLookahead = async (name: string) => {
    setError("");
    try {
      const job = await api.lookahead(name, hyperoptForm.timerange, hyperoptForm.trading_mode);
      setMessage(`前视偏差分析已创建：${job.id}`);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <h1 className="page-title">策略管理</h1>
      <p className="page-sub">策略文件位于 user_data/strategies；支持校验、超参寻优与前视偏差检查</p>
      {error && <div className="error">{error}</div>}
      {message && <div className="warn">{message}</div>}

      <div className="card">
        <h3>策略列表</h3>
        {strategies.length === 0 && (
          <div className="muted">
            未发现策略。请把 Python 策略放入 user_data/strategies 后重试，或先安装 freqtrade。
          </div>
        )}
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>文件</th>
              <th>校验</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => (
              <tr key={s.name}>
                <td>{s.name}</td>
                <td className="mono">{s.file || s.path}</td>
                <td className="muted">{validation[s.name] ?? "—"}</td>
                <td>
                  <div className="row">
                    <button className="btn-sm" onClick={() => validate(s.name)}>
                      校验
                    </button>
                    <button className="btn-sm" onClick={() => runLookahead(s.name)}>
                      前视偏差
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>超参寻优（Hyperopt）</h3>
        <div className="form-row">
          <label>
            策略
            <input
              list="strategy-options"
              value={hyperoptForm.strategy}
              onChange={(e) => setHyperoptForm({ ...hyperoptForm, strategy: e.target.value })}
            />
            <datalist id="strategy-options">
              {strategies.map((s) => (
                <option key={s.name} value={s.name} />
              ))}
            </datalist>
          </label>
          <label>
            时间范围
            <input
              value={hyperoptForm.timerange}
              onChange={(e) => setHyperoptForm({ ...hyperoptForm, timerange: e.target.value })}
            />
          </label>
          <label>
            周期
            <input
              value={hyperoptForm.timeframe}
              onChange={(e) => setHyperoptForm({ ...hyperoptForm, timeframe: e.target.value })}
            />
          </label>
          <label>
            交易对
            <input value={hyperoptForm.pairs} onChange={(e) => setHyperoptForm({ ...hyperoptForm, pairs: e.target.value })} />
          </label>
          <label>
            Epochs
            <input
              type="number"
              value={hyperoptForm.epochs}
              onChange={(e) => setHyperoptForm({ ...hyperoptForm, epochs: e.target.value })}
            />
          </label>
          <label>
            损失函数
            <select value={hyperoptForm.loss} onChange={(e) => setHyperoptForm({ ...hyperoptForm, loss: e.target.value })}>
              <option>MultiMetricHyperOptLoss</option>
              <option>SharpeHyperOptLoss</option>
              <option>SortinoHyperOptLossDaily</option>
              <option>CalmarHyperOptLoss</option>
              <option>ProfitDrawDownHyperOptLoss</option>
            </select>
          </label>
          <label>
            模式
            <select
              value={hyperoptForm.trading_mode}
              onChange={(e) => setHyperoptForm({ ...hyperoptForm, trading_mode: e.target.value })}
            >
              <option value="spot">现货</option>
              <option value="futures">合约</option>
            </select>
          </label>
        </div>
        <button className="btn-primary" onClick={runHyperopt}>
          开始超参寻优
        </button>
        <p className="hint" style={{ marginTop: 10 }}>
          Hyperopt 非常消耗 CPU/内存，建议在区间收窄的小样本上先跑。结果文件在 user_data/hyperopt_results。
        </p>
      </div>

      <div className="card">
        <h3>后台任务</h3>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>类型</th>
              <th>状态</th>
              <th>消息</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="mono">{job.id.slice(0, 8)}</td>
                <td>{job.kind}</td>
                <td>
                  {job.status === "done" && <span className="badge badge-ok">完成</span>}
                  {job.status === "running" && <span className="badge badge-run">运行中</span>}
                  {job.status === "queued" && <span className="badge badge-run">排队中</span>}
                  {job.status === "error" && <span className="badge badge-err">失败</span>}
                </td>
                <td className="mono">{job.message.slice(0, 160)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
