# OKX 历史数据目录与 Freqtrade 回测可用性

日期：2026-09-06
范围：回答“OKX API 都能返回什么数据，尤其是历史数据（交易量、RSI、维加斯通道等），以及哪些能用于 freqtrade 回测”。
相关文件：`research-okx-mcp.md`（同一调研系列）、`.scratch/freqtrade-desktop/spec.md`。

## 1. 先厘清概念：交易所给“原材料”，指标本地算

- OKX REST/WS 返回的是**原始市场数据**（K 线 OHLCV、成交、盘口、资金费率、合约规格、账户/订单等）与少量**交易所统计口径数据**（Rubik 类）。
- **RSI、维加斯通道（EMA144/169/576/676 隧道）、MACD、布林带等指标，OKX 不返回**，任何交易所都不返回；它们由策略/回测引擎从 OHLCV 计算（freqtrade 在 `populate_indicators` 中用 pandas/TA-Lib 实现）。
- 个别 MCP/AI 工具自称“提供技术指标”（如 OKX 官方 Agent Trade Kit `market` 模块），那是**服务端帮你算好的结果**，不是 OKX REST API 的能力，也不改变 freqtrade 需要自己算的事实。
- 因此本项目做回测，真正要关心的是：**OKX 历史数据有多深、每根 K 线里有什么字段、下载成本多高**。

## 2. OKX v5 REST 能返回什么（按“能否进 freqtrade 回测”分组）

### A. 能进回测的原始历史序列（下载后本地落盘）

| 数据 | 端点（OKX v5） | 内容 | 对回测的意义 |
|---|---|---|---|
| 普通 K 线（现货/合约） | `/market/candles`（近期 ≤1440 根）与 `/market/history-candles`（更早，分页） | 每根含时间戳、O/H/L/C、成交量（合约张/币/计价币三种口径）、K 线确认标志 | freqtrade `download-data` 主数据；RSI/维加斯/量价类指标的输入 |
| 标记价格 K 线 | `/market/mark-price-candles` | mark 价格 OHLCV | 合约资金费计算、强平价/浮盈评估；**OKX 仅约 3 个月**，更早回测资金费有偏差 |
| 指数价格 K 线 | `/market/index-candles` | 指数 OHLCV | 基差（futures−index）、跨市场分析 |
| 资金费率 | `/public/funding-rate`（当前）与 `/public/funding-rate-history`（历史） | 每 8h 一次的资金费率 | 回测中模拟资金费收支、资金费因子（年化 = 8h 费率 × 3 × 365） |
| 公开成交历史 | `/market/history-trades` | 逐笔成交（价/量/方向/时间） | 可做 tick 级微观结构研究；数据量大、一般不作为 freqtrade 回测主通道 |
| 交割/行权历史 | `/public/delivery-exercise-history` | 交割/行权结算数据 | 合约换月/交割分析（小众） |
| 合约持仓量历史（Rubik 统计） | `/rubik/stat/contracts/open-interest-volume` | OI 与成交量的历史序列 | OI 因子；**非 freqtrade 原生数据通道，需自定义下载**；ccxt 提供 `fetchOpenInterestHistory` |
| 多空账户比（Rubik 统计） | `/rubik/stat/contracts/long-short-account-ratio` | 多头/空头账户数比例 | 情绪/拥挤度因子；同需自定义下载；ccxt 提供 `fetchLongShortRatioHistory` |
| Taker 买卖量（Rubik 统计） | `/rubik/stat/trading-data/taker-volume` | taker 主动买/卖量 | 主动买卖力量；同需自定义下载 |
| 期权统计（Rubik） | 期权 OI/成交量、put-call ratio、隐含波动率等 | 期权市场情绪 | 仅做期权/宏观情绪时用，v1 现货+合约可先不接 |

来源：ccxt OKX 支持矩阵（`fetchOHLCV` 支持 `price=mark/index`、`type=HistoryCandles`；`fetchFundingRateHistory`、`fetchOpenInterestHistory`、`fetchLongShortRatioHistory`、`fetchSettlementHistory` 均列在 OKX 方法表）：
https://raw.githubusercontent.com/wiki/ccxt/ccxt/exchanges/okx.md

### B. 只能当“实时快照”，不能进回测

- ticker（最新价/盘口价差/24h 量/当前资金费率等）；
- 订单簿 `/market/books`（历史全量深度无公开 API）；
- 当前 open interest `/public/open-interest`；
- 当前 mark price、强平价、价格上下限、清算订单 `/public/liquidation-orders`；
- 合约规格 `/public/instruments`（面值、tick size、杠杆档位等——静态元数据，不是时间序列）。

这些适合信号触发时做“环境快照”、图表叠加、风控提示，但不能用来回测（回测没有订单簿历史，也不需要）。

### C. 私有账户/成交历史（用于复盘，不是策略因子）

余额、持仓、挂单（`orders-pending`）、订单历史（近 7 天 `orders-history` / 近 3 个月 `orders-history-archive`）、成交明细 `fills`、账单 `bills`（手续费/资金费收支）。这些对应上一份调研里 mbarinov MCP 的 5 个只读工具，用来做“回测 vs 实盘”滑点/资金费偏差复盘，详见 `research-okx-mcp.md` 第 2.4-C 节。

## 3. 你点名指标的落地对照

