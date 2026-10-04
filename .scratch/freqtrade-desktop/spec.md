# Freqtrade Desktop — v1 本地版规格

## 目标

个人使用的 Freqtrade 桌面端应用，v1 全本地部署（不部署服务器，架构为服务器化预留）。
重心：策略回测与分析（多维指标仪表盘、综合评分、多策略对比、K 线指标叠加）；保留直接交易
（默认信号模式，可显式开启 dry-run / OKX 实盘）。Telegram 控制本机运行的 bot。

## 架构

- 桌面端：Electron + React + TypeScript + TradingView lightweight-charts。
- 本地后端：Python FastAPI，与 freqtrade 共用同一 venv；subprocess 调用 freqtrade CLI。
- 执行器抽象：local（原生 venv）当前实现；WSL/远端留作后续。
- BotClient：封装 freqtrade REST API（JWT 登录），local/remote 连接类型，remote 本期不启用。
- 存储：本地 SQLite（连接、回测记录、评分权重、信号事件）。
- 密钥：keyring 优先，缺失时用环境变量 `FTDESK_SECRET_*`，不落明文配置文件。

## 核心接口

- `GET/POST /api/connections`、`POST /api/connections/{id}/test`
- `GET /api/bot/{id}/{status,profit,balance,trades,...}`、`POST /api/bot/{id}/{action}`
- `GET /api/strategies`、`POST /api/strategies/validate`
- `POST /api/backtests`（后台执行）、`GET /api/backtests`、`GET /api/backtests/{id}`、
  `POST /api/backtests/compare`、`GET /api/backtests/{id}/chart`
- `POST /api/data/download`（后台）、`GET /api/data/available`
- `GET/PUT /api/score/weights`、`GET /api/score/baselines?strategy=`
- `POST /api/signals/refresh`、`GET /api/signals`
- `POST /api/settings/build-config`
- `WS /api/ws`：每 2s 推送回测/信号/bot 快照

## 评分

默认权重：Sharpe 20%、Sortino 20%、Calmar 10%、利润因子 15%、胜率 10%、最大回撤 15%、期望 10%。
归一化基准：该策略历史最优，缺失时用内置默认值；指标缺失/不可计算记 0 分并标注。

## OKX 约束（官方文档核实）

- `exchange.name: okx`（EAA 用户 `myokx`），API 需 `password`（passphrase）。
- 每次 API 调用仅 100 根 K 线，初次下载较慢；合约 MARK 数据约 3 个月，更早回测资金费率有偏差。
- 合约：`trading_mode: futures`、`margin_mode: isolated`、仓位模式 Buy/Sell，不中途切换。

## 验收

- 信号模式无需 OKX 密钥即可运行。
- 回测 → 解析 → 评分 → 对比 → 图表闭环可用。
- 实盘需显式开启 + 二次确认；`force_entry_enable` 默认关闭。
- `api_server` 仅监听 127.0.0.1；密钥不进配置文件明文。
