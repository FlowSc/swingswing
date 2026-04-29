from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.schemas.bot import BotControlIn, BotControlOut, WatchTickIn
from app.services.broker_credentials import get_decrypted_broker_credentials, set_bot_enabled
from app.services.scan_worker import queue_admin_scan
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import run_watch_tick_for_user


router = APIRouter(prefix="/bot", tags=["bot"])


@router.post("/control", response_model=BotControlOut)
async def control_bot(
    payload: BotControlIn,
    user: CurrentUser = Depends(get_current_user),
) -> BotControlOut:
    row = await set_bot_enabled(user.id, payload.enabled)
    return BotControlOut(user_id=row["user_id"], enabled=row["enabled"])


@router.post("/scan")
async def scan(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    settings = get_settings()
    if (user.email or "").lower() != settings.scan_admin_email.lower():
        raise HTTPException(status_code=403, detail="Only scan admin can run signal scans")
    scan_run = await queue_admin_scan()
    scan_run_id = scan_run["id"]
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
