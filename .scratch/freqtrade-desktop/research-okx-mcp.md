# OKX 调研备忘：官方 MCP 与 Freqtrade 约束核验

日期：2026-09-06
范围：本文件为 `freqtrade-desktop` 的调研产出，覆盖三部分：
1. OKX 官方 MCP（Agent Trade Kit）的能力、配置与安全边界；
2. 用户链接的社区仓库 **mbarinov/okx-mcp** 的能力、工具→OKX REST 端点映射，以及可结合进 FreqtradeDesktop v1 的接口/指标/因子头脑风暴；
3. `.scratch/freqtrade-desktop/spec.md` 中“OKX 约束（官方文档核验）”逐条对照官方来源的结论。

说明：正文里所有关键结论均附引用。OKX 官网 API 文档页面（okx.com/docs-v5）在本调研环境中无法直接抓取（SSRF/SSL 拦截），因此 OKX REST 行为以 freqtrade 官方文档与 ccxt 官方仓库/issue 的引用为准，二者均直接标注了 OKX 官方文档链接。

---

## 1. OKX 官方 MCP：Agent Trade Kit

### 1.1 结论速览

OKX 已发布官方 MCP 交易工具包 **Agent Trade Kit**，用于把 AI Agent 直接接到 OKX CEX 账户（现货/合约/期权/理财/交易机器人等）：

| 项目 | 内容 |
|---|---|
| 官方仓库 | github.com/okx/agent-trade-kit（MIT 开源） |
| npm 包 | `@okx_ai/okx-trade-mcp`（MCP server）、`@okx_ai/okx-trade-cli`（CLI） |
| 前置要求 | Node.js >= 18 |
| 传输方式 | 本地 stdio 进程（MCP 标准），无服务器、无数据库 |
| 凭据 | `~/.okx/config.toml`，支持多 profile（live/demo）；demo 需 `demo = true` |
| 能力 | 167 个工具、11 个模块（market/spot/swap/futures/option/account/event/earn/bot/news/smartmoney） |
| 安全 | `--read-only`、按模块过滤、内置限速；API key 只留在本机 |

来源：仓库 README（github.com/okx/agent-trade-kit）、npm 页面（npmjs.com/package/@okx_ai/okx-trade-mcp）。

### 1.2 安装与配置

```bash
npm install -g @okx_ai/okx-trade-mcp @okx_ai/okx-trade-cli
okx config init          # 交互式向导写入凭据
okx-trade-mcp setup --client claude-desktop|cursor|claude-code|vscode
```

手工配置 `~/.okx/config.toml` 示例（来自 npm 页）：

```toml
default_profile = "demo"

[profiles.live]
api_key = "your-live-api-key"
secret_key = "your-live-secret-key"
passphrase = "your-live-passphrase"

[profiles.demo]
api_key = "your-demo-api-key"
secret_key = "your-demo-secret-key"
passphrase = "your-demo-passphrase"
demo = true
```

注意：与 OKX REST API 一致，MCP 凭据也包含 **passphrase**。`demo = true` 走 OKX 模拟盘。

### 1.3 运行方式

```bash
okx-trade-mcp                          # 默认模块：spot, swap, account
okx-trade-mcp --modules market         # 仅行情（免 API key）
okx-trade-mcp --profile live --modules all
okx-trade-mcp --read-only              # 只读，禁止下单
```

### 1.4 能力边界

- `market` 模块 19 个工具：ticker、orderbook、candles（+history）、index candles、funding rate、mark price、open interest、70+ 技术指标等，**无需鉴权**。
- 交易模块覆盖 spot（13）、swap（17）、futures（18）、option（10）、account（14），含条件单/OCO/移动止损等算法单。
- `account` 模块含 “position mode” 查询工具。
- 内置 Agent Skills（`okx-cex-market` / `okx-cex-trade` / `okx-cex-portfolio` / `okx-cex-bot` / `okx-cex-earn` / `okx-cex-smartmoney`），供 Claude/Codex 类框架直接使用。

### 1.5 与 freqtrade-desktop 的关系（判断与建议）

