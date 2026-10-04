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
