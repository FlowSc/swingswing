from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.broker_credentials import get_broker_credentials, list_enabled_broker_credentials
from app.services.scanner import scan_and_store_for_user
from app.services.supabase_rest import SupabaseRest
from app.services.watcher import run_watch_tick_for_user


_scheduler: AsyncIOScheduler | None = None


async def daily_scan_job() -> None:
    settings = get_settings()
    admin = await SupabaseRest().find_user_by_email(settings.scan_admin_email)
    if not admin:
        return
    credentials = await get_broker_credentials(admin["id"])
    telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
    await scan_and_store_for_user(admin["id"], telegram_chat_id)


async def intraday_watch_job() -> None:
    credentials_rows = await list_enabled_broker_credentials()
    for credentials in credentials_rows:
        await run_watch_tick_for_user(credentials, test_mode=False, dry_run=False)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    settings = get_settings()
    timezone = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(daily_scan_job, "cron", day_of_week="mon-fri", hour=13, minute=30)
    scheduler.add_job(intraday_watch_job, "cron", day_of_week="mon-fri", hour="9-15", minute="*/5")
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
