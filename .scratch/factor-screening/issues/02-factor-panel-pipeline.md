# 02 — 面板构建管线（严格因果）

Status: ready-for-agent
Type: task
Blocked by: 01

## 目标

把本地 json.gz 行情拼成长表面板 `ts × pair × factor`，落成 parquet，作为因子库唯一的输入。

## 交付物

- `backend/app/services/factor_panel.py`：读取本地 K 线/funding/mark/index，按 UTC 对齐，输出
  `user_data/factors/<universe>/panel-<tf>.parquet`（列：`ts, pair, open, high, low, close, volume,
  funding_rate, index_close, mark_close, universe`）。
- `factor_research.py panel` 子命令 + 缓存（文件未变则不重算）。

## 验收标准

1. 因果性：前缀重算与整段重算逐列一致（沿用 `test_cascade_features.py` 范式）。
2. 资金费按 `merge_asof` 向后合并，标的下行不存在未来值。
3. 面板中每列的可用性时点被显式记录（哪个字段从哪根 K 线开始可用）。
4. 缺数据的标的形成明确定义的空值列，不参与后续因子计算，而不是报错中断。
5. 同一份 parquet 可被筛选与组合模块重复读取，且与 freqtrade 读到的 K 线完全同源。

## Comments

### 2026-09-25 — 已实现并验证

- 落地 `factor_panel.build_panel / write_panel / read_panel / pivot`，输出
  `user_data/factors/<pool>/panel-1h.parquet`（加密 231,056 行 / 股票 100,645 行）。
- 因果性由 `tests/test_factor_pipeline.py` 固化：前缀重算与整段重算逐列一致；
  资金费与指数价都是 `merge_asof(direction="backward")`。
- 新增 `funding_settled` 标记列，供组合层只在真实结算时点计提资金费。
