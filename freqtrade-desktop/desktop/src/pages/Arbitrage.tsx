import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ArbPlanPreview,
  ArbPosition,
  ArbRiskSettings,
  ArbTradeStatus,
  FundingAmplitude,
  FundingBasisStats,
  FundingHistory,
  FundingOpportunity,
  FundingScanResult,
} from "../types";

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;

const usd = (v: number | null | undefined) => {
  if (v === null || v === undefined) return "—";
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

const fmtTime = (ms: number | null | undefined) =>
  ms ? new Date(ms).toISOString().slice(0, 16).replace("T", " ") : "—";

const valueOf = (v: unknown) => (v === null || v === undefined ? "—" : String(v));

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="muted">数据点不足</div>;
  const width = 480;
  const height = 56;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / span) * (height - 8) - 4;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke="#4f8cff" strokeWidth="1.5" />
    </svg>
  );
}

const DEFAULT_ORDER = {
  inst_id: "BTC-USDT-SWAP",
  side: "sell",
  ordertype: "limit",
  sz: "",
  px: "",
  td_mode: "cross",
};

const RISK_META: Record<
  string,
  { label: string; hint: string; min: number; max: number; step: number }
> = {
  warn_liq_distance_pct: {
    label: "爆仓距离警戒",
    hint: "持仓与强平价的距离低于该比例时自动平仓，越保守该值越大。",
    min: 0.05,
    max: 0.3,
    step: 0.01,
  },
  max_delta_pct: {
    label: "delta 偏离上限",
    hint: "两腿净敞口占名义本金的比例超过该值时自动平仓（对冲失衡保护）。",
    min: 0.01,
    max: 0.1,
    step: 0.005,
  },
  fee_bps: {
    label: "手续费 bps（万分之）",
    hint: "单边手续费率，用于估算年化收益，开平两腿共 4 次；OKX 默认 5（万分之五）。",
    min: 1,
    max: 10,
    step: 0.5,
  },
};

const fmtCountdown = (target: number | null | undefined, now: number) => {
  if (!target) return "—";
  const left = target - now;
  if (left <= 0) return "已结算";
  const hours = Math.floor(left / 3_600_000);
  const minutes = Math.floor((left % 3_600_000) / 60_000);
  const seconds = Math.floor((left % 60_000) / 1000);
  return hours > 0
    ? `${hours}h${String(minutes).padStart(2, "0")}m`
    : `${minutes}m${String(seconds).padStart(2, "0")}s`;
};

type SortState = { key: string; dir: "asc" | "desc" } | null;

const SORT_ACCESSORS: Record<string, (i: FundingOpportunity) => number | null> = {
  funding_interval_hours: (i) => i.funding_interval_hours,
  next_settlement_ms: (i) => i.next_settlement_ms,
  funding_rate: (i) => i.funding_rate,
  funding_annualized: (i) => i.funding_annualized,
  next_funding_rate: (i) => i.next_funding_rate,
  max_funding_rate: (i) => i.max_funding_rate,
  premium: (i) => i.premium,
  interest_rate: (i) => i.interest_rate,
  funding_mean_annualized: (i) => i.funding_mean_annualized,
  funding_std: (i) => i.funding_std,
  streak: (i) => i.streak,
  reversal_freq: (i) => i.reversal_freq,
  half_life: (i) => i.half_life,
  basis_pct: (i) => i.basis_pct,
  adv_usd: (i) => i.adv_usd,
};

