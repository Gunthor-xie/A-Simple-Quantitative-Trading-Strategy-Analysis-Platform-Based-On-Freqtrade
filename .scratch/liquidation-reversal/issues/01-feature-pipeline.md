# 01 — 特征管线：Binance 归档 → 1 分钟级联特征文件

Status: ready-for-agent
Type: task

## 目标

用 Binance USD-M 公共归档（1m klines、5m metrics、30s bookDepth、aggTrades、
fundingRate）生成严格因果的 1 分钟特征文件
`user_data/liquidation/<PAIR>-1m-cascade.csv.gz`，作为清算瀑布策略唯一的
微观结构数据源。

## 已实现（2026-09-21）

- `backend/app/services/binance_archive.py`：归档客户端（磁盘缓存、重试、
  headered/headerless CSV 兼容、`data.binance.vision` 路径与列名映射）。
- `backend/app/services/cascade_features.py`：特征构建（价格结构、主动买卖、
  OI/资金费、盘口深度、强平流、抛压分）、特征文件读写、事件筛选。
- `backend/scripts/build_cascade_features.py`：CLI。
- `backend/tests/test_binance_archive.py`、`backend/tests/test_cascade_features.py`。
- 真实数据验证：BTC/USDT:USDT 2025-09-01（1,440 行 × 57 列）。

## 验收标准

1. `python -m pytest -q`（backend）全绿。
2. `--pair BTC/USDT:USDT --start D --end D --trades --funding` 对任意有归档的日期
   都能生成文件；重复运行命中缓存、不重复下载。
3. 因果性测试通过：对同一数据集做前缀重算，最后一行的每一列都与整段重算一致。
4. 缺任一可选数据源（metrics/depth/trades/funding）时仍能产出文件，缺项列为空、
   `cx_flush_*_score` 按可用分量重归一化。

## 待补

- 多月/多币回归（BTC + ETH，≥3 个月），产出覆盖率与缺失报告。
- aggTrades 处理性能（单日 1.38M 行）：当前全量读入内存，若扩展到多月需要
  按日增量聚合后再拼接。
- 失败日归档（交易所缺档/节假日）记录到 manifests，避免静默空洞。

## Comments

### 2026-09-21 — 支持 OKX 本地 1m 作为特征基底

- 新增 `--klines-source okx`：直接复用 `PublicDataDownloader` 已下载的 OKX 1m
  json.gz（`vol` 按合约面值换算成 BTC/USDT 名义量），使**触发信号与执行同所**，
  代价是拿不到 taker 买卖拆分（OKX K 线无该字段），主动买卖相关列留空、策略自动跳过。
- 新增 `--no-derivatives`：跳过 Binance 的 OI/盘口归档，用于快速纯价格样本。
- 新增 `--klines-period monthly` 与下载节流（`--pause`，默认 0.8s，404 退避 10~30s）：
  Binance 归档 CDN 在批量拉取时会返回 404（不是永久缺档），节流+重试+缓存续传后可续跑。
- 实测：2026-03-01 → 2026-09-01 的 OKX 1m 特征（266,400 行）在本机 5 秒内生成。
