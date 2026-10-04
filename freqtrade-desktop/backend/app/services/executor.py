from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any

from ..config import settings
from ..schemas import BacktestParams, DownloadParams


class FreqtradeUnavailable(Exception):
    """freqtrade binary could not be located or executed."""


class FreqtradeError(Exception):
    """freqtrade command exited with a non-zero code."""


class FreqtradeExecutor:
    """Adapter around the freqtrade CLI.

    The current implementation targets a local native venv on Windows/macOS/Linux.
    Future server deployments swap this class for a remote executor without
    touching the routers.
    """

    def __init__(self, bin_path: str | None = None, user_data: str | Path | None = None) -> None:
        self.user_data = Path(user_data or settings.user_data)
        explicit = bin_path or settings.freqtrade_bin
        self.bin = explicit
        launcher = (
            Path(__file__).resolve().parent.parent.parent
            / "scripts"
            / "freqtrade_offline.py"
        )
        if launcher.exists():
            # Route every freqtrade invocation through the offline-market
            # launcher so backtesting works without a live OKX connection.
            self._prefix = [sys.executable, str(launcher)]
        elif explicit and (resolved := shutil.which(explicit)):
            self._prefix = [resolved]
        elif importlib.util.find_spec("freqtrade") is not None:
            # Fallback: run freqtrade through the same Python interpreter.
            self._prefix = [sys.executable, "-m", "freqtrade"]
        else:
            self._prefix = [explicit]

    def _cmd(self, subcommand: str, args: list[str]) -> list[str]:
        """freqtrade places ``--userdir`` on the subcommand (not globally).

        ``freqtrade --userdir X <sub>`` fails with "invalid choice" on newer
        releases, so build ``freqtrade <sub> --userdir X ...`` instead.
        """
        return [*self._prefix, subcommand, "--userdir", str(self.user_data), *args]

    @property
    def run_args_for_version(self) -> list[str]:
        return [*self._prefix, "--version"]

    def run(
        self,
        args: list[str],
        timeout: int | None = 1800,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        # ``args`` is the full argv (already including self._prefix, e.g. from
        # _cmd()). Prepending the prefix again would duplicate the executable
        # path and break argparse ("invalid choice: ...freqtrade.EXE").
        cmd = list(args)
        run_env = os.environ.copy()
        run_env["FTDESK_USER_DATA"] = str(self.user_data)
        if env:
            run_env.update(env)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )
        except FileNotFoundError as exc:
            raise FreqtradeUnavailable(
                f"找不到 freqtrade 命令（{self.bin}）。请先在本机 venv 中安装 freqtrade，"
                "或设置 FTDESK_FREQTRADE_BIN 指向可执行文件路径。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise FreqtradeError(f"freqtrade 命令超时（>{timeout}s）：{' '.join(cmd)}") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            raise FreqtradeError(f"freqtrade 退出码 {proc.returncode}: {detail}")
        return proc

    def available(self) -> bool:
        try:
            self.run([*self._prefix, "--version"], timeout=30)
            return True
        except Exception:
            return False

    def version(self) -> str:
        proc = self.run([*self._prefix, "--version"], timeout=30)
        text = (proc.stdout or proc.stderr or "").strip()
        match = re.search(r"Freqtrade Version:\s*(\S.*)", text)
        if match:
            return match.group(1).strip()
        return text

    def list_strategies(self) -> list[dict[str, str]]:
        """List strategies; tolerates both JSON and table output."""
        try:
            proc = self.run(self._cmd("list-strategies", ["--print-json"]), timeout=60)
            text = proc.stdout.strip()
            if text:
                data = json.loads(text)
                strategies = data if isinstance(data, list) else data.get("strategies", [])
                return [
                    {"name": s.get("name", ""), "file": s.get("file", ""), "path": s.get("path", "")}
                    for s in strategies
                    if isinstance(s, dict) and s.get("name")
                ]
        except Exception:
            pass
        # Fallback: scan the strategies directory for *.py files with a strategy class.
        strategies_dir = self.user_data / "strategies"
        found: list[dict[str, str]] = []
        if strategies_dir.exists():
            for py in sorted(strategies_dir.glob("*.py")):
                if py.name.startswith("_"):
                    continue
                text = py.read_text(encoding="utf-8", errors="ignore")
                names = re.findall(r"^class\s+(\w+)\s*\(IStrategy\)", text, re.MULTILINE)
                if not names:
                    names = re.findall(r"^class\s+(\w+)\s*\(.*Strategy.*\)", text, re.MULTILINE)
                found.extend(
                    {"name": n, "file": py.name, "path": str(py)} for n in names
                )
        return found

    def strategy_exists(self, name: str) -> bool:
        return any(s["name"] == name for s in self.list_strategies())

    def download_data(self, params: DownloadParams) -> subprocess.CompletedProcess[str]:
        pairs = list(params.pairs)
        if params.trading_mode == "spot":
            pairs = [p.split(":")[0] for p in pairs]
        proc: subprocess.CompletedProcess[str] | None = None
        for timeframe in params.timeframes:
            args: list[str] = [
                "--exchange", params.exchange,
                "--pairs", *pairs,
                "--timeframe", timeframe,
                "--data-format-ohlcv", params.data_format,
                "--trading-mode", params.trading_mode,
            ]
            if params.timerange:
                args += ["--timerange", params.timerange]
            proc = self.run(self._cmd("download-data", args), timeout=7200)
        if proc is None:
            raise FreqtradeError("下载任务没有执行任何周期")
        return proc

    def backtest(self, params: BacktestParams, export_dir: str | Path) -> Path:
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        # 2025.x backtesting has no --trading-mode flag; the mode comes from the
        # config file. Build a per-run config so spot/futures match the request
        # instead of inheriting user_data/config.json.
        template = self.user_data / f"config-okx-{params.trading_mode}.example.json"
        if not template.exists():
            raise FreqtradeError(
                f"缺少配置模板 {template}（回测需要完整配置作底）。请从项目 user_data 恢复。"
            )
        run_config: dict[str, Any] = json.loads(template.read_text(encoding="utf-8"))
        run_config["trading_mode"] = params.trading_mode
        run_config["margin_mode"] = (
            params.margin_mode if params.trading_mode == "futures" else ""
        )
        run_config["dry_run"] = True
        run_config["stake_currency"] = "USDT"
        run_config["dataformat_ohlcv"] = "jsongz"
        run_config["pairlists"] = [{"method": "StaticPairList"}]
        config_file = export_dir / f"_{params.strategy}_runconfig.json"
        config_file.write_text(
            json.dumps(run_config, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        pairs = list(params.pairs)
        if params.trading_mode == "spot":
            # Spot symbols never carry the :STAKES currency suffix.
            pairs = [p.split(":")[0] for p in pairs]
        args: list[str] = [
            "-c", str(config_file),
            "--strategy", params.strategy,
            "--timerange", params.timerange,
            "--timeframe", params.timeframe,
            "--export", "trades",
            "--cache", "none",
            "--dry-run-wallet", str(params.dry_run_wallet),
            "--stake-amount", params.stake_amount,
            "--max-open-trades", str(params.max_open_trades),
        ]
        if pairs:
            args += ["--pairs", *pairs]
        # Offline market cache carries no fee schedule; fall back to 0.1% taker
        # (OKX default) unless the user overrides the fee explicitly.
        args += ["--fee", str(params.fee if params.fee is not None else 0.001)]
        if params.timeframe_detail:
            args += ["--timeframe-detail", params.timeframe_detail]
        if params.enable_protections:
            args += ["--enable-protections"]
        self.run(self._cmd("backtesting", args))
        # 2025.x archives results as backtest-result-<ts>.zip in
        # user_data/backtest_results; prefer the newest archive.
        candidates = sorted(
            (p for p in export_dir.glob("backtest-result-*.zip") if not p.name.startswith("_")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        result_file = candidates[0] if candidates else None
        if result_file is None:
            raise FreqtradeError("回测完成但未找到结果归档文件（backtest-result-*.zip）")
        return result_file

    def hyperopt(self, params: BacktestParams, epochs: int = 100,
                 loss: str = "MultiMetricHyperOptLoss", export_dir: str | Path | None = None) -> Path:
        args: list[str] = [
            "--strategy", params.strategy,
            "--timerange", params.timerange,
            "--timeframe", params.timeframe,
            "--epochs", str(epochs),
            "--hyperopt-loss", loss,
            "--dry-run-wallet", str(params.dry_run_wallet),
            "--stake-amount", params.stake_amount,
            "--max-open-trades", str(params.max_open_trades),
        ]
        if params.pairs:
            args += ["--pairs", *params.pairs]
        if params.trading_mode == "futures":
            args += ["--trading-mode", "futures"]
        self.run(self._cmd("hyperopt", args), timeout=10800)
        results_dir = self.user_data / "hyperopt_results"
        results_dir.mkdir(parents=True, exist_ok=True)
        candidates = sorted(results_dir.glob("*.json"))
        if not candidates:
            raise FreqtradeError("超参优化完成但未找到结果文件")
        return candidates[-1]

    def lookahead_analysis(self, strategy: str, timerange: str,
                           trading_mode: str = "spot") -> subprocess.CompletedProcess[str]:
        args: list[str] = [
            "--strategy", strategy,
            "--timerange", timerange,
        ]
        if trading_mode == "futures":
            args += ["--trading-mode", "futures"]
        return self.run(self._cmd("lookahead-analysis", args), timeout=7200)

    def list_data(self) -> dict[str, Any]:
        """Downloaded data inventory: {pair: {timeframe: path}}."""
        data_root = self.user_data / "data"
        inventory: dict[str, dict[str, str]] = {}
        if not data_root.exists():
            return inventory
        for exchange_dir in sorted(data_root.iterdir()):
            if not exchange_dir.is_dir():
                continue
            pair_dir = exchange_dir
            # futures data lives under <exchange>/futures/<pair>
            children = [pair_dir] if exchange_dir.name == "futures" else []
            for sub in sorted(exchange_dir.iterdir()):
                if sub.is_dir() and sub.name == "futures":
                    children.extend(sorted(sub.iterdir()))
            for pair_path in children:
                if not pair_path.is_dir():
                    continue
                key = f"{exchange_dir.name}:{pair_path.name}"
                for tf_file in sorted(pair_path.glob("*.json*")):
                    inventory.setdefault(key, {})[tf_file.stem] = str(tf_file)
        return inventory