const numOrNull = (text: string): number | null => {
  if (text.trim() === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
};

function SortHeader({
  label,
  k,
  sort,
  onSort,
  hint,
}: {
  label: string;
  k: string;
  sort: SortState;
  onSort: (key: string) => void;
  hint?: string;
}) {
  const active = sort?.key === k;
  const mark = !active ? "↕" : sort!.dir === "asc" ? "▲" : "▼";
  return (
    <th>
      <button
        type="button"
        className="sort-btn"
        onClick={() => onSort(k)}
        title={`${hint ? hint + " · " : ""}点击切换：升序 → 降序 → 不排序`}
      >
        {label} <span style={{ color: active ? "var(--accent)" : "var(--muted)" }}>{mark}</span>
      </button>
    </th>
  );
}

export default function Arbitrage() {
  const [scan, setScan] = useState<FundingScanResult | null>(null);
  const [history, setHistory] = useState<FundingHistory | null>(null);
  const [amplitude, setAmplitude] = useState<FundingAmplitude | null>(null);
  const [basis, setBasis] = useState<FundingBasisStats | null>(null);
  const [selected, setSelected] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [filters, setFilters] = useState({
    annualMin: "",
    stdMax: "",
    streakMin: "",
    settleMinH: "",
  });
  const [limit, setLimit] = useState(100);
  const [minVolume, setMinVolume] = useState(1_000_000);
  const [requireSpot, setRequireSpot] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");

  const [trade, setTrade] = useState<ArbTradeStatus | null>(null);
  const [cred, setCred] = useState({ api_key: "", secret: "", passphrase: "" });
  const [tradeConfirm, setTradeConfirm] = useState(false);
  const [tradeMsg, setTradeMsg] = useState("");
  const [tradeErr, setTradeErr] = useState("");
  const [account, setAccount] = useState<Record<string, unknown> | null>(null);
  const [order, setOrder] = useState(DEFAULT_ORDER);
  const [orderConfirm, setOrderConfirm] = useState(false);
  const [ordId, setOrdId] = useState("");

  const [positions, setPositions] = useState<ArbPosition[]>([]);
  const [showClosed, setShowClosed] = useState(false);
  const [openForm, setOpenForm] = useState({
    pair: "BTC/USDT:USDT",
    capital_usd: 1000,
    leverage: 3,
    direction: "long_spot_short_perp",
    ordertype: "market",
    note: "",
  });
  const [openConfirm, setOpenConfirm] = useState(false);
  const [planPreview, setPlanPreview] = useState<ArbPlanPreview | null>(null);
  const [posMsg, setPosMsg] = useState("");
  const [posErr, setPosErr] = useState("");

  const [risk, setRisk] = useState<ArbRiskSettings | null>(null);
  const [riskMsg, setRiskMsg] = useState("");
  const [riskErr, setRiskErr] = useState("");

  const runScan = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setScan(await api.arbFunding({ limit, min_volume_usd: minVolume, require_spot: requireSpot }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [limit, minVolume, requireSpot]);

  const loadTrade = useCallback(() => {
    api.arbTradeStatus().then(setTrade).catch(() => undefined);
  }, []);

  useEffect(() => {
    runScan();
  }, [runScan]);

  useEffect(() => {
    loadTrade();
  }, [loadTrade]);

  // Tick once a second so the settlement countdown stays live.
  useEffect(() => {
    if (!scan) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [scan]);

  const cycleSort = (key: string) =>
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" };
      if (prev.dir === "asc") return { key, dir: "desc" };
      return null; // third click clears the sort
    });

  const fail = (e: unknown) => setTradeErr((e as Error).message);

  const saveCred = async () => {
    setTradeErr("");
    setTradeMsg("");
    try {
      await api.arbTradeCredentials({ ...cred, confirm: tradeConfirm });
      setCred({ api_key: "", secret: "", passphrase: "" });
      setTradeConfirm(false);
      setTradeMsg("交易密钥已保存（独立于只读密钥）");
      loadTrade();
    } catch (e) {
      fail(e);
    }
  };

  const clearCred = async () => {
    setTradeErr("");
    setTradeMsg("");
    try {
      await api.arbTradeClearCredentials();
      setAccount(null);
      setTradeMsg("交易密钥已清除，下单已关闭");
      loadTrade();
    } catch (e) {
      fail(e);
    }
  };

  const setEnabled = async (enabled: boolean) => {
    setTradeErr("");
    setTradeMsg("");
    try {
      await api.arbTradeSettings({ enabled });
      loadTrade();
    } catch (e) {
      fail(e);
    }
  };

  const setDemo = async (demo: boolean) => {
    setTradeErr("");
    try {
      await api.arbTradeSettings({ demo });
      loadTrade();
    } catch (e) {
      fail(e);
    }
  };

  const setMode = async (mode: "paper" | "live") => {
    setTradeErr("");
    setTradeMsg("");
    try {
      await api.arbTradeSettings({ mode });
      setAccount(null);
      loadTrade();
    } catch (e) {
      fail(e);
    }
  };

  const loadAccount = async () => {
    setTradeErr("");
    try {
      setAccount(await api.arbTradeAccount());
    } catch (e) {
      fail(e);
    }
  };

  const placeOrder = async () => {
    setTradeErr("");
    setTradeMsg("");
    try {
      const result = await api.arbTradeOrder({ ...order, confirm: orderConfirm });
      setTradeMsg(`下单已提交：${JSON.stringify(result)}`);
      setOrderConfirm(false);
    } catch (e) {
      fail(e);
    }
  };

  const cancelOrder = async () => {
    setTradeErr("");
    setTradeMsg("");
    try {
      const result = await api.arbTradeCancel({ inst_id: order.inst_id, ord_id: ordId });
      setTradeMsg(`撤单结果：${JSON.stringify(result)}`);
      setOrdId("");
    } catch (e) {
      fail(e);
    }
  };

  const loadPositions = useCallback(async () => {
    try {
      const res = await api.arbPositions(showClosed ? undefined : "open");
      setPositions(res.positions);
    } catch {
      /* ignored - surfaced by the scan error area */
    }
  }, [showClosed]);

  useEffect(() => {
    loadPositions();
  }, [loadPositions]);

  const runPlan = async () => {
    setPosErr("");
    setPosMsg("");
    try {
      setPlanPreview(
        await api.arbPlan({
          pair: openForm.pair,
          capital_usd: openForm.capital_usd,
          leverage: openForm.leverage,
          direction: openForm.direction,
        }),
      );
    } catch (e) {
      setPosErr((e as Error).message);
    }
  };

  const openPos = async () => {
    setPosErr("");
    setPosMsg("");
    if (planPreview && planPreview.leverage_ok === false) {
      setPosErr(
        `杠杆 ${planPreview.leverage}x 超过建议杠杆 ${planPreview.suggested_leverage}x，无法开仓`,
      );
      return;
    }
    try {
      const pos = await api.arbOpen({ ...openForm, confirm: openConfirm });
      setPosMsg(`已建仓 #${pos.id}（${pos.status}）`);
      setOpenConfirm(false);
      setPlanPreview(null);
      loadPositions();
    } catch (e) {
      setPosErr((e as Error).message);
    }
  };

  const closePos = async (id: number) => {
    setPosErr("");
    setPosMsg("");
    try {
      const pos = await api.arbClose(id);
      setPosMsg(`已平仓 #${pos.id}，估算盈亏 ${pos.realized_pnl.toFixed(4)}`);
      loadPositions();
    } catch (e) {
      setPosErr((e as Error).message);
    }
  };

  const refreshPos = async (id: number) => {
    setPosErr("");
    try {
      await api.arbRefreshPosition(id);
      loadPositions();
    } catch (e) {
      setPosErr((e as Error).message);
    }
  };

  const runUnwind = async () => {
    setPosErr("");
    setPosMsg("");
    try {
      const res = await api.arbUnwind();
      setPosMsg(`风险检查完成，自动平仓 ${res.unwound.length} 个`);
      loadPositions();
    } catch (e) {
      setPosErr((e as Error).message);
    }
  };

  const selectSymbol = async (pair: string) => {
    setSelected(pair);
    setHistory(null);
    setAmplitude(null);
    setBasis(null);
    setError("");
    // Copy the instrument name to the clipboard as soon as a row is picked.
    try {
      await navigator.clipboard?.writeText(pair);
      setCopied(pair);
    } catch {
      setCopied("");
    }
    try {
      setHistory(await api.arbFundingHistory(pair, 90));
    } catch (e) {
      setError((e as Error).message);
    }
    try {
      setAmplitude(await api.arbFundingAmplitude(pair, 730));
    } catch (e) {
      setError((e as Error).message);
    }
    // Basis history is expensive (two paginated candle calls) -> on demand only.
    try {
      setBasis(await api.arbFundingBasis(pair, 365));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const loadRisk = useCallback(() => {
    api.arbRisk().then(setRisk).catch(() => undefined);
  }, []);

  useEffect(() => {
    loadRisk();
  }, [loadRisk]);

  const saveRisk = async () => {
    if (!risk) return;
    setRiskErr("");
    setRiskMsg("");
    try {
      setRisk(await api.arbPutRisk(risk));
      setRiskMsg("风险参数已保存");
    } catch (e) {
      setRiskErr((e as Error).message);
    }
  };

  const items = scan?.items ?? [];

  // Filters run on the fetched rows (instant, no re-scan); every input is
  // optional - blank means "no condition".
  const visible = useMemo(() => {
    const annualMin = numOrNull(filters.annualMin);
    const stdMax = numOrNull(filters.stdMax);
    const streakMin = numOrNull(filters.streakMin);
    const settleMinH = numOrNull(filters.settleMinH);

    let list = items.filter((i) => {
      if (annualMin !== null && !((i.funding_annualized ?? -Infinity) >= annualMin)) return false;
      if (stdMax !== null && !(i.funding_std !== null && i.funding_std <= stdMax)) return false;
      if (streakMin !== null && !(i.streak !== null && Math.abs(i.streak) >= streakMin)) return false;
      if (settleMinH !== null) {
        const left = i.next_settlement_ms ? (i.next_settlement_ms - now) / 3_600_000 : null;
        if (left === null || left < settleMinH) return false;
      }
      return true;
    });

    if (sort) {
      const accessor = SORT_ACCESSORS[sort.key];
      const direction = sort.dir === "asc" ? 1 : -1;
      list = [...list].sort((a, b) => {
        const va = accessor(a);
        const vb = accessor(b);
        if (va === null && vb === null) return 0;
        if (va === null) return 1; // unknown values always sink to the bottom
        if (vb === null) return -1;
        return (va - vb) * direction;
      });
    }
    return list;
  }, [items, sort, filters, now]);

  const positive = visible.filter((i) => (i.funding_annualized ?? 0) > 0).length;
  const best = visible[0]?.funding_annualized ?? null;
  const ascending = history ? [...history.points].sort((a, b) => a.time - b.time) : [];
  const recent = history ? [...history.points].reverse().slice(0, 20) : [];
  const config = account?.config as Record<string, unknown> | undefined;

  return (
    <div>
      <h1 className="page-title">套利机会（资金费率 / 基差）</h1>
      <p className="page-sub">
        基于本地已下载的 OKX 永续资金费与指数数据评估 carry 机会
      </p>
      {error && <div className="error">{error}</div>}

      <div className="card">
        <div className="row">
          <button className="btn-primary" onClick={runScan} disabled={loading}>
            {loading ? "扫描中…" : "刷新扫描（OKX 实时）"}
          </button>
          <label>
            返回数量
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[50, 100, 200, 300].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label title="低于该 24h 成交额的标的自动排除；100 万为固定下限">
            24h成交额下限
            <select value={minVolume} onChange={(e) => setMinVolume(Number(e.target.value))}>
              <option value={1e6}>$1M（默认下限）</option>
              <option value={5e6}>$5M</option>
              <option value={2e7}>$20M</option>
            </select>
          </label>
          <label
            title="OKX 有 200+ 个合约没有现货交易对（代币化股票/商品等），无法构建现货+永续对冲"
            style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <input
              type="checkbox"
              checked={requireSpot}
              onChange={(e) => setRequireSpot(e.target.checked)}
            />
            仅显示可对冲（有现货）
          </label>
          {scan && (
            <span className="hint">
              数据源 {scan.source} · 生成于 {fmtTime(scan.generated_ms)}
            </span>
          )}
        </div>
        <p className="hint">
          数据全部来自 OKX 实时公共接口，不读取本地数据；超过 10 秒无反馈会提示网络连接超时。
          点击某一行会复制合约名称，并拉取资金费历史与近两年单日最大振幅（据此给出建议杠杆）。
        </p>
      </div>

      <div className="grid grid-3">
        <div className="card">
          <h3>标的数</h3>
          <div className="score-big">{items.length}</div>
        </div>
        <div className="card">
          <h3>正资金费（可做 carry）</h3>
          <div className="score-big" style={{ color: "var(--green)" }}>
            {positive}
          </div>
        </div>
        <div className="card">
          <h3>最高年化资金费</h3>
          <div className="score-big">{pct(best)}</div>
        </div>
      </div>

      <div className="card">
        <h3>筛选条件（留空表示不限）</h3>
        <div className="form-row">
          <label title="只显示年化资金费不低于该值的标的">
            年化资金费 ≥
            <input
              type="number"
              step={0.01}
              placeholder="如 0.10 = 10%"
              value={filters.annualMin}
              onChange={(e) => setFilters({ ...filters, annualMin: e.target.value })}
            />
          </label>
          <label title="历史费率标准差越小，费率越稳定；留空不限">
            历史费率标准差 ≤
            <input
              type="number"
              step={0.00001}
              placeholder="如 0.0001"
              value={filters.stdMax}
              onChange={(e) => setFilters({ ...filters, stdMax: e.target.value })}
            />
          </label>
          <label title="最近连续同号（同为正或同为负）的结算次数，取绝对值">
            连续同号次数 ≥
            <input
              type="number"
              step={1}
              placeholder="如 5"
              value={filters.streakMin}
              onChange={(e) => setFilters({ ...filters, streakMin: e.target.value })}
            />
          </label>
          <label title="距下次资金费结算的剩余小时数；太近开仓可能来不及收整期">
            距下次结算 ≥ (小时)
            <input
              type="number"
              step={0.5}
              placeholder="如 1"
              value={filters.settleMinH}
              onChange={(e) => setFilters({ ...filters, settleMinH: e.target.value })}
            />
          </label>
        </div>
        <p className="hint">
          筛选命中 {visible.length} / {items.length} 条
        </p>
      </div>

      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>合约</th>
                <th>现货</th>
                <SortHeader label="结算周期(h)" k="funding_interval_hours" sort={sort}
                  onSort={cycleSort} hint="8h = 费率×3×365；也有 4h/1h 的标的" />
                <SortHeader label="距下次结算" k="next_settlement_ms" sort={sort}
                  onSort={cycleSort} hint="距下次资金费结算的倒计时" />
                <SortHeader label="当前费率" k="funding_rate" sort={sort} onSort={cycleSort} />
                <SortHeader label="年化资金费" k="funding_annualized" sort={sort}
                  onSort={cycleSort} hint="当前费率按结算周期折年" />
                <SortHeader label="预测费率" k="next_funding_rate" sort={sort}
                  onSort={cycleSort} hint="OKX 给出的下一期预测，常为空" />
                <SortHeader label="费率上限" k="max_funding_rate" sort={sort}
                  onSort={cycleSort} hint="极端费率的封顶值，用于判断可持续性" />
                <SortHeader label="溢价指数" k="premium" sort={sort}
                  onSort={cycleSort} hint="资金费的溢价成分" />
                <SortHeader label="利率成分" k="interest_rate" sort={sort}
                  onSort={cycleSort} hint="资金费的固定利率成分" />
                <SortHeader label="均值年化" k="funding_mean_annualized" sort={sort}
                  onSort={cycleSort} hint="近 60 次结算费率的均值折年" />
                <SortHeader label="费率标准差" k="funding_std" sort={sort}
                  onSort={cycleSort} hint="越小越稳定，均值相同时更安全" />
                <SortHeader label="连续同号" k="streak" sort={sort}
                  onSort={cycleSort} hint="末尾连续正/负次数，正数=连续正费率" />
                <SortHeader label="反转频率" k="reversal_freq" sort={sort}
                  onSort={cycleSort} hint="符号切换次数占比，越低越持续" />
                <SortHeader label="半衰期(期)" k="half_life" sort={sort}
                  onSort={cycleSort} hint="AR(1) 半衰期，越小回归越快" />
                <SortHeader label="基差" k="basis_pct" sort={sort} onSort={cycleSort} />
                <SortHeader label="24h成交额" k="adv_usd" sort={sort} onSort={cycleSort} />
                <th>数据时间</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((i) => (
                <tr
                  key={i.symbol}
                  onClick={() => selectSymbol(i.pair)}
                  title={
                    i.has_spot
                      ? "点击复制合约名称并加载资金费/基差详情"
                      : "该标的在 OKX 没有现货交易对，无法构建现货+永续对冲"
                  }
                  style={{
                    cursor: "pointer",
                    background: selected === i.pair ? "var(--panel-2)" : undefined,
                  }}
                >
                  <td className="mono">{i.pair}</td>
                  <td>
                    {i.has_spot ? (
                      <span className="badge badge-ok">有</span>
                    ) : (
                      <span className="badge badge-err" title="无现货交易对，无法对冲">
                        无
                      </span>
                    )}
                  </td>
                  <td>{i.funding_interval_hours}h</td>
                  <td className="mono">{fmtCountdown(i.next_settlement_ms, now)}</td>
                  <td>{pct(i.funding_rate, 4)}</td>
                  <td className={i.funding_annualized && i.funding_annualized > 0 ? "" : "muted"}>
                    {pct(i.funding_annualized)}
                  </td>
                  <td>{pct(i.next_funding_rate, 4)}</td>
                  <td>{pct(i.max_funding_rate, 3)}</td>
                  <td>{pct(i.premium, 4)}</td>
                  <td>{pct(i.interest_rate, 4)}</td>
                  <td>{pct(i.funding_mean_annualized)}</td>
                  <td>{i.funding_std === null ? "—" : i.funding_std.toFixed(6)}</td>
                  <td>{i.streak ?? "—"}</td>
                  <td>{pct(i.reversal_freq, 0)}</td>
                  <td>{i.half_life ?? "—"}</td>
                  <td>{pct(i.basis_pct, 4)}</td>
                  <td>{usd(i.adv_usd)}</td>
                  <td className="mono">{fmtTime(i.updated_ms)}</td>
                </tr>
              ))}
              {visible.length === 0 && (
                <tr>
                  <td colSpan={18} className="muted">
                    没有符合条件的机会（扫描已排除 24h 成交额 &lt; ${minVolume / 1e6}M、资金费为 0
                    {requireSpot ? "、以及没有现货交易对的标的" : ""}；请放宽上方筛选）
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <div className="card">
          <h3>
            资金费历史 · {selected}
            {copied === selected && (
              <span className="hint" style={{ marginLeft: 10 }}>
                已复制合约名称
              </span>
            )}
            {history && (
              <span className="hint" style={{ marginLeft: 10 }}>
                结算间隔 {history.interval_hours}h · 每日 {history.settlements_per_day} 次 · 共{" "}
                {history.points.length} 个结算点
              </span>
            )}
          </h3>
          {amplitude && (
            <div className="grid grid-3" style={{ marginBottom: 12 }}>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>近两年单日最大振幅</h3>
                <div className="score-big">{pct(amplitude.max_daily_amplitude, 1)}</div>
                <p className="hint">
                  {amplitude.max_amplitude_date ?? "—"} · 共 {amplitude.days} 天（
                  {amplitude.from} ~ {amplitude.to}）
                </p>
              </div>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>平均单日振幅</h3>
                <div className="score-big">{pct(amplitude.avg_daily_amplitude, 1)}</div>
              </div>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>建议杠杆</h3>
                <div className="score-big" style={{ color: "var(--green)" }}>
                  {amplitude.suggested_leverage}x
                </div>
                <p className="hint">{amplitude.rule}</p>
              </div>
            </div>
          )}
          <Sparkline values={ascending.map((p) => p.annualized)} />
          {basis && (
            <div className="grid grid-3" style={{ marginTop: 12 }}>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>基差历史分位数</h3>
                <div className="score-big">{pct(basis.percentile, 0)}</div>
                <p className="hint">
                  当前 {pct(basis.current, 4)}，近 {basis.count} 天区间 [
                  {pct(basis.min, 4)}, {pct(basis.max, 4)}]；分位越高说明当前基差越大，正基差套利越有利
                </p>
              </div>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>基差波动率</h3>
                <div className="score-big">{pct(basis.volatility, 4)}</div>
                <p className="hint">基差标准差；越大越易造成保证金压力（最大 {pct(basis.max_abs, 4)}）</p>
              </div>
              <div className="card" style={{ marginBottom: 0 }}>
                <h3>基差收敛速度</h3>
                <div className="score-big">{basis.half_life ?? "—"}</div>
                <p className="hint">
                  |基差| 的 AR(1) 半衰期（天）；越小收敛越快，额外收益兑现越快
                </p>
              </div>
            </div>
          )}
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>结算时间</th>
                  <th>费率</th>
                  <th>年化</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((p) => (
                  <tr key={p.time}>
                    <td className="mono">{fmtTime(p.time)}</td>
                    <td>{pct(p.rate, 4)}</td>
                    <td>{pct(p.annualized)}</td>
                  </tr>
                ))}
                {recent.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      该区间无结算数据
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h3>
          交易权限（OKX 下单能力 · 默认关闭）
          {trade && (
            <span className="hint" style={{ marginLeft: 10 }}>
              {trade.mode === "paper" ? "纸面模拟" : "实盘"} ·{" "}
              {trade.configured ? "密钥已配置" : "未配置密钥"} ·{" "}
              {trade.enabled ? "下单已开启" : "下单已关闭"}
              {trade.mode === "live" ? ` · ${trade.demo ? "模拟盘" : "真实盘"}` : ""}
            </span>
          )}
        </h3>
        <p className="warn">
          纸面模拟用实时公共价格在本机模拟成交，不发送任何交易请求；实盘使用独立的 okx_trade 密钥。
          系统不会自动交易。
        </p>
        {tradeErr && <div className="error">{tradeErr}</div>}
        {tradeMsg && <div className="warn">{tradeMsg}</div>}

        {trade && trade.mode === "live" && !trade.configured && (
          <>
            <div className="form-row">
              <label>
                交易 API Key
                <input value={cred.api_key} onChange={(e) => setCred({ ...cred, api_key: e.target.value })} />
              </label>
              <label>
                Secret
                <input
                  type="password"
                  value={cred.secret}
                  onChange={(e) => setCred({ ...cred, secret: e.target.value })}
                />
              </label>
              <label>
                Passphrase
                <input
                  type="password"
                  value={cred.passphrase}
                  onChange={(e) => setCred({ ...cred, passphrase: e.target.value })}
                />
              </label>
            </div>
            <label style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <input
                type="checkbox"
                checked={tradeConfirm}
                onChange={(e) => setTradeConfirm(e.target.checked)}
              />
              我确认该密钥具备交易权限，并自行承担交易风险
            </label>
            <button className="btn-primary" onClick={saveCred} disabled={!tradeConfirm}>
              保存交易密钥
            </button>
          </>
        )}

        {trade && (trade.mode === "paper" || trade.configured) && (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              <button onClick={() => setMode(trade.mode === "paper" ? "live" : "paper")}>
                切换为{trade.mode === "paper" ? "实盘" : "纸面模拟"}
              </button>
              <button onClick={() => setEnabled(!trade.enabled)}>
                {trade.enabled ? "关闭下单" : "开启下单"}
              </button>
              {trade.mode === "live" && (
                <button onClick={() => setDemo(!trade.demo)}>
                  切换为{trade.demo ? "真实盘" : "模拟盘"}
                </button>
              )}
              <button onClick={loadAccount}>读取账户配置</button>
              {trade.configured && (
                <button className="btn-danger btn-sm" onClick={clearCred}>
                  清除交易密钥
                </button>
              )}
            </div>

            {config && (
              <table style={{ marginBottom: 12 }}>
                <tbody>
                  <tr>
                    <td className="muted">账户等级 acctLv</td>
                    <td>{valueOf(config.acctLv)}</td>
                    <td className="muted">持仓模式 posMode</td>
                    <td>{valueOf(config.posMode)}</td>
                    <td className="muted">UPL</td>
                    <td>{valueOf(config.upl)}</td>
                  </tr>
                </tbody>
              </table>
            )}

            <div className="form-row">
              <label>
                合约 instId
                <input
                  value={order.inst_id}
                  onChange={(e) => setOrder({ ...order, inst_id: e.target.value })}
                />
              </label>
              <label>
                方向
                <select value={order.side} onChange={(e) => setOrder({ ...order, side: e.target.value })}>
                  <option value="sell">sell（开空/平多）</option>
                  <option value="buy">buy（开多/平空）</option>
                </select>
              </label>
              <label>
                类型
                <select
                  value={order.ordertype}
                  onChange={(e) => setOrder({ ...order, ordertype: e.target.value })}
                >
                  <option value="limit">limit</option>
                  <option value="market">market</option>
                </select>
              </label>
              <label>
                数量 sz
                <input value={order.sz} onChange={(e) => setOrder({ ...order, sz: e.target.value })} />
              </label>
              <label>
                价格 px（限价）
                <input value={order.px} onChange={(e) => setOrder({ ...order, px: e.target.value })} />
              </label>
              <label>
                保证金模式
                <select value={order.td_mode} onChange={(e) => setOrder({ ...order, td_mode: e.target.value })}>
                  <option value="cross">cross</option>
                  <option value="isolated">isolated</option>
                </select>
              </label>
            </div>
            <div className="row">
              <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={orderConfirm}
                  onChange={(e) => setOrderConfirm(e.target.checked)}
                />
                确认下单
              </label>
              <button
                className="btn-danger"
                onClick={placeOrder}
                disabled={!trade.enabled || !orderConfirm}
              >
                提交订单
              </button>
            </div>

            <div className="row" style={{ marginTop: 12 }}>
              <label>
                撤单 ordId
                <input value={ordId} onChange={(e) => setOrdId(e.target.value)} />
              </label>
              <button onClick={cancelOrder} disabled={!trade.enabled || !ordId}>
                撤单
              </button>
            </div>
          </>
        )}
      </div>

      <div className="card">
        <h3>
          风险检查参数
          <span className="hint" style={{ marginLeft: 10 }}>
            鼠标悬停参数名可看简介与建议区间；超出建议区间会标红
          </span>
        </h3>
        {riskErr && <div className="error">{riskErr}</div>}
        {riskMsg && <div className="warn">{riskMsg}</div>}
        {risk && (
          <>
            <div className="form-row">
              {Object.keys(RISK_META).map((key) => {
                const meta = RISK_META[key];
                const value = (risk as unknown as Record<string, number>)[key];
                const outOfRange = value < meta.min || value > meta.max;
                const tip = `${meta.hint} 建议区间 ${meta.min} ~ ${meta.max}。`;
                return (
                  <label key={key}>
                    <span
                      title={tip}
                      style={{ color: outOfRange ? "var(--red)" : undefined, cursor: "help" }}
                    >
                      {meta.label}
                      {outOfRange ? " ⚠ 超出建议区间" : ""}
                    </span>
                    <input
                      type="number"
                      step={meta.step}
                      value={value}
                      title={tip}
                      style={{ borderColor: outOfRange ? "var(--red)" : undefined }}
                      onChange={(e) => setRisk({ ...risk, [key]: Number(e.target.value) })}
                    />
                  </label>
                );
              })}
            </div>
            <button className="btn-primary" onClick={saveRisk}>
              保存风险参数
            </button>
          </>
        )}
      </div>

      <div className="card">
        <h3>
          双腿持仓（现货 + 永续）
          <span className="hint" style={{ marginLeft: 10 }}>
            共 {positions.length} 个
          </span>
        </h3>
        <p className="warn">
          开仓为两腿顺序下单（先现货、后永续），永续腿失败会自动回滚现货腿；仅供人工操作。
        </p>
        {posErr && <div className="error">{posErr}</div>}
        {posMsg && <div className="warn">{posMsg}</div>}

        <div className="form-row">
          <label>
            交易对
            <input value={openForm.pair} onChange={(e) => setOpenForm({ ...openForm, pair: e.target.value })} />
          </label>
          <label>
            方向
            <select
              value={openForm.direction}
              onChange={(e) => setOpenForm({ ...openForm, direction: e.target.value })}
            >
              <option value="long_spot_short_perp">多现货 + 空永续（正资金费）</option>
              <option value="short_spot_long_perp">多永续 + 空现货（负资金费）</option>
            </select>
          </label>
          <label>
            总资金 USD
            <input
              type="number"
              value={openForm.capital_usd}
              onChange={(e) => setOpenForm({ ...openForm, capital_usd: Number(e.target.value) })}
            />
          </label>
          <label>
            永续杠杆
            <input
              type="number"
              value={openForm.leverage}
              onChange={(e) => setOpenForm({ ...openForm, leverage: Number(e.target.value) })}
            />
          </label>
          <label>
            下单类型
            <select
              value={openForm.ordertype}
              onChange={(e) => setOpenForm({ ...openForm, ordertype: e.target.value })}
            >
              <option value="market">market</option>
              <option value="limit">limit</option>
            </select>
          </label>
          <label>
            备注
            <input value={openForm.note} onChange={(e) => setOpenForm({ ...openForm, note: e.target.value })} />
          </label>
        </div>
        {planPreview && (
          <div className="hint" style={{ marginBottom: 8 }}>
            <div>
              计划：现货 {planPreview.spot_side} {planPreview.inst_spot} {planPreview.spot_qty} @{" "}
              {planPreview.spot_price}（≈${planPreview.spot_notional.toLocaleString()}）｜ 永续{" "}
              {planPreview.perp_side} {planPreview.inst_perp} {planPreview.perp_contracts} 张 @{" "}
              {planPreview.perp_price}（≈${planPreview.perp_notional.toLocaleString()}）
            </div>
            <div>
              预计年化：<b>{pct(planPreview.expected_annual)}</b>（资金费{" "}
              {pct(planPreview.funding_annualized)} − 开平手续费 {planPreview.fee_bps} bps ×4 ={" "}
              {pct(planPreview.round_trip_fee)}）
            </div>
            <div className={planPreview.leverage_ok === false ? "error" : ""}>
              建议杠杆：{planPreview.suggested_leverage ?? "—"}x
              {planPreview.max_daily_amplitude !== null &&
                `（近两年单日最大振幅 ${pct(planPreview.max_daily_amplitude, 1)}）`}
              {planPreview.leverage_ok === false
                ? ` · 当前 ${planPreview.leverage}x 超过建议杠杆，无法开仓`
                : planPreview.leverage_ok === true
                  ? ` · 当前 ${planPreview.leverage}x 通过`
                  : " · 未能获取建议杠杆，开仓时会被拒绝"}
            </div>
          </div>
        )}
        <div className="row">
          <button onClick={runPlan}>试算仓位</button>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={openConfirm}
              onChange={(e) => setOpenConfirm(e.target.checked)}
            />
            确认开仓
          </label>
          <button
            className="btn-danger"
            onClick={openPos}
            disabled={!trade?.enabled || !openConfirm || planPreview?.leverage_ok === false}
            title={
              planPreview?.leverage_ok === false
                ? "杠杆超过建议杠杆，已被强制禁止开仓"
                : undefined
            }
          >
            开仓（双腿）
          </button>
          <button onClick={runUnwind} disabled={!trade?.enabled}>
            风险检查 / 自动平仓
          </button>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <input
              type="checkbox"
              checked={showClosed}
              onChange={(e) => setShowClosed(e.target.checked)}
            />
            含已平仓
          </label>
          <button onClick={loadPositions}>刷新列表</button>
        </div>

        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>交易对</th>
                <th>方向</th>
                <th>状态</th>
                <th>每腿名义</th>
                <th>现货量</th>
                <th>永续张数</th>
                <th>Delta(USD)</th>
                <th>爆仓距离</th>
                <th>累计资金费</th>
                <th>已实现</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td className="mono">{p.pair}</td>
                  <td className="hint">
                    {p.direction === "short_spot_long_perp" ? "多永续+空现货" : "多现货+空永续"}
                  </td>
                  <td>
                    <span className={`badge ${p.status === "open" ? "badge-ok" : p.status === "error" ? "badge-err" : "badge-run"}`}>
                      {p.status}
                    </span>
                    {p.demo ? <span className="hint"> 模拟</span> : null}
                  </td>
                  <td>{usd(p.notional_usd)}</td>
                  <td>{p.spot_qty}</td>
                  <td>{p.perp_contracts}</td>
                  <td>{usd(p.delta_usd)}</td>
                  <td>{pct(p.liq_distance_pct, 1)}</td>
                  <td>{usd(p.funding_accrued)}</td>
                  <td className={p.realized_pnl < 0 ? "error" : ""}>{usd(p.realized_pnl)}</td>
                  <td>
                    {p.status === "open" && (
                      <>
                        <button className="btn-sm" onClick={() => refreshPos(p.id)}>
                          刷新
                        </button>{" "}
                        <button className="btn-sm btn-danger" onClick={() => closePos(p.id)}>
                          平仓
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {positions.length === 0 && (
                <tr>
                  <td colSpan={12} className="muted">
                    暂无持仓
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
