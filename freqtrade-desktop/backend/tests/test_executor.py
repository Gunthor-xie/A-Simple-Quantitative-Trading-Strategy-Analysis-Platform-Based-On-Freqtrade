from __future__ import annotations

from pathlib import Path

from app.services.executor import FreqtradeExecutor


def test_userdir_is_placed_after_subcommand(tmp_path) -> None:
    executor = FreqtradeExecutor(bin_path="freqtrade", user_data=tmp_path)
    cmd = executor._cmd("backtesting", ["--strategy", "SampleStrategy", "--pairs", "BTC/USDT:USDT"])
    # prefix may be [resolved exe] or [python, -m, freqtrade]; only the tail matters.
    tail = cmd[len(executor._prefix) :]
    assert tail[:3] == ["backtesting", "--userdir", str(tmp_path)]
    assert "--strategy" in tail


def test_version_command_has_no_userdir(tmp_path) -> None:
    executor = FreqtradeExecutor(bin_path="freqtrade", user_data=tmp_path)
    assert executor._prefix + ["--version"] == executor.run_args_for_version


def test_prefix_resolves_to_script_when_available(tmp_path) -> None:
    executor = FreqtradeExecutor(bin_path="freqtrade", user_data=tmp_path)
    assert len(executor._prefix) >= 1
    # When the system has freqtrade, the prefix should not be a bare "freqtrade".
    assert executor._prefix[0].lower().endswith(("freqtrade.exe", "python", "python.exe"))


def test_run_does_not_duplicate_prefix(monkeypatch, tmp_path) -> None:
    from app.services import executor as executor_module

    captured: dict | None = {}

    def fake_run(cmd, capture_output, text, timeout, env):
        captured["cmd"] = cmd
        return type(
            "Proc",
            (),
            {"returncode": 0, "stdout": "ok", "stderr": ""},
        )()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)
    executor = FreqtradeExecutor(bin_path="freqtrade", user_data=tmp_path)
    executor.run(executor._cmd("backtesting", ["--strategy", "SampleStrategy"]))
    cmd = captured["cmd"]
    assert cmd.count(executor._prefix[0]) == 1
    assert cmd[cmd.index("backtesting") - 1] == executor._prefix[-1]
