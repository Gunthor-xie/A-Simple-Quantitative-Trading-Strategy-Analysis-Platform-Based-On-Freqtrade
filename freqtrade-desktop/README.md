# Freqtrade Desktop

本地运行的 Freqtrade 桌面端：Electron + React 前端，Python FastAPI 后端，后端通过
subprocess 调用 freqtrade CLI。重心是**策略回测与分析**（综合评分、多策略对比、
K 线指标叠加），同时支持**信号模式**（不需要交易所密钥）以及可显式开启的
dry-run / OKX 实盘交易。

> 完整功能说明、架构细节与测试范围见 [freqtrade-desktop/README.md](freqtrade-desktop/README.md)。

## 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 | 当前主要支持 Windows（含 `dev.cmd` / `start-*.ps1`） |
| Python | 3.11+（64 位） | 后端与 freqtrade 共用同一个 venv |
| Node.js | 18+ | 前端 Electron / Vite |
| Freqtrade | 最新稳定版 | 需先单独安装，见下一步 |

## 快速开始

### 1. 安装 Freqtrade

```powershell
git clone https://github.com/freqtrade/freqtrade.git freqtrade-src
cd freqtrade-src
.\setup.ps1          # 按提示安装到 .venv
```

### 2. 安装本项目依赖

```powershell
cd freqtrade-desktop\backend
pip install -r requirements.txt

cd ..\desktop
npm install
```

### 3. 一键启动（推荐）

```powershell
cd freqtrade-desktop
.\dev.cmd
```

`dev.cmd` 会检查本地后端（127.0.0.1:8766）并在需要时重启，然后以前台方式打开
Electron 窗口；关闭终端即停止前端。

其他用法：

```bat
dev.cmd backend   :: 只启动后端（后台常驻）
dev.cmd web       :: 后端 + Vite，浏览器访问 http://127.0.0.1:5173
dev.cmd stop      :: 停止后端与 Vite
```

希望服务在关闭终端后继续运行（只通过浏览器使用）时，也可以执行
`.\start-services.ps1`，日志写在 `freqtrade-desktop\backend\data\` 与
`freqtrade-desktop\desktop\` 下。

## 配置密钥

项目**不会**把密钥写进配置文件，全部通过环境变量注入：

1. 复制模板：`freqtrade-desktop\APIserverKey.example.txt` → `freqtrade-desktop\APIserverKey.txt`
2. 填入自己的 OKX API Key / Secret / Passphrase 与本机 api_server 密码
3. 在终端执行该文件中的 `$env:...` 行，再启动服务

只做回测或信号模式时，交易所的三行密钥可以留空。`APIserverKey.txt` 与 `.env`
已被 `.gitignore` 忽略，请勿提交到 GitHub。

桌面端自己保存的连接密码写入系统钥匙串；钥匙串不可用时回退到环境变量
`FTDESK_SECRET_*`。更多细节见 [user_data/README.md](freqtrade-desktop/user_data/README.md)。

## 目录结构

```
freqtrade-desktop/
  backend/       FastAPI 后端（routers / services / scripts / tests）
  desktop/       Electron + React 前端
  user_data/     策略与配置（行情、回测结果在首次运行时生成）
