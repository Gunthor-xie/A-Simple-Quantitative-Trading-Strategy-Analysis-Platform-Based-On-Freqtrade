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
