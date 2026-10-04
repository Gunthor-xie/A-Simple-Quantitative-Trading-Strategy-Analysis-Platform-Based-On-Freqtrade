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

