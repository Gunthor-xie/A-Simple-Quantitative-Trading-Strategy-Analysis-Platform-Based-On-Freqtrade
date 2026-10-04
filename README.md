# Freqtrade Desktop

本地运行的 Freqtrade 桌面端：Electron + React 前端，Python FastAPI 后端，后端通过
subprocess 调用 freqtrade CLI。重心是**策略回测与分析**（综合评分、多策略对比、
K 线指标叠加），同时支持**信号模式**（不需要交易所密钥）以及可显式开启的
dry-run / OKX 实盘交易。

> 完整功能说明、架构细节与测试范围见 [freqtrade-desktop/README.md](freqtrade-desktop/README.md)。

## 环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10/11 | 当前主要支持 Windows（含 `dev.cmd` / `start-*.ps1`） |
| Python | 3.11+（64 位） | 后端与 freqtrade 共用同一个 venv |
| Node.js | 18+ | 前端 Electron / Vite |
| Freqtrade | 最新稳定版 | 需先单独安装，见下一步 |

## 快速开始

### 1. 安装 Freqtrade

```powershell
git clone https://github.com/freqtrade/freqtrade.git freqtrade-src
cd freqtrade-src
.\setup.ps1          # 按提示安装到 .venv
```

### 2. 安装本项目依赖

```powershell
cd freqtrade-desktop\backend
pip install -r requirements.txt

cd ..\desktop
npm install
```

### 3. 一键启动（推荐）

```powershell
cd freqtrade-desktop
.\dev.cmd
```

`dev.cmd` 会检查本地后端（127.0.0.1:8766）并在需要时重启，然后以前台方式打开
Electron 窗口；关闭终端即停止前端。

其他用法：

```bat
dev.cmd backend   :: 只启动后端（后台常驻）
dev.cmd web       :: 后端 + Vite，浏览器访问 http://127.0.0.1:5173
dev.cmd stop      :: 停止后端与 Vite
```

希望服务在关闭终端后继续运行（只通过浏览器使用）时，也可以执行
`.\start-services.ps1`，日志写在 `freqtrade-desktop\backend\data\` 与
`freqtrade-desktop\desktop\` 下。

## 配置密钥

项目**不会**把密钥写进配置文件，全部通过环境变量注入：

1. 复制模板：`freqtrade-desktop\APIserverKey.example.txt` → `freqtrade-desktop\APIserverKey.txt`
2. 填入自己的 OKX API Key / Secret / Passphrase 与本机 api_server 密码
3. 在终端执行该文件中的 `$env:...` 行，再启动服务

只做回测或信号模式时，交易所的三行密钥可以留空。`APIserverKey.txt` 与 `.env`
已被 `.gitignore` 忽略，请勿提交到 GitHub。

桌面端自己保存的连接密码写入系统钥匙串；钥匙串不可用时回退到环境变量
`FTDESK_SECRET_*`。更多细节见 [user_data/README.md](freqtrade-desktop/user_data/README.md)。

## 目录结构

```
freqtrade-desktop/
  backend/       FastAPI 后端（routers / services / scripts / tests）
  desktop/       Electron + React 前端
  user_data/     策略与配置（行情、回测结果在首次运行时生成）
docs/            ADR 与文档
.scratch/        规格与调研草稿
```

## 克隆下来之后

仓库里只放源码、策略和配置模板；下面这些**体积大、可重新生成**的东西没有提交，
首次运行时自动出现在本地：

| 内容 | 位置 | 怎么来 |
| --- | --- | --- |
| Python / Node 依赖 | `.venv`、`node_modules/` | `pip install -r requirements.txt`、`npm install` |
| 历史行情 K 线 | `user_data/data/` | 界面「设置 → 数据」下载 |
| 回测结果 | `user_data/backtest_results/` | 「回测中心」运行回测 |
| 超参优化结果 | `user_data/hyperopt_results/` | 运行 hyperopt |
| 清算流特征与采集数据 | `user_data/liquidation/` | `python scripts\build_cascade_features.py` |
| 因子面板 | `user_data/factors/` | `python scripts\factor_research.py` |
| 应用数据库与日志 | `backend/data/`、`user_data/logs/` | 启动后端时自动创建 |

因此从零开始只需要：`pip install` → `npm install` → `dev.cmd`，然后在界面里下载数据即可。

## 测试

```powershell
cd freqtrade-desktop\backend
python -m pytest -q
```

覆盖评分引擎边界、回测 JSON 解析、BotClient REST 封装、信号去重与 API 冒烟。

## 安全说明

- 仓库中不包含任何真实密钥；`APIserverKey.txt` 仅保留示例模板。
- freqtrade `api_server` 默认只监听 `127.0.0.1`。
- 实盘交易需要在界面中显式勾选风险确认。

## 已知限制

- OKX 合约回测在早于近 3 个月的区间上，资金费率数据存在偏差；单次调用仅 100 根 K 线。
- 回测精度为 OHLCV 级，手续费按交易所默认，未单独建模滑点。
- Telegram 控制的是本机运行中的 bot，需要本机保持在线。

## 免责声明

本项目仅供个人学习与研究使用，不构成投资建议。使用实盘交易功能产生的任何盈亏
由使用者自行承担。
