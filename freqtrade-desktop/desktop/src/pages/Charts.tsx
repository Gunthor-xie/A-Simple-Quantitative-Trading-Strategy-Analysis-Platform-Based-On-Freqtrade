import { useEffect, useState } from "react";
import ChartView from "../components/ChartView";
import { ApiError, api } from "../api";
import type { BacktestRun, ChartData, ConnectionOut } from "../types";

const TFS = ["5m", "15m", "1h", "4h"] as const;
const INDICATOR_OPTIONS = [
  { key: "ema144", label: "EMA144" },
  { key: "ema169", label: "EMA169" },
  { key: "vwap24", label: "VWAP(24h)" },
  { key: "boll", label: "布林带" },
] as const;

interface ChartStyle {
  candleUp: string;
  candleDown: string;
  lineWidth: number;
  pnlWidth: number;
}

interface LocalOption {
  symbol: string;
  mode: "spot" | "futures";
  timeframes: string[];
  types: string[];
  count: number;
}

function buildLocalOptions(coverage: unknown): LocalOption[] {
  const cov = coverage as Record<
    string,
    Record<string, Record<string, Record<string, { count?: number }>>>
  >;
  const options: LocalOption[] = [];
  const seen = new Set<string>();
  for (const exchange of Object.keys(cov || {})) {
    for (const pairKey of Object.keys(cov[exchange])) {
      const tfMap = cov[exchange][pairKey];
      const timeframes = Object.keys(tfMap);
      const types = new Set<string>();
      let count = 0;
      timeframes.forEach((tf) => {
        Object.values(tfMap[tf] || {}).forEach((entry) => {
          types.add(String((entry as { type?: string })?.type || ""));
          count += Number(entry?.count || 0);
        });
      });
      const isFutures = [...types].some((t) => ["futures", "mark", "funding_rate", "index"].includes(t));
      let symbol: string;
      if (isFutures) {
        const parts = pairKey.split("_");
        const settle = parts[2] || "USDT";
        symbol = `${parts[0]}/${parts[1]}:${settle}`;
      } else {
        symbol = pairKey.replace(/_/g, "/");
      }
      const key = `${exchange}|${symbol}|${isFutures ? "futures" : "spot"}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const ordered = ["5m", "15m", "1h", "4h"].filter((tf) => timeframes.includes(tf))
        .concat(timeframes.filter((tf) => !["5m", "15m", "1h", "4h"].includes(tf)));
      options.push({
        symbol,
        mode: isFutures ? "futures" : "spot",
        timeframes: ordered,
        types: [...types].filter(Boolean),
        count,
      });
    }
  }
  return options.sort((a, b) => a.symbol.localeCompare(b.symbol));
}

const TYPE_LABELS: Record<string, string> = {
  spot: "现货K线",
  futures: "合约K线",
  mark: "标记价",
  funding_rate: "资金费率",
  index: "指数",
};

const DEFAULT_STYLE: ChartStyle = {
  candleUp: "#26a69a",
  candleDown: "#ef5350",
  lineWidth: 1,
  pnlWidth: 2,
};

function loadStyle(): ChartStyle {
  try {
    const raw = localStorage.getItem("ftdesk-chart-style");
    return raw ? { ...DEFAULT_STYLE, ...JSON.parse(raw) } : DEFAULT_STYLE;
  } catch {
    return DEFAULT_STYLE;
  }
}

export default function Charts() {
  const [source, setSource] = useState<"local" | "backtest" | "live">("local");
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [connections, setConnections] = useState<ConnectionOut[]>([]);
  const [runId, setRunId] = useState<number | null>(null);
  const [connectionId, setConnectionId] = useState("");
  const [strategy, setStrategy] = useState("");
  const [pair, setPair] = useState("BTC/USDT");
  const [timeframe, setTimeframe] = useState<string>("15m");
  const [mode, setMode] = useState<"spot" | "futures">("spot");
  // Vegas channel (EMA144/EMA169) + rolling 24h VWAP are the default overlay set
  const [mainSelection, setMainSelection] = useState<string[]>(["ema144", "ema169", "vwap24"]);
  const [subSelection, setSubSelection] = useState<"none" | "rsi" | "macd">("rsi");
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showStyle, setShowStyle] = useState(false);
  const [style, setStyle] = useState<ChartStyle>(loadStyle);
  const [localOptions, setLocalOptions] = useState<LocalOption[]>([]);
  const [localLoaded, setLocalLoaded] = useState(false);

  useEffect(() => {
    api.backtests().then(setRuns).catch(() => undefined);
    api.connections().then(setConnections).catch(() => undefined);
  }, []);

  const persistStyle = (next: ChartStyle) => {
    setStyle(next);
    localStorage.setItem("ftdesk-chart-style", JSON.stringify(next));
  };

  const load = async () => {
    setError("");
    if (source === "backtest" && runId === null) {
      setError("请先选择一个回测结果");
      return;
    }
    if (source === "live" && (!connectionId || !strategy)) {
      setError("实时图表需要选择连接与策略");
      return;
    }
    setLoading(true);
    try {
      const indicators: string[] = [...mainSelection];
      if (subSelection === "rsi") indicators.push("rsi");
      if (subSelection === "macd") indicators.push("macd");
      const backtestRun = runs.find((r) => r.id === runId);
      const chartPair =
        source === "backtest" && backtestRun && backtestRun.params.pairs.length > 0
          ? backtestRun.params.pairs[0]
          : pair;
      if (source === "backtest" && runId !== null) {
        setData(
          await api.backtestChart(runId, {
            pair: chartPair, timeframe, indicators: indicators.join(","), limit: 5000, offset: 0,
          }),
        );
      } else if (source === "live") {
        setData(
          await api.liveChart({
            connection_id: connectionId, strategy, pair, timeframe,
            indicators: indicators.join(","), limit: 5000,
          }),
        );
      } else {
        setData(
          await api.localChart({
            pair, timeframe, trading_mode: mode, exchange: "okx",
            indicators: indicators.join(","), limit: 5000, offset: 0,
          }),
        );
      }
    } catch (e) {
      const err = e as ApiError;
      if (source === "local" && err.status === 404) {
        // Requested pair/timeframe has no local file: refresh the inventory and
        // jump to the first usable option so the user is not stuck.
        try {
          const coverage = await api.dataCoverage();
          const options = buildLocalOptions(coverage);
          setLocalOptions(options);
          const fallback = options[0];
          if (fallback) {
            setPair(fallback.symbol);
            setMode(fallback.mode);
            setTimeframe(fallback.timeframes[0] || "15m");
            setLocalLoaded(true);
            setError(
              `当前选择没有本地数据，已自动切换到 ${fallback.symbol}（${fallback.timeframes.join("/")}），请再次点击加载`,
            );
            return;
          }
          setError("本地没有可用数据文件：请到「设置 → 下载历史数据」下载后再试");
          return;
        } catch {
          setError(err.message);
          return;
        }
      }
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (source !== "backtest" || runId === null) return;
    const run = runs.find((r) => r.id === runId);
    if (!run) return;
    if (run.params.pairs.length > 0) setPair(run.params.pairs[0]);
    const tf = ["5m", "15m", "1h", "4h"].includes(run.params.timeframe) ? run.params.timeframe : "15m";
    setTimeframe(tf);
  }, [source, runId]);

  useEffect(() => {
    if (source === "backtest" && runId !== null && runs.some((r) => r.id === runId)) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, runId, timeframe]);

  const toggleMain = (key: string) =>
    setMainSelection((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  useEffect(() => {
    if (source !== "local") return;
    api
      .dataCoverage()
      .then((coverage) => {
        const options = buildLocalOptions(coverage);
        setLocalOptions(options);
        if (options.length === 0) {
          setError("本地没有可用数据文件：请到「设置 → 下载历史数据」下载后再试");
        }
        if (!localLoaded && options.length > 0) {
          const first = options[0];
          setPair(first.symbol);
          setMode(first.mode);
          setTimeframe(first.timeframes[0] || "15m");
          setLocalLoaded(true);
        }
      })
      .catch(() => {
        setError(
          "无法读取本地数据清单：运行中的后端可能是旧版本，请重启后端（start-services.ps1）后刷新页面",
        );
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  const currentOption = localOptions.find((o) => o.symbol === pair);
  const availableTfs = currentOption?.timeframes || TFS;
  const localCount = localOptions.reduce((sum, o) => sum + o.count, 0);

  // If the currently selected pair/timeframe disappeared (files removed or a
  // different data set downloaded), snap back to a valid local option.
  useEffect(() => {
    if (source !== "local" || localOptions.length === 0) return;
    const exists = localOptions.some((o) => o.symbol === pair && o.mode === mode);
    if (!exists) {
      const first = localOptions[0];
      setPair(first.symbol);
      setMode(first.mode);
      setTimeframe(first.timeframes[0] || "15m");
    } else if (currentOption && !currentOption.timeframes.includes(timeframe)) {
      setTimeframe(currentOption.timeframes[0] || "15m");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localOptions, pair, mode, timeframe, source]);

  useEffect(() => {
    if (source === "local" && localLoaded && currentOption) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, localLoaded, pair, timeframe, mode]);

  return (
    <div>
      <h1 className="page-title">图表分析</h1>
      <p className="page-sub">本地数据预览（15m/1h/4h）与回测买卖点/盈亏线叠加</p>
      <div className="card">
        <div className="form-row">
          <label>
            数据来源
            <select value={source} onChange={(e) => setSource(e.target.value as "local" | "backtest" | "live")}>
              <option value="local">本地数据</option>
              <option value="backtest">回测结果</option>
              <option value="live">运行中的机器人</option>
            </select>
          </label>
          <label>
            周期
            <div className="row">
              {TFS.map((tf) => (
                <button
                  key={tf}
                  className={timeframe === tf ? "btn-primary" : ""}
                  disabled={!availableTfs.includes(tf)}
                  onClick={() => setTimeframe(tf)}
                >
                  {tf}
                </button>
              ))}
            </div>
          </label>
          {source === "backtest" && (
            <label>
              回测记录
              <select value={runId ?? ""} onChange={(e) => setRunId(Number(e.target.value) || null)}>
                <option value="">选择回测…</option>
                {runs.filter((r) => r.status === "done").map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} · {r.params.strategy} · {r.params.timerange}
                  </option>
                ))}
              </select>
            </label>
          )}
          {source === "live" && (
            <>
              <label>
                连接
                <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
                  <option value="">选择连接…</option>
                  {connections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </label>
              <label>
                策略
                <input value={strategy} onChange={(e) => setStrategy(e.target.value)} />
              </label>
            </>
          )}
          {source === "local" && (
            <label>
              本地数据（{localOptions.length} 个交易对 · {localCount} 根K线）
            </label>
          )}
          <label>
            交易对
            {source === "local" && localOptions.length > 0 ? (
              <select
                value={pair}
                onChange={(e) => {
                  const next = localOptions.find((o) => o.symbol === e.target.value);
                  setPair(e.target.value);
                  if (next) {
                    setMode(next.mode);
                    setTimeframe(next.timeframes[0] || "15m");
                  }
                }}
              >
                {localOptions.map((o) => (
                  <option key={`${o.mode}:${o.symbol}`} value={o.symbol}>
                    {o.symbol}（{o.mode} · {o.timeframes.join("/")}）
                  </option>
                ))}
              </select>
            ) : (
              <input value={pair} onChange={(e) => setPair(e.target.value)} />
            )}
          </label>
          {source === "local" && currentOption && (
            <span className="badge badge-ok badge-stack">
              <span>{currentOption.mode === "futures" ? "合约" : "现货"}</span>
              <span>
                {currentOption.types.map((t) => TYPE_LABELS[t] || t).join("/") || "仅K线"}
              </span>
            </span>
          )}
          <label>
            主图指标（维加斯通道 EMA144/EMA169）
            <div className="row">
              {INDICATOR_OPTIONS.map((opt) => (
                <label key={opt.key} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <input
                    type="checkbox"
                    checked={mainSelection.includes(opt.key)}
                    onChange={() => toggleMain(opt.key)}
                  />
                  {opt.label}
                </label>
              ))}
            </div>
          </label>
          <label>
            副图
            <select value={subSelection} onChange={(e) => setSubSelection(e.target.value as "none" | "rsi" | "macd")}>
              <option value="none">无</option>
              <option value="rsi">RSI</option>
              <option value="macd">MACD</option>
            </select>
          </label>
        </div>
        <div className="row">
          <button className="btn-primary" onClick={load} disabled={loading}>
            {loading ? "加载中…" : "加载图表"}
          </button>
          <button onClick={() => setShowStyle((v) => !v)}>图表设置</button>
        </div>
        {showStyle && (
          <div className="card" style={{ marginTop: 12 }}>
            <div className="form-row">
              <label>
                上涨色
                <input type="color" value={style.candleUp} onChange={(e) => persistStyle({ ...style, candleUp: e.target.value })} />
              </label>
              <label>
                下跌色
                <input type="color" value={style.candleDown} onChange={(e) => persistStyle({ ...style, candleDown: e.target.value })} />
              </label>
              <label>
                指标线宽
                <input type="number" min={1} max={5} value={style.lineWidth} onChange={(e) => persistStyle({ ...style, lineWidth: Number(e.target.value) })} />
              </label>
              <label>
                盈亏线宽
                <input type="number" min={1} max={6} value={style.pnlWidth} onChange={(e) => persistStyle({ ...style, pnlWidth: Number(e.target.value) })} />
              </label>
            </div>
            <button onClick={() => persistStyle(DEFAULT_STYLE)}>恢复默认</button>
          </div>
        )}
        {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      {data && (
        <ChartView
          data={data}
          mainIndicators={mainSelection}
          subIndicator={subSelection === "none" ? null : subSelection}
          colors={{ ...style, indicatorColors: {} }}
        />
      )}
    </div>
  );
}
