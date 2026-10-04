# 04 — 筛选引擎（IC / 分位 / FDR / 成本）

Status: ready-for-agent
Type: task
Blocked by: 03

## 目标

实现 `factor_screen.py`：对因子库做滚动 walk-forward 评估，输出通过/否决结论与可复核依据。

## 交付物

- 切分：训练 8 周 / 测试 2 周 / embargo 1 天，按日历滚动，禁用随机打乱。
- 指标：RankIC 均值与 IR、NW(lag=5) t 值、IC 衰减（1/2/4/8/24 bars）、五分位价差、多头 top-decile
  相对等权基准、换手率、成本后净价差、最大回撤、胜率。
- 成本模型：taker 0.05%/边基准 + 0.02%/0.10% 敏感性；滑点 `max(1 tick, 2bps)`/边；资金费按真实序列。
- 多重检验：试验登记表 + BH FDR `q<0.1` + 最终组合 Deflated Sharpe。
- 去冗余：`|ρ|>0.7` 分组，仅保留组内 IC 更高者。
- 输出 `user_data/factors/<universe>/screen-<yyyymmdd>.json`。

## 验收标准

1. 合成数据里「已知有效因子」通过、随机因子被拒绝（判别力测试）。
2. 同一输入重复运行结果完全一致（可复现）。
3. 每条因子结论都能追溯到具体 OOS 窗口、成本假设与试验次数。
4. 成本敏感性表可直接回答「什么费率下该因子失效」。
5. 报告里显式列出被否决的因子与原因，不留沉默失败。

## Comments

### 2026-09-25 — 已实现并验证

- 落地 `factor_screen.py`：`rank_ic` / `newey_west_t` / `quantile_series` / `leg_turnover` /
  `bh_fdr` / `walk_forward_windows` / `deflated_sharpe` / `cluster_factors`。
- 协议按 spec §7 收紧为真正的 walk-forward：因子定向只用前 40 个观测估计，
  IC/NW t/FDR/分位价差/换手/回撤全部只在样本外计算，且观测按时间网格非重叠采样。
- 关键实现细节：稀疏因子（如周末跳空）用**时间网格**抽稀而不是按观测序号，
  否则周频因子会被拉成月频。
- `tests/test_factor_screen.py` 覆盖：完美信号 IC=1、NW 对噪声与信号的区分、
  BH 单调性、动量通过而随机因子被拒、四条闸门的原因逐条可追溯。
