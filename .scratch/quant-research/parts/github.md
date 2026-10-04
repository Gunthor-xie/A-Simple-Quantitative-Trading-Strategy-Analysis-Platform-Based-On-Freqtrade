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