- Agent Trade Kit 是“AI 直连 OKX 交易所”的通道；freqtrade-desktop 的 BotClient 封装的是 **freqtrade 的 REST API**（回测/干跑/信号由 freqtrade 管理）。两者定位不同：MCP 不会替代回测与评分闭环。
- 潜在用途：作为桌面端“行情/信号来源”或 Codex 侧的只读查询通道（`--modules market --read-only`，无需 API key 即可取行情）；如需实盘执行，走 freqtrade bot 仍比让 LLM 直接下单更可控。
- 安全实践：默认 `--read-only` + demo profile + 二次确认；不要把 passphrase 落明文配置文件（freqtrade-desktop 的密钥策略是 keyring 优先、环境变量兜底，见 spec “密钥”一节）。
- 另一条官方产品线是 **OnchainOS（web3.okx.com）MCP Server**，覆盖 DEX/链上行情与交易（HTTP + OK-ACCESS-KEY 头），与 CEX 的 Agent Trade Kit 是两套东西，不要混用。

### 1.6 社区/第三方 OKX MCP（简表，供甄别）

| 名称 | 说明 | 风险提示 |
|---|---|---|
| pipeworx-io/mcp-okx | 只读行情型（instruments/tickers/candles/funding/mark），另有 Pipeworx 网关版 | 非官方；若接交易需自行审计 |
| aahl/mcp-okx 等个人仓库 | 行情 + 下单，README 即要求 API key/secret/passphrase | 非官方；凭据处理与限速策略不透明，不建议在项目内使用 |

本项目如需要“AI 助手可交易 OKX”，应优先评估官方 Agent Trade Kit；社区实现仅作只读行情参考。

---

## 2. 用户所指仓库：mbarinov/okx-mcp（社区项目，非 OKX 官方）

### 2.1 定位与前提澄清

用户提问原文：结合 github.com/mbarinov/okx-mcp 这个“来自 OKX”的 MCP 项目，阅读文档后头脑风暴：有哪些接口、指标或因子可以结合进 FreqtradeV1 桌面项目。

**前提澄清**：该仓库不是 OKX 官方出品，而是社区作者 Max Barinov 的 MIT 开源项目（npm 包名 `okx-mcp`，v0.2.0，Node >= 20），用 `xmcp` 框架（stdio MCP）封装第三方 Node 库 `okx-api`（作者 tiagosiebler/okx-api）。OKX 官方 MCP 是另一套 Agent Trade Kit（见第 1 节），两者不要混用。

