# Freqtrade Desktop（v1 全本地版）

个人使用的 Freqtrade 桌面端应用。v1 完全本地运行，重心是**策略回测与分析**
（多维指标仪表盘、综合评分、多策略对比、K 线指标叠加），同时支持**信号模式**
（无需交易所密钥）与可显式开启的 dry-run / OKX 实盘交易；Telegram 可控制本机
运行中的 bot。架构预留 local/remote 连接抽象，便于后续服务器化迁移。

## 技术栈

- 桌面端：Electron + React + TypeScript + TradingView lightweight-charts
- 本地后端：Python FastAPI（与 freqtrade 共用 venv，subprocess 调用 freqtrade CLI）
- 存储：SQLite（回测记录、评分权重、信号事件）；密钥走系统钥匙串/环境变量

## 快速开始

### 1. 安装 Freqtrade（Windows）

官方推荐 64 位 Python 3.11+。原生安装（便于后端 subprocess 集成）：

```powershell
cd <你想放代码的目录>
git clone https://github.com/freqtrade/freqtrade.git freqtrade-src
cd freqtrade-src
.\setup.ps1          # 按提示安装到 .venv
```

如果原生安装受阻，回退 WSL2（在 WSL 中按 Linux 方式安装）。

### 2. 启动后端

```bat
cd freqtrade-desktop\backend
pip install -r requirements.txt
set FTDESK_PORT=8766
python -m app.main        # 桌面端与网页端默认连 http://127.0.0.1:8766
```

后端默认端口是 8765，而桌面端固定连 8766，所以手动启动前要先 `set FTDESK_PORT=8766`
（`dev.cmd` 会替你设好）。若 freqtrade 装在别的 venv，设置 `FTDESK_FREQTRADE_BIN`
指向 `freqtrade.exe` 的完整路径。

### 3. 启动桌面端

```powershell
cd freqtrade-desktop\desktop
npm install
npm run dev
```

浏览器直接打开 http://localhost:5173 也可以使用同一套界面。

### 一键启动（推荐）

```powershell
cd freqtrade-desktop
.\dev.cmd
```

`dev.cmd` 是纯 cmd 启动器：不经过 PowerShell 执行策略，也不依赖其他脚本。它会先检查
本地后端（127.0.0.1:8766），没启动或版本过旧就重启，然后以前台方式运行 `npm run dev`
（Electron 窗口）。请在自己的终端窗口里运行，关闭终端即停止前端；后端日志在
`backend\data\backend-dev.log`。

可选参数：

```bat
dev.cmd            :: 后端 + 桌面端窗口（默认）
dev.cmd backend    :: 只启动后端，后台常驻
dev.cmd web        :: 后端 + Vite，浏览器访问 http://127.0.0.1:5173
dev.cmd stop       :: 停止后端与 Vite
```

### 持久后台模式（浏览器，推荐日常使用）

`dev.cmd` 默认的前端是前台进程：关掉 Electron 窗口或终端，前端就会停止。如果希望
服务在关闭终端后继续运行（只通过浏览器使用），用 `dev.cmd web`，或者：

```powershell
cd freqtrade-desktop
.\start-services.ps1
```

它会以隐藏后台窗口启动后端与 Vite（日志分别写入
`backend\data\backend-services.log` 和 `desktop\vite-services.log`），然后浏览器
访问 http://127.0.0.1:5173 即可。停止服务：

```bat
dev.cmd stop
```

### 4. 最小使用流程

1. 「设置 → 数据」下载 OKX 历史数据（现货/合约）。
2. 「策略管理」确认 `SampleStrategy` 可见并校验。
3. 「回测中心」新建回测 → 完成后查看评分报告与对比。
4. 「图表分析」加载回测或实时图，叠加 SMA/EMA/布林带/RSI/MACD。
5. 「设置 → 生成 freqtrade 配置」→ 按 user_data/README 注入密钥 → 启动 bot 后
   在「信号与交易」刷新信号；实盘需显式勾选风险确认。

## 测试

```powershell
cd freqtrade-desktop\backend
python -m pytest -q
```

覆盖：评分引擎边界（0 交易、负 Sharpe、Sortino 除零）、回测 JSON 新旧格式解析、
BotClient REST 封装（登录/401 刷新/强开载荷）、信号去重、API 冒烟。

## 安全与已知限制

- freqtrade `api_server` 只监听 127.0.0.1；OKX 密钥不写入配置文件明文。
- OKX 合约回测早于近 3 个月资金费率有偏差；OKX 单次调用仅 100 根 K 线。
- 回测精度为 OHLCV 级，手续费按交易所默认，不单独建模滑点。
- Telegram 控制的是本机运行中的 bot，本机需保持在线。

## 目录

```
freqtrade-desktop/
  backend/       FastAPI 后端（routers/services/tests）
  desktop/       Electron + React 前端
  user_data/     策略、数据、配置示例
```

项目规格与拆票约定见仓库根 `.scratch/freqtrade-desktop/spec.md`。
