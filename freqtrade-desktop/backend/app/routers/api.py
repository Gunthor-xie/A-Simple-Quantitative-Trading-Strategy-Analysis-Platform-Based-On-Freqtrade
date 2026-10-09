from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..config import settings
from ..schemas import (
    AppSettings,
    BacktestParams,
    BacktestResult,
    BacktestRun,
    BotConnection,
    BuildConfigParams,
    ChartData,
    ChartCoverage,
    ConnectionOut,
    ConnectionTestResult,
    DownloadParams,
    JobState,
    ScoreReport,
    ScoreWeights,
    SignalEvent,
    StrategyInfo,
    StrategyValidateResult,
)
from ..security import SecretUnavailable, secret_store
from ..storage import db
from ..runtime import current_export_dir, current_user_data, z_thresholds
from ..services.bot_client import BotClient, BotClientError
from ..services.chart_service import ChartService
from ..services.coverage import scan as scan_coverage
from ..services.public_data import PublicDataDownloader, network_diagnostics
from ..services.analytics import analyze_trades
from ..services.excel_export import build_report, default_filename, parse_catalog
from ..services.executor import FreqtradeError, FreqtradeExecutor, FreqtradeUnavailable
from ..services.parser import parse_backtest_file
from ..services.scoring import build_baselines, compute_score
from ..services.signal_engine import SignalEngine


router = APIRouter(prefix="/api")
executor = FreqtradeExecutor()
chart_service = ChartService(settings.user_data, db)
signal_engine = SignalEngine(db)
logger = logging.getLogger("freqtrade-desktop.api")