| 你想要的 | OKX API 是否返回 | 在 freqtrade 里怎么做 |
|---|---|---|
| 交易量（每根 K 线） | 是：K 线自带 vol / volCcy / volCcyQuote（张数/币/计价币） | `download-data` 落盘后，df 的 `volume` 列直接可用；量价因子（OBV、VWAP、成交量 z-score、量能突变）在 `populate_indicators` 里算 |
| RSI | 否 | 用 TA-Lib `RSI` 或 pandas 自实现；回测/实盘同一段代码 |
| 维加斯通道（Vegas Tunnel） | 否 | 用收盘价 EMA（通常 144/169 隧道 + 576/676 周线级隧道），纯 pandas `ewm` 可实现，无 TA-Lib 依赖；注意 `startup_candle_count` 要给足预热 |
| 资金费率/年化资金费率 | 是（历史+当前） | 合约回测自动使用本地 funding_rate 建模资金费；想要“资金费因子”可把费率列 merge 进策略或做图表叠加 |
| 基差（futures−index/mark） | 是（两类 K 线都有历史） | 下载 index/mark 后，按时间对齐算差；回测与实盘用同一套本地数据 |
| 持仓量 OI、多空比 | 仅 Rubik 统计类，覆盖主流币种/有限时段 | freqtrade 暂无官方通道：做“下载服务”把序列存成 CSV/parquet 供桌面分析层使用；若必须进策略，只能自定义读取，注意回测/实盘一致性 |

## 4. 历史深度与限制（关键事实）

- 单次 K 线请求：近期端默认最多 ~100–300 根；`history-candles` 是专为“早期数据”设计的，**配合分页可拉很长历史**，主流币种可回溯到较早上线时间（初次下载慢的原因不是“拿不到”，而是 100 根/次 × 历史端限速，见 ccxt issue #20756）。
- freqtrade `download-data` 合约模式**自动下载 futures + funding_rate + mark**；显式 `--candle-types` 还可加 index。本地 `user_data/data/okx/futures/` 已有 `funding_rate` 与 `mark` 文件佐证。
- **mark 价格 K 线仅约 3 个月**（freqtrade 官方文档 OKX 节）；早于该区间的合约回测，资金费计算会有偏差——UI 应在回测/下载时提示。
- 资金费率历史端点属于“滚动窗口”式数据（非永久归档），长期资金费因子如需更长历史，官方另有网页历史数据下载（https://www.okx.com/historical-data 可下 CSV），或持续自建归档。
- Rubik 统计类端点多有币种/粒度/条数限制（例：多空比支持 5m/1H/8H/1D 粒度），使用前以 OKX 官方文档为准，接入后要标“数据覆盖有限”。
- OKX 官方同时提供网页历史数据下载（K 线 CSV；VIP 另有三档订单簿历史），适合一次性灌很长的底仓数据。

## 5. 对本项目（v1 回测为主）的建议

1. **P1 数据页扩展**：`DownloadParams`/下载 UI 增加 candle 类型（futures/index/mark/funding_rate）与覆盖率展示；回测前检查合约所需的 funding_rate/mark 是否齐备，缺失就出警告（数据文件已能被 `executor.list_data()` 列出）。
2. **P1 因子落库**：把 index/mark/funding_rate 下载纳入“数据下载”流程（freetrader 官方机制），基差与资金费因子在 `ChartService`/图表层叠加，不侵入策略主逻辑。
3. **P2 自定义因子下载服务**（OI 历史、多空比、taker 量）：新增后台 job，用 ccxt 的 `fetchOpenInterestHistory`/`fetchLongShortRatioHistory` 或直连 Rubik 端点拉取，统一存成带时间戳的 parquet/CSV，供图表叠加与信号环境提示用。
4. **策略指标规范**：RSI/维加斯等一律在 `populate_indicators` 用同一份本地 OHLCV 计算；合约注意 `startup_candle_count`（维加斯需要数百根预热）；回测与实盘共享策略代码，避免“回测无此列、实盘有”的漂移。
5. **诚实标注**：凡是“只有当前值/覆盖有限”的因子（OI 当前值、ticker 预测资金费率、Rubik 多空比），在 UI 标注为“实时参考，不回测”，防止用户把回测误认为包含这些因子。

## 6. 来源清单（访问日期 2026-09-06）

- Freqtrade 官方文档 Data Downloading（candle-types / 合约自动下载 mark+funding_rate）：https://docs.freqtrade.io/en/2026.3/data-download/
- Freqtrade 官方文档 Exchange-specific Notes（OKX 节：100 根/次、MARK 约 3 个月、资金费偏差）：https://docs.freqtrade.io/en/2026.4/exchanges/
- ccxt OKX 支持矩阵（fetchOHLCV mark/index、funding、OI history、long/short ratio、settlement 等）：https://raw.githubusercontent.com/wiki/ccxt/ccxt/exchanges/okx.md
- ccxt issue #20756（OKX 近期/历史 K 线切换、100 根/次、限速）：https://github.com/ccxt/ccxt/issues/20756
- OKX 官方历史数据下载页：https://www.okx.com/historical-data
- OKX v5 API 文档（行情/公共数据/交易数据区，本环境直连受限，以链接为准）：https://www.okx.com/docs-v5/en/
- 同系列笔记：`.scratch/freqtrade-desktop/research-okx-mcp.md`
