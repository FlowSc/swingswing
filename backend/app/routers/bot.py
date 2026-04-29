import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.bot import BotControlIn, BotControlOut, WatchTickIn
from app.services.broker_credentials import get_broker_credentials, get_decrypted_broker_credentials, set_bot_enabled
from app.services.scanner import scan_and_store_for_user
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import run_watch_tick_for_user


router = APIRouter(prefix="/bot", tags=["bot"])
logger = logging.getLogger(__name__)


async def run_scan_background(scan_run_id: int, user_id: str, telegram_chat_id: str | None) -> None:
    rest = SupabaseRest()
    finished_at = lambda: datetime.now(ZoneInfo(get_settings().timezone)).isoformat()
    try:
        result = await scan_and_store_for_user(user_id, telegram_chat_id)
        await rest.patch(
            "scan_runs",
            filters={"id": f"eq.{scan_run_id}"},
            payload={
                "status": "completed",
                "trade_date": result.get("trade_date"),
                "signals_count": result.get("signals", 0),
                "shared_saved": result.get("shared_saved", 0),
                "result": result,
                "finished_at": finished_at(),
            },
        )
        logger.info("Signal scan completed: %s", result)
    except Exception as exc:
        await rest.patch(
            "scan_runs",
            filters={"id": f"eq.{scan_run_id}"},
            payload={"status": "failed", "error": str(exc)[:2000], "finished_at": finished_at()},
        )
        logger.exception("Signal scan failed")


@router.post("/control", response_model=BotControlOut)
async def control_bot(
    payload: BotControlIn,
    user: CurrentUser = Depends(get_current_user),
) -> BotControlOut:
    row = await set_bot_enabled(user.id, payload.enabled)
    return BotControlOut(user_id=row["user_id"], enabled=row["enabled"])


@router.post("/scan")
async def scan(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    settings = get_settings()
    if (user.email or "").lower() != settings.scan_admin_email.lower():
        raise HTTPException(status_code=403, detail="Only scan admin can run signal scans")
    credentials = await get_broker_credentials(user.id)
    telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
    rows = await SupabaseRest().insert(
        "scan_runs",
        {"requested_by": user.id, "status": "running"},
    )
    scan_run_id = rows[0]["id"]
    background_tasks.add_task(run_scan_background, scan_run_id, user.id, telegram_chat_id)
    return {"queued": True, "scan_run_id": scan_run_id, "message": "Signal scan started. Results will be saved to shared_signals."}


@router.get("/scan-runs/latest")
async def latest_scan_run(user: CurrentUser = Depends(get_current_user)) -> dict | None:
    rows = await SupabaseRest().select("scan_runs", order="created_at.desc", limit=1)
    return rows[0] if rows else None


@router.post("/watch-tick")
async def watch_tick(
    payload: WatchTickIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    return await run_watch_tick_for_user(credentials, test_mode=payload.test_mode, dry_run=payload.dry_run)
