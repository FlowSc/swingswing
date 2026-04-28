from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, get_current_user
from app.schemas.bot import BotControlIn, BotControlOut, WatchTickIn
from app.services.broker_credentials import get_broker_credentials, get_decrypted_broker_credentials, set_bot_enabled
from app.services.scanner import scan_and_store_for_user
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
async def scan(user: CurrentUser = Depends(get_current_user)) -> dict:
    credentials = await get_broker_credentials(user.id)
    telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
    return await scan_and_store_for_user(user.id, telegram_chat_id)


@router.post("/watch-tick")
async def watch_tick(
    payload: WatchTickIn,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    credentials = await get_decrypted_broker_credentials(user.id)
    return await run_watch_tick_for_user(credentials, test_mode=payload.test_mode, dry_run=payload.dry_run)
