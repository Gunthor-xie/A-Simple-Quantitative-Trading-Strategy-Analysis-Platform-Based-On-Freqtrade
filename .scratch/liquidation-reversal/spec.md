# 清算瀑布反转策略 — 可行性分析与落地设计

状态：草案（本文件是本功能的规格与可行性结论，工单见 `issues/`）
日期：2026-09-21
引擎：本机 freqtrade `2025.5-dev`（`D:\CraftTable\freqtrade\freqtrade`）
平台：`freqtrade-desktop`（FastAPI 后端 + Electron 前端 + 本地 freqtrade CLI）

## 1. 结论速览

| 策略要素 | 判定 | 结论 |
| --- | --- | --- |
| 1 分钟触发/确认/入场 | **可落地** | freqtrade 原生支持 1m 周期、收线信号、`stoploss`/`minimal_roi`/`custom_exit`；1m 是本引擎最细粒度 |
| 强平金额 > 过去 1h 95% 分位 | **有条件可落地** | 历史强平无法从交易所归档取得（已实测 404）；实盘可用 OKX `/public/liquidation-orders`（已实测可达）与 Binance `!forceOrder` 流；回测期须用"抛压代理分"替代 |
| 价格急跌/急涨 0.5%–1.5% | **需改写阈值** | BTC 在 1 分钟尺度几乎不会出现 0.5% 波动（2025-09-01 实测最大 0.27%，ATR% 均值 0.062%）→ 改为"波动率自适应阈值 + 抛压分" |
| 价格不再创新低/新高 | **可落地** | 由 1m OHLC 直接计算（已实现 `cx_no_new_low/high`） |
| 订单簿买卖盘恢复 | **有条件可落地** | 历史：Binance `bookDepth` 归档（±1..5% 五档、约 30 秒一个快照，已实测可用）；实盘：`dp.orderbook()` 需自行轮询；**拿不到 L2 队列与撤单流** |
| OFI 由负转正 | **不可原生落地** | freqtrade 无逐笔/盘口队列通道；用 `aggTrades` 计算的"主动买卖失衡 + 其 1 分钟变化"作为 OFI 近似（已实现），非严格 OFI |
| Microprice 反向突破 | **不可原生落地** | 真正的 microprice 需要 L1 买卖价量快照；归档只有百分比档位深度。用"收盘价突破前一根 K 线高低点"作为同族代理（已实现） |
| 资金费率 | **可落地** | freqtrade 原生 `funding_rate` candle（本地 `user_data/data/okx/futures/*-8h-funding_rate.json.gz` 已有），回测自动计入资金费 |
| 未平仓量 OI | **有条件可落地** | freqtrade 无 OI 通道；历史用 Binance `metrics` 归档（5 分钟粒度，已实测可用）或 OKX Rubik；实盘用 OKX `/public/open-interest` |
| 目标 0.3%–0.8% / 止损 0.2%–0.5% | **可落地（需口径换算）** | freqtrade 的 `stoploss`/`minimal_roi` 是**保证金口径**：源码 `adjust_stop_loss` 用 `price*(1-|stoploss|/leverage)`。价格口径参数必须乘杠杆 |
| 时间止损 5–15 分钟 | **可落地** | `custom_exit` 按持仓分钟数退出（已实现） |
| 避开重大宏观事件 | **部分可落地** | 引擎没有经济日历；策略提供 `cascade_blackout_windows` 静默窗口，需人工/外部数据维护 |
| 回测精度 | **有条件** | 1m 已是最细；0.2–0.5% 的止损/止盈在 1m OHLC 下存在"同根 K 线先后顺序"歧义，`timeframe_detail` 无法比主周期更细（主周期已是 1m） |

一句话结论：**核心逻辑可以在当前 Freqtrade 平台落地，但不能按"原始描述"直译**。
引擎能提供的是"1 分钟 K 线 + 外部预计算特征文件"这一组合；强平流、盘口、OFI
都必须由桌面端在引擎之外采集/计算，回测与实盘共用同一份特征文件。

