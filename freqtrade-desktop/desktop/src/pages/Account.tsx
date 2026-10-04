import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { ConnectionOut } from "../types";

function valueOf(v: unknown): string {
  return v === null || v === undefined ? "—" : String(v);
}

export default function Account() {
  const [configured, setConfigured] = useState(false);
  const [cred, setCred] = useState({ api_key: "", secret: "", passphrase: "" });
  const [summary, setSummary] = useState<Record<string, unknown> | null>(null);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [reconcile, setReconcile] = useState<Record<string, unknown> | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refreshSummary = useCallback(async () => {
    setError("");
    try {
      setSummary(await api.okxSummary());
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    api.okxStatus().then((s) => setConfigured(s.configured)).catch(() => undefined);
    api.connections().then(setConnections).catch(() => undefined);
    if (configured) refreshSummary();
  }, [configured, refreshSummary]);

  const saveCred = async () => {
    setError("");
    try {
      const result = await api.okxCredentials(cred);
      setConfigured(result.configured);
      setCred({ api_key: "", secret: "", passphrase: "" });
      setMessage("OKX 只读密钥已保存（与实盘交易密钥分离）");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const runReconcile = async () => {
    setError("");
    try {
      setReconcile(await api.okxReconcile({ connection_id: connectionId || null }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const balance = summary?.balance as Array<Record<string, unknown>> | undefined;
  const positions = (summary?.positions as Array<Record<string, unknown>> | undefined) ?? [];
  const orders = (summary?.open_orders as Array<Record<string, unknown>> | undefined) ?? [];
  const fills = (summary?.recent_fills as Array<Record<string, unknown>> | undefined) ?? [];
  const details = (balance?.[0]?.details as Array<Record<string, unknown>> | undefined) ?? [];

  return (
    <div>
      <h1 className="page-title">OKX 账户（只读）</h1>
      <p className="page-sub">独立只读 key 查看资产/持仓/挂单/成交，并与机器人交叉核对</p>
      {error && <div className="error">{error}</div>}
      {message && <div className="warn">{message}</div>}

      {!configured && (
        <div className="card">
          <h3>配置只读 API（Read 权限，不开放提现）</h3>
          <div className="form-row">
            <label>API Key<input value={cred.api_key} onChange={(e) => setCred({ ...cred, api_key: e.target.value })} /></label>
            <label>Secret<input type="password" value={cred.secret} onChange={(e) => setCred({ ...cred, secret: e.target.value })} /></label>
            <label>Passphrase<input type="password" value={cred.passphrase} onChange={(e) => setCred({ ...cred, passphrase: e.target.value })} /></label>
          </div>
          <button className="btn-primary" onClick={saveCred}>保存（写入钥匙串/环境变量）</button>
        </div>
      )}

      {configured && (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <button className="btn-primary" onClick={refreshSummary}>刷新</button>
          </div>
          <div className="grid grid-3">
            <div className="card">
              <h3>账户权益</h3>
              <div className="score-big">{valueOf(balance?.[0]?.totalEq)}</div>
              <p className="hint">币种：{valueOf(balance?.[0]?.ccy || "USDT")}</p>
            </div>
            <div className="card">
              <h3>持仓数 / 挂单数</h3>
              <div className="value" style={{ fontSize: 24 }}>{positions.length} / {orders.length}</div>
            </div>
            <div className="card">
              <h3>资产明细</h3>
              <table>
                <tbody>
                  {details.slice(0, 8).map((d) => (
                    <tr key={valueOf(d.ccy)}>
                      <td>{valueOf(d.ccy)}</td>
                      <td>{Number(d.eq ?? 0).toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="card">
            <h3>持仓</h3>
            <table>
              <thead><tr><th>合约</th><th>方向</th><th>数量</th><th>开仓价</th><th>未实现盈亏</th></tr></thead>
              <tbody>
                {positions.map((p, i) => (
                  <tr key={i}>
                    <td>{valueOf(p.instId)}</td>
                    <td>{p.posSide === "short" ? "空" : "多"}</td>
                    <td>{valueOf(p.pos)}</td>
                    <td>{valueOf(p.avgPx)}</td>
                    <td className={Number(p.upl) < 0 ? "error" : ""}>{valueOf(p.upl)}</td>
                  </tr>
                ))}
                {positions.length === 0 && <tr><td colSpan={5} className="muted">无持仓</td></tr>}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3>交叉核对</h3>
            <div className="row">
              <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
                <option value="">不选连接（仅 OKX 持仓）</option>
                {connections.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button onClick={runReconcile}>运行核对</button>
            </div>
            {reconcile && (
              <table style={{ marginTop: 12 }}>
                <thead><tr><th>级别</th><th>交易对</th><th>说明</th></tr></thead>
                <tbody>
                  {((reconcile.diffs as unknown[]) ?? []).map((d, i) => {
                    const diff = d as Record<string, string>;
                    return (
                      <tr key={i}>
                        <td className={diff.level === "high" ? "error" : "muted"}>{diff.level === "high" ? "高" : "低"}</td>
                        <td>{diff.pair}</td>
                        <td>{diff.detail}</td>
                      </tr>
                    );
                  })}
                  {!((reconcile.diffs as unknown[]) ?? []).length && <tr><td colSpan={3} className="muted">无差异</td></tr>}
                </tbody>
              </table>
            )}
          </div>

          <div className="card">
            <h3>近期成交（最近 {fills.length} 笔）</h3>
            <table>
              <thead><tr><th>时间</th><th>合约</th><th>方向</th><th>价格</th><th>数量</th><th>手续费</th></tr></thead>
              <tbody>
                {fills.map((f, i) => (
                  <tr key={i}>
                    <td className="mono">{new Date(Number(f.ts ?? 0)).toISOString().slice(0, 19)}</td>
                    <td>{valueOf(f.instId)}</td>
                    <td>{valueOf(f.side)}</td>
                    <td>{valueOf(f.px)}</td>
                    <td>{valueOf(f.sz)}</td>
                    <td>{valueOf(f.fee)}</td>
                  </tr>
                ))}
                {fills.length === 0 && <tr><td colSpan={6} className="muted">暂无成交记录</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
