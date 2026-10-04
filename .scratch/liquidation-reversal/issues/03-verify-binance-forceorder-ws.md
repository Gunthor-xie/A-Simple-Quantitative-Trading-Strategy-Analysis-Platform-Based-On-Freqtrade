# 03 — 复核 Binance `!forceOrder` 流连通性与降级策略

Status: ready-for-human
Type: research

## 背景

本机经代理 `127.0.0.1:17891` 访问 `https://fstream.binance.com/ws/btcusdt@forceOrder`
返回 HTTP 400（说明主机与 CONNECT 隧道可用），但用 `websockets` 15.0.1
`connect(..., proxy=...)` 在 20 秒内未完成握手。需要在真实网络条件下确认：

1. Binance 强平流（`wss://fstream.binance.com/ws/!forceOrder@arr`）是否能稳定连接；
2. 若不能，代理是否不支持 WS 升级（需要改用 SOCKS5/其他出口）；
3. 若 Binance 不可用，是否只用 OKX 轮询（已实测可达）即可满足策略；
4. 是否接受第三方历史清算数据（Tardis.dev / CoinGlass / Amberdata）用于回测。

## 为什么需要人工

这依赖本机网络出口与代理策略，属于环境事实，代码层面无法自证；且涉及是否付费购买
历史清算数据的决策。

## 产出

- 一份结论（可用/不可用 + 证据：抓到的原始消息样本、时间戳、延迟量级）。
- 若可用：把 Binance WS 作为采集器首选源，OKX 作为兜底与交叉校验。
- 若不可用：明确"实盘仅 OKX 强平流"，并评估 OKX 流稀疏（27.7 分钟 100 条）是否够用。

## 备注

即便 Binance WS 可用，其 `forceOrder` 流也**只推送每个合约每 1000ms 的最大一笔**强平，
因此所有来源的强平金额都是"有偏抽样"，这一点必须写进策略预期，不能当作全量强平。
