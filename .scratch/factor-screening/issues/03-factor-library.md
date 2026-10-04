# 03 — 因子库 v1

Status: ready-for-agent
Type: task
Blocked by: 02

## 目标

实现 `factor_lib.py`：以面板为输入，输出各因子列与截面标准化版本，覆盖 spec 第 6 节的十个族。

## 交付物

- 时序动量、短反转、波动、量能、carry（资金费）、基差、横截面（rank/z）、风险（beta/残差动量）。
- 股票结构族：美国现金时段 vs 非时段收益（13:30–20:00 UTC）、周末跳空、跟踪误差 vs QQQ/SPY 永续、
  同族 ETF 领先滞后。
- 加密结构族：永续−现货基差、资金费周期位置。
- 每个因子带 `name / family / direction / lookback / requires` 元数据，供筛选引擎自动遍历。

## 验收标准

1. 新增因子只需登记函数与元数据，不改筛选引擎代码。
2. 已知动量因子在合成数据上被检出（正 IC、方向正确）。
3. 每个因子的计算都不使用 t 时刻之后的信息（因果性测试覆盖）。
4. 因子在标的上市不足 lookback 时输出空值而非 0。
5. 股票结构族因子在加密池上自动跳过（`requires` 不满足）。

## Comments

### 2026-09-25 — 已实现并验证

- 落地 `factor_lib.py`：27 个因子（动量 6、反转 3、波动 4、量能 3、carry 3、基差 2、
  风险 2、股票时段结构 4），带 `family/direction/lookback/requires/equity_only` 元数据。
- 新增因子只改 `FACTORS` + `_IMPLEMENTATIONS` 两处，筛选与组合自动遍历。
- `tests/test_factor_pipeline.py` 覆盖：前缀因果性、`equity_only` 跳过、已知动量在
  自相关序列上被检出。