def _exception_message(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def _connection_from_row(row: dict[str, Any]) -> BotConnection:
    return BotConnection(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        url=row["url"],
        username=row["username"],
        ws_token=row.get("ws_token"),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


def _connection_out(row: dict[str, Any]) -> ConnectionOut:
    has_password = False
    if row.get("id"):
        try:
            secret_store.get(f"conn:{row['id']}:password")
            has_password = True
        except SecretUnavailable:
            has_password = False
    return ConnectionOut(
        id=row["id"],
        name=row["name"],
        kind=row["kind"],
        url=row["url"],
        username=row["username"],
        has_password=has_password,
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


def _run_to_model(row: dict[str, Any]) -> BacktestRun:
    result = row["result_json"]
    return BacktestRun(
        id=row["id"],
        params=BacktestParams(**row["params_json"]),
        status=row["status"],
        error=row.get("error"),
        result=BacktestResult(**result) if result else None,
        result_file=row.get("result_file"),
        created_at=row["created_at"],
        finished_at=row.get("finished_at"),
    )


def _run_backtest_job(run_id: int) -> None:
    row = db.get_backtest(run_id)
    if not row:
        return
    params = BacktestParams(**row["params_json"])
    executor.user_data = current_user_data()
    db.update_backtest(run_id, status="running")
    export_dir = executor.user_data / "backtest_results"
    try:
        result_file = executor.backtest(params, export_dir)
        result = parse_backtest_file(result_file)
        db.update_backtest(
            run_id,
            status="done",
            result=result.model_dump(mode="json"),
            result_file=str(result_file),
        )
    except Exception as exc:
        db.update_backtest(run_id, status="error", error=_exception_message(exc))


def _run_download_job(job_id: str, params: DownloadParams) -> None:
    db.update_job(job_id, "running", "开始下载数据（OKX 公开行情接口）…")
    try:
        root = current_user_data()
        downloader = PublicDataDownloader(
            root,
            proxy=db.get_setting("http_proxy") or None,
            progress=lambda msg: db.update_job(job_id, "running", msg),
        )
        result = downloader.download(params)
        inventory = scan_coverage(root, write_file=True)
        groups = sum(len(tfs) for ex in inventory.values() for tfs in ex.values())
        rows = sum(item["rows"] for item in result["files"])
        failed = result.get("errors") or []
        extra = f"；失败 {len(failed)} 项：{failed[0]['error'][:120]}" if failed else ""
        db.update_job(
            job_id,
            "done",
            f"公开行情下载完成：{result['total_files']} 个文件 / {rows} 根K线；"
            f"数据目录共 {groups} 组{extra}",
        )
    except Exception as exc:
        db.update_job(job_id, "error", _exception_message(exc))


def _run_hyperopt_job(job_id: str, params: BacktestParams, epochs: int, loss: str) -> None:
    db.update_job(job_id, "running", "超参优化进行中…")
    try:
        executor.user_data = current_user_data()
        result_path = executor.hyperopt(params, epochs=epochs, loss=loss)
        db.update_job(job_id, "done", f"完成，结果文件：{result_path}")
    except Exception as exc:
        db.update_job(job_id, "error", _exception_message(exc))


def _run_lookahead_job(job_id: str, strategy: str, timerange: str, trading_mode: str) -> None:
    db.update_job(job_id, "running", "前视偏差分析进行中…")
    try:
        executor.user_data = current_user_data()
        proc = executor.lookahead_analysis(strategy, timerange, trading_mode)
        output = (proc.stdout or proc.stderr or "").strip()[-3000:]
        db.update_job(job_id, "done", output or "分析完成，无输出")
    except Exception as exc:
        db.update_job(job_id, "error", _exception_message(exc))


def _run_export_job(job_id: str, run_id: int) -> None:
    db.update_job(job_id, "running", "正在计算逐笔指标并生成 Excel…")
    try:
        row = db.get_backtest(run_id)
        if not row or row["status"] != "done" or not row["result_json"]:
            raise ValueError("回测不存在或未完成")
        params = BacktestParams(**row["params_json"])
        result = BacktestResult(**row["result_json"])
        if not result.trades:
            raise ValueError("???????????????? Excel")
        executor.user_data = current_user_data()
        data_rows, notes = analyze_trades(
            result.trades,
            user_data=executor.user_data,
            exchange=params.exchange,
            trading_mode=params.trading_mode,
            timeframe=params.timeframe,
        )
        sections = parse_catalog()
        soft, hard = z_thresholds()
        workbook = build_report(
            data_rows,
            sections,
            run_params={
                "回测ID": run_id,
                "策略": params.strategy,
                "交易对": ", ".join(params.pairs),
                "区间": params.timerange,
                "周期": params.timeframe,
                "模式": params.trading_mode,
                "交易笔数": len(result.trades),
            },
            z_soft=soft,
            z_hard=hard,
            notes=notes,
        )
        out_dir = current_export_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / default_filename(params.strategy)
        workbook.save(target)
        db.update_job(job_id, "done", f"已导出 {len(data_rows)} 笔：{target}")
    except Exception as exc:
        db.update_job(job_id, "error", _exception_message(exc))


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.2.0",
        "features": [
            "public_download",
            "coverage",
            "diagnostics",
            "proxy_setting",
            "timeframe_detail",
            "local_chart_inventory",
            "funding_arb",
        ],
    }


@router.get("/settings/status")
def settings_status() -> dict[str, Any]:
    version = ""
    error = ""
    try:
        version = executor.version()
        freqtrade_ok = True
    except Exception as exc:
        freqtrade_ok = False
        error = _exception_message(exc)
        logger.warning("freqtrade unavailable: %s", error)
    return {
        "freqtrade_available": freqtrade_ok,
        "freqtrade_version": version,
        "freqtrade_error": error,
        "user_data": str(current_user_data()),
        "keyring_available": secret_store.available,
        "default_db": str(settings.db_path),
    }


@router.get("/settings", response_model=AppSettings)
def get_settings() -> AppSettings:
    soft, hard = z_thresholds()
    return AppSettings(
        data_root=str(current_user_data()),
        export_dir=str(current_export_dir()),
        z_soft=soft,
        z_hard=hard,
        http_proxy=db.get_setting("http_proxy") or "",
    )


@router.put("/settings", response_model=AppSettings)
def put_settings(params: AppSettings) -> AppSettings:
    if params.data_root:
        db.set_setting("data_root", str(params.data_root))
    if params.export_dir:
        db.set_setting("export_dir", str(params.export_dir))
    db.set_setting("z_soft", str(params.z_soft))
    db.set_setting("z_hard", str(params.z_hard))
    db.set_setting("http_proxy", params.http_proxy or "")
    soft, hard = z_thresholds()
    return AppSettings(
        data_root=str(current_user_data()),
        export_dir=str(current_export_dir()),
        z_soft=soft,
        z_hard=hard,
        http_proxy=db.get_setting("http_proxy") or "",
    )


@router.post("/settings/build-config")
def build_config(params: BuildConfigParams) -> dict[str, Any]:
    config: dict[str, Any] = {
        "max_open_trades": params.max_open_trades,
        "stake_currency": params.stake_currency,
        "stake_amount": params.stake_amount,
        "tradable_balance_ratio": 0.99,
        "fiat_display_currency": "USD",
        "dry_run": params.dry_run,
        "dry_run_wallet": params.dry_run_wallet,
        "cancel_open_orders_on_exit": False,
        "trading_mode": params.trading_mode,
        "margin_mode": params.margin_mode,
        "unfilledtimeout": {"entry": 10, "exit": 10, "exit_timeout_count": 0, "unit": "minutes"},
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exit_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1},
        "exchange": {
            "name": params.exchange,
            "pair_whitelist": params.pairs,
            "pair_blacklist": [],
            "key": "",
            "secret": "",
            "password": "",
            "ccxt_config": {},
            "ccxt_async_config": {},
        },
        "pairlists": [{"method": "StaticPairList"}],
        "telegram": {
            "enabled": bool(params.telegram_token and params.telegram_chat_id),
            "token": params.telegram_token or "",
            "chat_id": params.telegram_chat_id or "",
            "notification_settings": {
                "status": "silent",
                "warning": "on",
                "startup": "silent",
                "entry": "silent",
                "exit": "silent",
            },
        },
        "api_server": {
            "enabled": True,
            "listen_ip_address": "127.0.0.1",
            "listen_port": params.api_port,
            "verbosity": "error",
            "enable_openapi": False,
            "jwt_secret_key": "",
            "CORS_origins": [],
            "username": "Freqtrader",
            "password": "",
            "ws_token": "",
        },
        "force_entry_enable": params.force_entry_enable,
        "initial_state": "running",
        "internals": {"process_throttle_secs": 5},
    }
    root = current_user_data()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "ok": True,
        "path": str(config_path),
        "hint": "请在运行前通过环境变量 FREQTRADE__EXCHANGE__KEY/SECRET/PASSWORD 注入交易所密钥，"
        "以及 FREQTRADE__API_SERVER__PASSWORD / JWT_SECRET_KEY / WS_TOKEN，避免明文入库。",
    }


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections() -> list[ConnectionOut]:
    return [_connection_out(row) for row in db.list_connections()]