## 2. 平台事实（本轮实测/源码核实）

### 2.1 引擎能力（源码证据）

| 事实 | 证据 |
| --- | --- |
| 数据通道只有 candle：`CandleType` 含 futures/mark/index/premiumIndex/funding_rate，**没有** liquidation / open_interest | `D:\CraftTable\freqtrade\freqtrade\freqtrade\data\dataprovider.py:300,351,362,482,509` |
| `DataProvider.orderbook(pair, maximum)` 存在，但**会发起网络请求**，仅在 dry-run/live 有意义 | `dataprovider.py:556` |
| 回测支持 `timeframe_detail`，且要求 `timeframe_detail` 小于主周期 | `optimize\backtesting.py:248-258` |
| 回测里强制关闭交易所侧止损 | `optimize\backtesting.py:278-281` |
| `stoploss` 是**保证金（持仓）收益率**：`new_loss = price * (1 - abs(stoploss/leverage))` | `persistence\trade_model.py:832-836` |
| 收益率同样乘杠杆：`profit_ratio = (close/open - 1) * leverage` | `persistence\trade_model.py:1176-1199` |
| ROI 也按杠杆折算：`roi_rate = trade.open_rate * roi / leverage` | `optimize\backtesting.py:590` |
| 出场/加仓回调齐全：`custom_stoploss`、`custom_exit`、`custom_entry_price`、`confirm_trade_entry`、`adjust_trade_position`、`leverage` | `strategy\interface.py:350,438,469,557,617,795` |
| OKX 支持交易所侧止损（`_ft_has["stoploss_on_exchange"]=True`） | `exchange\okx.py:35` |

### 2.2 数据源实测（2026-09-21，经本机代理 `127.0.0.1:17891`）

| 目标 | 结果 |
| --- | --- |
| Binance 清算归档 `data/futures/um/{daily,monthly}/liquidationSnapshot/...` | **HTTP 404**：交易所不提供历史强平归档 |
| Binance `metrics` 归档（5 分钟 OI / OI 名义值 / taker 多空量比） | HTTP 200，11 KB/天 |
| Binance `bookDepth` 归档（±1..5% 深度、约 30 秒快照） | HTTP 200，460 KB/天；实测 28,110 行/天、2,811 个时间戳 |
| Binance `aggTrades` 归档（逐笔聚合成交，含主动方标记） | HTTP 200，17 MB/天（解压 93 MB，1.38M 行） |
| Binance 1m klines / markPriceKlines / fundingRate | HTTP 200（1m klines 63 KB/天，月档 1.8 MB/月） |
| OKX `/api/v5/public/liquidation-orders`（SWAP） | HTTP 200；100 条记录覆盖 27.7 分钟，字段 `posSide/bkPx/sz/ts`，可翻页 |
| Binance `fapi.binance.com`（REST） | HTTP 200（经代理） |
| Binance `fstream.binance.com`（WS 主机） | 经代理返回 HTTP 400（主机可达，非拒绝）；本项目内 websockets 15 直连测试超时 → **待复核**，见 `issues/03` |
| OKX 直连（不走代理） | TCP 连接超时 → 必须走代理 |

### 2.3 数据量级（用于估算下载/存储成本）

BTCUSDT 单日：1m klines 63 KB、metrics 11 KB、bookDepth 460 KB、aggTrades 17 MB；
一年 ≙ klines 23 MB + metrics 4 MB + depth 168 MB + aggTrades 6.2 GB（按月/按需取舍）。

## 3. 策略要素 → 平台实现映射

