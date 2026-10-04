# Freqtrade 引擎能力核实（本地源码 2025.5-dev）

用途：为"清算瀑布反转策略"的可行性判定提供一手证据。所有结论均来自本机源码
`D:\CraftTable\freqtrade\freqtrade\freqtrade`，行号为 2026-09-21 该版本的实际情况。

| 能力 | 结论 | 证据（绝对路径:行） |
| --- | --- | --- |
| 数据通道：K 线种类 | 只有 futures / mark / index / premiumIndex / funding_rate | `D:\CraftTable\freqtrade\freqtrade\freqtrade\data\dataprovider.py:300,351,362,482,509` |
| 强平 / OI 数据通道 | **不存在** | 同上（`candle_type` 取值集合里没有清算/OI） |
| 策略可取二级数据 | `get_pair_dataframe` 可（回测/干跑/实盘），`orderbook` 仅 dry-run/live 且**会联网** | `dataprovider.py:351,556` |
| 回测盘中粒度 | 支持 `timeframe_detail`，且要求其小于主周期 | `D:\CraftTable\freqtrade\freqtrade\freqtrade\optimize\backtesting.py:248-258,335-339,1517-1526` |
| 回测中交易所侧止损 | 被强制关闭 | `optimize\backtesting.py:278-281` |
| `stoploss` 口径 | **保证金（持仓）收益率**：`price*(1-|stoploss|/leverage)` | `D:\CraftTable\freqtrade\freqtrade\freqtrade\persistence\trade_model.py:832-836` |
| 收益率口径 | 乘杠杆：`(close/open-1)*leverage` | `persistence\trade_model.py:1176-1199` |
| ROI 口径 | 同样除杠杆：`roi_rate = open_rate*roi/leverage` | `optimize\backtesting.py:589-592`，止损价 `:557-562` |
| 出场/加仓回调 | 齐全：`confirm_trade_entry` / `custom_stoploss` / `custom_entry_price` / `custom_exit` / `adjust_trade_position` / `leverage` | `D:\CraftTable\freqtrade\freqtrade\freqtrade\strategy\interface.py:350,438,469,557,617,795` |
| OKX 交易所侧止损 | 支持（`_ft_has["stoploss_on_exchange"]=True`） | `D:\CraftTable\freqtrade\freqtrade\freqtrade\exchange\okx.py:35` |
| 实盘循环节拍 | `process_throttle_secs`（模板默认 5 秒），由 worker 消费 | `D:\CraftTable\freqtrade\freqtrade\freqtrade\worker.py:58`、`templates\base_config.json.j2:67` |
| 回测手续费 | 取配置 `fee`，否则取交易所最差档 | `optimize\backtesting.py:184-195`，成交计入 `:892,1140` |
| 回测资金费 | 按 `funding_fee_timeframe` 逐次结算 | `optimize\backtesting.py:349-357,926-934` |
| 策略读取本地自定义文件 | 无限制（策略是普通 Python 类，可自行读文件/缓存） | `strategy\interface.py`（`IStrategy` 无文件访问限制）、`resolvers\strategy_resolver.py` |

## 对 1 分钟清算反转策略的硬约束

1. **没有任何清算/OI/盘口/逐笔数据通道**，必须由引擎外预计算并落文件
   （见 `docs/adr/0001-offline-microstructure-feature-bridge.md`）。
2. **1m 是本引擎的下限**：`timeframe_detail` 必须小于主周期，主周期已是 1m 时无法
   再细化，因此 0.2%–0.5% 级别的止损/止盈在回测中存在"同根 K 线先后顺序"歧义。
3. **stoploss / minimal_roi 是保证金口径**：把价格口径的目标/止损写进策略时必须
   × 杠杆，否则风险会放大 5 倍（本策略已按此换算并加测试固化）。
4. **回测里 `stoploss_on_exchange` 无效**，交易所侧止损只在实盘/dry-run 生效；
   回测按 K 线高低点判定。
5. **实盘信号存在 0–5 秒延迟**（`process_throttle_secs=5` + 1m 收线），
   这也是策略必须依赖交易所侧止损的原因。
