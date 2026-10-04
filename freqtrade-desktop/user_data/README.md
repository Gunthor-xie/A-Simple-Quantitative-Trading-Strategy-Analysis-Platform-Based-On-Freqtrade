# user_data 说明

本目录是 Freqtrade 的 userdir（`freqtrade --userdir user_data`），桌面端后端默认指向这里。

## 目录结构

- `strategies/`：Python 策略，例如 `SampleStrategy.py`（纯 pandas，无需 TA-Lib）。
- `data/okx/`：下载的历史 K 线（默认 json.gz 格式，便于解析）。
- `backtest_results/`：回测导出 JSON。
- `hyperopt_results/`：超参优化结果。
- `liquidation/`：清算瀑布策略用的 1 分钟特征文件（见下节）与 Binance 归档缓存。
- `config.json`：由「设置 → 生成 freqtrade 配置」生成，或复制 `config-okx-*.example.json` 修改。

## 清算瀑布特征文件（LiquidationCascade 策略）

Freqtrade 只能回测 K 线，拿不到强平流、盘口、OI 与逐笔成交，因此这些微观结构
特征由后端预计算成一份按分钟对齐的文件，策略再合并回自己的 dataframe；
回测与实盘读的是同一份文件。

```powershell
cd freqtrade-desktop\backend
# 生成 BTC/USDT:USDT 2025 年 9 月的特征（含逐笔成交与资金费）
python scripts\build_cascade_features.py --pair BTC/USDT:USDT `
    --start 2025-09-01 --end 2025-09-30 --trades --funding
```

- 输出：`user_data/liquidation/<PAIR>-1m-cascade.csv.gz`（每行 = 1 分钟，列名以 `cx_` 开头）。
- 原始归档缓存在 `user_data/liquidation/raw_binance/`，重复运行不会重复下载。
- 缺少该文件时 `LiquidationCascade` 不会开仓并在日志中提示；
  没有真实强平数据时 `cx_flush_*_score` 会退化为"价格速度 + 主动买卖失衡 + OI 收缩"的代理分数。
- 设计与可行性结论见仓库根 `.scratch/liquidation-reversal/spec.md`。

## 清算流采集器（真实强平数据）

交易所不提供历史强平归档，所以要验证"强平驱动"这一原始假设，只能自己边跑边录。
采集器只读 OKX 公共接口（无需 API key），把三路数据按行追加到 `liquidation/`：

| 文件 | 内容 |
| --- | --- |
| `<PAIR>-liq-raw.jsonl` | 逐笔强平单：时间、被清算方向（long/short）、张数、破产价、折算后的 USD 名义金额 |
| `<PAIR>-okx-oi.jsonl` | 未平仓量（Rubik，5 分钟，USD + 币本位数） |
| `<PAIR>-okx-taker.jsonl` | 主动买/主动卖成交额（Rubik，5 分钟，USD） |

```powershell
cd freqtrade-desktop
.\start-collector.ps1            # 后台启动（隐藏窗口，日志 backend\data\collector.log）
.\start-collector.ps1 status     # 查看已采集的起止时间、条数、强平名义金额
.\start-collector.ps1 once       # 只采集一次（可交给计划任务）
.\start-collector.ps1 stop       # 停止
```

采集够一段时间后，用真实强平流重建特征并重测：

```powershell
cd backend
python scripts\build_cascade_features.py --pair BTC/USDT:USDT `
    --start 2026-09-21 --end 2026-10-19 `
    --klines-source okx --no-derivatives --liquidations --okx-derivatives
```

这样得到的特征文件里 `cx_liq_long_usd` / `cx_liq_short_usd` / `cx_liq_ratio_1h` 是真实强平金额，
`cx_oi_chg_5m_pct` 与主动买卖列来自 OKX 本所数据，触发条件才与策略原始描述一致。

## OKX 注意事项（官方文档核实）

- 交易所名称为 `okx`；在 my.okx.com（EAA）注册的用户用 `myokx`，否则报
  “OKX Error 50119: API key doesn't exist”。
- OKX API key 需要配置 `password`（passphrase）。
- OKX 每次 API 调用仅返回 100 根 K 线，下载长历史耗时较长。
- 合约模式：`trading_mode: futures`、`margin_mode: isolated`、仓位模式建议 Buy/Sell，
  不要中途切换仓位模式；MARK 数据仅约 3 个月，更早回测的资金费率有偏差。

## 密钥注入（不写明文）

交易所密钥与 api_server 密码通过环境变量注入，避免落盘明文：

```powershell
$env:FREQTRADE__EXCHANGE__KEY = "你的 API Key"
$env:FREQTRADE__EXCHANGE__SECRET = "你的 Secret"
$env:FREQTRADE__EXCHANGE__PASSWORD = "你的 Passphrase"
$env:FREQTRADE__API_SERVER__PASSWORD = "随机强密码"
$env:FREQTRADE__API_SERVER__JWT_SECRET_KEY = "随机 32+ 位字符串"
$env:FREQTRADE__API_SERVER__WS_TOKEN = "随机字符串"
```

桌面端自己的连接密码写入系统钥匙串；钥匙串不可用时用 `FTDESK_SECRET_*` 环境变量。
