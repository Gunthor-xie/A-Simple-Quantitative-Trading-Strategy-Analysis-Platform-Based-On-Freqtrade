# 量化交易资源调研：GitHub 项目 + 论文 + 网站

日期：2026-09-14（Asia/Shanghai）
范围：回答两个问题——**(1) GitHub 上有没有优秀的量化交易策略项目；(2) 有哪些值得注意的量化策略相关网站或论文。** 结论面向 `freqtrade-desktop`（Freqtrade + 桌面端，目标市场 OKX 现货/合约）的判断在本文件第 4 节。

## 0. 结论速览

**第一个问题的答案分两层，这个区分是本报告最重要的结论。**

- **"能直接跑的策略代码"其实只在少数几个仓库里**：[freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies)（5,473 star，官方策略集，含趋势/形态/**执行算法 TWAP·Almgren-Chriss**/止损风控示例）、[iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity)（3,409 star，社区最出名的生产级 Freqtrade 策略）、[je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading)（10,728 star，一个仓库并列多套完整策略）、[hugo2046/QuantsPlaybook](https://github.com/hugo2046/QuantsPlaybook)（6,107 star，券商金工研报复现）、[paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading)（14,262 star，论文→策略→实测 Sharpe）。
- **star 最高的那些几乎都不是"赚钱的策略"，而是好用的工具**：OpenBB（72,962）、freqtrade（54,325）、microsoft/qlib（48,533，自带 Alpha158/Alpha360 因子库）、ccxt（43,978）、nautilus_trader（28,887，回测与实盘同源）、QuantConnect/Lean（21,617）。
- **一个必须知道的反直觉数据**：paperswithbacktest 仓库 README 自述已把 **4,843 篇论文按其完整历史编码运行，复现收益的中位 Sharpe 只有 0.37，48% 能过 t=1.96**；扣掉股票 beta 后中位信息比率降到 0.21。→ 论文提供的是**方法与陷阱**，不是现成的印钞机。

**第二个问题**：值得长期看的入口是 Quantpedia（策略百科）、arXiv q-fin.TR 每日列表（最活跃方向雷达）、paperswithbacktest（复现统计）、Robot Wealth / QuantStart（实操博客）、Man Group Insights（一线 CTA 公开研究）、Ken French Data Library（因子基准数据）。论文则从第 2 节 2.4「方法与陷阱」读起——回测过拟合、多重检验、交易成本这三组文献决定了你其余所有工作是否有意义。

**如果只花两小时**：先读第 2 节 2.4（防自欺），再看第 1 节 1.4（选型表），然后照第 4 节的三条落地建议动手。

---

## 本报告的取证口径

所有数字与链接都来自 2026-09-14 的真实抓取，原料留在同目录下可复核：

- GitHub 数据：官方 REST API（搜索 + 仓库详情），原始 JSON 在 `.scratch/quant-research/raw/`（`s1..s16.json`、`repo*.json`）。
- 论文数据：Crossref DOI 直查（`api.crossref.org/works/<doi>`）、arXiv 摘要页直访（`arxiv.org/abs/<id>`）、arXiv q-fin.TR 列表页。
- 站点数据：带浏览器 UA 的 HTTP 访问，结果（含不可达/被拦）如实记录在第 3 节 3.1。
- 统一标注：✅ = 本次已核验；⚠️ = 未逐页核验或本次不可达。**凡本次未能取证的编号/数字一律不写。**

---

## 1. GitHub 上的量化交易项目

### 1.1 取证方法与口径

- 数据来源：GitHub 官方 REST API（`search/repositories` 与 `repos/{owner}/{repo}`），抓取时间 **2026-09-14**（Asia/Shanghai）。原始 JSON 留存在 `.scratch/quant-research/raw/`，共 493 个去重后的仓库记录，可复核。
- 检索式（两组批次，各取星标前 30）：
  - 主批次 `s1..s8.json`：`topic:quantitative-trading`、`topic:algorithmic-trading`、`topic:trading-strategies`、`topic:quantitative-finance`、`topic:backtesting`、`quant trading framework`、`machine learning trading`、`awesome quant`；
  - 补充批次 `s20..s25.json`（重跑，与上表口径一致）：`topic:factor-investing`、`topic:high-frequency-trading`、`reinforcement+learning+trading`、`crypto+trading+strategy`、`topic:market-making`、`topic:portfolio-optimization`；
  - 并行采集脚本批次 `s9..s16.json`（脚本见 `tools/fetch-repos.ps1`，由另一个调研分支运行）：`topic:crypto-trading-bot`、`topic:trading-strategy`、`topic:factor-investing`、`quantitative trading strategy`、`algorithmic trading strategies`、`financial reinforcement learning` 等。
  - 说明：两批次的文件名有重叠（后者覆盖过前者），因此**文件名与检索式不严格一一对应**；报告中所有星标/日期/许可证数字均已用 `repo*.json`（单仓库直查）或以上任一快照二次核对通过。
- 表中 `star` 为抓取时刻值，`最近提交` 用 `pushed_at`（默认分支最后一次推送），`许可证` 用 GitHub API 的 SPDX 识别值。
- **筛选原则**：优先「有明确策略/回测语义 + 仍在维护 + 许可证清楚」；纯数据管道、时序数据库、量子计算等被同名关键词牵连进来的项目已在 1.5 说明为何剔除。

### 1.2 头部总览（按星标排序，已剔除噪声）

| 项目 | star | 语言 | 最近提交 | 许可证 | 一句话定位 |
|---|---:|---|---|---|---|
| [OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | 72,962 | Python | 2026-09-11 | 识别为 NOASSERTION（需人工确认） | 开源金融数据/研究终端平台，含面向 AI agent 的接口层 |
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | 54,325 | Python | 2026-09-13 | GPL-3.0 | 加密现货/合约机器人，回测→超参优化→dry-run→实盘闭环（本项目的基础设施） |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 48,533 | Python | 2026-09-02 | MIT | 微软的 AI 量化研究平台，内置 Alpha158/Alpha360 因子库与滚动训练流水线 |
| [vnpy/vnpy](https://github.com/vnpy/vnpy) | 45,367 | Python | 2026-09-13 | MIT | 中文圈最完整的量化交易平台框架（CTP/期货/期权 + 图形化） |
| [ccxt/ccxt](https://github.com/ccxt/ccxt) | 43,978 | Rust/Python 等 | 2026-09-13 | MIT | 100+ 交易所统一 API（本项目 freqtrade 的交易所适配层就是它） |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 28,887 | Rust | 2026-09-14 | LGPL-3.0 | Rust 原生、事件驱动、确定性回测与实盘同源的机构级引擎 |
| [mementum/backtrader](https://github.com/mementum/backtrader) | 23,241 | Python | **2024-08-19（已停更）** | GPL-3.0 | 经典 Python 回测框架，生态庞大但上游停滞 |
| [QuantConnect/Lean](https://github.com/QuantConnect/Lean) | 21,617 | C# | 2026-09-12 | Apache-2.0 | QuantConnect 云平台的开源引擎，多资产、Python/C# 双语言 |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | 20,886 | Jupyter | 2026-09-14 | MIT | 《Machine Learning for Trading》配套代码（数据→因子→回测→执行） |
| [quantopian/zipline](https://github.com/quantopian/zipline) | 20,094 | Python | **2024-02-13（已停更）** | Apache-2.0 | 老牌事件驱动回测库；上游停更，改用 `zipline-reloaded` |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | 19,989 | Python | 2026-09-10 | Apache-2.0 | 做市/高频加密机器人框架，含流动性挖矿策略模板 |
| [bbfamily/abu](https://github.com/bbfamily/abu) | 18,605 | Python | 2026-01-24 | GPL-3.0 | 中文老牌量化系统（股票/期货/期权/比特币） |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16,278 | Jupyter | 2026-07-13 | MIT | 金融强化学习框架，含论文与教学流水线 |
| [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | 14,262 | Python | 2026-09-03 | — | 系统化交易资源合集，**按论文聚合策略实现**，与本报告第 2 节互补 |
| [goldmansachs/gs-quant](https://github.com/goldmansachs/gs-quant) | 12,948 | Python | 2026-09-09 | Apache-2.0 | 高盛开源的量化金融工具包（定价/风险/回测组件） |
| [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) | 12,244 | Cython | 2026-09-14 | BSD-2-Clause | 技术指标库的事实标准（freqtrade 也支持） |
| [yutiansut/QUANTAXIS](https://github.com/yutiansut/QUANTAXIS) | 11,191 | Python | 2026-09-01 | MIT | 本地化「数据-回测-模拟-交易-可视化」一体化方案（中文圈） |
| [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 10,728 | Python | 2026-06-20 | Apache-2.0 | **单个仓库塞满可读策略与说明**（VIX、形态识别、商品、期权等） |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9,080 | Python | 2026-08-02 | 识别为 NOASSERTION | 向量化回测，适合一次性扫成千上万组参数 |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | 8,960 | Python | 2026-08-05 | **AGPL-3.0** | 轻量回测库，上手快；注意 AGPL 对网络服务分发的约束 |
| [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | 8,494 | Python | 2026-09-13 | MIT | 面向加密的「研究→回测→实盘」一体化框架，语法直观 |
| [wondertrader/wondertrader](https://github.com/wondertrader/wondertrader) | 6,338 | C++ | 2026-09-01 | MIT | 国产 C++ 量化研发交易一体框架（期货为主，性能取向） |
| [ricequant/rqalpha](https://github.com/ricequant/rqalpha) | 6,765 | Python | 2026-09-08 | 识别为 NOASSERTION | 米筐开源回测引擎，A 股生态成熟 |
| [hugo2046/QuantsPlaybook](https://github.com/hugo2046/QuantsPlaybook) | 6,107 | Jupyter | 2026-09-03 | — | **券商金工研报复现代码集**（A 股因子/择时），中文圈少见的高质量复现 |
| [PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) | 6,023 | Jupyter | 2026-07-07 | MIT | 组合优化（均值方差/Black-Litterman/风险预算） |
| [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5,473 | Python | 2026-09-08 | GPL-3.0 | 官方策略示例集，学习 freqtrade 策略接口的最佳起点 |
| [google/tf-quant-finance](https://github.com/google/tf-quant-finance) | 5,500 | Python | 2026-08-06 | Apache-2.0 | Google 的 TensorFlow 金融定价/风险库（偏衍生品定价，非策略） |
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | 4,680 | Rust | 2025-12-23 | MIT | 支持 L2 盘口/延迟建模的高频回测器 |
| [pst-group/pysystemtrade](https://github.com/pst-group/pysystemtrade) | 3,510 | Python | 2026-07-18 | GPL-3.0 | Robert Carver《Systematic Trading》的可运行参考实现（注意仓库已从个人账号迁移到 pst-group） |
| [edtechre/pybroker](https://github.com/edtechre/pybroker) | 3,538 | Python | 2026-09-07 | 识别为 NOASSERTION | 机器学习驱动策略的回测/实盘框架（含 walk-forward） |
| [fasiondog/hikyuu](https://github.com/fasiondog/hikyuu) | 3,501 | C++ | 2026-09-12 | Apache-2.0 | 国产高性能量化框架，强调「策略部件复用、逐步累积策略资产」 |
| [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | 3,409 | Python | 2026-09-13 | GPL-3.0 | **社区最有名的 Freqtrade 实盘策略**（多时间框架 + 保护机制） |
| [TradeMaster-NTU/TradeMaster](https://github.com/TradeMaster-NTU/TradeMaster) | 3,069 | Jupyter | 2025-06-04 | Apache-2.0 | 强化学习量化的开源平台（南洋理工），内置多市场数据集与基准 |
| [letianzj/QuantResearch](https://github.com/letianzj/QuantResearch) | 3,030 | Jupyter | **2023-08-26（基本停更）** | MIT | 量化研究方法与回测笔记合集，适合当教材读 |

> 说明：表内所有数字均来自 2026-09-14 的 API 快照；星标数只反映关注度，**不反映策略是否赚钱**（见 1.5）。

### 1.3 按用途分类，值得逐个点开看的项目

#### A. 加密实盘机器人框架（与 freqtrade 同赛道，可横向对比）

| 项目 | star | 最近提交 | 值得看的原因 |
|---|---:|---|---|
| freqtrade/freqtrade | 54,325 | 2026-09-13 | 本项目底座；回测-FreqAI-超参优化-干跑-实盘一条链，社区策略生态最大 |
| hummingbot/hummingbot | 19,989 | 2026-09-10 | 做市/跨所套利是 freqtrade 的弱项，这份代码补足「挂单与库存管理」视角 |
| jesse-ai/jesse | 8,494 | 2026-09-13 | 策略 API 比 freqtrade 更接近「脚手架」，适合借鉴其回测/实盘同源代码组织 |
| Drakkar-Software/OctoBot | 6,568 | 2026-09-13 | DCA/网格/「TradingView 信号接入」的产品化做法，UI 完整 |
| Superalgos/Superalgos | 5,654 | 2026-09-13 | 可视化策略编排 + 社区市场，产品形态值得参考 |
| thrasher-corp/gocryptotrader | 3,457 | 2026-09-11 | Go 语言实现，多交易所行情/下单网关的工程参考 |
| iterativv/NostalgiaForInfinity | 3,409 | 2026-09-13 | 真实在跑的 freqtrade 策略，是研究「多时间框架 + 保护机制」的活样本 |
| Rikj000/MoniGoMani | 1,025 | 2023-03-11 | 曾流行的 freqtrade 超集（自动权重回溯）；已停更，仅作思路参考 |
| 51bitquant/howtrader | 959 | 2026-06-07 | 中文加密 quant 框架，接口设计对中文用户友好 |
| Open-Trader/opentrader | 2,859 | 2025-06-29 | DCA/网格的产品化实现（TypeScript），含前端 UI |

判断：**加密实盘框架这一层，freqtrade 在「策略生态与文档」上仍是最强**；hummingbot（做市）与 jesse（研究体验）是能力上最互补的两个。

#### B. 通用回测 / 研究框架（做策略验证的工具箱）

- [microsoft/qlib](https://github.com/microsoft/qlib)（48,533）：不是回测器而是「AI 量化流水线」——数据、因子、模型、组合、回测全链路，含 Alpha158/Alpha360 两个可直接用的因子集，还带滚动训练与模型集成。做因子研究时最值得抄的是它的**因子表达式引擎与数据集切分约定（防未来函数）**。
- [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader)（28,887）：事件驱动、回测与实盘同源、Rust 核心 + Python 接口；对「回测结果与实盘不一致」问题的工程解法最正统。
- [QuantConnect/Lean](https://github.com/QuantConnect/Lean)（21,617）：多资产、企业级、云平台同款引擎；文档与社区课程质量高。
- [polakowo/vectorbt](https://github.com/polakowo/vectorbt)（9,080）：向量化，适合参数扫描与因子横截面研究；它把「一次跑上万组参数」做成常规操作。
- [kernc/backtesting.py](https://github.com/kernc/backtesting.py)（8,960）：几十行代码跑出一个策略，适合快速证伪；许可证是 AGPL-3.0，商用需注意。
- [mementum/backtrader](https://github.com/mementum/backtrader)（23,241，**2024-08 停更**）：资料与中文教程最多，但上游停滞，新项目不建议作为主力依赖。
- [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)（1,937）：`quantopian/zipline`（20,094，已停更）的维护版，Pipeline API 的因子截面处理思路仍值得学习。
- [pst-group/pysystemtrade](https://github.com/pst-group/pysystemtrade)（3,510）：趋势跟踪的最小可用生产系统，含仓位波动率目标、品种分散、成本建模——**做「组合级」而不是「单币种」策略时最值得读的实现**。
- [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest)（4,680）与 [barter-rs](https://github.com/barter-rs/barter-rs)（2,279）：微观结构/延迟建模与 Rust 事件驱动基础设施。
- [edtechre/pybroker](https://github.com/edtechre/pybroker)（3,538）、[pmorissette/bt](https://github.com/pmorissette/bt)（2,982）、[cuemacro/finmarketpy](https://github.com/cuemacro/finmarketpy)（3,806）：轻量、思路各异的回测层。

#### C. 策略集合 / 研报复现（「有没有现成策略」的正确答案就在这一类）

| 项目 | star | 最近提交 | 内容 |
|---|---:|---|---|
| [je-suis-tm/quant-trading](https://github.com/je-suis-tm/quant-trading) | 10,728 | 2026-06-20 | 一个仓库里并列多个完整策略（VIX 计算器、形态识别、商品、配对、期权），每个都带说明与图，**最适合当策略阅读清单** |
| [hugo2046/QuantsPlaybook](https://github.com/hugo2046/QuantsPlaybook) | 6,107 | 2026-09-03 | 券商金工研报复现（A 股因子/择时/行业轮动），中文量化里少见的成体系复现 |
| [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) | 5,473 | 2026-09-08 | 官方策略集，规范写法与回测配置的参考 |
| [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | 14,262 | 2026-09-03 | 按**论文**聚合并配套策略实现的合集（与本报告第 2 节互为索引） |
| [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | 3,409 | 2026-09-13 | 生产级 freqtrade 策略（不是玩具） |
| [letianzj/QuantResearch](https://github.com/letianzj/QuantResearch) | 3,030 | 2023-08-26 | 研究笔记式策略集（动量、配对、风险平价等） |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | 20,886 | 2026-09-14 | 书配套代码：从数据到模型到回测的完整流水线 |
| [Hvass-Labs/Finance-Research](https://github.com/Hvass-Labs/Finance-Research) | 1,132 | 2026-07-03 | 投资研究 notebook（数据/组合/因子） |
| [warren618/AlphaForge](https://github.com/warren618/AlphaForge) | 33 | 2026-04-02 | **加密永续合约**的因子挖掘/组合系统；star 很少但与本项目场景高度对口 |

补充取证：官方 `freqtrade-strategies` 里可直接读的策略文件，本次逐一点了 raw 直链确认存在（✅ 200）的有 `TrendRiderStrategy.py`（趋势）、`Supertrend.py`、`UniversalMACD.py`、`PatternRecognition.py`（形态）、`SwingHighToSky.py`（波段）、`TWAPStrategy.py` 与 `AlmgrenChrissStrategy.py`（执行算法）、`CustomStoplossWithPSAR.py` 与 `BreakEven.py`（风控/止损）、`InformativeSample.py`（informative pairs 示例）等；另有 `multi_tf.py`、`FixedRiskRewardLoss.py` 本次请求超时未确认（⚠️）。这份文件名清单本身就是最好的"freqtrade 策略接口该怎么用"教材——**执行算法（TWAP/Almgren-Chriss）是最容易被忽略但最影响实盘结果的一类**。

#### D. AI / 机器学习 / 强化学习量化

- [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL)（16,278，MIT）：RL 量化的教学与实验平台，论文与代码对应关系清楚；配套的 [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)（21,247）与 [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)（7,980）分别走 LLM 金融与金融 agent 路线。
- [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab)（4,924，**2023-10 后转向商业闭源**）：López de Prado 体系（分数阶差分、三重障碍标注、meta-labeling）的实现曾在此；现在只剩历史版本可读，**新代码不建议依赖**。
- [hudson-and-thames/arbitragelab](https://github.com/hudson-and-thames/arbitragelab)（696）：均值回归/协整套利工具箱（同样偏停更状态）。
- [TradeMaster-NTU/TradeMaster](https://github.com/TradeMaster-NTU/TradeMaster)（3,069）：RL 量化的基准与数据集。
- [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) 之上的衍生项目（AutoHedge 6,057、QuantGPT 464 等）多为 2025-2026 新起，**热度高但样本外证据少**，建议只作思路参考。

#### E. 资源索引类仓库（省时间的第一入口）

| 项目 | star | 最近提交 | 说明 |
|---|---:|---|---|
| [wilsonfreitas/awesome-quant](https://github.com/wilsonfreitas/awesome-quant) | 29,572 | 2026-09-13 | 英文圈最全的量化资源索引（库/数据/论文/博客），**首选入口** |
| [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading) | 14,262 | 2026-09-03 | 系统化交易资源 + 论文-代码对照 |
| [thuquant/awesome-quant](https://github.com/thuquant/awesome-quant) | 5,623 | 2026-09-07 | 中文圈资源索引（清华背景整理） |
| [wangzhe3224/awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading) | 5,129 | 2026-08-30 | 另一份系统化交易索引，与上面那份互补 |
| [firmai/financial-machine-learning](https://github.com/firmai/financial-machine-learning) | 8,781 | 2025-01-03 | 金融 ML 的实用工具/应用清单 |
| [georgezouq/awesome-ai-in-finance](https://github.com/georgezouq/awesome-ai-in-finance) | 6,562 | 2026-09-08 | LLM/深度学习在金融市场的策略与工具索引 |
| [EliteQuant/EliteQuant](https://github.com/EliteQuant/EliteQuant) | 4,181 | 2024-06-15 | 老牌经典资源清单（对冲基金/量化学习路径） |
| [grananqvist/Awesome-Quant-Machine-Learning-Trading](https://github.com/grananqvist/Awesome-Quant-Machine-Learning-Trading) | 4,026 | 2025-05-21 | 偏向 ML 的量化资源 |
| [cybergeekgyan/Quant-Developers-Resources](https://github.com/cybergeekgyan/Quant-Developers-Resources) | 3,893 | 2026-08-15 | 面试/求职向的量化技能地图 |
| [just-nilux/awesome-freqtrade](https://github.com/just-nilux/awesome-freqtrade) | 98 | 2023-08-16 | 专门的 Freqtrade/FreqAI 资源与代码片段（小但精准） |

#### F. 组合优化与绩效分析（策略之外的「必需零件」）

- 组合优化：[PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt)（6,023，MIT）、[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)（4,496）、[skfolio](https://github.com/skfolio/skfolio)（2,392，sklearn 风格）、[cvxportfolio](https://github.com/cvxgrp/cvxportfolio)（1,286，带交易成本的多期优化）。
- 绩效与风险分析：[quantstats](https://github.com/ranaroussi/quantstats)（7,630）、[pyfolio](https://github.com/quantopian/pyfolio)（6,421，**2023-12 停更**）、[alphalens](https://github.com/quantopian/alphalens)（4,445，**2024-02 停更**，因子分层分析仍经典）、[FinanceToolkit](https://github.com/JerBouma/FinanceToolkit)（5,332）。
- 数据与基础设施：[yfinance](https://github.com/ranaroussi/yfinance)（25,240）、[questdb](https://github.com/questdb/questdb)（17,320，时序库）、[man-group/ArcticDB](https://github.com/man-group/ArcticDB)（2,510，Man Group 的 DataFrame 存储）、[QuantLib](https://github.com/lballabio/QuantLib)（7,610，衍生品定价）。

#### G. 中文生态（值得单独看一眼）

- 框架：[vnpy](https://github.com/vnpy/vnpy)（45,367）、[QUANTAXIS](https://github.com/yutiansut/QUANTAXIS)（11,191）、[wondertrader](https://github.com/wondertrader/wondertrader)（6,338）、[hikyuu](https://github.com/fasiondog/hikyuu)（3,501）、[rqalpha](https://github.com/ricequant/rqalpha)（6,765）、[abu](https://github.com/bbfamily/abu)（18,605）。
- 学习与研究：[charliedream1/ai_quant_trade](https://github.com/charliedream1/ai_quant_trade)（6,508，从入门到实盘的中文一站式教程）、[xingwudao/xquant-beginner](https://github.com/xingwudao/xquant-beginner)（716，开源量化入门书）、[QuantsPlaybook](https://github.com/hugo2046/QuantsPlaybook)（6,107，研报复现）。
- 数据/选股工具：[myhhub/stock](https://github.com/myhhub/stock)（14,353）、[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)（9,811）、[shashankvemuri/Finance](https://github.com/shashankvemuri/Finance)（4,258）——这类项目以「A 股数据 + 指标 + 选股」为主，**数据源稳定性与合规性需自行评估**。

### 1.4 若是给本项目（Freqtrade + 桌面端，OKX 合约）选型，建议这么切

| 需求 | 建议看 | 理由 |
|---|---|---|
| 策略代码与写法 | freqtrade-strategies、NostalgiaForInfinity、je-suis-tm/quant-trading | 前两个直接可跑，后一个扩宽策略思路 |
| 因子/模型研究（想接 FreqAI 之外的东西） | microsoft/qlib、stefan-jansen 书代码、paperswithbacktest | qlib 的因子表达式与防未来函数约定最值得抄 |
| 回测可信度提升 | nautilus_trader、nautilus 的延迟/撮合模型；hftbacktest | 「回测虚高」的根因多在撮合与延迟假设 |
| 组合与仓位管理 | pysystemtrade、PyPortfolioOpt/Riskfolio-Lib | 从「单币种信号」走向「多币种组合 + 波动率目标」 |
| 绩效与归因展示 | quantstats、alphalens（因子分层） | 桌面端评分/报告页可直接借鉴其指标定义 |
| 资源横向扩展 | wilsonfreitas/awesome-quant、thuquant/awesome-quant、awesome-systematic-trading | 一页看全生态，避免重复造轮子 |

### 1.5 甄别与风险提示（这一节比榜单更重要）

1. **星标数不等于策略有效**。GitHub 热度衡量的是「代码易用性/教程价值」，与策略在真实市场的边际收益无关；本表里 star 最高的项目基本都不是「赚钱的策略」，而是「好用的工具」。
2. **识别异常热度**。抓取时发现若干仓库 star 与 fork 比例异常（例如某中文 LLM 选股仓库 star 6.5 万、fork 5.4 万，接近 1:0.84，而 freqtrade 是 5.4 万 star / 1.1 万 fork），且创建时间很短（2026-01）。这类项目更可能是「fork 刷量/教程型」而非可依赖的量化基础设施，**不建议作为技术底座**；同理，2025-2026 年新起的一批「AI 交易 OS / AI 交易 agent」仓库（Vibe-Trading、QuantDinger、FinceptTerminal 等）热度增长快，但缺少长周期实盘与样本外证据，建议只作思路参考。
3. **停更信号要看清**：backtrader（2024-08）、zipline（2024-02）、pyfolio（2023-12）、alphalens（2024-02）、mlfinlab（2023-10 后闭源化）、tradytics/eiten（2022）、gekko（2020 已归档）。老项目仍可读（思路经典），但**不要拿来做新系统的依赖**。
4. **许可证是硬约束**：
   - GPL-3.0（freqtrade、backtrader、abu、NostalgiaForInfinity、pysystemtrade）——分发衍生作品需开源；直接抄策略代码进闭源产品前先读条款。
   - AGPL-3.0（backtesting.py、Financial-Models-Numerical-Methods）——**通过网络提供服务也算分发**，桌面/服务端产品尤其要小心。
   - LGPL-3.0（nautilus_trader、blankly）、Apache-2.0/MIT（qlib、Lean、hummingbot、jesse、PyPortfolioOpt 等）——对商业集成较友好。
   - 部分项目 API 返回 `NOASSERTION`（OpenBB、vectorbt、StockSharp、rqalpha、pybroker 等），表示 GitHub 无法自动识别或为自定义许可证，**必须人工找到 LICENSE 文件确认**。
5. **数据与合规**：A 股类「一站式选股/数据」项目常依赖爬虫或非授权接口，长期可用性与合规性风险高；加密类项目还要注意部分交易所 API 的区域可用性。
6. **被本次检索剔除的噪声**（说明为何不在榜单里）：量子计算/量子机器学习（`awesome-quantum-*`）、时序数据库（questdb）、模型量化（`Awesome-Model-Quantization`）、自我量化（`awesome-quantified-self`）等——它们只是名字里含 "quant"，与交易策略无关。

## 2. 论文：策略思想的源头，也是「祛魅」的地方

### 2.1 先看一条现实数据

在推荐论文之前，必须先说清一件事。GitHub 上最值得看的策略索引仓库 [paperswithbacktest/awesome-systematic-trading](https://github.com/paperswithbacktest/awesome-systematic-trading)（14,262 star）在其 README 里公开了自己**逐篇复现论文策略**的结果（原文抓取于 2026-09-14）：

> We have coded and run 4,843 of these papers over their own full history. …
> - The median replication returns a **Sharpe ratio of 0.37**, and **48% clear a t-statistic of 1.96**.
> - Median test window: **34 years**. … a Sharpe of 0.4 needs about 24 of them.
> - The median strategy carries a **beta of +0.17** to the S&P 500. Removing it takes the median information ratio down to **0.21** …
> - Across 2,838 papers with a record on both sides of their publication date, we could find **no measurable decay after publication** once the market period is controlled for …

来源：仓库 README `https://raw.githubusercontent.com/paperswithbacktest/awesome-systematic-trading/main/README.md`（✅ 本次已抓取）。

翻译成人话：**论文策略复现后有一半在统计上无法与「零」区分**；剩下的里还有相当一部分收益来自股票 beta 而不是技巧。所以下面这份论文清单的用法是——**先读「方法与陷阱」那一节（2.4），再读具体策略**，否则很容易拿着一个有样本内漂亮曲线的想法就上实盘。

标注约定：✅ = 本次调研已从一手来源核验（DOI/arXiv 元数据/原始页面）；⚠️ = 论文本身权威但我本次未逐项核验编号，按题名给出检索入口，不写可能出错的编号。

### 2.2 奠基性论文（策略家族的源头）

| 论文 | 作者 / 年份 | 为什么值得读 | 引用 |
|---|---|---|---|
| Time Series Momentum | Moskowitz, Ooi, Pedersen / 2012 | **趋势跟踪的现代学术地基**：跨资产 1–12 个月动量、与横截面动量的区别、以及"恐慌时动量失效"的风险管理含义 | ✅ JFE 104(2)，DOI `10.1016/j.jfineco.2011.11.003`（Crossref 核验：标题/作者/年份一致） |
| A Century of Evidence on Trend-Following Investing | Hurst, Ooi, Pedersen / 2017 | 用 100 年以上数据回答"趋势跟踪是不是只是近年现象"；对加密这种新资产类别有借鉴意义 | ✅ DOI `10.2139/ssrn.2993026` |
| Pairs Trading: Performance of a Relative-Value Arbitrage Rule | Gatev, Goetzmann, Rouwenhorst / 2006 | 配对交易/统计套利的经典基准，含交易成本与执行摩擦的讨论；加密里"主流币-山寨币协整"是同一套思路 | ✅ RFS，DOI `10.1093/rfs/hhj020` |
| Trading Costs of Asset Pricing Anomalies | Frazzini, Israel, Moskowitz / 2012 | **成本吃掉多少 alpha** 的量化答案；做高频/小市值类策略前必读 | ✅ DOI `10.2139/ssrn.2294498` |
| … and the Cross-Section of Expected Returns | Harvey, Liu, Zhu / 2015 | 提出用多重检验校正因子发现（t 值门槛应远高于 2）；是"因子动物园"问题的开端 | ✅ RFS，DOI `10.1093/rfs/hhv059` |
| Replicating Anomalies | Hou, Xue, Zhang / 2018 | 用同一套数据与方法复核数百个异象，**约六成无法复现**；读它的意义在于建立怀疑本能 | ✅ RFS，DOI `10.1093/rfs/hhy131`（NBER WP 版 `10.3386/w23394`） |
| Pseudo-Mathematics and Financial Charlatanism | Bailey, Borwein, López de Prado, Zhu / 2014 | 用"最小回测长度"证明：短样本上的高 Sharpe 几乎必然是过拟合 | ✅ Notices of the AMS，DOI `10.1090/noti1105` |
| The Deflated Sharpe Ratio | Bailey, López de Prado / 2019 | 把"试了多少组参数"折进 Sharpe 的显著性检验；**给策略打分时最该抄的方法** | ✅ DOI `10.2139/ssrn.2460551` |
| 151 Trading Strategies | Kakushadze, Serur / 2018 | 一本顶十篇：把当时主流策略整理成目录手册（含公式与参考文献），适合当"策略字典"翻阅 | ✅ 书籍版 DOI `10.1007/978-3-030-02792-6`（另有 arXiv 预印本，⚠️ 编号未核验） |

### 2.3 机器学习 / 深度学习类

| 论文 | 作者 / 年份 | 要点 | 引用 |
|---|---|---|---|
| Deep Learning for Limit Order Books | Sirignano / 2018 | 用 LOB 全历史状态做空间神经网络预测价格变动，是"盘口建模"的早期代表作 | ✅ Quantitative Finance，DOI `10.1080/14697688.2018.1546053` |
| DeepLOB: Deep Convolutional Neural Networks for Limit Order Books | Zhang, Zohren, Roberts / 2019 | CNN+LSTM 处理盘口，**有公开数据与代码复现路径**，是做微观结构特征工程的必读 | ✅ IEEE TSP，DOI `10.1109/tsp.2019.2907260`；arXiv:1808.03668 |
| Deep Reinforcement Learning for Trading | Zhang, Zohren, Roberts / 2019 | 趋势/动量策略 + RL 组合，给出"RL 相对规则策略的边际收益" | ✅ arXiv:1911.10107（本次已核验标题；作者沿用该组同年 DeepLOB 的一致署名） |
| Enhancing Time Series Momentum Strategies Using Deep Neural Networks | Lim, Zohren, Roberts / 2019 | 把 TSMOM 的"择时开关"交给神经网络做，是该组最有工程价值的一篇 | ✅ DOI `10.2139/ssrn.3369195`；arXiv:1904.04912 |
| FinRL: A Deep Reinforcement Learning Library for Automated Stock Trading | Liu 等 / 2020 | RL 量化的开源基线库论文，配套 GitHub 可直接跑（纪律要求高的教学流水线） | ✅ arXiv:2011.09607（本次已核验标题）；落地代码见第 1 节 FinRL |
| Deep neural networks, gradient-boosted trees, random forests: Statistical arbitrage on the S&P 500 | Krauss, Do, Huck / 2017 | 传统 ML 三种模型做统计套利的横向对比（比"深度学习必赢"的叙事理性得多） | ✅ EJOR，DOI `10.1016/j.ejor.2016.10.031` |
| Advances in Financial Machine Learning（书）＋ Machine Learning for Asset Managers（书） | López de Prado / 2018, 2020 | 三重障碍标注、meta-labeling、分数阶差分、样本唯一性与 purged CV——**做 ML 策略前的规范手册** | ⚠️ 书籍，无可靠 DOI（Crossref 中同题条目为书评与讲座系列，不作为引用）；方法实现见第 1 节 mlfinlab 历史版本 |

### 2.4 方法与陷阱（这一节建议先读）

做量化最贵的学费不是策略，而是**自欺**。这几篇合起来是一套"防自欺"工具箱：

1. **回测过拟合**：Bailey–Borwein–López de Prado–Zhu（2014，✅ `10.1090/noti1105`）给出最小回测长度；Bailey–López de Prado（2019，✅ `10.2139/ssrn.2460551`）给出 Deflated Sharpe Ratio。→ 实践含义：报告 Sharpe 时必须同时报告"试了多少组参数/多少个币种/多少个时间段"。
2. **多重检验**：Harvey–Liu–Zhu（2015，✅ `10.1093/rfs/hhv059`）。→ 实践含义：单因子 t 值 2.5 不算发现。
3. **可复现性**：Hou–Xue–Zhang（2018，✅ `10.1093/rfs/hhy131`）。→ 实践含义：换数据源、换市场（股票→加密）、换生存样本偏差后是否还成立。
4. **成本与容量**：Frazzini–Israel–Moskowitz（✅ `10.2139/ssrn.2294498`）。→ 实践含义：加密里对应的是资金费、滑点、手续费与深度限制，回测里必须显式建模（本项目在 OKX 合约上尤其要注意资金费）。
5. **样本外与滚动验证**：这块的规范做法散落在 López de Prado 的书与 purged K-fold 相关文献中（⚠️ 未逐篇核验编号），工程上可直接参考 qlib 的数据集切分约定与 pybroker 的 walk-forward 实现（见第 1 节）。

### 2.5 加密资产专题（与本次项目最相关）

| 论文 | 作者 / 年份 | 要点 | 引用 |
|---|---|---|---|
| Risks and Returns of Cryptocurrency | Liu, Tsyvinski / 2018 | 加密货币的收益分布、动量与投资者关注度因子；**横截面加密因子研究的起点** | ✅ NBER WP `10.3386/w24877` |
| Common Risk Factors in Cryptocurrency | Liu, Tsyvinski, Wu / 2019 | 提出加密三因子（市场/规模/动量），是"加密版 Fama-French"的主要候选 | ✅ NBER WP `10.3386/w25882` |
| Artificial Intelligence in Equity and Crypto Markets: Progress, Profitability Evidence, and the Limits of Automated Investing | Zhu, Cai / 2026（综述） | **2026 年 9 月最新综述**，横跨股票与加密、专门讨论"AI 策略到底赚不赚钱"的实证证据与自动化投资的边界；文献截止 2026-08-31 | ✅ arXiv:2609.04917（2026-09-07 提交，q-fin.PM/q-fin.TR 交叉） |

判断：加密策略的学术证据远弱于股票，但**动量、波动率、资金费/基差**这几条是文献与实盘都反复出现的；建议把研究重点放在"能否用公开数据（资金费、基差、链上）构造可复现的因子"，而不是再去追 LLM 预测价格。

### 2.6 当前活跃方向：arXiv q-fin.TR 最近提交（2026-09-04 ~ 09-11，共 8 篇，本次实抓）

来源：`https://arxiv.org/list/q-fin.TR/recent`（✅ 本次抓取，标题与编号如下，均为该页面原文）：

| arXiv ID | 标题 | 作者 |
|---|---|---|
| 2609.11614 | Deep Learning of Robust Market Making under Regime-Switching Order Flow | Felipe Moret, Fabrizio Lillo |
| 2609.10543 | The Privacy Subsidy in Market Microstructure | Yuki Nakamura |
| 2609.10407 | dexamine: A Python package for Uniswap event data on Ethereum | Magnus Hansson |
| 2609.08881 | The Double-Edged Sword of Short-Selling Bans | Della Corte, Kosowski, Papadimitriou, Rapanos |
| 2609.07989 | Regimes in the Order Flow | Ramzi Jebali |
| 2609.06085 | Explainable Deep Learning for Price-Trade Dynamics: From Black-Box Forecasts to Effective Parametric Models | Manuel Naviglio, Fabrizio Lillo |
| 2609.04917 | Artificial Intelligence in Equity and Crypto Markets: Progress, Profitability Evidence, and the Limits of Automated Investing | Linsen Zhu, Mengqing Cai |
| 2609.03115 | Mean-field equilibrium of heterogeneous agents under market impact | Joseph Leclère, Mathieu Rosenbaum |

看这张表能得出一个有用的判断：**当前最活跃的是"做市/微观结构 + 可解释性"，而不是"预测涨跌"**。做市（market making）恰好是 freqtrade 这类趋势框架的盲区，也是 hummingbot 的主场（见第 1 节 A 类）。若本项目未来要拓展，加密永续的做市/基差类策略比继续堆指标更可能有增量。

### 2.7 检索入口（比记住论文更有用）

- **arXiv q-fin**：`https://arxiv.org/list/q-fin.TR/recent`（交易与市场微观结构，✅ 可达）、`q-fin.PM`（组合管理）、`q-fin.ST`（统计金融）、`q-fin.CP`（计算金融）。订阅这几个列表比看二手转述可靠。
- **arXiv 检索**：按 ID 直访 `https://arxiv.org/abs/<id>` 可确认标题（✅ 本次用这个方法核验了 4 篇）；注意 arXiv 的 API 出口（export.arxiv.org）在本环境多次超时/限流（429），网页端反而稳定。
- **Crossref API**：`https://api.crossref.org/works/<doi>` 按 DOI 直查标题/作者/年份，是本次核验主力（✅ 可用，但密集请求会被限流）。
- **SSRN 量化金融网络**：论文预印本集中地，但 `ssrn.com` 在本环境不可达（http 000），只能通过 DOI 或机构页面间接访问。

### 2.8 本节取证状态说明

- **已核验（DOI/arXiv 直查）**：`10.1016/j.jfineco.2011.11.003`、`10.2139/ssrn.2993026`、`10.1093/rfs/hhj020`、`10.2139/ssrn.2294498`、`10.1093/rfs/hhv059`、`10.1093/rfs/hhy131`、`10.3386/w23394`、`10.1090/noti1105`、`10.2139/ssrn.2460551`、`10.1007/978-3-030-02792-6`、`10.1080/14697688.2018.1546053`、`10.1109/tsp.2019.2907260`、`10.2139/ssrn.3369195`、`10.1016/j.ejor.2016.10.031`、`10.3386/w24877`、`10.3386/w25882`；arXiv `1911.10107`、`1904.04912`、`2011.09607`、`1808.03668`。
- **未核验**：各书目的 ISBN/DOI（书中内容权威，但我本次未取到可引用的标识）；`151 Trading Strategies` 的 arXiv 预印本编号；López de Prado 体系里 purged CV 的具体论文编号。
- **本次不可达**：SSRN（http 000）、Semantic Scholar API（429）、arXiv API 出口（429/超时）。因此本节**没有**依赖这三处的任何二手数字。

## 3. 网站 / 平台 / 数据源 / 社区 / 课程

### 3.1 先说取证状态（重要）

本次（2026-09-14）对每个站点都做了一次真实访问（带浏览器 UA），结果如下。**"不可达"多数是本环境的网络出口限制（本机出口 IP 为境内地址），不代表站点本身有问题**；这类站点我按官方入口给出链接，并标注未逐页核验。

| 状态 | 站点 |
|---|---|
| ✅ 本次可达（HTTP 200） | Quantpedia、Robot Wealth、QuantStart、arXiv q-fin.TR、Ken French Data Library、QuantConnect、Numerai、Man Group Insights、JoinQuant 聚宽、RiceQuant 米筐、优矿 UQER、Kaggle Competitions、CryptoDataDownload、WorldQuant BRAIN 平台、Hudson & Thames、Two Sigma Articles、QuantInsti、Ernie Chan (epchan.com)、paperswithbacktest.com、QuantLib、WorldQuant Brain 官网 |
| ⚠️ 本次不可达（连接失败 http 000） | SSRN、AQR、Quantocracy、Newfound Research、TradingView、FRED、CoinGecko |
| ⚠️ 本次被拒（403，反爬/Cloudflare） | Alpha Architect、Portfolio Management Research、Taylor & Francis（Quantitative Finance 期刊页） |

### 3.2 研究 / 知识站（值得长期订阅的）

| 站点 | 擅长什么 | 对加密合约策略的用处 | 状态 |
|---|---|---|---|
| [Quantpedia](https://quantpedia.com/) | **策略百科**：把学术论文里的策略翻译成可执行描述，并按因子/异象分类索引（页面标题实测为 "QuantPedia \| The Encyclopedia of Algorithmic and Quantitative Trading Strategies"） | 找策略灵感的第一站；注意它同时也卖 screener 服务，**免费部分当索引看，付费结论要自己验证** | ✅ 可达 |
| [Robot Wealth](https://robotwealth.com/) | 系统化交易的实操博客，强调"简单策略 + 严谨执行"与成本 | 适合校准"散户可实现的策略长什么样" | ✅ 可达 |
| [QuantStart](https://www.quantstart.com/) | 从零到系统的教程体系（回测框架、统计套利、风险管理），文章质量稳定 | 团队新人的入门材料 | ✅ 可达 |
| [Ernie Chan (epchan.com)](https://www.epchan.com/) | 均值回归/统计套利/期权的布道者，含书中代码与数据说明 | 均值回归类策略在两两币对上的落地参考 | ✅ 可达 |
| [Hudson & Thames](https://hudsonthames.org/) | 金融 ML 研究博客与工具（原 mlfinlab/arbitragelab 的组织） | ML 策略工程化（特征、标注、回测切分） | ✅ 可达 |
| [Two Sigma Articles](https://www.twosigma.com/articles/) | 机构视角的市场结构与研究方法文章 | 提升"研究品味"，理解机构如何看数据与执行 | ✅ 可达 |
| [Man Group Insights](https://www.man.com/insights) | 一线 CTA/趋势跟踪机构的公开研究（页面标题实测 "Man Insights \| Man Group"） | 趋势与组合层思考，和加密趋势策略同源 | ✅ 可达 |
| [paperswithbacktest.com](https://paperswithbacktest.com/) | 论文策略的**复现统计库**（其仓库 README 自述已复现 4,843 篇，中位 Sharpe 0.37） | 用它的统计给"论文策略到底值不值得做"定调 | ✅ 可达 |
| [AQR Research](https://www.aqr.com/Insights/Research) | 因子投资研究的权威来源（动量、价值、carry、低波动） | 因子方法论；**注意 AQR 有商业立场** | ⚠️ 本次不可达 |
| [Alpha Architect](https://alphaarchitect.com/) | 把学术因子结论翻译成投资实务的长文博客 | 因子类文章的通俗解释 | ⚠️ 本次 403 |
| [Quantocracy](https://quantocracy.com/) | 全网友量化博客的**每日聚合器** | 想广撒网看博客时最省时间的入口 | ⚠️ 本次不可达 |
| [Newfound Research](https://www.newfoundresearch.com/) | 组合构建、风险预算、"Flirting with Models" 系列 | 从单标的信号走向组合的思路来源 | ⚠️ 本次不可达 |
| [SSRN 量化金融网络](https://www.ssrn.com/index.cfm/en/fin/) | 预印本仓库，新研究的第一落点 | 追踪最新论文；本次只能靠 DOI 间接访问 | ⚠️ 本次不可达 |
| [arXiv q-fin.TR 列表](https://arxiv.org/list/q-fin.TR/recent) | 交易与市场微观结构的每日新论文 | **最活跃方向的实时雷达**（见第 2 节 2.6） | ✅ 可达 |
| [Quantopian 遗留资料](https://github.com/quantopian) | 已关停平台留下的研究库与教学材料（pyfolio、alphalens、zipline 等仍在） | 因子分层与绩效归因的经典工具（已停更，见第 1 节） | ✅ 其中仓库可达 |

### 3.3 回测/研究平台与竞赛

| 平台 | 说明 | 与加密的关系 |
|---|---|---|
| [QuantConnect](https://www.quantconnect.com/) | 云端回测与实盘平台，引擎开源（Lean），多资产、Python/C# | 加密支持有限但研究框架可借鉴；适合学习"规范化研究流程" |
| [WorldQuant BRAIN](https://platform.worldquantbrain.com/) | 平台的因子挖掘竞技场（✅ 可达），用标准化数据集与打分机制训练因子思维 | 与加密无关，但**因子研究的纪律与评估方式值得学** |
| [Numerai](https://numer.ai/) | 用加密数据做锦标赛的对冲基金，玩家提交模型获得 NMR 奖励 | 加密数据 + 竞赛机制；注意它本质是卖数据的协议，不是策略库 |
| [Kaggle Competitions](https://www.kaggle.com/competitions) | 含大量金融/加密预测竞赛与公开 notebook | 学习特征工程与防泄漏；**竞赛高分≠可交易**（成本与容量被忽略） |
| [TradingView](https://www.tradingview.com/) | Pine 脚本策略社区与图表 | 想法来源；策略可移植到 freqtrade 需重写并重新验证（⚠️ 本次不可达） |
| [聚宽 JoinQuant](https://www.joinquant.com/) / [米筐 RiceQuant](https://www.ricequant.com/) / [优矿 UQER](https://uqer.datayes.com/) | 中文在线回测与社区（✅ 三个本次均可达） | 主要用于 A 股研究；可借鉴其数据接口与因子库设计 |

### 3.4 数据源（免费/低价为主）

| 数据源 | 内容 | 备注 |
|---|---|---|
| [KEN FRENCH Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html) | 因子收益、行业组合、动量/价值等基准数据（✅ 可达） | 做因子对照的行业标准，加密研究可借用其方法论 |
| [FRED](https://fred.stlouisfed.org/) | 宏观时间序列（利率、通胀、美元指数） | ⚠️ 本次不可达（本环境）；加密策略可用作宏观 regime 变量 |
| [CoinGecko](https://www.coingecko.com/) | 币价与市值、交易所数据 | ⚠️ 本次不可达；有官方 API，注意免费额度与授权条款 |
| [CryptoDataDownload](https://www.cryptodatadownload.com/) | 交易所历史 K 线下载（✅ 可达） | 适合快速取证与交叉校验；**回测前务必核对与交易所原始数据的一致性** |
| [Binance / OKX 公开数据接口](https://docs.freqtrade.io/) | 官方 REST/WS 与历史数据（本项目已用 OKX） | 免费但有限速；freqtrade `download-data` 已封装 |
| [Yahoo Finance / yfinance](https://github.com/ranaroussi/yfinance) | 股票/ETF/指数日线 | 免费、稳定度一般；用于基准对比 |
| [Tiingo / Polygon / Alpha Vantage](https://www.tiingo.com/) 等 | 付费但质量更高的行情与基本面 | 视预算选；加密研究通常用不上 |

### 3.5 教材与课程

- **书**：Ernie Chan《Quantitative Trading》《Algorithmic Trading》《Machine Trading》；López de Prado《Advances in Financial Machine Learning》《Machine Learning for Asset Managers》；Robert Carver《Systematic Trading》《Leveraged Trading》（配套代码即 pysystemtrade，见第 1 节）；Andreas Clenow《Following the Trend》。这条书单覆盖了"策略—风控—组合"的最短路径。
- **课程**：QuantInsti（[quantinsti.com](https://www.quantinsti.com/)，✅ 可达，含免费博客与付费 EPAT）；WorldQuant University 的免费 MSc（应用金融数据科学，无需学费，⚠️ 本次未逐页核验入口）；CQF（偏衍生品定价，费用高，对加密趋势策略帮助有限）。
- **文档优先原则**：与其买课，不如把 freqtrade 官方文档、QuantConnect 文档、qlib 文档读透——这三份是免费的、且与代码同源。

### 3.6 期刊与会议（想追前沿时的去处）

| 名称 | 定位 | 状态 |
|---|---|---|
| Journal of Portfolio Management / [Portfolio Management Research](https://www.pm-research.com/) | 实务界组合管理与因子研究 | ⚠️ 本次 403（反爬） |
| Journal of Financial Data Science | 金融 ML/数据科学前沿 | ⚠️ 未单独核验 |
| [Quantitative Finance](https://www.tandfonline.com/journals/rquf20)（Taylor & Francis） | 量化金融综合期刊（Sirignano 那篇 Deep Learning for LOB 就发在这里） | ⚠️ 本次 403 |
| ICAIF（ACM 国际金融 AI 会议）、NeurIPS/ICML 金融 WS | 金融 ML 的会议论文 | ⚠️ 未逐项核验；arXiv 上可检索到 |

### 3.7 中文圈资源

- **平台社区**：聚宽（JoinQuant）、米筐（RiceQuant）、优矿（UQER）——研究 A 股与因子时资料最全，均有活跃社区与公开策略/因子库。
- **书与教程**：`xingwudao/xquant-beginner`（开源量化入门书，含防过拟合与数据泄露章节）、`charliedream1/ai_quant_trade`（一站式教程）、`Barca0412/Introduction-to-Quantitative-Finance`（多因子投研框架教程）——均为第 1 节列出的仓库，质量参差，**建议只用来看"知识点清单"，不要直接抄策略**。
- **注意**：中文圈的"量化"内容噪音比例高，公众号/短视频里承诺收益的内容按 3.8 处理。

### 3.8 风险识别清单（怎么一眼看穿不靠谱的"量化"）

以下是我在浏览过程中总结的判据，按"看到就别信"的强度排序：

1. **承诺收益**：出现"月化 5%–10%""稳定复利""保本"字样，或展示一条几乎不回撤的净值曲线。公开研究里中位 Sharpe 只有 0.37（见第 2 节），任何高喊稳定高收益的都违反先验。
2. **只给结果不给方法**：没有样本外区间、没有交易成本假设、没有滑点，或者回测起止时间恰好是某个牛市。**正确做法是同时给"试了多少次参数"**（Deflated Sharpe / 最小回测长度，见第 2 节 2.4）。
3. **要钱的方式暴露动机**：卖信号、收"入金分润"、拉人头返佣、要求把资金打到对方平台。真正的量化研究靠资管/自营赚钱，不靠卖课卖信号。
4. **代码/数据不透明但宣传很响**：GitHub 仓库里没有可运行回测、star 与 fork 比例异常（例如 star 6.5 万 / fork 5.4 万这种几乎 1:1 的结构，见第 1 节 1.5）、创建时间极短却热度极高。
5. **只看单币单周期的漂亮回测**：把"某个币在某段行情里的表现"当成策略，换个币种/换段时间就失效。要看**跨品种、跨时期、参数敏感性**三项。
6. **忽视资金费与滑点**：加密合约的 funding 与手续费经常吃掉全部 alpha。任何不讨论这两项的永续策略结论都不可信。
7. **AI/LLM 万能叙事**："让 AI 自动发现 alpha""GPT 选股必赚"。LLM 能帮你写代码、整理研报，但公开证据不支持"LLM 直接预测价格就能赚钱"（第 2 节 2.6 的 2026 年综述正是在讨论这一边界）。

---

## 4. 给本项目的落地建议（Freqtrade + 桌面端，OKX 合约）

按"投入产出比"排序，三条：

1. **先去抄"执行"，再去抄"信号"**。策略文件里真正稀缺的不是入场条件，而是执行与风控：`TWAPStrategy.py`、`AlmgrenChrissStrategy.py`、`CustomStoplossWithPSAR.py`、`BreakEven.py`（第 1 节 1.3-C 已验证存在）。OKX 合约的手续费与资金费会吃掉大部分边际 alpha，把执行算法与真实成本（含 funding）建模进回测，收益大于再加一个指标。
2. **给策略评分加一层"防过拟合"**。桌面端已有回测评分体系，建议把第 2 节 2.4 的判据变成字段：试参数量、样本外区间长度、最小回测长度（Bailey 等 2014）、Deflated Sharpe（Bailey & López de Prado 2019，DOI `10.2139/ssrn.2460551`）。这比多加几个指标更能防止把噪音当 alpha。
3. **把研究重点从"单币种信号"移到"组合 + 环境变量"**。加密文献里可复现的东西集中在动量、波动率、资金费/基差（Liu–Tsyvinski 系列，第 2 节 2.5）；组合层面的参考实现是 pysystemtrade（波动率目标 + 品种分散 + 成本），组合优化可直接用 PyPortfolioOpt / Riskfolio-Lib。freqtrade 单币种策略的天花板很大程度来自这里。

另外两条"别做"：

- **别把 2025–2026 年冒出来的"AI 交易 OS / AI agent"当底座**。热度增长快，但缺少长周期实盘与样本外证据（第 1 节 1.5），代码工程性也未经验证。
- **别在 star 数上做技术选型**。星标衡量的是教程价值与易用性；许可证（GPL/AGPL 是硬约束）与"是否还在维护"才是工程决策依据。

---

## 5. 来源清单（访问日期均为 2026-09-14）

**GitHub（官方 API 抓取）**

- 仓库检索：`https://api.github.com/search/repositories?q=<query>&sort=stars`（14 组检索式，见 1.1）
- 仓库详情：`https://api.github.com/repos/<owner>/<name>`（含 star/pushed_at/license/archived）
- 策略文件核验：`https://raw.githubusercontent.com/freqtrade/freqtrade-strategies/main/user_data/strategies/<file>.py`
- paperswithbacktest 复现统计：`https://raw.githubusercontent.com/paperswithbacktest/awesome-systematic-trading/main/README.md`

**论文（Crossref / arXiv 直查，均为本次核验）**

- `10.1016/j.jfineco.2011.11.003`（Time series momentum, JFE）
- `10.2139/ssrn.2993026`（A Century of Evidence on Trend-Following Investing）
- `10.1093/rfs/hhj020`（Pairs Trading）
- `10.2139/ssrn.2294498`（Trading Costs of Asset Pricing Anomalies）
- `10.1093/rfs/hhv059`（…and the Cross-Section of Expected Returns）
- `10.1093/rfs/hhy131`、`10.3386/w23394`（Replicating Anomalies）
- `10.1090/noti1105`（Pseudo-Mathematics and Financial Charlatanism）
- `10.2139/ssrn.2460551`（The Deflated Sharpe Ratio）
- `10.1007/978-3-030-02792-6`（151 Trading Strategies）
- `10.1080/14697688.2018.1546053`（Deep learning for limit order books）
- `10.1109/tsp.2019.2907260`（DeepLOB）
- `10.2139/ssrn.3369195`（Enhancing Time Series Momentum Strategies Using DNN）
- `10.1016/j.ejor.2016.10.031`（Krauss/Do/Huck 统计套利对比）
- `10.3386/w24877`、`10.3386/w25882`（加密资产收益与风险因子）
- arXiv：`1911.10107`、`1904.04912`、`2011.09607`、`1808.03668`、`2609.04917`
- arXiv 列表：`https://arxiv.org/list/q-fin.TR/recent`

**网站（本次可达性已记录，见 3.1）**

- `https://quantpedia.com/`、`https://robotwealth.com/`、`https://www.quantstart.com/`
- `https://www.quantconnect.com/`、`https://numer.ai/`、`https://platform.worldquantbrain.com/`
- `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html`、`https://www.cryptodatadownload.com/`
- `https://www.man.com/insights`、`https://www.twosigma.com/articles/`、`https://hudsonthames.org/`、`https://www.epchan.com/`
- `https://www.joinquant.com/`、`https://www.ricequant.com/`、`https://uqer.datayes.com/`、`https://www.kaggle.com/competitions`
- `https://paperswithbacktest.com/`、`https://www.quantlib.org/`、`https://www.quantinsti.com/`
- 本次不可达/被拦（仅作入口参考）：`aqr.com`、`alphaarchitect.com`、`quantocracy.com`、`newfoundresearch.com`、`ssrn.com`、`tradingview.com`、`fred.stlouisfed.org`、`coingecko.com`、`pm-research.com`、`tandfonline.com/journals/rquf20`

---

## 附录：本目录文件说明

- `research-quant-strategy-sources.md`（本文件）：合并后的唯一交付物。
- `parts/github.md`、`parts/papers.md`、`parts/websites.md`：三节各自的源文件（便于单独修订）。
- `raw/`：GitHub API 原始 JSON、Crossref 查询结果、arXiv 页面、paperswithbacktest README 等一手缓存。
- `raw-web/`：站点抓取的 HTML 快照（用于复核 3.1 的可达性结论）。
- `tools/fetch-repos.ps1`：并行的 GitHub 数据采集脚本（另一调研分支产出），其输出即 `raw/s9..s16.json`。

复现提示：GitHub 未认证 API 的限额很低（搜索 10 次/分钟；核心接口 60 次/小时），密集抓取会直接返回 403 rate limit——本次调研中途就撞到了这个限额，这也是"分批 + 间隔 + 单仓库直查"这套口径的由来。

