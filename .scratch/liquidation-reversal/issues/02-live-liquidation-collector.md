# 02 — 实时清算采集器（OKX REST 轮询 + Binance WS）

Status: claimed
Type: task

## 目标

把实时强平流、OI、盘口按分钟写进与历史特征文件同一格式的存储，使实盘/dry-run
与回测使用同源特征，并让"1 分钟强平金额 > 过去 1h 95% 分位"这一原始触发条件
在实盘真正可用。

## 实测前提（2026-09-21）

- OKX `/api/v5/public/liquidation-orders`（`instType=SWAP&uly=BTC-USDT&state=filled`）
  经本机代理可达，100 条覆盖约 27.7 分钟，字段 `posSide`(long/short)、`sz`(张)、
  `bkPx`、`ts`；可翻页。需乘合约面值换算 USD 名义金额。
- Binance `fapi.binance.com` REST 经代理可达；`fstream.binance.com` 主机可达
  （HTTP 400 = 正常拒绝非 WS 请求），但本项目 websockets 15 直连测试超时，
  需在 03 中复核。
- 交易所均**不提供**历史强平归档（Binance `liquidationSnapshot` 404）。

## 验收标准

1. `backend/app/services/liquidation_collector.py`：可独立运行的采集进程
   （OKX 轮询 + 可选 Binance WS），把事件按 `[ts, pair, side, notional, price, source]`
   写入 `user_data/liquidation/<PAIR>-liq-raw.jsonl` 或 sqlite。
2. 分钟聚合器把原始事件汇总为 `liq_long_usd / liq_short_usd / liq_count`，并与
   `cascade_features` 的历史列同名同单位（USD）。
3. 断线/限速退避、重启续采（记录最后处理时间戳）、去重（OKX 同 `ts+instId+sz` 视为一条）。
4. 桌面端后端暴露 `/api/liquidation/status` 与 `/api/liquidation/events`，
   前端"信号与交易"页展示最近事件与覆盖率。
5. 单元测试：用录制的 OKX 响应样本（不含真实密钥）验证解析、去重、分钟聚合。

## 注意

- OKX 返回 `sz` 为合约张数，必须按 `ctVal`（BTC-USDT-SWAP = 0.01 BTC）换算；
  不要直接把张数当 USD。
- 采集器写入的特征与历史文件必须口径一致，否则回测/实盘信号会漂移。

## Comments

### 2026-09-21 — 本工单现在是继续投入的唯一前置条件

价格代理版已经测完（约 40 次回测，见 `results/2026-09-21-sample-btc-6m.md`）：
反转方向只有"急涨后做空"有 +0.053% 价格/笔的毛期望，付不起 0.04%~0.1% 的摩擦成本；
延续方向零费率下就是负期望。也就是说，**价格本身提供的信息不足以支撑这个策略**。

因此下一步唯一有意义的验证是：用真实强平流（而不是价格代理）做触发，
看"强平金额超过 1h 95% 分位"这个原始条件是否能带来价格之外的增量信息。
建议最小可行版本：

1. 只采集 BTC-USDT-SWAP 的强平流 + Rubik OI/主动买卖（端点均已实测可达）。
2. 采集 2~4 周，按分钟落盘，与现有特征文件同格式。
3. 用同一套回测脚本比较"价格代理触发" vs "真实强平触发"的毛期望与 PF。
4. 判定标准（先定好，避免事后调参）：真实强平触发的毛 PF 需 ≥1.5 且
   单笔毛期望 ≥0.15% 价格，才有必要继续做执行与风控。

### 2026-09-21 — 采集器已实现并开始运行

- 模块：`backend/app/services/liquidation_collector.py`；CLI：`backend/scripts/collect_liquidations.py`；
  启动器：`freqtrade-desktop/start-collector.ps1`（`start|status|once|compact|stop`）。
- 三路数据：`/public/liquidation-orders`（30s 轮询）、Rubik `open-interest-volume`（5m）、
  Rubik `taker-volume`（5m，instType=CONTRACTS）。落盘为 append-only JSONL，
  `--compact` 可去重；`--once` 幂等（会先按磁盘状态重建游标），可交给计划任务。
- 关键实现细节（已实测校正）：
  - OKX 分页语义：`before=<ts>` 返回**更新**的记录，`after=<ts>` 返回**更旧**的记录。
    增量轮询用 `before=cursor`；若该页满 100 条，再用 `after=<本页最旧 ts>` 往回补齐，
    避免两次轮询之间 >100 笔强平时丢掉中间段。
  - 名义金额 = `sz × ctVal × bkPx`（BTC-USDT-SWAP 的 ctVal = 0.01 BTC）。
  - 首次运行会往回补 `backfill_pages`（默认 5 页 ≈ 500 条）作为起点。
- 运行状态：2026-09-21 03:03 UTC 启动，首轮已录 600 条强平（约 3 小时，$6.6M 名义金额）、
  OI 576 行（2 天）、主动买卖 72 行（6 小时）。
- 验收进度：1、2、3 已满足（含 7 项单元测试：解析/去重/分页/断点续采/状态）。
  第 4 项（真实强平触发的重测）需等采集 ≥2~3 周后执行，判定门槛保持上文不变。
