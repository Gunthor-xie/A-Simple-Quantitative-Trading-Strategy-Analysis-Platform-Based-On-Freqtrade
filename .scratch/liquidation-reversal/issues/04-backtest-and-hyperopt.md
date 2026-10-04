# 04 — 回测与参数寻优：数据准备、费率口径、评分对比

Status: ready-for-agent
Type: task

## 目标

在桌面端完成一次可信的清算瀑布反转回测，并给出与既有策略（ETH_MomentumBreakout、
BTC_2025_Breakout）可比的评分结论。

## 前置

- 特征文件：`issues/01`（已具备单日；需扩到回测区间全部日期）。
- 行情数据：OKX 1m futures（`PublicDataDownloader` 经代理 `127.0.0.1:17891` 下载；
  注意 100 根/次的历史端限速），并补齐 funding_rate / mark。

## 验收标准

1. 用 OKX 1m 数据 + 同一时间区间的特征文件跑通
   `freqtrade backtesting --strategy LiquidationCascade --timerange ... --timeframe-detail 1m`（若可行），
   输出交易数、胜率、期望、Profit Factor、最大回撤、Sharpe/Sortino。
2. 成本口径明确：手续费按交易所档位显式设置（不要留 0），滑点单独估计；
   给出"含成本/不含成本"两组结果，量化成本对 0.5% 目标的影响。
3. 参数敏感性：
   - `move_pct × move_atr_mult`（触发阈值）
   - `flush_score_min`（强度阈值）
   - `depth_delta_min` / `taker_delta_min`（确认强度）
   - `stoploss`（保证金口径，注意 × 杠杆换算）与 `minimal_roi`
   - `max_holding_minutes`
   输出至少一组热力图/表格，标出稳健区间而非单点最优。
4. 反事实对照：把 `flush_score_min` 设为不可达（等于关闭强平/抛压条件）后的表现，
   用于检验"级联信息是否真的有增量"。
5. 结果写入 `.scratch/liquidation-reversal/results/<date>-backtest.md`，并在桌面端
   "回测中心"生成可比对的记录。

## 风险提示

- 1m 粒度下 0.35% 止损与 0.5% 目标存在同根 K 线先后歧义，回测结论必须标注该不确定性。
- 若样本（触发次数）过少，结论不足以支撑实盘，应扩展时间区间或多标的。

## Comments

### 2026-09-21 — 抽样回测已完成（BTC，2026-03-01 → 2026-09-01，183 天）

- 数据：OKX `BTC/USDT:USDT` 1m 269,280 根 + 8h 资金费（代理经 `127.0.0.1:17891` 下载，
  耗时 10 分钟）；特征用 OKX 1m 自算（`build_cascade_features.py --klines-source okx
  --no-derivatives`，代理模式，无强平/OI/盘口）。
- 扫描 10 组参数（含手续费 0.05%/边）**全部亏损**：-15.8% ~ -97.0%，回撤 15.9% ~ 97.0%。
- 零手续费对照：`cascade_short`（淡化上涨脉冲）+7.87%/PF 1.55/夏普 2.60；
  `cascade_long`（淡化下跌瀑布）-3.34%/PF 0.78。成本（保证金口径 ~0.5%/笔）
  是毛期望（0.04%~0.15%/笔）的 3~5 倍。
- 详细表格与解读：`.scratch/liquidation-reversal/results/2026-09-21-sample-btc-6m.md`
  扫描脚本：`.scratch/liquidation-reversal/smoke/run_sample_backtests.py`
- 未完成项：真实强平流下的重测（依赖 `issues/02`）、maker 费率下的重测、
  walk-forward 分段验证（当前为单段样本）。