| 策略描述 | 在 Freqtrade 上的实现 | 限制 |
| --- | --- | --- |
| 1 分钟强平金额 > 过去 1h 95% 分位 | 特征文件列 `cx_liq_long_usd/cx_liq_total_usd` + `cx_liq_p95_1h`（前 60 分钟、剔除当根）+ `cx_liq_ratio_1h` | 需要真实强平流（采集器）；历史期该列为空 |
| （回测替代）抛压强度 | `cx_flush_long_score/short_score`：跌幅 z、主动买卖失衡 z、OI 收缩 z、强平 z 的加权分（缺项自动重归一化） | 是代理，不是真实强平 |
| 急跌/急涨确认 | `max(move_pct, move_atr_mult × cx_atr_pct)`，默认 `max(0.35%, 2×ATR%)` | 与原始 0.5%–1.5% 不同，理由见 §4 |
| 不再创新低/新高 | `cx_no_new_low` / `cx_no_new_high`（当前 low/high 对比前 3 根的极值） | 无 |
| 买盘恢复 | `cx_bid_depth_change_1m`、`cx_depth_imbalance_1pct`、`cx_depth_imbalance_delta_1m` | 历史仅 ±1/2/5% 档位聚合深度；无队列 |
| OFI 转正 | `cx_taker_imbalance` 及其 1 分钟差分 `cx_taker_imbalance_delta` | 近似（成交侧失衡），非订单流失衡 |
| Microprice 反向突破 | 收盘价突破前一根 K 线高点（多头）/低点（空头） | 近似 |
| 入场 | 1m 收线后 `enter_long/enter_short`，市价 + `confirm_trade_entry` 二次确认 | 实际入场有 0–5 秒延迟（`process_throttle_secs: 5`） |
| 目标 0.3%–0.8% | `minimal_roi = {"0": 价格目标 × 杠杆}`（默认 0.5%×5=2.5% 保证金） | 回测按当根 high/low 判定，1m 内先后顺序有歧义 |
| 止损 0.2%–0.5% | `stoploss = -价格止损 × 杠杆`（默认 0.35%×5=1.75%），实盘 `stoploss_on_exchange=True` | 同上 |
| 时间止损 5–15 分钟 | `custom_exit` 返回 `time_stop`（默认 10 分钟） | 受 1m 粒度限制 |
| 反向信号离场 | `populate_exit_trend` 用反向清算瀑布/flush 分触发 | 无 |
| 流动性过滤 | `cx_liquidity_percentile_24h`（±1% 总深度在过去 24h 的分位） | 需要 ≥2h 特征历史 |

## 4. 阈值必须改写：为什么 0.5%–1.5% 不能直接用

用 2025-09-01 BTCUSDT 的 1 分钟真实数据实测（本轮构建的特征文件）：

- `|ret_1m|` 最大值 **0.268%**，均值 0.0006%，标准差 0.050%；
- `ATR(14)/close` 均值 **0.062%**，最大 0.124%；
- 按原始描述"急跌 0.5%–1.5%"筛选，当天触发 **0 次**。

结论：对 BTC 这种流动性最好的标的，1 分钟 0.5% 的位移属于尾部事件（分钟级年化波动
≈ 0.05%×√525600 ≈ 36%，0.5% 约等于 10σ）。可执行的写法是**波动率自适应阈值**：

```
触发 = (ret_1m ≤ -max(0.35%, k×ATR%)) 且 (flush 分 ≥ 阈值) [且 强平分位数 ≥ 阈值]
```

默认 `k=2`；实际触发区间 0.12%–0.4%，与"1 分钟瀑布"的直觉一致。

## 5. 架构

```
                        ┌── 历史 ─────────────────────────────────────────┐
                        │ data.binance.vision: 1m klines / metrics(5m OI)  │
                        │   bookDepth(30s, ±1..5%) / aggTrades / funding   │
                        └───────────────┬─────────────────────────────────┘
                                        │  backend/scripts/build_cascade_features.py
                                        ▼
   ┌── 实时（issue 02/03）────────┐   特征文件（点对点、因果）
   │ OKX /public/liquidation-orders│   user_data/liquidation/<PAIR>-1m-cascade.csv.gz
   │ Binance !forceOrder WS        ├──▶（采集器按分钟追加，与历史同格式）
   │ OKX /public/open-interest     │    │
   └───────────────────────────────┘    │  merge on `date`
                                        ▼
                        user_data/strategies/LiquidationCascade.py
                        （1m / futures / can_short / 5x）
                                        │
                        freqtrade backtesting | dry-run | 实盘
                                        │
                        桌面端：回测中心 / 评分对比 / 图表 / 信号
```

