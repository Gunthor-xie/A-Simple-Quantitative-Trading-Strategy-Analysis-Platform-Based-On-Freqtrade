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
