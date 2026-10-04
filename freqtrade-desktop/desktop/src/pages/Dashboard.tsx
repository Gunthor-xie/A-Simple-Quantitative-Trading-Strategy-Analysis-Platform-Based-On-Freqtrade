import { useEffect, useState } from "react";
import { api, connectSnapshot, type SnapshotMessage } from "../api";
import type { BacktestRun, ConnectionOut, ScoreReport, SettingsStatus } from "../types";

export default function Dashboard() {
  const [settings, setSettings] = useState<SettingsStatus | null>(null);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [signalsCount, setSignalsCount] = useState(0);
  const [profit, setProfit] = useState<Record<string, unknown> | null>(null);
  const [botError, setBotError] = useState("");
  const [scores, setScores] = useState<Record<number, ScoreReport>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .settingsStatus()
      .then(setSettings)
      .catch((e: Error) => setError(e.message));
    api
      .connections()
      .then(setConnections)
      .catch(() => undefined);
    const ws = connectSnapshot((snapshot: SnapshotMessage) => {
      setBacktests(snapshot.backtests);
      setSignalsCount(snapshot.signals_count);
    });
    return () => ws.close();
  }, []);

  useEffect(() => {
    if (connections.length === 0) return;
    api
      .botRead<Record<string, unknown>>(connections[0].id, "profit")
      .then(setProfit)
      .catch((e: Error) => setBotError(e.message));
  }, [connections]);

  const loadScore = (id: number) => {
    api
      .backtestScore(id)
      .then((report) => setScores((prev) => ({ ...prev, [id]: report })))
      .catch((e: Error) => setError(e.message));
  };

  return (
    <div>
      <h1 className="page-title">仪表盘</h1>
      <p className="page-sub">本地 Freqtrade 运行状态与最近回测概览</p>
      {error && <div className="error">{error}</div>}

      <div className="grid grid-3">
        <div className="card">
          <h3>环境</h3>
          <div className="metric">
            <div className="label">Freqtrade</div>
            <div className="value">
              {settings ? (
                settings.freqtrade_available ? (
                  <span className="badge badge-ok">可用 {settings.freqtrade_version}</span>
                ) : (
                  <span className="badge badge-err">未安装/未找到</span>
                )
              ) : (
                "加载中…"
              )}
            </div>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            user_data: {settings?.user_data || "-"}
            <br />
            系统钥匙串: {settings ? (settings.keyring_available ? "可用" : "不可用（使用环境变量）") : "-"}
            {settings?.freqtrade_error && (
              <>
                <br />
                探测失败原因: {settings.freqtrade_error}
              </>
            )}
          </p>
        </div>

        <div className="card">
          <h3>机器人连接</h3>
          {connections.length === 0 && <div className="muted">尚未配置连接，请到「设置」添加。</div>}
          {connections.map((conn) => (
            <div key={conn.id} className="row" style={{ marginBottom: 6 }}>
              <span>{conn.name}</span>
              <span className="mono muted">{conn.url}</span>
              <span className={conn.enabled ? "badge badge-ok" : "badge badge-err"}>
                {conn.enabled ? "启用" : "停用"}
              </span>
            </div>
          ))}
          {botError && <div className="error">{botError}</div>}
          {profit && (
            <div className="metric" style={{ marginTop: 10 }}>
              <div className="label">已平仓利润（USD）</div>
              <div className="value">
                {typeof profit.profit_closed_currency === "number"
                  ? profit.profit_closed_currency.toFixed(2)
                  : "—"}
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <h3>信号与任务</h3>
          <div className="metric">
            <div className="label">已入库信号数</div>
            <div className="value">{signalsCount}</div>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            信号可在「信号与交易」页刷新；历史信号来自回测或运行中的机器人。
          </p>
        </div>
      </div>

      <div className="card">
        <h3>最近回测</h3>
        {backtests.length === 0 && <div className="muted">还没有回测记录，去「回测中心」跑一次吧。</div>}
        {backtests.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>策略</th>
                <th>状态</th>
                <th>区间</th>
                <th>模式</th>
                <th>交易数</th>
                <th>综合评分</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {backtests.slice(0, 10).map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.params.strategy}</td>
                  <td>
                    {run.status === "done" && <span className="badge badge-ok">完成</span>}
                    {run.status === "running" && <span className="badge badge-run">运行中</span>}
                    {run.status === "queued" && <span className="badge badge-run">排队中</span>}
                    {run.status === "error" && <span className="badge badge-err">失败</span>}
                  </td>
                  <td className="mono">{run.params.timerange}</td>
                  <td>{run.params.trading_mode}</td>
                  <td>{run.result?.total_trades ?? "—"}</td>
                  <td>
                    {scores[run.id] ? (
                      <strong>{scores[run.id].composite}</strong>
                    ) : run.status === "done" ? (
                      <button className="btn-sm" onClick={() => loadScore(run.id)}>
                        评分
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="mono">{run.created_at.slice(0, 19)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
