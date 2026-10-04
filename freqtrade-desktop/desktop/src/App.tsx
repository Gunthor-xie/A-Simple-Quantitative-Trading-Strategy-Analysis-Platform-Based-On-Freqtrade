import { useState } from "react";
import Backtests from "./pages/Backtests";
import Account from "./pages/Account";
import Charts from "./pages/Charts";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import Strategies from "./pages/Strategies";
import Trading from "./pages/Trading";

type TabKey = "dashboard" | "backtests" | "charts" | "account" | "trading" | "strategies" | "settings";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dashboard", label: "仪表盘" },
  { key: "backtests", label: "回测中心" },
  { key: "charts", label: "图表分析" },
  { key: "account", label: "账户" },
  { key: "trading", label: "信号与交易" },
  { key: "strategies", label: "策略管理" },
  { key: "settings", label: "设置" },
];

export default function App() {
  const [tab, setTab] = useState<TabKey>("dashboard");

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-logo">FT</span>
          <span className="brand-name">Freqtrade Desktop</span>
        </div>
        <nav className="nav">
          {TABS.map((item) => (
            <button
              key={item.key}
              className={`nav-item${tab === item.key ? " active" : ""}`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">v0.1.0 · 本地部署</div>
      </aside>
      <main className="main">
        {tab === "dashboard" && <Dashboard />}
        {tab === "backtests" && <Backtests />}
        {tab === "charts" && <Charts />}
        {tab === "account" && <Account />}
        {tab === "trading" && <Trading />}
        {tab === "strategies" && <Strategies />}
        {tab === "settings" && <Settings />}
      </main>
    </div>
  );
}