@router.post("/connections", response_model=ConnectionOut)
def upsert_connection(connection: BotConnection) -> ConnectionOut:
    if not connection.id:
        connection.id = str(uuid.uuid4())
    existing = db.get_connection(connection.id)
    if existing:
        connection.created_at = existing["created_at"]
    if connection.password:
        try:
            secret_store.set(f"conn:{connection.id}:password", connection.password)
        except SecretUnavailable as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        connection.password = None
    row = db.upsert_connection(connection.model_dump(exclude_none=True))
    return _connection_out(row)


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: str) -> dict[str, Any]:
    if not db.get_connection(connection_id):
        raise HTTPException(status_code=404, detail="连接不存在")
    db.delete_connection(connection_id)
    secret_store.delete(f"conn:{connection_id}:password")
    return {"ok": True}


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestResult)
def test_connection(connection_id: str) -> ConnectionTestResult:
    row = db.get_connection(connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    client = BotClient(_connection_from_row(row))
    try:
        client.ping()
        version = client.version()
        return ConnectionTestResult(ok=True, message="连接成功", version=version or None)
    except (BotClientError, SecretUnavailable) as exc:
        return ConnectionTestResult(ok=False, message=_exception_message(exc))
    finally:
        client.close()


def _client_for(connection_id: str) -> BotClient:
    row = db.get_connection(connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="连接不存在")
    return BotClient(_connection_from_row(row))


@router.get("/bot/{connection_id}/read/{endpoint}")
def bot_read(connection_id: str, endpoint: str) -> Any:
    allowed = {
        "status", "profit", "balance", "trades", "count", "whitelist", "blacklist",
        "locks", "show-config", "sysinfo", "logs", "health", "version", "strategies",
    }
    if endpoint not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的端点: {endpoint}")
    client = _client_for(connection_id)
    try:
        method = getattr(client, endpoint.replace("-", "_"))
        if endpoint == "trades":
            return method(limit=200)
        return method()
    except (BotClientError, SecretUnavailable) as exc:
        raise HTTPException(status_code=502, detail=_exception_message(exc)) from exc
    finally:
        client.close()


@router.post("/bot/{connection_id}/action/{action}")
def bot_action(connection_id: str, action: str, payload: dict[str, Any] | None = None) -> Any:
    payload = payload or {}
    client = _client_for(connection_id)
    try:
        if action in ("start", "pause", "stop", "stopbuy", "reload-config"):
            return getattr(client, action.replace("-", "_"))()
        if action == "force-enter":
            pair = payload.get("pair")
            if not pair:
                raise HTTPException(status_code=400, detail="force-enter 需要 pair")
            return client.force_enter(
                pair=pair,
                side=payload.get("side", "long"),
                price=payload.get("price"),
                ordertype=payload.get("ordertype"),
                stake_amount=payload.get("stake_amount"),
                leverage=payload.get("leverage"),
                enter_tag=payload.get("enter_tag"),
            )
        if action == "force-exit":
            tradeid = payload.get("tradeid")
            if tradeid is None:
                raise HTTPException(status_code=400, detail="force-exit 需要 tradeid")
            return client.force_exit(
                tradeid=tradeid,
                ordertype=payload.get("ordertype"),
                amount=payload.get("amount"),
            )
        if action == "blacklist-add":
            pair = payload.get("pair")
            if not pair:
                raise HTTPException(status_code=400, detail="blacklist-add 需要 pair")
            return client.blacklist_add(pair)
        if action == "lock-add":
            pair = payload.get("pair")
            until = payload.get("until")
            if not pair or not until:
                raise HTTPException(status_code=400, detail="lock-add 需要 pair 与 until")
            return client.lock_add(pair, until, reason=payload.get("reason", ""))
        raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")
    except (BotClientError, SecretUnavailable) as exc:
        raise HTTPException(status_code=502, detail=_exception_message(exc)) from exc
    finally:
        client.close()


@router.get("/strategies", response_model=list[StrategyInfo])
def list_strategies() -> list[StrategyInfo]:
    try:
        return [StrategyInfo(**item) for item in executor.list_strategies()]
    except FreqtradeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FreqtradeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/strategies/validate", response_model=StrategyValidateResult)
def validate_strategy(payload: dict[str, str]) -> StrategyValidateResult:
    name = payload.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="需要策略名称")
    strategy_file = settings.user_data / "strategies" / f"{name}.py"
    errors: list[str] = []
    warnings: list[str] = []
    if not strategy_file.exists():
        errors.append(f"策略文件不存在: {strategy_file}")
    else:
        try:
            compile(strategy_file.read_text(encoding="utf-8"), str(strategy_file), "exec")
        except SyntaxError as exc:
            errors.append(f"语法错误: {exc}")
    try:
        known = executor.list_strategies()
        if not any(s["name"] == name for s in known):
            warnings.append(f"freqtrade 未识别策略 {name}（可能尚未刷新或不在 user_data/strategies）")
    except Exception:
        warnings.append("无法访问 freqtrade，仅做了本地文件检查")
    return StrategyValidateResult(ok=not errors, name=name, errors=errors, warnings=warnings)