来源：
- 仓库主页与 README：https://github.com/mbarinov/okx-mcp 、https://raw.githubusercontent.com/mbarinov/okx-mcp/main/README.md
- npm 页：https://www.npmjs.com/package/okx-mcp
- 本机已抓取的主源文件（package.json、src/services/okxApiClient.ts、src/tools/get_positions.ts）：`%TEMP%\okx_mcp_primary\`

### 2.2 能力清单：5 个只读工具

该 MCP 只暴露 5 个**只读**工具，README 明确要求 OKX API key 只开 Read 权限（不开 Trade/Withdraw），数据本地直连 OKX、无持久化：

| MCP 工具 | 底层 okx-api 方法 | OKX REST 端点 | 返回与参数 |
|---|---|---|---|
| `get_account_summary` | 聚合其余 3 个查询 | —（组合） | 总资产 USDT、按币种分配、挂单数、持仓数；无参数 |
| `get_portfolio` | `getBalance()` | `GET /api/v5/account/balance` + 对非 USDT 币种调 `GET /api/v5/market/ticker` | 币种余额/冻结/折算 USDT 值；无参数 |
| `get_positions` | `getPositions()` | `GET /api/v5/account/positions` | 合约持仓 size/avgPx/upl/margin；无参数 |
| `get_open_orders` | `getOrderList()` | `GET /api/v5/trade/orders-pending` | 挂单 ordId/instId/ordType/px/sz/side/state；无参数 |
| `get_order_history` | `getOrderHistory()` | `GET /api/v5/trade/orders-history` | 成交/历史订单；参数 instId(必填)、begin/end 时间戳 |

端点映射依据（okx-api 端点表，访问 2026-09-06）：
https://raw.githubusercontent.com/tiagosiebler/okx-api/master/docs/endpointFunctionList.md

**源码里的坑（对照 src/services/okxApiClient.ts 逐条核实）：**
- `get_order_history` 硬编码 `instType: "SPOT"` 且调用的是 `orders-history`（OKX 语义为近 7 天已成交/已撤销单，非 3 个月归档 `orders-history-archive`）。也就是说**期货成交历史、超过 7 天的成交单都取不到**，与桌面端“现货+合约并重、长期复盘”的目标不匹配，移植时必须换用 fills/archive/bills 系列端点。
- `get_open_orders` 未传 `instType`；按 OKX 语义该参数默认 SPOT，若要覆盖合约挂单需显式传 SWAP/FUTURES（或按统一账户模式核实实际行为）。
- `get_portfolio` 用 `account/balance` 的交易账户余额折算，折算价取 `${ccy}-USDT` 现货 ticker；对无 USDT 现货对（如部分合约保证金币种）会静默跳过，折算口径可能与 freqtrade `/balance` 不一致。
- `get_account_summary` 只是前两者的计数与占比聚合，没有额外信息。

### 2.3 定性：它提供“交易所侧只读账户/订单可见性”，不是行情或因子源

5 个工具里唯一碰到行情的是折算用的 `market/ticker`；没有 candles/history/funding-rate/open-interest/orderbook/指数/mark K 线等市场数据工具，也没有任何交易执行能力。因此：

- 想让它“给回测加指标/因子”是方向性错误——它不提供指标或历史行情；
- 它的正确借鉴方式是“**OKX 侧真实账户快照**”：总资产与资产分配、持仓（uPnL/保证金）、挂单、近期成交，正好补 freqtrade REST 看不到的交易所侧事实（freqtrade 的 `/balance /profit /status /trades` 是 bot 视角，且不含 OKX 账单/资金费明细）；
- 真正能当“指标/因子”的行情数据源见 2.4-B，走 OKX v5 公开数据端点 + freqtrade 的下载机制，与这个 MCP 工具集无关（OKX 官方 Agent Trade Kit 的 `market` 模块倒是包含这些，见第 1 节）。

### 2.4 FreqtradeDesktop v1 结合点头脑风暴

以下结合 `.scratch/freqtrade-desktop/spec.md` 与现有代码（`backend/app/services/bot_client.py`、`routers/api.py`、`signal_engine.py`、`executor.py`、`desktop/src/pages/Trading.tsx`）。

#### A. 直接把“5 个只读工具”移植成后端 OkxClient + 桌面账户视图（P2，低风险，推荐）

不必在桌面端跑一个 Node MCP stdio 进程；用 Python 直连 OKX v5 只读端点即可实现同样能力：

1. 后端新增 `OkxClient` 服务（httpx 直接签名，或复用 freqtrade venv 里的 ccxt.okx 只读方法），实现 `account_summary / portfolio / positions / open_orders / order_history` 五个方法与 `/api/okx/...` 路由，镜像 MCP 工具语义但按 v1 需要扩展：
   - 持仓/挂单/成交都显式支持 `instType=SPOT/SWAP/FUTURES`（修复仓库硬编码 SPOT 的坑）；
   - 成交历史改用 `trade/fills`（成交明细）与 `trade/orders-history-archive`（3 个月），必要时接 `account/bills`（账单：手续费、资金费收支）；
2. 密钥治理沿用项目现状：OKX **只读 key**（Read 权限）与实盘交易 key 分开，都存系统钥匙串（keyring 键名如 `okx:{id}:readonly:key/secret/passphrase`），不回落到配置文件明文；设置页提供“只读密钥可留空，仅信号模式不受影响”的文案（与 spec 的信号模式约定一致）；
3. 前端在“信号与交易”页（或新“账户”卡片）展示：总资产/资产分配、持仓表（size/entry/uPnL/margin）、挂单、近 N 天成交；并与 `BotClient` 的 `/balance /profit /status /trades` **交叉核对**：出现“bot 显示无持仓但 OKX 有持仓”“bot 成交时间与 OKX fills 不一致”时告警——这对 dry-run 验证和 bot 崩溃后恢复都很有价值；
4. 因为只读、无持久化、本地直连，风险与 MCP 宣称的安全边界一致；再加一层：只读 key 绑定 IP 白名单、轮询节流（如 10–30s），避免踩 OKX 限速。

#### B. 真正的“指标/因子”结合点：OKX v5 市场数据 + freqtrade candle 类型（P1，推荐）

freqtrade 官方 `download-data`（2026.x）已支持多 candle 类型：
`--candle-types {spot,futures,mark,index,premiumIndex,funding_rate}`，且**合约模式默认自动下载 futures + funding_rate + mark**（官方文档原文见第 3/4 节引用）。本仓库 `user_data/data/okx/futures/` 下已有的 `BTC_USDT_USDT-5m-futures.json.gz`、`BTC_USDT_USDT-8h-funding_rate.json.gz`、`BTC_USDT_USDT-4h-mark.json.gz` 就是该机制的实际产物。

据此可按“能不能进回测”把 OKX 数据分成三类：

1. **能进回测（本地文件，无前视风险）**——走 `download-data` 落盘、策略经 DataProvider/informative pairs 读取：
   - futures OHLCV（已支持）、**funding_rate 历史**（资金费建模，回测更准）、**mark K 线**（回测与资金费计算必需，OKX 仅约 3 个月）、**index K 线**；
   - 由以上可衍生：**基差**（futures close − index close / mark−index）、**资金费年化**（8h 费率 × 3 × 365）、资金费 z-score/分位、指数与合约乖离等——作为策略可 merge 的列或图表叠加序列；
2. **只能实盘 overlay（策略运行时或桌面图表层拉取）**：
   - 当前 funding rate / 预测下一次 funding rate（swap ticker 公开字段）、盘口/深度、最新成交、当前 open interest（OKX `/public/open-interest` 只给当前值）——适合“信号触发时环境快照”和 lightweight-charts 叠加，不适合回测；
3. **只适合桌面“辅助分析/提示”**（OKX Rubik 统计类历史序列，覆盖币种有限、口径需核实）：
   - 多空账户数/持仓人数比、taker 买卖量、合约持仓量/成交量历史等——可用作信号触发时的大盘环境提示，不建议进策略主逻辑。

**落地建议（不偏离 spec 的“回测/实盘同一策略代码库”原则）：**
- 下载 UI（`POST /api/data/download` 参数 `DownloadParams`）增加 candle 类型与 coverage 元数据；`executor.list_data()` 已经会列出 funding_rate/mark 文件，前端据此显示“合约回测所需数据齐备/缺失”并给出 OKX 约 3 个月 mark 限制的提示；
- 回测结果页新增“资金费/基差环境摘要”（如区间平均年化资金费、极端资金费时段数与策略敞口重叠度），不改变现有评分权重，仅作归因参考；
- 图表服务（`ChartService`/lightweight-charts）支持叠加 index/mark/funding_rate/基差序列；实时图额外叠加 ticker 里的当前资金费率与 OI（现有 `/charts/live` 通道扩展即可，不必侵入策略）；
- 若未来要这些因子真的参与信号，优先做成“策略从本地 funding_rate/index 文件 merge 出列”，保持回测与实盘一致（两端都读同一套下载数据），避免仅实盘可用导致信号漂移。

#### C. 实盘复盘与归因（P2/P3，价值高）

- 用 OKX `fills`（逐笔成交）与 `account/bills`（资金费/手续费收支）对账：桌面端可度量**真实滑点**（成交均价 vs 信号价/回测假设价）、**真实资金费支出** vs 回测资金费假设、真实手续费率，回填到 `BacktestResult`/评分报告作为“回测-实盘偏差”警告——正好补 spec“回测不单独建模滑点”的已知局限；
- 通过 exchange order id 把 OKX 成交与 freqtrade `tradesv3.sqlite` 记录关联，做“真实成交回放/复盘”（spec 扩展联想已列出“实盘复盘”，这里给出数据来源与对账路径）。

#### D. 信号触发时的“市场环境提示”（P2，产品化亮点）

信号模式/dry-run 下，`SignalEngine` 产生信号时让后端顺带取一次公开行情快照（swap ticker 资金费率、基差、OI 增量、盘口价差），写进 `SignalEvent` 扩展字段或图表标注：例如“做多信号，但当前资金费年化 > 30%，多单拥挤度高”提示。v1 只提示不阻断；后续若要变成可配置的“风控闸门”，应在桌面端显式开关（与 spec 的二次确认、`force_entry_enable` 默认关闭精神一致）。

#### E. 未来 AI 助手形态（P3/P4，可选，不推荐 v1 引入）

如果未来想给桌面端/Telegram 加“用自然语言查持仓/解释账户”，更合适的形态是：在 FastAPI 内实现只读 `OkxClient` + 一个受控的问答端点（本地 LLM 或 Codex 类助手），而不是嵌一个 Node MCP stdio 子进程；MCP 的价值在“给 LLM 客户端统一工具协议”，等 v2 服务器化、或用户确实在用 Claude/Codex 直连账户数据时再评估（届时官方 Agent Trade Kit 比 mbarinov 仓库更完整：167 工具/11 模块、`--read-only`、demo profile、`market` 模块免 key）。

### 2.5 优先级小结（对应 P0–P4）

| 结合点 | 建议阶段 | 工作量/风险 |
|---|---|---|
| 下载 UI 扩展 candle 类型 + 数据齐备提示 | P1 | 小 / 低 |
| 图表叠加 index/mark/基差/资金费率 | P1–P2 | 中 / 低 |
| OkxClient 只读账户/持仓/挂单/成交视图 + bot 交叉核对 | P2 | 中 / 低（密钥只读、keyring） |
| 信号触发环境快照与提示横幅 | P2 | 小 / 低 |
| fills/bills 复盘：真实滑点与资金费对比 | P2–P3 | 中 / 低 |
| AI 助手/MCP 接入（官方 Kit 优先） | P3–P4 | 大 / 中（需审计与二次确认） |

### 2.6 风险与取舍

1. **依赖选型**：`okx-api` 是第三方 Node 库；Python 侧要么用 freqtrade 自带的 ccxt（已随 venv 存在），要么官方 Python SDK/自签名只读请求。只实现上述 5 个查询其实只涉及 3 个私密 GET + 1 个公开 GET，不值得为此引入 Node 运行时依赖。
2. **SPOT 硬编码与 7 天窗口**：照搬 mbarinov 的 `get_order_history` 会漏掉合约与超过 7 天的单子，复盘必须扩展为 fills/archive/bills。
3. **限速与翻页**：OKX 私密接口有每 IP/密钥限速与 100 条/页分页，账户轮询频率要克制，历史成交分页拉取要放后台任务（复用现有 jobs 机制）。
4. **密钥边界**：桌面“看账户”用只读 key；freqtrade 实盘 key 仍走 `FREQTRADE__EXCHANGE__*` 环境注入，两者不要复用、不要落盘；如未来接 MCP/AI，也先走只读/demo profile。
5. **不改变执行终端结论**：OKX 没有“接收外部信号”的 API，实盘仍由 freqtrade 作为交易终端下单；MCP 只是查询通道，不能让 LLM 直接具备下单权限（spec 既定决策不变）。

---

## 3. spec “OKX 约束”逐条核验

核验对象为 spec.md 的 “OKX 约束（官方文档核验）”与 README “安全与已知限制”，主依据为 freqtrade 官方文档 Exchange-specific Notes（docs.freqtrade.io/en/2026.4/exchanges/）。

### 2.1 结论总表

| spec 断言 | 核验结论 | 依据 |
|---|---|---|
| `exchange.name: okx`；EAA 用户用 `myokx` | 正确 | freqtrade 官方文档 OKX 节 |
| API 需要 `password`（passphrase） | 正确 | 同上 |
| 每次 API 调用仅 100 根 K 线，初次下载较慢 | 正确（freqtrade 数据获取路径按 100/次分页） | freqtrade 文档 + ccxt issue #20756 |
| 合约用 MARK 数据，仅约 3 个月 | 正确 | freqtrade 文档 OKX 节 |
| 更早回测资金费率有偏差 | 正确（MARK 不足时无法正确计算资金费） | freqtrade 文档 OKX 节 |
| `trading_mode: futures` + `margin_mode: isolated` | 正确（OKX 期货仅列 isolated 支持） | freqtrade 支持矩阵 |
| 仓位模式 Buy/Sell（单向），不中途切换 | 正确 | freqtrade 文档 OKX 节 |

### 2.2 引用原文（freqtrade 官方文档，OKX 节）

1) API key passphrase：
> OKX requires a passphrase for each api key, you will therefore need to add this key into the configuration so your exchange section looks as follows:
> `"password": "your_exchange_api_key_password"`

2) EAA：
> If you've registered with OKX on the host my.okx.com (OKX EAA)- you will need to use "myokx" as the exchange name. Using the wrong exchange will result in the error "OKX Error 50119: API key doesn't exist" - as the 2 are separate entities.

3) 100 根 K 线：
> Warning: OKX only provides 100 candles per api call. Therefore, the strategy will only have a pretty low amount of data available in backtesting mode.

4) 仓位模式与 MARK 数据：
> OKX Futures has the concept of "position mode" - which can be "Buy/Sell" or long/short (hedge mode). Freqtrade supports both modes (we recommend to use Buy/Sell mode) - but changing the mode mid-trading is not supported and will lead to exceptions and failures to place trades. OKX also only provides MARK candles for the past ~3 months. Backtesting futures prior to that date will therefore lead to slight deviations, as funding-fees cannot be calculated correctly without this data.

5) 支持矩阵（同页表格）：
> OKX | spot | limit
> OKX | futures | isolated | limit

### 2.3 补充核验：为什么“100 根/次 + 初次下载慢”

- ccxt issue #20756（引用 OKX 官方行为）：
  > Okx states that limit is 300 for live candles, and 100 for history candles … Live mode for last 1440 candles with limit 300 and maximim 40 requests per 2 seconds - History mode with limit 100 and maximim 20 requests per 2 seconds
- 含义：freqtrade 从历史端分页下载时每请求最多 100 根；配合历史端限速（约 20 次/2 秒）与网络往返，多币种/多年份/小周期全量下载确实慢。参考量级（纯请求次数，未计限速与失败重试）：
  - 5m：约 105,120 根/年 → 约 1,052 次请求/年/交易对
  - 1m：约 525,600 根/年 → 约 5,256 次请求/年/交易对
  - 3 个月 5m 合约数据约 25,920 根 → 约 260 次请求/交易对
- freqtrade 下载合约数据时自动补齐必要数据类型：
  > When downloading futures data (--trading-mode futures or a configuration specifying futures mode), freqtrade will automatically download the necessary candle types (e.g. mark and funding_rate candles) unless specified otherwise via --candle-types.

### 2.4 与仓库现状的一致性

`freqtrade-desktop/user_data/config.json` 当前即为：`exchange.name = okx`、`trading_mode = futures`、`margin_mode = isolated`、`stake_currency = USDT`、`dry_run = True`、api_server 监听 127.0.0.1 —— 与 spec 一致，也落在 freqtrade 文档 OKX 支持范围内。

---

## 4. 对桌面端落地的提示

1. 回测 UI 对 OKX 合约应提示“约 3 个月前资金费率/MARK 数据缺失，结果会有偏差”（与 README 已知限制一致）。
2. “下载数据”页面对 OKX 应预估“每请求 100 根 + 历史端限速”导致的耗时，并支持断点续传（freqtrade 自动补齐缺失区间）。
3. 连接配置向导需包含 passphrase 字段；EAA 注册用户需能切换 `myokx`，并对错误 50119 给出明确文案。
4. 合约交易前检查仓位模式为单向 Buy/Sell；文档明确中途切换不受支持，应阻止运行中切换并提示。

---

## 5. 来源清单（访问日期 2026-09-06）

- Freqtrade 官方文档 Exchange-specific Notes（OKX 节）：https://docs.freqtrade.io/en/2026.4/exchanges/
- Freqtrade 官方文档 Data Downloading：https://docs.freqtrade.io/en/2026.4/data-download/
- OKX Agent Trade Kit 官方仓库：https://github.com/okx/agent-trade-kit
- npm @okx_ai/okx-trade-mcp：https://www.npmjs.com/package/@okx_ai/okx-trade-mcp
- mbarinov/okx-mcp 仓库 README：https://github.com/mbarinov/okx-mcp 、https://raw.githubusercontent.com/mbarinov/okx-mcp/main/README.md
- mbarinov/okx-mcp npm 页：https://www.npmjs.com/package/okx-mcp
- mbarinov/okx-mcp 主源文件（本机抓取副本）：`%TEMP%\okx_mcp_primary\`（package.json、src/services/okxApiClient.ts、src/tools/get_positions.ts）
- okx-api（Node SDK）端点映射表：https://raw.githubusercontent.com/tiagosiebler/okx-api/master/docs/endpointFunctionList.md
- ccxt issue #20756（OKX candles/history-candles 自动切换与限速）：https://github.com/ccxt/ccxt/issues/20756
- OnchainOS（OKX 官方，DEX/行情 MCP，另一产品线）：https://web3.okx.com/onchainos/dev-docs/
- 项目 spec：`.scratch/freqtrade-desktop/spec.md`（本仓库）
