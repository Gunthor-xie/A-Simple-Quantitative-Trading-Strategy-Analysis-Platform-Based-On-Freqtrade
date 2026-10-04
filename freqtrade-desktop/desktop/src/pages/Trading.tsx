import { useEffect, useState } from "react";
import { api } from "../api";
import type { ConnectionOut, SignalEvent } from "../types";

export default function Trading() {
  const [mode, setMode] = useState<"signal" | "dryrun" | "live">("signal");
  const [liveConfirmed, setLiveConfirmed] = useState(false);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [strategy, setStrategy] = useState("");
  const [pairsInput, setPairsInput] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState("5m");
  const [status, setStatus] = useState<Record<string, unknown>[]>([]);
  const [profit, setProfit] = useState<Record<string, unknown> | null>(null);
  const [whitelist, setWhitelist] = useState<string[]>([]);
  const [signals, setSignals] = useState<SignalEvent[]>([]);
  const [enterForm, setEnterForm] = useState({ pair: "", side: "long", price: "", stake: "", leverage: "" });
  const [exitForm, setExitForm] = useState({ tradeid: "", ordertype: "" });
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.connections().then(setConnections).catch(() => undefined);
    api.signals().then(setSignals).catch(() => undefined);
  }, []);

  const refreshBot = async () => {
    setError("");
    if (!connectionId) {
      setError("请先选择连接");
      return;
    }
    try {
      const [st, pf, wl] = await Promise.all([
        api.botRead<Record<string, unknown>[]>(connectionId, "status"),
        api.botRead<Record<string, unknown>>(connectionId, "profit"),
        api.botRead<{ whitelist?: string[] }>(connectionId, "whitelist"),
      ]);
      setStatus(st);
      setProfit(pf);
      setWhitelist(wl.whitelist ?? []);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const act = async (action: string, payload?: unknown) => {
    setError("");
    setMessage("");
    if (!connectionId) {
      setError("请先选择连接");
      return;
    }
    if (action.startsWith("force-") && !confirm(`确认执行 ${action}？${mode === "live" ? "（实盘模式）" : ""}`)) {
      return;
    }
    try {
      const result = await api.botAction(connectionId, action, payload);
      setMessage(JSON.stringify(result).slice(0, 300));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const refreshSignals = async () => {
    setError("");
    if (!connectionId || !strategy) {
      setError("信号刷新需要连接与策略");
      return;
    }
    try {
      const pairs = pairsInput.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean);
      const events = await api.refreshSignals({ connection_id: connectionId, strategy, pairs, timeframe });
      setSignals((prev) => [...events, ...prev].slice(0, 200));
      setMessage(`新增信号 ${events.length} 条`);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div>
      <h1 className="page-title">信号与交易</h1>
      <p className="page-sub">默认信号模式无需 OKX 密钥；dry-run / 实盘需本地 bot 与连接</p>
      {error && <div className="error">{error}</div>}
      {message && <div className="warn">{message}</div>}

      <div className="card">
        <h3>运行模式</h3>
        <div className="row">
          {(["signal", "dryrun", "live"] as const).map((m) => (
            <label key={m} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <input type="radio" checked={mode === m} onChange={() => setMode(m)} />
              {m === "signal" ? "信号模式（默认）" : m === "dryrun" ? "dry-run 纸面" : "OKX 实盘"}
            </label>
          ))}
        </div>
        {mode === "live" && (
          <div className="card" style={{ background: "var(--panel-2)" }}>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={liveConfirmed}
                onChange={(e) => setLiveConfirmed(e.target.checked)}
              />
              我已确认：实盘将把信号订单发送至 OKX，涉及真实资金，风险自负。
            </label>
            {!liveConfirmed && <div className="error">未确认前无法执行实盘强开/强平。</div>}
          </div>
        )}
      </div>

      <div className="card">
        <h3>机器人控制</h3>
        <div className="form-row">
          <label>
            连接
            <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
              <option value="">选择连接…</option>
              {connections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}（{c.url}）
                </option>
              ))}
            </select>
          </label>
          <label>
            策略
            <input value={strategy} onChange={(e) => setStrategy(e.target.value)} />
          </label>
          <label>
            交易对
            <input value={pairsInput} onChange={(e) => setPairsInput(e.target.value)} />
          </label>
          <label>
            周期
            <input value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
          </label>
        </div>
        <div className="row">
          <button onClick={refreshBot}>刷新状态</button>
          <button onClick={() => act("start")}>启动</button>
          <button onClick={() => act("pause")}>暂停开仓</button>
          <button onClick={() => act("stopbuy")}>停止买入</button>
          <button onClick={() => act("stop")}>停止</button>
          <button onClick={() => act("reload-config")}>重载配置</button>
          <button className="btn-primary" onClick={refreshSignals}>
            刷新信号
          </button>
        </div>
        {profit && (
          <div className="grid grid-3" style={{ marginTop: 14 }}>
            <div className="metric">
              <div className="label">已平仓利润 USD</div>
              <div className="value">
                {typeof profit.profit_closed_currency === "number"
                  ? profit.profit_closed_currency.toFixed(2)
                  : "—"}
              </div>
            </div>
            <div className="metric">
              <div className="label">胜率</div>
              <div className="value">
                {typeof profit.winrate === "number" ? (profit.winrate * 100).toFixed(1) + "%" : "—"}
              </div>
            </div>
            <div className="metric">
              <div className="label">白名单数量</div>
              <div className="value">{whitelist.length}</div>
            </div>
          </div>
        )}
      </div>

      <div className="card">
        <h3>强制操作（dry-run 与实盘共用）</h3>
        <div className="form-row">
          <label>
            强开交易对
            <input value={enterForm.pair} onChange={(e) => setEnterForm({ ...enterForm, pair: e.target.value })} />
          </label>
          <label>
            方向
            <select value={enterForm.side} onChange={(e) => setEnterForm({ ...enterForm, side: e.target.value })}>
              <option value="long">做多</option>
              <option value="short">做空（仅合约）</option>
            </select>
          </label>
          <label>
            限价（可选）
            <input value={enterForm.price} onChange={(e) => setEnterForm({ ...enterForm, price: e.target.value })} />
          </label>
          <label>
            金额（可选）
            <input value={enterForm.stake} onChange={(e) => setEnterForm({ ...enterForm, stake: e.target.value })} />
          </label>
          <label>
            杠杆（可选）
            <input value={enterForm.leverage} onChange={(e) => setEnterForm({ ...enterForm, leverage: e.target.value })} />
          </label>
        </div>
        <button
          className="btn-primary"
          onClick={() => {
            if (mode === "live" && !liveConfirmed) {
              setError("实盘模式需先确认风险声明");
              return;
            }
            act("force-enter", {
              pair: enterForm.pair,
              side: enterForm.side,
              price: enterForm.price ? Number(enterForm.price) : null,
              stake_amount: enterForm.stake ? Number(enterForm.stake) : null,
              leverage: enterForm.leverage ? Number(enterForm.leverage) : null,
            });
          }}
        >
          强制入场
        </button>
        <div className="form-row" style={{ marginTop: 16 }}>
          <label>
            强平 trade id（或 "all"）
            <input value={exitForm.tradeid} onChange={(e) => setExitForm({ ...exitForm, tradeid: e.target.value })} />
          </label>
          <label>
            订单类型
            <select value={exitForm.ordertype} onChange={(e) => setExitForm({ ...exitForm, ordertype: e.target.value })}>
              <option value="">默认</option>
              <option value="limit">limit</option>
              <option value="market">market</option>
            </select>
          </label>
        </div>
        <button
          className="btn-danger"
          onClick={() => {
            if (mode === "live" && !liveConfirmed) {
              setError("实盘模式需先确认风险声明");
              return;
            }
            act("force-exit", { tradeid: exitForm.tradeid || "all", ordertype: exitForm.ordertype || null });
          }}
        >
          强制出场
        </button>
      </div>

      <div className="card">
        <h3>持仓与信号</h3>
        <table>
          <thead>
            <tr>
              <th>Trade ID</th>
              <th>交易对</th>
              <th>方向</th>
              <th>当前盈亏</th>
              <th>入场标签</th>
            </tr>
          </thead>
          <tbody>
            {status.map((trade) => (
              <tr key={String(trade.trade_id)}>
                <td>{String(trade.trade_id)}</td>
                <td>{String(trade.pair)}</td>
                <td>{trade.is_short ? "空" : "多"}</td>
                <td>{typeof trade.profit_ratio === "number" ? (trade.profit_ratio * 100).toFixed(2) + "%" : "—"}</td>
                <td>{String(trade.enter_tag ?? "")}</td>
              </tr>
            ))}
            {status.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  无持仓（或尚未连接机器人）
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <h3 style={{ marginTop: 18 }}>信号事件（{signals.length}）</h3>
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>交易对</th>
              <th>方向</th>
              <th>原因</th>
              <th>价格</th>
            </tr>
          </thead>
          <tbody>
            {signals.slice(0, 50).map((s, i) => (
              <tr key={i}>
                <td className="mono">{s.time}</td>
                <td>{s.pair}</td>
                <td>{s.side === "exit" ? "退出" : s.side === "long" ? "做多" : "做空"}</td>
                <td>{s.reason}</td>
                <td>{s.price ?? "—"}</td>
              </tr>
            ))}
            {signals.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  暂无信号
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