@router.post("/backtests", response_model=BacktestRun)
def create_backtest(params: BacktestParams, background: BackgroundTasks) -> BacktestRun:
    run_id = db.create_backtest(params.model_dump(mode="json"))
    background.add_task(_run_backtest_job, run_id)
    return _run_to_model(db.get_backtest(run_id) or {})


@router.get("/backtests", response_model=list[BacktestRun])
def list_backtests(limit: int = 100) -> list[BacktestRun]:
    return [_run_to_model(row) for row in db.list_backtests(limit)]


@router.delete("/backtests/{run_id}")
def delete_backtest(run_id: int) -> dict[str, Any]:
    """删除一条回测记录，并清理它关联的本地回测文件。

    - 运行中的回测不允许删除（避免删掉正在写入的结果文件）。
    - 只删除 user_data/backtest_results 目录内的文件，防止路径穿越。
    """
    row = db.get_backtest(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="回测不存在")
    if row["status"] == "running":
        raise HTTPException(status_code=400, detail="回测正在运行，暂时不能删除")

    removed = db.delete_backtest(run_id)
    deleted_files: list[str] = []
    warnings: list[str] = []

    raw = (removed or {}).get("result_file")
    if raw:
        root = (Path(current_user_data()) / "backtest_results").resolve()
        result_path = Path(raw)
        targets = [result_path, result_path.parent / f"{result_path.stem}.meta.json"]
        for target in targets:
            try:
                resolved = target.resolve()
            except OSError:
                warnings.append(f"无法解析路径：{target}")
                continue
            if resolved != root and root not in resolved.parents:
                warnings.append(f"跳过回测目录外的文件：{target}")
                continue
            if not resolved.exists():
                continue
            try:
                resolved.unlink()
                deleted_files.append(str(resolved))
            except OSError as exc:
                warnings.append(f"删除失败 {resolved}：{exc}")

        # .last_result.json 只是"最新结果"指针，指向被删文件时一并清掉
        pointer = root / ".last_result.json"
        try:
            if pointer.exists():
                payload = json.loads(pointer.read_text(encoding="utf-8"))
                if str(payload.get("latest_backtest", "")) == result_path.name:
                    pointer.unlink()
                    deleted_files.append(str(pointer))
        except (OSError, ValueError):
            warnings.append("无法读取 .last_result.json，已跳过")

    return {
        "ok": True,
        "id": run_id,
        "deleted_files": deleted_files,
        "warnings": warnings,
    }