设计要点：

1. **引擎外算特征、引擎内做决策**。freqtrade 没有这些数据通道，硬塞进策略内部去
   联网会破坏回测可复现性；预计算文件让回测/实盘读同一份数据。
2. **严格因果**。特征文件里第 t 行的值只使用 t+1min（该 K 线收盘）之前的信息：
   盘口快照取"该分钟内最后一个快照"、OI/资金费按 `merge_asof` 向后取、
   分位数窗口 `shift(1)` 后滚动。`tests/test_cascade_features.py::test_features_are_causal`
   用"前缀重算必须与整段重算一致"来固化这一点。
3. **缺数据即降级而非报错**：没有强平流 → 用代理分；没有 aggTrades → 用 K 线的
   taker 买卖量；没有盘口 → 跳过盘口确认条件。

## 6. 本轮已交付（增量 1）

| 文件 | 作用 |
| --- | --- |
| `freqtrade-desktop/backend/app/services/binance_archive.py` | Binance 公共归档客户端（缓存、重试、header/无 header CSV 兼容） |
| `freqtrade-desktop/backend/app/services/cascade_features.py` | 1 分钟级联特征构建 + 特征文件读写 + 事件筛选 |
| `freqtrade-desktop/backend/scripts/build_cascade_features.py` | CLI：下载归档 → 生成 `user_data/liquidation/<PAIR>-1m-cascade.csv.gz` |
| `freqtrade-desktop/user_data/strategies/LiquidationCascade.py` | 策略：触发/确认/入场/出场/过滤/风控仓位 |
| `freqtrade-desktop/backend/tests/test_binance_archive.py`、`test_cascade_features.py` | 15 项新测试（含因果性、盘口对齐、强平分位、落盘往返） |
| `freqtrade-desktop/backend/tests/test_liquidation_strategy.py` | 8 项策略契约测试（入场链路、缺文件不开仓、杠杆口径、时间止损、静默窗口） |
| `docs/adr/0001-offline-microstructure-feature-bridge.md` | 架构决策记录 |

验证结果：

- `python -m pytest -q` → **68 passed**（其中新增 23 项）。
- `freqtrade list-strategies --userdir user_data` → `LiquidationCascade | OK | Hyperoptable`（9 buy / 2 sell 参数）。
- 真实数据跑通：`--pair BTC/USDT:USDT --start 2025-09-01 --end 2025-09-01 --trades --funding`
  → 1,440 行 × 57 列；当日最大抛压聚集在 **20:37–20:38**（1 分钟 -0.14%/-0.23%、
  主动买卖失衡 -0.51/-0.26、OI 5 分钟收缩 -0.22%），与"级联 + 反转"形态一致。
- **真实回测闭环**（OKX 1m 数据 + 特征文件，futures，5 倍杠杆）：
  - 默认参数：`Backtested 2025-09-01 01:10 -> 2025-09-02 00:00`，0 笔交易 ——
    正确行为，因为当日最大 1 分钟位移 0.27% < 默认触发 0.35%（见 §4）。
  - 放宽阈值（`.scratch/liquidation-reversal/smoke/LiquidationCascadeLoose.py`）：
    成交 1 笔，`enter_tag=cascade_long`、`exit_reason=time_stop`、
    杠杆 5、金额 344 USDT（风险预算换算）、保证金收益 -0.72%（≈ 价格 -0.145%）、
    账户回撤 0.25% —— 说明"特征 → 触发 → 确认 → 入场 → 风控 → 时间止损"整条链路在
    真实引擎里可跑通。

