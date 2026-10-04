# 01 — 标的池定义与数据下载

Status: ready-for-agent
Type: task

## 目标

把「哪个池子、哪些标的、下载什么数据」固化成配置 + 可复用下载流程，产出一份可离线研究的
本地行情库（含股票类永续，当前本地一个都没有）。

## 交付物

- `freqtrade-desktop/user_data/factors/universes.json`：
  `crypto_majors`（上市 ≥24 个月、近 7 日均额 ≥2000 万美元）、
  `equity_liquid`（`instCategory=3`、上市 ≥90 天、近 7 日均额 ≥500 万美元）、
  `commodity_index`（`instCategory=4` + JP225）、`preipo_watch`（只观察不交易）。
- `factor_research.py universe` 子命令：拉取最新 instruments/tickers，套用筛选规则，写出配置并打印
  入池/出池原因。
- `factor_research.py download` 子命令：按池子下载 1h 与 1d candles + `funding_rate` + `mark` + `index`
  到 `user_data/data/okx/futures/`（复用 `PublicDataDownloader`，保持 freqtrade 原生布局与断点续传）。
- 覆盖率报告：每个标的的首末时间戳、行数、缺失周期、下载失败原因。

## 验收标准

1. `TSLA/USDT:USDT` 走现有 `to_instrument()` 得到 `TSLA-USDT-SWAP`，能成功下载 1h/1d/funding/mark/index。
2. 股票类标的的 `index-candles` 使用 `instId=TSLA-USDT`（去掉 `-SWAP`）。
3. 重复运行命中本地缓存、不重复下载；断线后可续跑。
4. 覆盖率报告能明确标出「上市太晚导致历史不足」的标的，而不是静默空文件。
5. 刷新 `leverage_tiers_USDT.json`（当前只有 1 条记录）。

## 待补

- 周末/假期 K 线完整性报告（24/7 交易 vs 美股休市）。
- 资金费非零比例统计（实测 TSLA 29/100、NVDA 41/100），供 carry 因子分层使用。

## Comments

### 2026-09-25 — 已实现并验证

- 落地 `backend/app/services/factor_panel.py`：`build_universe` / `download_pool` /
  `contract_values` / `load_candles` 等，CLI 为 `scripts/factor_research.py universe|download`。
- 标的池：`user_data/factors/universes.json` → 加密 25、股票 25、商品指数 8（未入池 416）。
- 实抓数据：加密池 12 个月、股票池 7 个月，25 标的 × (1h/1d + 资金费 [+ 指数价])，零错误。
- 发现并修正口径问题：成交量是「合约张数」，需按 `ctVal` 换算（BTC 0.01、DOGE 1000）。
- 新发现的硬约束：股票类指数价仅 60 天、资金费历史仅约 95 天（见 spec §2.2）。
