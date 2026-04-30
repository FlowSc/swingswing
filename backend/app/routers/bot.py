from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.bot import BotControlIn, BotControlOut, StrategySettingsIn, StrategySettingsOut, WatchTickIn
from app.services.broker_credentials import get_broker_credentials, get_decrypted_broker_credentials, set_bot_enabled
from app.services.ai_report import send_daily_signal_report
from app.services.scanner import finalize_chunked_scan, prepare_chunked_scan_state, process_scan_chunk
from app.services.strategy_settings import get_strategy_settings, save_strategy_settings
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import run_watch_tick_for_user


router = APIRouter(prefix="/bot", tags=["bot"])


class SingleSignalReportIn(BaseModel):
    trade_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    code: str = Field(pattern=r"^\d{6}$")


def require_scan_admin(user: CurrentUser) -> None:
    settings = get_settings()
    if (user.email or "").lower() != settings.scan_admin_email.lower():
        raise HTTPException(status_code=403, detail="Only scan admin can run signal scans")


def now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


@router.post("/control", response_model=BotControlOut)
async def control_bot(
    payload: BotControlIn,
    user: CurrentUser = Depends(get_current_user),
) -> BotControlOut:
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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    require_scan_admin(user)
    state = await prepare_chunked_scan_state()
    rows = await SupabaseRest().insert(
        "scan_runs",
        {
            "requested_by": user.id,
            "status": "running",
            "trade_date": state["trade_date"],
            "result": state,
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
        "message": "Signal scan initialized. Continue with scan step API.",
    }


@router.post("/scan-runs/{scan_run_id}/step")
async def scan_step(scan_run_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    require_scan_admin(user)
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
            credentials = await get_broker_credentials(user.id)
            telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
            final_result = await finalize_chunked_scan(user.id, state, telegram_chat_id)
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
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    require_scan_admin(user)
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
    sent = await send_daily_signal_report(signals, datetime.fromisoformat(target_date).date())
    return {"sent": sent, "trade_date": target_date, "signals": len(signals)}


@router.post("/reports/signal")
async def send_single_signal_report(
    payload: SingleSignalReportIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    require_scan_admin(user)
    rows = await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{payload.trade_date}", "code": f"eq.{payload.code}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Signal not found for report date and code.")

    signal = shared_signal_record_to_signal(rows[0])
    sent = await send_daily_signal_report([signal], datetime.fromisoformat(payload.trade_date).date())
    return {
        "sent": sent,
        "trade_date": payload.trade_date,
        "code": payload.code,
        "name": signal.get("Name"),
    }


@router.post("/watch-tick")
async def watch_tick(
    payload: WatchTickIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    return await run_watch_tick_for_user(credentials, test_mode=payload.test_mode, dry_run=payload.dry_run)


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