顺带修复的平台缺陷（`public_data.py`）：OKX 分页原先从"当前时间"往回走，
下载一年前的窗口会白白翻约 5,500 页（1 天 1m 数据的下载在实测中 25 分钟仍未完成）。
现在从请求区间的结束时间开始回翻：同样的 2 天 1m 数据 **8.3 秒**完成。

## 7. 已知偏差与风险（诚实清单）

1. **清算流缺失**：回测期的"强平"是代理分，不等于真实强平金额；首次回测结论只能
   验证"瀑布反转"本身，不能验证"强平驱动"这一因果假设。
2. **跨所数据**：历史特征来自 Binance 归档，而桌面端交易/回测数据源是 OKX。
   两所价格、资金费、深度不同；若用 OKX 回测，应改抓 OKX 1m 数据（OKX 历史端
   100 根/次 + 限速，1 年 1m ≈ 5,256 次请求，代价高）。
3. **同根 K 线歧义**：0.35% 止损与 0.5% 目标在 1 分钟 K 线内可能先后触及，
   回测按引擎规则判定，实盘以真实成交为准，二者会有系统性差异。
4. **成本**：本仓库既有回测口径为单边 0.1%；0.5% 目标下双边成本占 40%，
   0.35% 止损下止损成本占 57% —— 成本决定策略能否成立，必须用真实费率回测。
5. **滑点未建模**：本平台回测不建模滑点，清算瀑布时点差与冲击成本最大，
   实盘表现预期劣于回测。
6. **资金费**：持仓 5–15 分钟一般只跨一次资金费结算，影响小，但高频累积不可忽视。
7. **实盘时延**：`process_throttle_secs=5` + 1m 收线 → 入场延迟 0–5 秒；
   止损依赖交易所侧委托（`stoploss_on_exchange`，OKX 支持）。
8. **样本量**：`|ret_1m| ≥ 0.35%` 在 BTC 上一天 0–3 次，一年约数百次；
   单币单参数回测的统计显著性有限，需要多币种/多月样本。

## 8. 工单

| 编号 | 标题 | 状态 |
| --- | --- | --- |
| 01 | 特征管线：Binance 归档 → 1 分钟级联特征文件 | 本轮已实现，待补多日/多币回归 |
| 02 | 实时清算采集器（OKX REST 轮询 + Binance WS） | ready-for-agent |
| 03 | 复核 Binance `!forceOrder` WS 连通性与降级策略 | ready-for-human（需要网络/代理确认） |
| 04 | 回测与参数寻优：数据准备、费率口径、评分对比 | ready-for-agent |
| 05 | 桌面端集成：数据下载/覆盖率/信号页展示清算事件 | ready-for-agent |

## 9. 待用户决策

已定（2026-09-21）：**OKX 为主、只做 BTC、暂不购买历史清算数据、先用抽样回测判断收益/回撤**。

## 10. 抽样回测结论（2026-09-21，BTC，2026-03-01 → 2026-09-01）

完整数据见 `.scratch/liquidation-reversal/results/2026-09-21-sample-btc-6m.md`。

- 样本设置：OKX `BTC/USDT:USDT` 永续、1m、5 倍、0.05%/边手续费；特征为 OKX 1m
  自算（无真实强平/OI/盘口，代理模式）；同期 BTC +18.09%。
- **含手续费：10 组参数全部亏损**，收益 -15.8% ~ -97.0%，最大回撤 15.9% ~ 97.0%。
- **零手续费对照**：只有"淡化上涨脉冲"（cascade_short）一侧正期望（+7.87%，PF 1.55，
  回撤 1.97%，夏普 2.60）；"淡化下跌瀑布"（cascade_long）毛期望为负（-3.34%，PF 0.78）。
- 根因：单笔毛期望 0.04%~0.15%（保证金）≈ 0.008%~0.03%（价格），而 5 倍杠杆下
  双边手续费 ≈ 0.1%（价格）——成本是毛期望的 3~5 倍。
