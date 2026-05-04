from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.bot import BotControlIn, BotControlOut, StrategySettingsIn, StrategySettingsOut, WatchTickIn
from app.services.broker_credentials import get_decrypted_broker_credentials, set_bot_enabled
from app.services.ai_report import queue_ai_report
from app.services.memberships import require_admin_access, require_live_trading_access, require_report_access
from app.services.scanner import finalize_chunked_scan, get_scan_market_status, prepare_chunked_scan_state, process_scan_chunk
from app.services.strategy_settings import get_strategy_settings, save_strategy_settings
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import force_liquidate_position_for_user, run_watch_tick_for_user


router = APIRouter(prefix="/bot", tags=["bot"])


class SingleSignalReportIn(BaseModel):
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    code: str = Field(pattern=r"^\d{6}$")


class ForceLiquidateIn(BaseModel):
    dry_run: bool = False


def now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


@router.post("/control", response_model=BotControlOut)
async def control_bot(
    payload: BotControlIn,
    user: CurrentUser = Depends(get_current_user),
) -> BotControlOut:
    if payload.enabled:
        credentials = await get_decrypted_broker_credentials(user.id)
        if (credentials.get("mode") or "paper") == "live":
            await require_live_trading_access(user.id, user.email)
    row = await set_bot_enabled(user.id, payload.enabled)
    return BotControlOut(user_id=row["user_id"], enabled=row["enabled"])


@router.get("/strategy", response_model=StrategySettingsOut)
async def strategy_settings(user: CurrentUser = Depends(get_current_user)) -> StrategySettingsOut:
    return StrategySettingsOut(**await get_strategy_settings(user.id))


@router.put("/strategy", response_model=StrategySettingsOut)
async def update_strategy_settings(
    payload: StrategySettingsIn,
    user: CurrentUser = Depends(get_current_user),
) -> StrategySettingsOut:
    return StrategySettingsOut(**await save_strategy_settings(user.id, payload.model_dump()))


