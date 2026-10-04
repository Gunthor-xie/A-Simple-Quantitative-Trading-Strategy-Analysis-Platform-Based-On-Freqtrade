import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AppSettings,
  BackendHealth,
  ConnectionOut,
  ConnectionTestResult,
  JobState,
  ScoreWeights,
  SettingsStatus,
} from "../types";

const WEIGHT_KEYS = [
  "sharpe",
  "sortino",
  "calmar",
  "profit_factor",
  "winrate",
  "max_drawdown",
  "expectancy",
] as const;

const WEIGHT_LABELS: Record<string, string> = {
  sharpe: "Sharpe",
  sortino: "Sortino",
  calmar: "Calmar",
  profit_factor: "利润因子",
  winrate: "胜率",
  max_drawdown: "最大回撤",
  expectancy: "期望",
};

export default function Settings() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [backend, setBackend] = useState<BackendHealth | null>(null);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [connForm, setConnForm] = useState({
    name: "",
    kind: "local",
    url: "http://127.0.0.1:8080",
    username: "Freqtrader",
    password: "",
    enabled: true,
  });
  const [testResults, setTestResults] = useState<Record<string, ConnectionTestResult>>({});
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [configForm, setConfigForm] = useState({
    exchange: "okx",
    trading_mode: "spot",
    margin_mode: "isolated",
    stake_currency: "USDT",
    pairs: "BTC/USDT:USDT",
    timeframe: "5m",
    dry_run: true,
    dry_run_wallet: "1000",
    stake_amount: "unlimited",
    max_open_trades: "3",
    force_entry_enable: false,
    telegram_token: "",
    telegram_chat_id: "",
    api_port: "8080",
  });
  const [configResult, setConfigResult] = useState<{ path: string; hint: string } | null>(null);
  const [downloadForm, setDownloadForm] = useState({
    pairs: "BTC/USDT",
    trading_mode: "spot",
    start: "",
    end: "",
    extraTimeframes: [] as string[],
  });
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [appSettingsForm, setAppSettingsForm] = useState({
    data_root: "",
    export_dir: "",
    z_soft: "2.0",
    z_hard: "3.0",
    http_proxy: "",
  });
  const [netDiag, setNetDiag] = useState<Record<string, unknown> | null>(null);
  const [jobs, setJobs] = useState<JobState[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = () => {
    api.settingsStatus().then(setStatus).catch(() => undefined);
    api.health().then(setBackend).catch(() => setBackend(null));
    api
      .getSettings()
      .then((s) => {
        setAppSettings(s);
        setAppSettingsForm({
          data_root: s.data_root,
          export_dir: s.export_dir,
          z_soft: String(s.z_soft),
          z_hard: String(s.z_hard),
          http_proxy: s.http_proxy || "",
        });
      })
      .catch(() => undefined);
    api.connections().then(setConnections).catch(() => undefined);
    api
      .getWeights()
      .then((w) => {
        const next: Record<string, string> = {};
        WEIGHT_KEYS.forEach((key) => {
          next[key] = String(w[key]);
        });
        setWeights(next);
      })
      .catch(() => undefined);
    api.jobs().then(setJobs).catch(() => undefined);
  };

  useEffect(refresh, []);

  const saveConnection = async () => {
    setError("");
    setMessage("");
    if (!connForm.name.trim()) {
      setError("连接名称必填");
      return;
    }
    try {
      await api.saveConnection({
        name: connForm.name.trim(),
        kind: connForm.kind,
        url: connForm.url,
        username: connForm.username,
        password: connForm.password || null,
        enabled: connForm.enabled,
      });
      setConnForm({ ...connForm, name: "", password: "" });
      refresh();
      setMessage("连接已保存（密钥写入系统钥匙串/环境变量）");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const testConnection = async (id: string) => {
    try {
      setTestResults((prev) => ({ ...prev, [id]: { ok: false, message: "测试中…" } }));
      const result = await api.testConnection(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveWeights = async () => {
    setError("");
    try {
      const payload = {} as ScoreWeights;
      WEIGHT_KEYS.forEach((key) => {
        payload[key] = Number(weights[key]);
      });
      const saved = await api.putWeights(payload);
      setWeights(
        Object.fromEntries(WEIGHT_KEYS.map((key) => [key, String(saved[key])])) as Record<string, string>,
      );
      setMessage("评分权重已保存（总和需为 1）");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const buildConfig = async () => {
    setError("");
    setMessage("");
    try {
      const result = await api.buildConfig({
        exchange: configForm.exchange,
        trading_mode: configForm.trading_mode,
        margin_mode: configForm.margin_mode,
        stake_currency: configForm.stake_currency,
        pairs: configForm.pairs.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean),
        timeframe: configForm.timeframe,
        dry_run: configForm.dry_run,
        dry_run_wallet: Number(configForm.dry_run_wallet),
        stake_amount: configForm.stake_amount,
        max_open_trades: Number(configForm.max_open_trades),
        force_entry_enable: configForm.force_entry_enable,
        telegram_token: configForm.telegram_token || null,
        telegram_chat_id: configForm.telegram_chat_id || null,
        api_port: Number(configForm.api_port),
      });
      setConfigResult(result);
      setMessage("配置已生成");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const downloadData = async () => {
    setError("");
    setMessage("");
    try {
      const job = await api.downloadData({
        exchange: "okx",
        pairs: downloadForm.pairs.split(/[,\s]+/).map((p) => p.trim()).filter(Boolean),
        timeframes: ["15m", "1h", "4h", ...downloadForm.extraTimeframes],
        timerange:
          downloadForm.start || downloadForm.end
            ? `${(downloadForm.start || "").replace(/-/g, "")}-${(downloadForm.end || "").replace(/-/g, "")}`
            : null,
        trading_mode: downloadForm.trading_mode,
        data_format: "jsongz",
        candle_types: downloadForm.trading_mode === "futures" ? ["futures", "mark", "funding_rate"] : ["spot"],
      });
      setMessage(`数据下载任务已创建：${job.id}`);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveAppSettings = async () => {
    setError("");
    try {
      const saved = await api.putSettings({
        data_root: appSettingsForm.data_root,
        export_dir: appSettingsForm.export_dir,
        z_soft: Number(appSettingsForm.z_soft),
        z_hard: Number(appSettingsForm.z_hard),
        http_proxy: appSettingsForm.http_proxy,
      });
      setAppSettings(saved);
      setMessage("设置已保存（数据/导出路径下次任务生效）");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const testNetwork = async () => {
    setError("");
    setMessage("");
    try {
      const result = await api.networkDiagnostics(appSettingsForm.http_proxy || undefined);
      setNetDiag(result);
    } catch (e) {
      const err = e as { status?: number; message: string };
      if (err.status === 404) {
        setError("后端缺少网络诊断接口（运行的是旧版本）。请执行 .\\start-services.ps1 重启后端后重试");
      } else {
        setError(err.message);
      }
    }
  };

  const toggleExtra = (tf: string) => {
    const current = downloadForm.extraTimeframes;
    setDownloadForm({
      ...downloadForm,
      extraTimeframes: current.includes(tf)
        ? current.filter((x) => x !== tf)
        : [...current, tf],
    });
  };

  const setDownloadMode = (mode: "spot" | "futures") => {
    const hasSuffix = downloadForm.pairs.split(/[,\s]+/).some((p) => p.includes(":"));
    const nextPairs =
      mode === "spot"
        ? downloadForm.pairs
            .split(/[,\s]+/)
            .map((p) => p.split(":")[0])
            .join(", ")
        : hasSuffix
          ? downloadForm.pairs
          : downloadForm.pairs
              .split(/[,\s]+/)
              .map((p) => `${p}:USDT`)
              .join(", ");
    setDownloadForm({ ...downloadForm, trading_mode: mode, pairs: nextPairs });
  };

  return (
    <div>
      <h1 className="page-title">设置</h1>
      <p className="page-sub">连接、密钥、评分权重、freqtrade 配置生成与数据下载</p>
      {error && <div className="error">{error}</div>}
      {message && <div className="warn">{message}</div>}

      <div className="card">
        <h3>环境状态</h3>
        <div className="grid grid-3">
          <div className="metric">
            <div className="label">Freqtrade</div>
            <div className="value">
              {status?.freqtrade_available
                ? `可用（${status.freqtrade_version || "?"}）`
                : "未安装/未找到"}
            </div>
          </div>
          {status?.freqtrade_error && (
            <div className="error" style={{ gridColumn: "1 / -1" }}>
              探测失败原因：{status.freqtrade_error}
            </div>
          )}
          <div className="metric">
            <div className="label">user_data</div>
            <div className="value mono" style={{ fontSize: 13 }}>
              {status?.user_data ?? "—"}
            </div>
          </div>
          <div className="metric">
            <div className="label">本地后端</div>
            <div className="value">
              {backend
                ? `v${backend.version}${backend.features.includes("diagnostics") ? "" : "（需重启）"}`
                : "无法读取版本"}
            </div>
          </div>
          <div className="metric">
            <div className="label">钥匙串</div>
            <div className="value">{status?.keyring_available ? "可用" : "不可用（环境变量）"}</div>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>机器人连接</h3>
        <div className="form-row">
          <label>
            名称
            <input value={connForm.name} onChange={(e) => setConnForm({ ...connForm, name: e.target.value })} />
          </label>
          <label>
            类型
            <select value={connForm.kind} onChange={(e) => setConnForm({ ...connForm, kind: e.target.value })}>
              <option value="local">本地</option>
              <option value="remote">远端（预留 v2）</option>
            </select>
          </label>
          <label>
            API 地址
            <input value={connForm.url} onChange={(e) => setConnForm({ ...connForm, url: e.target.value })} />
          </label>
          <label>
            用户名
            <input value={connForm.username} onChange={(e) => setConnForm({ ...connForm, username: e.target.value })} />
          </label>
          <label>
            密码（写入钥匙串）
            <input
              type="password"
              value={connForm.password}
              onChange={(e) => setConnForm({ ...connForm, password: e.target.value })}
            />
          </label>
        </div>
        <button className="btn-primary" onClick={saveConnection}>
          保存连接
        </button>
        <table style={{ marginTop: 14 }}>
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>URL</th>
              <th>启用</th>
              <th>测试</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {connections.map((conn) => (
              <tr key={conn.id}>
                <td>{conn.name}</td>
                <td>{conn.kind}</td>
                <td className="mono">{conn.url}</td>
                <td>{conn.enabled ? "是" : "否"}</td>
                <td>
                  {testResults[conn.id] && (
                    <div className={testResults[conn.id].ok ? "badge badge-ok" : "badge badge-err"}>
                      {testResults[conn.id].ok ? "成功" : testResults[conn.id].message}
                    </div>
                  )}
                  <button className="btn-sm" onClick={() => testConnection(conn.id)}>
                    测试
                  </button>
                </td>
                <td>
                  <button
                    className="btn-sm btn-danger"
                    onClick={async () => {
                      await api.deleteConnection(conn.id);
                      refresh();
                    }}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="hint" style={{ marginTop: 8 }}>
          安全说明：密码经系统钥匙串或环境变量（FTDESK_SECRET_*）保存，不写入配置文件明文；
          freqtrade 的 api_server 应仅监听 127.0.0.1。
          <br />
          若本机钥匙串不可用：先填好密码点一次“保存连接”，页面会提示所需的环境变量名
          （形如 FTDESK_SECRET_CONN_xxx_PASSWORD）；在你的终端设置该变量后，密码留空再保存一次即可。
        </p>
      </div>

      <div className="card">
        <h3>评分权重（总和必须为 1）</h3>
        <div className="form-row">
          {WEIGHT_KEYS.map((key) => (
            <label key={key}>
              {WEIGHT_LABELS[key]}
              <input
                type="number"
                step="0.01"
                value={weights[key] ?? ""}
                onChange={(e) => setWeights({ ...weights, [key]: e.target.value })}
              />
            </label>
          ))}
        </div>
        <button onClick={saveWeights}>保存权重</button>
      </div>

      <div className="card">
        <h3>生成 freqtrade 配置（user_data/config.json）</h3>
        <div className="form-row">
          <label>
            交易所
            <select value={configForm.exchange} onChange={(e) => setConfigForm({ ...configForm, exchange: e.target.value })}>
              <option value="okx">okx</option>
              <option value="myokx">myokx（OKX EAA）</option>
            </select>
          </label>
          <label>
            模式
            <select
              value={configForm.trading_mode}
              onChange={(e) => setConfigForm({ ...configForm, trading_mode: e.target.value })}
            >
              <option value="spot">现货</option>
              <option value="futures">合约</option>
            </select>
          </label>
          <label>
            保证金模式
            <select
              value={configForm.margin_mode}
              onChange={(e) => setConfigForm({ ...configForm, margin_mode: e.target.value })}
            >
              <option value="isolated">逐仓</option>
              <option value="cross">全仓</option>
            </select>
          </label>
          <label>
            交易对
            <input value={configForm.pairs} onChange={(e) => setConfigForm({ ...configForm, pairs: e.target.value })} />
          </label>
          <label>
            周期
            <input value={configForm.timeframe} onChange={(e) => setConfigForm({ ...configForm, timeframe: e.target.value })} />
          </label>
          <label>
            起始资金
            <input
              value={configForm.dry_run_wallet}
              onChange={(e) => setConfigForm({ ...configForm, dry_run_wallet: e.target.value })}
            />
          </label>
          <label>
            单笔金额
            <input value={configForm.stake_amount} onChange={(e) => setConfigForm({ ...configForm, stake_amount: e.target.value })} />
          </label>
          <label>
            Telegram Token
            <input value={configForm.telegram_token} onChange={(e) => setConfigForm({ ...configForm, telegram_token: e.target.value })} />
          </label>
          <label>
            Telegram Chat ID
            <input value={configForm.telegram_chat_id} onChange={(e) => setConfigForm({ ...configForm, telegram_chat_id: e.target.value })} />
          </label>
          <label>
            API 端口
            <input value={configForm.api_port} onChange={(e) => setConfigForm({ ...configForm, api_port: e.target.value })} />
          </label>
        </div>
        <div className="row">
          <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={configForm.dry_run}
              onChange={(e) => setConfigForm({ ...configForm, dry_run: e.target.checked })}
            />
            dry_run（模拟）
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={configForm.force_entry_enable}
              onChange={(e) => setConfigForm({ ...configForm, force_entry_enable: e.target.checked })}
            />
            force_entry_enable（允许强开）
          </label>
          <button className="btn-primary" onClick={buildConfig}>
            生成配置
          </button>
        </div>
        {configResult && (
          <div className="hint" style={{ marginTop: 10 }}>
            已写入 {configResult.path}
            <br />
            {configResult.hint}
          </div>
        )}
      </div>

      <div className="card">
        <h3>数据与导出路径 / Z 值阈值</h3>
        <div className="form-row">
          <label>
            历史数据根目录
            <input
              value={appSettingsForm.data_root}
              onChange={(e) => setAppSettingsForm({ ...appSettingsForm, data_root: e.target.value })}
            />
          </label>
          <label>
            Excel 导出目录
            <input
              value={appSettingsForm.export_dir}
              onChange={(e) => setAppSettingsForm({ ...appSettingsForm, export_dir: e.target.value })}
            />
          </label>
          <label>
            Z 软阈值
            <input type="number" step="0.1" value={appSettingsForm.z_soft} onChange={(e) => setAppSettingsForm({ ...appSettingsForm, z_soft: e.target.value })} />
          </label>
          <label>
            Z 硬阈值
            <input type="number" step="0.1" value={appSettingsForm.z_hard} onChange={(e) => setAppSettingsForm({ ...appSettingsForm, z_hard: e.target.value })} />
          </label>
          <label>
            下载代理（可选，如 http://127.0.0.1:7890）
            <input
              value={appSettingsForm.http_proxy}
              onChange={(e) => setAppSettingsForm({ ...appSettingsForm, http_proxy: e.target.value })}
              placeholder="留空则自动探测"
            />
          </label>
        </div>
        <div className="row">
          <button className="btn-primary" onClick={saveAppSettings}>保存路径与阈值</button>
          <button onClick={testNetwork}>测试网络</button>
        </div>
        {netDiag && (
          <div className="hint" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
            结论：{String(netDiag.conclusion ?? "")}
            {"\n"}通道测试：
            {((netDiag.requests as Array<Record<string, unknown>>) || [])
              .map((r) => `${String(r.route)}=${r.ok ? "OK" : "失败"}${r.error ? `(${String(r.error).slice(0, 40)})` : ""}`)
              .join("；")}
          </div>
        )}
        {appSettings && (
          <p className="hint" style={{ marginTop: 8 }}>
            当前生效：{appSettings.data_root} · 导出目录 {appSettings.export_dir}
          </p>
        )}
      </div>

      <div className="card">
        <h3>下载历史数据（OKX）</h3>
        <div className="form-row">
          <label>
            交易对
            <input value={downloadForm.pairs} onChange={(e) => setDownloadForm({ ...downloadForm, pairs: e.target.value })} />
          </label>
          <label>
            周期（15m/1h/4h 固定，5m/1d 可选）
            <div className="row">
              {["15m", "1h", "4h"].map((tf) => <span key={tf} className="badge badge-ok">{tf}</span>)}
            </div>
            <div className="row">
              {["5m", "1d"].map((tf) => (
                <label key={tf} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={downloadForm.extraTimeframes.includes(tf)} onChange={() => toggleExtra(tf)} />
                  +{tf}
                </label>
              ))}
            </div>
          </label>
          <label>
            开始日期
            <input type="date" value={downloadForm.start} onChange={(e) => setDownloadForm({ ...downloadForm, start: e.target.value })} />
          </label>
          <label>
            结束日期
            <input type="date" value={downloadForm.end} onChange={(e) => setDownloadForm({ ...downloadForm, end: e.target.value })} />
          </label>
          <label>
            快捷区间
            <div className="row">
              {[
                { label: "近30天", days: 30 },
                { label: "近90天", days: 90 },
              ].map((preset) => {
                const ago = (d: number) => {
                  const x = new Date();
                  x.setDate(x.getDate() - d);
                  return x.toISOString().slice(0, 10);
                };
                return (
                  <button
                    key={preset.label}
                    className="btn-sm"
                    onClick={() =>
                      setDownloadForm({
                        ...downloadForm,
                        start: ago(preset.days),
                        end: ago(1),
                      })
                    }
                  >
                    {preset.label}
                  </button>
                );
              })}
            </div>
          </label>
          <label>
            模式
            <select
              value={downloadForm.trading_mode}
              onChange={(e) => setDownloadMode(e.target.value as "spot" | "futures")}
            >
              <option value="spot">现货</option>
              <option value="futures">合约</option>
            </select>
          </label>
        </div>
        <button onClick={downloadData}>开始下载</button>
        <p className="hint" style={{ marginTop: 10 }}>
          下载走 OKX 公开行情接口（无需机器人/API 密钥）：每次调用 100 根 K 线，大区间耗时较长；
          合约模式会同时写入 mark 与 funding_rate 文件。
        </p>
      </div>

      <div className="card">
        <h3>任务记录</h3>
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
                <td>{job.status}</td>
                <td className="mono">{job.message.slice(0, 200)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