docs/            ADR 与文档
.scratch/        规格与调研草稿
```

## 克隆下来之后

目前你获得了该项目的源码、策略和配置模板；下面这些数据首次运行时有些自动出现在本地，有些需要你自行创建：

| 内容 | 位置 | 怎么来 |
| --- | --- | --- |
| Python / Node 依赖 | `.venv`、`node_modules/` | `pip install -r requirements.txt`、`npm install` |
| 历史行情 K 线 | `user_data/data/` | 界面「设置 → 数据」下载 |
| 回测结果 | `user_data/backtest_results/` | 「回测中心」运行回测 |
| 超参优化结果 | `user_data/hyperopt_results/` | 运行 hyperopt |
| 清算流特征与采集数据 | `user_data/liquidation/` | `python scripts\build_cascade_features.py` |
| 因子面板 | `user_data/factors/` | `python scripts\factor_research.py` |
| 应用数据库与日志 | `backend/data/`、`user_data/logs/` | 启动后端时自动创建 |

因此从零开始只需要：`pip install` → `npm install` → `dev.cmd`，然后在界面里下载数据即可。

## 套利模块（资金费率 / 基差）

与策略机器人**并列独立**的一个模块（「套利机会」页），默认关闭、默认纸面模拟。之所以
独立：freqtrade 单进程只能是现货**或**合约、且是单腿方向性交易，无法承载 delta 中性
双腿，因此双腿执行器直接走 OKX 的公共/私有 REST。

三层能力：

1. **资金费 / 基差扫描（只读，全部实时）**：每次扫描都调 OKX 公共接口，**不读本地数据**。
   自动排除 24h 成交额 < **$1M**、资金费为 **0**、以及**没有现货交易对**的标的——OKX 的
   485 个 USDT 永续里只有约 220 个有现货对，代币化股票/商品（AAPL、MSFT、NG、SAMSUNG…）
   仅有合约、无法做现货+永续对冲。扫描有 **10 秒硬超时**，超时返回「网络连接超时」（HTTP 504）。
2. **下单能力**：`okx_read:*`（只读）与 `okx_trade:*`（交易）密钥分离存放；下单需先开启
   且逐次勾选确认。
3. **双腿执行器**：支持 **多现货 + 空永续**（正费率）与 **多永续 + 空现货**（负费率，需
   OKX 开通逐币种杠杆/借币）。现货腿先下单，永续腿失败自动回滚现货腿；记录方向、delta、
   爆仓距离、累计资金费。

**点击某个标的**会：复制合约名称到剪贴板 → 拉资金费历史 → 拉近两年日 K 算**单日最大振幅**
并给出**建议杠杆** `clamp(int(0.5 / 最大振幅), 1, 5)` → 拉基差历史（分位数/波动率/收敛半衰期）。

**试算仓位**给出每腿名义、预计年化（资金费 − 开平共 4 次手续费，默认单边 **5 bps**，可改）
与建议杠杆；**下单前强制校验杠杆**，超过建议杠杆直接拒绝开仓。

### 决策因子：哪些进表格、哪些点开才算

按获取成本分层，避免耗光 10 秒扫描预算：

| 因子 | 获取方式 | 位置 |
| --- | --- | --- |
| 结算周期 (8h/4h/1h)、下次结算倒计时、费率上下限、溢价指数、利率成分、预测费率 | 与「当前费率」同一次调用（本就用于过滤） | 表格 |
| 当前/年化费率、基差、24h 成交额、是否有现货 | 扫描时的批量接口 | 表格 |
| 近 60 次均值年化、历史费率标准差、连续同号次数、费率反转频率、半衰期 (AR(1)) | 每标的**多一次** `funding-rate-history`，只富集返回的 top-N | 表格 |
| 基差历史分位数、基差波动率、基差收敛半衰期 | 每标的**多次**日 K 翻页，成本高 | **点选后才拉** |

表格数值列的表头都是三态排序：**升序 → 降序 → 不排序**（空值恒排最后）；表格上方提供
筛选（留空即不设条件）：年化资金费 ≥、历史费率标准差 ≤、连续同号次数 ≥、距下次结算 ≥ N 小时。

### 风险参数与调度器

风险参数在持仓区上方可调，悬停参数名显示简介与建议区间，超出区间标红：爆仓距离警戒
（建议 5%–30%）、delta 偏离上限（1%–10%）、手续费 bps（1–10）。

后台调度器（盯市 + 风险自动平仓）默认不随服务启动，未开启下单时是空转：

```bat
dev.cmd arb            :: 启动调度器（后台）
dev.cmd arb status     :: 查看持仓与事件
dev.cmd arb stop       :: 停止调度器
dev.cmd stop           :: 停止后端 / Vite / 调度器
```

或随服务一起 `.\start-services.ps1 -WithArb`；也可直接
`python scripts\run_arb_scheduler.py --status|--once`。

执行模式在套利页切换：`paper`（默认，本地纸面模拟，按实时公共价格模拟成交，**不发任何
交易请求、无需密钥**）/ `live`（真实 OKX，再分 `demo` 模拟盘与真实盘）。

HTTP 前缀 `/api/arb`：`/funding`、`/funding/history`、`/funding/amplitude`、`/funding/basis`、
`/risk`、`/trade/*`、`/positions/*`、`/events`。

## 测试

```powershell
cd freqtrade-desktop\backend
python -m pytest -q
```

覆盖评分引擎边界、回测 JSON 解析、BotClient REST 封装、信号去重与 API 冒烟。

## 安全说明

- 仓库不含任何交易所API与密钥，且同时不建议你在使用时像`APIserverKey.txt` 一样留下明文API与密钥。`APIserverKey.txt` 仅作为示例模板，方便你快速配置机器人。
- freqtrade `api_server` 默认只监听 `127.0.0.1`。
- 实盘交易未经测试，**不建议使用**。使用该功能前最好有一定的代码能力以及一段时间的Dry Run测试。**由此项目产生的任何资金损失概不负责**。
- 实盘交易需要在界面中显式勾选风险确认。

## 已知限制

- OKX 合约回测在早于近 3 个月的区间上，资金费率数据存在偏差；资金费率对回测收益率**影响较大**，务必合理设置。
- 回测精度为 OHLCV 级，手续费按交易所默认，未单独建模滑点。
- Telegram 控制的是本机运行中的 bot，需要本机保持在线。

## 免责声明

本项目仅供个人学习与研究使用，不构成投资建议。使用实盘交易功能产生的任何盈亏
由使用者自行承担。