- 出场结构：0.5% 目标 / 0.35% 止损在 1m 尺度上约为 ATR 的 8 倍 / 6 倍，10 分钟窗口
  内极少触及（254 笔里仅 2~4 笔），绝大多数由"时间止损"结束，等于每笔付一次手续费
  换一次未完成的均值回归。
- 未验证的部分：本轮是纯价格触发，**没有检验"强平瀑布"这一核心假设**。

结论：**不建议在现有设计上继续细化**。若继续，优先改造成本结构与出场（maker 入场、
目标 ≥0.6%、持有窗口放宽），并用 OKX 真实强平流（端点已实测可达）采集数周后重测。

## 11. 方案 1（改成本结构）重测结论（2026-09-21）

已实现并测过：被动挂单入场（带真实成交条件）、波动率门槛、目标 0.6%~0.8%、
持有 30~60 分钟、费率降到 0.035%/边（maker 入场 + taker 出场）。详细表格见
`results/2026-09-21-sample-btc-6m.md` 的追加章节。

- 最好组合仍为负：6 个月 **-2.1%**（回撤 4.8%，31 笔，0.035%/边）。
- **被动入场带来逆向选择**：同样参数、零手续费，市价入场毛收益 +7.87%（PF 1.55），
  改成"等价格回踩才成交"的挂单后只剩 +0.14%（PF 1.02）——不回头的那批信号
  （本来赚钱的）没有成交。降费（0.05%→0.02%）省下的量级（每笔约 0.3% 保证金）
  补不上被筛掉的收益。
- 放大目标 + 拉长持有无效：121 笔里目标只命中 4~8 次，止损被打了 47~67 次
  （目标:止损 ≈ 1:11）。
- 由此得到一个反直觉但有数据支持的推论：这套样本里"强平后顺势延续"比"反转"更常见。
  若还要继续这个方向，应把假设倒过来测（强平后顺势跟进），而不是继续调反转参数。

## 12. 延续假设（fade → follow）重测结论（2026-09-21）

策略新增 `entry_direction = fade | follow`（含方向镜像的确认条件与停损单式入场），
在样本上跑完延续方向：

| 假设 | 入场 | 交易数 | 毛收益% (0 费率) | PF | 净收益% (0.05%/边) |
| --- | --- | --- | --- | --- | --- |
| 延续·双向 | 追价 | 718 | -12.26 | 0.92 | -74.5 |
| 延续·只做多 | 追价 | 403 | -4.43 | 0.95 | -52.4 |
| 延续·只做空 | 追价 | 332 | -10.14 | 0.85 | -49.1 |
| 延续·延伸入场+波动率门槛 | 停损单 | 204 | -4.85 | 0.91 | -33.0 |

**延续方向在零费率下就是负期望（PF 0.85~0.95，胜率约 50%），不是费用问题。**

## 13. 总体判定（BTC · 2026-03-01 → 2026-09-01 · 约 40 次回测后）

1. 只有"急涨后用市价做空"这一组合有正毛期望：+7.87%/6 个月，PF 1.55，折合
   ≈ +0.053% 价格/笔；现实费率（0.04%~0.1% 价格/笔）比它大，因此净收益为负。
2. 省手续费的被动挂单会因逆向选择把这点正期望筛掉（+7.87% → +0.14%）。
3. 反方向（延续）无正期望；放大目标/拉长持有无效（目标:止损 ≈ 1:11）。
4. 全部实验里最好的净结果是 **-2.1%/6 个月**（31 笔，回撤 4.8%）。

**结论：以 1 分钟价格代理信号 + 现实费率的"清算瀑布"策略，在当前平台上不具备可交易优势。**
唯一还没验证的是原始假设里的"强平"本身：需要按 `issues/02` 采集真实强平流，
用它替代价格代理触发后再判定；在那之前不建议继续投入细化。