@router.get("/backtests/{run_id}", response_model=BacktestRun)
def get_backtest(run_id: int) -> BacktestRun:
    row = db.get_backtest(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="回测不存在")
    return _run_to_model(row)


@router.get("/backtests/{run_id}/score", response_model=ScoreReport)
def backtest_score(run_id: int, weights: ScoreWeights | None = None) -> ScoreReport:
    row = db.get_backtest(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="回测不存在")
    if row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="回测尚未完成")
    result = BacktestResult(**row["result_json"])
    saved_weights = db.get_weights()
    weight_model = ScoreWeights(**saved_weights) if saved_weights else ScoreWeights()
    if weights is not None:
        weight_model = weights
    history = db.best_metrics_for_strategy(result.strategy)
    baselines, source = build_baselines(history)
    return compute_score(result, weight_model, baselines=baselines, baseline_source=source)


@router.post("/backtests/compare", response_model=list[dict[str, Any]])
def compare_backtests(ids: list[int]) -> list[dict[str, Any]]:
    if not 2 <= len(ids) <= 10:
        raise HTTPException(status_code=400, detail="对比需要 2-10 个回测")
    rows = [db.get_backtest(i) for i in ids]
    if any(r is None for r in rows):
        raise HTTPException(status_code=404, detail="存在不存在的回测 ID")
    loaded = [_run_to_model(row) for row in rows if row is not None]
    base_params = loaded[0].params
    incompatible = [
        f"回测 #{run.id} 参数与首个回测不一致（timerange/pairs/timeframe/mode）"
        for run in loaded[1:]
        if (
            run.params.timerange != base_params.timerange
            or run.params.pairs != base_params.pairs
            or run.params.timeframe != base_params.timeframe
            or run.params.trading_mode != base_params.trading_mode
        )
    ]
    saved_weights = db.get_weights()
    weight_model = ScoreWeights(**saved_weights) if saved_weights else ScoreWeights()
    out: list[dict[str, Any]] = []
    for run in loaded:
        if run.status != "done" or run.result is None:
            out.append({"run_id": run.id, "score": None, "result": None, "warnings": ["回测未完成"]})
            continue
        history = db.best_metrics_for_strategy(run.result.strategy)
        baselines, source = build_baselines(history)
        report = compute_score(run.result, weight_model, baselines=baselines, baseline_source=source)
        out.append(
            {
                "run_id": run.id,
                "score": report.composite,
                "result": run.result.model_dump(mode="json"),
                "warnings": report.warnings + incompatible,
            }
        )
    return out