@router.post("/scan")
async def scan(
    universe_scope: str = Query("all", pattern="^(limited|all)$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_admin_access(user.id, user.email)
    market_status = get_scan_market_status()
    if not market_status["is_open"]:
        return {
            "queued": False,
            "skipped": True,
            "reason": market_status["reason"],
            "trade_date": market_status["trade_date"],
            "message": market_status["message"],
            "market_status": market_status,
        }
    state = await prepare_chunked_scan_state(universe_scope=universe_scope)
    rows = await SupabaseRest().insert(
        "scan_runs",
        {
            "requested_by": user.id,
            "status": "running",
            "trade_date": state["trade_date"],
            "result": state,
            "universe_scope": state["universe_scope"],
            "started_at": now_iso(),
        },
    )
    scan_run = rows[0]
    scan_run_id = scan_run["id"]
    return {
        "queued": True,
        "scan_run_id": scan_run_id,
        "offset": state["offset"],
        "total": state["total"],
        "universe_scope": state["universe_scope"],
        "message": "Signal scan initialized. Continue with scan step API.",
    }


@router.post("/scan-runs/{scan_run_id}/step")
async def scan_step(scan_run_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    await require_admin_access(user.id, user.email)
    rows = await SupabaseRest().select("scan_runs", filters={"id": f"eq.{scan_run_id}"}, limit=1)
    if not rows:
        raise HTTPException(status_code=404, detail="Scan run not found")
    scan_run = rows[0]
    if scan_run["status"] == "completed":
        return scan_run
    if scan_run["status"] == "failed":
        raise HTTPException(status_code=400, detail=scan_run.get("error") or "Scan run failed")

    try:
        state = await process_scan_chunk(scan_run.get("result") or {})
    except Exception as exc:
        await SupabaseRest().patch(
            "scan_runs",
            filters={"id": f"eq.{scan_run_id}"},
            payload={"status": "failed", "error": str(exc), "finished_at": now_iso()},
        )
        raise
    if state["done"]:
        try:
            final_result = await finalize_chunked_scan(user.id, state)
            patched = await SupabaseRest().patch(
                "scan_runs",
                filters={"id": f"eq.{scan_run_id}"},
                payload={
                    "status": "completed",
                    "trade_date": final_result["trade_date"],
                    "signals_count": final_result["signals"],
                    "shared_saved": final_result["shared_saved"],
                    "result": {**state, "final": final_result},
                    "finished_at": now_iso(),
                },
            )
            return patched[0]
        except Exception as exc:
            await SupabaseRest().patch(
                "scan_runs",
                filters={"id": f"eq.{scan_run_id}"},
                payload={"status": "failed", "error": str(exc), "finished_at": now_iso()},
            )
            raise

    patched = await SupabaseRest().patch(
        "scan_runs",
        filters={"id": f"eq.{scan_run_id}"},
        payload={
            "status": "running",
            "signals_count": len(state.get("candidates") or []),
            "result": state,
        },
    )
    return patched[0]


@router.get("/scan-runs/latest")
async def latest_scan_run(user: CurrentUser = Depends(get_current_user)) -> dict | None:
    rows = await SupabaseRest().select("scan_runs", order="created_at.desc", limit=1)
    return rows[0] if rows else None


@router.post("/reports/daily")
async def send_daily_report(
    trade_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    report_style: str = Query("report", pattern=r"^(report|blog)$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_report_access(user.id, user.email)
    target_date = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    rows = await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{target_date}"},
        order="score.desc",
        limit=30,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No shared signals found for report date.")

    signals = [shared_signal_record_to_signal(row) for row in rows]
    result = await queue_ai_report(
        signals,
        datetime.fromisoformat(target_date).date(),
        report_type="daily_blog" if report_style == "blog" else "daily",
    )
    return {"trade_date": target_date, "signals": len(signals), **result}


@router.post("/reports/signal")
async def send_single_signal_report(
    payload: SingleSignalReportIn,
    report_style: str = Query("report", pattern=r"^(report|blog)$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_report_access(user.id, user.email)
    rows = await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{payload.trade_date}", "code": f"eq.{payload.code}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Signal not found for report date and code.")

    signal = shared_signal_record_to_signal(rows[0])
    result = await queue_ai_report(
        [signal],
        datetime.fromisoformat(payload.trade_date).date(),
        report_type="signal_blog" if report_style == "blog" else "signal",
        code=payload.code,
        name=signal.get("Name"),
    )
    return {
        "trade_date": payload.trade_date,
        "code": payload.code,
        "name": signal.get("Name"),
        **result,
    }


@router.get("/reports")
async def get_report(
    trade_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    report_type: str = Query(pattern=r"^(daily|signal|daily_blog|signal_blog)$"),
    code: str | None = Query(None, pattern=r"^\d{6}$"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    await require_report_access(user.id, user.email)
    filters = {
        "trade_date": f"eq.{trade_date}",
        "report_type": f"eq.{report_type}",
        "code": f"eq.{code or 'ALL'}",
    }
    rows = await SupabaseRest().select(
        "ai_reports",
        filters=filters,
        order="created_at.desc",
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="AI report not found.")
    return rows[0]


@router.get("/reports/dates")
async def list_report_dates(user: CurrentUser = Depends(get_current_user)) -> list[str]:
    await require_report_access(user.id, user.email)
    rows = await SupabaseRest().select(
        "ai_reports",
        columns="trade_date",
        order="trade_date.desc",
        limit=300,
    )
    dates: list[str] = []
    seen: set[str] = set()
    for row in rows:
        trade_date = row.get("trade_date")
        if not trade_date or trade_date in seen:
            continue
        seen.add(trade_date)
        dates.append(trade_date)
    return dates


@router.get("/reports/status")
async def list_report_statuses(
    trade_date: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    await require_report_access(user.id, user.email)
    return await SupabaseRest().select(
        "ai_reports",
        columns="id,trade_date,report_type,code,name,title,status,error,created_at,started_at,finished_at",
        filters={"trade_date": f"eq.{trade_date}"},
        order="created_at.desc",
        limit=100,
    )


@router.post("/watch-tick")
async def watch_tick(
    payload: WatchTickIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    if (credentials.get("mode") or "paper") == "live":
        await require_live_trading_access(user.id, user.email)
    return await run_watch_tick_for_user(credentials, test_mode=payload.test_mode, dry_run=payload.dry_run)


@router.post("/positions/{code}/force-liquidate")
async def force_liquidate_position(
    code: str = Path(pattern=r"^\d{6}$"),
    payload: ForceLiquidateIn | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    if (credentials.get("mode") or "paper") == "live":
        await require_live_trading_access(user.id, user.email)
    try:
        return await force_liquidate_position_for_user(credentials, code, dry_run=bool((payload or ForceLiquidateIn()).dry_run))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def shared_signal_record_to_signal(row: dict) -> dict:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    return {
        **raw,
        "Code": raw.get("Code") or row.get("code"),
        "Name": raw.get("Name") or row.get("name"),
        "Entry": raw.get("Entry") or row.get("entry"),
        "StopLoss": raw.get("StopLoss") or row.get("stop_loss"),
        "TakeProfit1": raw.get("TakeProfit1") or row.get("take_profit_1"),
        "TakeProfit2": raw.get("TakeProfit2") or row.get("take_profit_2"),
        "TrailingStop": raw.get("TrailingStop") or row.get("trailing_stop"),
        "Score": raw.get("Score") or row.get("score"),
    }
