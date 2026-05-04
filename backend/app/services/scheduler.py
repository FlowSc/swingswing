from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.broker_credentials import list_enabled_broker_credentials
from app.services.ai_report import process_queued_ai_reports
from app.services.scanner import get_scan_market_status, scan_and_store_for_user
from app.services.supabase_rest import SupabaseRest
from app.services.telegram import send_telegram_message_with_bot
from app.services.watch_jobs import enqueue_watch_jobs, process_watch_jobs
from app.services.watcher import run_realtime_position_watch_for_user, run_watch_tick_for_user


_scheduler: AsyncIOScheduler | None = None
logger = logging.getLogger(__name__)


async def daily_scan_job() -> None:
    settings = get_settings()
    market_status = get_scan_market_status()
    if not market_status["is_open"]:
        logger.warning("Daily scan skipped before start: %s", market_status)
        return
    admin = await SupabaseRest().find_user_by_email(settings.scan_admin_email)
    if not admin:
        return
    await scan_and_store_for_user(admin["id"])


async def intraday_watch_job() -> None:
    settings = get_settings()
    try:
        await enqueue_watch_jobs("intraday", interval_minutes=5)
        await process_watch_jobs(
            "intraday",
            run_intraday_watch_credentials,
            batch_size=max(1, int(settings.watch_worker_batch_size)),
            worker_id="scheduler:intraday",
        )
        return
    except RuntimeError:
        logger.exception("Queued intraday watcher failed. Falling back to direct execution.")

    credentials_rows = await list_enabled_broker_credentials()
    for credentials in credentials_rows:
        try:
            await run_intraday_watch_credentials(credentials)
        except Exception as exc:
            logger.exception("Intraday watcher failed: user_id=%s account_id=%s", credentials.get("user_id"), credentials.get("id"))


async def realtime_position_watch_job() -> None:
    settings = get_settings()
    try:
        await enqueue_watch_jobs("realtime_position", interval_minutes=1)
        await process_watch_jobs(
            "realtime_position",
            run_realtime_position_watch_credentials,
            batch_size=max(1, int(settings.realtime_watch_worker_batch_size)),
            worker_id="scheduler:realtime_position",
        )
        return
    except RuntimeError:
        logger.exception("Queued realtime position watcher failed. Falling back to direct execution.")

    credentials_rows = await list_enabled_broker_credentials()
    for credentials in credentials_rows:
        try:
            await run_realtime_position_watch_credentials(credentials)
        except Exception as exc:
            logger.exception("Realtime position watcher failed: user_id=%s account_id=%s", credentials.get("user_id"), credentials.get("id"))


async def run_intraday_watch_credentials(credentials: dict) -> dict:
    try:
        return await run_watch_tick_for_user(credentials, test_mode=False, dry_run=False)
    except Exception as exc:
        await notify_watcher_failure(credentials, "5분 와쳐", exc)
        raise


async def run_realtime_position_watch_credentials(credentials: dict) -> dict:
    try:
        return await run_realtime_position_watch_for_user(credentials, dry_run=False)
    except Exception as exc:
        await notify_watcher_failure(credentials, "1분 포지션 감시", exc)
        raise


async def notify_watcher_failure(credentials: dict, job_name: str, exc: Exception) -> None:
    message = "\n".join(
        [
            "KOSPI Swing Bot 오류",
            f"작업: {job_name}",
            f"계좌: {credentials.get('mode') or 'paper'} {credentials.get('kis_account_no')}-{credentials.get('kis_account_product_code') or '01'}",
            f"오류: {str(exc)[:500]}",
            "포지션과 미체결 주문을 확인하세요.",
        ]
    )
    try:
        await send_telegram_message_with_bot(credentials.get("telegram_bot_token"), credentials.get("telegram_chat_id"), message)
    except Exception:
        logger.exception("Failed to send watcher failure telegram: user_id=%s account_id=%s", credentials.get("user_id"), credentials.get("id"))


async def ai_report_worker_job() -> None:
    results = await process_queued_ai_reports(limit=1)
    for result in results:
        logger.warning("AI report worker result: %s", result)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    settings = get_settings()
    timezone = ZoneInfo(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(daily_scan_job, "cron", day_of_week="mon-fri", hour=13, minute=30)
    scheduler.add_job(intraday_watch_job, "cron", day_of_week="mon-fri", hour="9-15", minute="*/5", max_instances=1, coalesce=True)
    scheduler.add_job(
        realtime_position_watch_job,
        "cron",
        day_of_week="mon-fri",
        hour="9-15",
        minute="*",
        max_instances=1,
        coalesce=True,
    )
    if settings.ai_report_worker_enabled:
        scheduler.add_job(
            ai_report_worker_job,
            "interval",
            minutes=max(1, int(settings.ai_report_worker_interval_minutes)),
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    _scheduler = scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