@router.get("/backtests/{run_id}/chart", response_model=ChartData)
def backtest_chart(
    run_id: int,
    pair: str = Query(...),
    timeframe: str = Query("5m"),
    indicators: str = Query("sma20,ema20,rsi,macd,boll"),
    limit: int = Query(30000, ge=10, le=300000),
    offset: int = Query(0, ge=0),
) -> ChartData:
    chart_service.user_data = current_user_data()
    row = db.get_backtest(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="?????")
    if row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="??????")
    params = BacktestParams(**row["params_json"])
    result = BacktestResult(**row["result_json"])
    try:
        return chart_service.backtest_chart(
            result,
            exchange=params.exchange,
            pair=pair,
            timeframe=timeframe,
            trading_mode=params.trading_mode,
            indicators=[i.strip() for i in indicators.split(",") if i.strip()],
            limit=limit,
            offset=offset,
            timerange=_run_timerange_ms(params.timerange),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _run_timerange_ms(timerange: str) -> tuple[int | None, int | None] | None:
    if not timerange or "-" not in timerange:
        return None
    import datetime as _dt

    def ms(part: str, end: bool) -> int | None:
        try:
            y = int(part[0:4]); m = int(part[4:6]); d = int(part[6:8])
            value = _dt.datetime(y, m, d, tzinfo=_dt.timezone.utc)
            if end:
                # use timedelta so month-end dates (e.g. 20251231) do not overflow
                value += _dt.timedelta(days=1)
            return int(value.timestamp() * 1000)
        except Exception:
            return None
    parts = timerange.split("-")
    return ms(parts[0], False), (ms(parts[1], True) if parts[1] else None)


@router.get("/charts/local", response_model=ChartData)
def local_chart(
    pair: str = Query(...),
    timeframe: str = Query("15m"),
    trading_mode: str = Query("spot"),
    exchange: str = Query("okx"),
    indicators: str = Query("sma20,ema20,rsi,macd,boll"),
    limit: int = Query(20000, ge=10, le=60000),
    offset: int = Query(0, ge=0),
) -> ChartData:
    """Read candles straight from the local jsongz files (no network)."""
    chart_service.user_data = current_user_data()
    meta: dict = {}
    try:
        candles = chart_service.load_candles(
            exchange, pair, timeframe, trading_mode=trading_mode,
            limit=limit, offset=offset, meta=meta,
        )
    except FileNotFoundError as exc:
        inventory = scan_coverage(current_user_data(), write_file=False)
        available: list[str] = []
        for pair_key, tf_map in (inventory.get(exchange) or {}).items():
            available.append(f"{pair_key} [{'/'.join(sorted(tf_map.keys()))}]")
        detail = f"{exc} | available local data: {', '.join(available) or 'none'}"
        raise HTTPException(status_code=404, detail=detail) from exc
    coverage = None
    if meta.get("count"):
        fill = min(1.0, meta["count"] / max(meta.get("expected", 1), 1))
        coverage = ChartCoverage(
            start=meta["start"], end=meta["end"], count=meta["count"],
            expected=meta.get("expected", meta["count"]),
            fill_ratio=round(fill, 4), has_gap=fill < 0.995,
        )
    return ChartData(
        candles=candles,
        indicators=chart_service.compute_indicators(
            candles, [i.strip() for i in indicators.split(",") if i.strip()]
        ),
        markers=[],
        signals=[],
        total=len(candles),
        coverage=coverage,
    )


@router.get("/charts/live", response_model=ChartData)
def live_chart(
    connection_id: str = Query(...),
    strategy: str = Query(...),
    pair: str = Query(...),
    timeframe: str = Query("5m"),
    indicators: str = Query("sma20,ema20,rsi,macd,boll"),
    limit: int = Query(750, ge=10, le=5000),
) -> ChartData:
    chart_service.user_data = current_user_data()
    client = _client_for(connection_id)
    try:
        return chart_service.live_chart(
            client,
            strategy=strategy,
            pair=pair,
            timeframe=timeframe,
            indicators=[i.strip() for i in indicators.split(",") if i.strip()],
            limit=limit,
        )
    except (BotClientError, SecretUnavailable, FileNotFoundError) as exc:
        raise HTTPException(status_code=502, detail=_exception_message(exc)) from exc
    finally:
        client.close()


@router.post("/data/download")
def download_data(params: DownloadParams, background: BackgroundTasks) -> JobState:
    job_id = db.create_job("download")
    background.add_task(_run_download_job, job_id, params)
    return JobState(**db.get_job(job_id) or {})


@router.get("/data/available")
def data_available() -> dict[str, Any]:
    executor.user_data = current_user_data()
    return executor.list_data()


@router.get("/data/coverage")
def data_coverage() -> dict[str, Any]:
    return scan_coverage(current_user_data(), write_file=True)


@router.get("/diagnostics/network")
def diagnostics_network(proxy: str | None = Query(None)) -> dict[str, Any]:
    """Report which route to OKX works from the backend process."""
    return network_diagnostics(proxy or db.get_setting("http_proxy") or None)


@router.get("/jobs/{job_id}", response_model=JobState)
def get_job(job_id: str) -> JobState:
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JobState(**row)


@router.get("/jobs", response_model=list[JobState])
def list_jobs() -> list[JobState]:
    return [JobState(**row) for row in db.recent_jobs()]


@router.post("/hyperopt")
def start_hyperopt(
    params: BacktestParams,
    background: BackgroundTasks,
    epochs: int = Query(100, ge=1, le=5000),
    loss: str = Query("MultiMetricHyperOptLoss"),
) -> JobState:
    job_id = db.create_job("hyperopt")
    background.add_task(_run_hyperopt_job, job_id, params, epochs, loss)
    return JobState(**db.get_job(job_id) or {})


@router.post("/backtests/{run_id}/export")
def export_backtest(run_id: int, background: BackgroundTasks) -> JobState:
    job_id = db.create_job("export")
    background.add_task(_run_export_job, job_id, run_id)
    return JobState(**db.get_job(job_id) or {})


@router.post("/analysis/lookahead")
def start_lookahead(
    background: BackgroundTasks,
    strategy: str = Query(...),
    timerange: str = Query("20240101-"),
    trading_mode: str = Query("spot"),
) -> JobState:
    job_id = db.create_job("lookahead")
    background.add_task(_run_lookahead_job, job_id, strategy, timerange, trading_mode)
    return JobState(**db.get_job(job_id) or {})


@router.get("/score/weights", response_model=ScoreWeights)
def get_score_weights() -> ScoreWeights:
    saved = db.get_weights()
    return ScoreWeights(**saved) if saved else ScoreWeights()


@router.put("/score/weights", response_model=ScoreWeights)
def put_score_weights(weights: ScoreWeights) -> ScoreWeights:
    db.set_weights(weights.as_dict())
    return weights


@router.get("/score/baselines")
def score_baselines(strategy: str) -> dict[str, Any]:
    history = db.best_metrics_for_strategy(strategy)
    baselines, source = build_baselines(history)
    return {"baselines": baselines, "source": source, "history": history}


@router.get("/signals", response_model=list[SignalEvent])
def list_signals(strategy: str | None = None, limit: int = 200) -> list[SignalEvent]:
    return [SignalEvent(**row) for row in db.list_signals(strategy, limit)]


@router.post("/signals/refresh", response_model=list[SignalEvent])
def refresh_signals(payload: dict[str, Any]) -> list[SignalEvent]:
    connection_id = payload.get("connection_id")
    strategy = payload.get("strategy", "")
    pairs = payload.get("pairs", [])
    timeframe = payload.get("timeframe", "5m")
    if not connection_id or not strategy or not pairs:
        raise HTTPException(status_code=400, detail="需要 connection_id/strategy/pairs")
    client = _client_for(connection_id)
    try:
        events = signal_engine.live_signals(client, strategy, pairs, timeframe)
    except (BotClientError, SecretUnavailable) as exc:
        raise HTTPException(status_code=502, detail=_exception_message(exc)) from exc
    finally:
        client.close()
    return events


@router.post("/signals/from-backtest", response_model=list[SignalEvent])
def signals_from_backtest(payload: dict[str, Any]) -> list[SignalEvent]:
    run_id = payload.get("run_id")
    row = db.get_backtest(int(run_id)) if run_id else None
    if not row or row["status"] != "done" or not row["result_json"]:
        raise HTTPException(status_code=400, detail="回测不存在或未完成")
    result = BacktestResult(**row["result_json"])
    return signal_engine.backtest_signals(result)
