from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.broker_credentials import get_broker_credentials
from app.services.scanner import scan_and_store_for_user
from app.services.supabase_rest import SupabaseRest


logger = logging.getLogger(__name__)
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _now_iso() -> str:
    return datetime.now(ZoneInfo(get_settings().timezone)).isoformat()


def scan_worker_status() -> dict:
    return {
        "task_exists": _worker_task is not None,
        "running": _worker_task is not None and not _worker_task.done(),
        "done": _worker_task.done() if _worker_task else None,
        "cancelled": _worker_task.cancelled() if _worker_task else None,
        "exception": str(_worker_task.exception()) if _worker_task and _worker_task.done() and not _worker_task.cancelled() else None,
    }


async def queue_admin_scan() -> dict:
    settings = get_settings()
    logger.warning("Queueing admin signal scan: admin_email=%s", settings.scan_admin_email)
    admin = await SupabaseRest().find_user_by_email(settings.scan_admin_email)
    if not admin:
        raise RuntimeError(f"Scan admin not found: {settings.scan_admin_email}")
    rows = await SupabaseRest().insert(
        "scan_runs",
        {"requested_by": admin["id"], "status": "queued"},
    )
    logger.warning("Queued signal scan: scan_run_id=%s user_id=%s", rows[0]["id"], admin["id"])
    return rows[0]


async def reset_stale_running_scans() -> None:
    logger.warning("Scan worker resetting stale running scans")
    await SupabaseRest().patch(
        "scan_runs",
        filters={"status": "eq.running"},
        payload={"status": "queued", "error": "Recovered after worker restart"},
    )


async def _claim_next_scan() -> dict | None:
    rest = SupabaseRest()
    rows = await rest.select(
        "scan_runs",
        filters={"status": "eq.queued"},
        order="created_at.asc",
        limit=1,
    )
    if not rows:
        return None
    scan_run = rows[0]
    logger.warning("Scan worker claiming queued scan: scan_run_id=%s", scan_run["id"])
    patched = await rest.patch(
        "scan_runs",
        filters={"id": f"eq.{scan_run['id']}", "status": "eq.queued"},
        payload={"status": "running", "error": None, "started_at": _now_iso()},
    )
    if not patched:
        logger.warning("Scan worker claim lost race: scan_run_id=%s", scan_run["id"])
    return patched[0] if patched else None


async def _process_scan(scan_run: dict) -> None:
    rest = SupabaseRest()
    scan_run_id = scan_run["id"]
    user_id = scan_run["requested_by"]
    try:
        credentials = await get_broker_credentials(user_id)
        telegram_chat_id = credentials.get("telegram_chat_id") if credentials else None
        logger.warning("Signal scan started: scan_run_id=%s user_id=%s", scan_run_id, user_id)
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
                "finished_at": _now_iso(),
            },
        )
        logger.warning("Signal scan completed: %s", result)
    except Exception as exc:
        await rest.patch(
            "scan_runs",
            filters={"id": f"eq.{scan_run_id}"},
            payload={"status": "failed", "error": str(exc)[:2000], "finished_at": _now_iso()},
        )
        logger.exception("Signal scan failed")


async def _worker_loop(stop_event: asyncio.Event) -> None:
    logger.warning("Scan worker loop started")
    await reset_stale_running_scans()
    while not stop_event.is_set():
        scan_run = await _claim_next_scan()
        if scan_run:
            await _process_scan(scan_run)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


def start_scan_worker() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        logger.warning("Scan worker already running")
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(_stop_event))
    _worker_task.add_done_callback(_log_worker_done)
    logger.warning("Scan worker task created")


def _log_worker_done(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.warning("Scan worker task cancelled")
        return
    error = task.exception()
    if error:
        logger.exception("Scan worker task crashed", exc_info=error)
    else:
        logger.warning("Scan worker task stopped")


async def stop_scan_worker() -> None:
    global _worker_task, _stop_event
    if _stop_event:
        logger.warning("Stopping scan worker")
        _stop_event.set()
    if _worker_task:
        await _worker_task
    _worker_task = None
    _stop_event = None
