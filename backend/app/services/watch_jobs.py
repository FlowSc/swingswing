from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.broker_credentials import (
    get_decrypted_broker_credentials_by_account_id,
    list_enabled_broker_accounts_for_watch,
)
from app.services.supabase_rest import SupabaseRest


logger = logging.getLogger(__name__)
WATCH_JOBS_TABLE = "watch_jobs"
JOB_PENDING = "pending"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_SKIPPED = "skipped"


def now_kst() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def scheduled_bucket(dt: datetime, interval_minutes: int) -> datetime:
    minute = (dt.minute // interval_minutes) * interval_minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


async def enqueue_watch_jobs(job_type: str, *, interval_minutes: int) -> dict:
    scheduled_for = scheduled_bucket(now_kst(), interval_minutes)
    accounts = await list_enabled_broker_accounts_for_watch()
    open_position_account_ids = await account_ids_with_open_positions() if job_type == "realtime_position" else None
    rest = SupabaseRest()
    queued = 0
    for account in accounts:
        account_id = account.get("id")
        user_id = account.get("user_id")
        if not account_id or not user_id:
            continue
        if open_position_account_ids is not None and str(account_id) not in open_position_account_ids:
            continue
        await rest.upsert(
            WATCH_JOBS_TABLE,
            {
                "job_type": job_type,
                "user_id": user_id,
                "broker_account_id": account_id,
                "status": JOB_PENDING,
                "scheduled_for": scheduled_for.isoformat(),
                "run_after": scheduled_for.isoformat(),
                "attempts": 0,
                "locked_by": None,
                "locked_until": None,
                "started_at": None,
                "finished_at": None,
                "error": None,
                "result": {},
            },
            on_conflict="job_type,broker_account_id,scheduled_for",
        )
        queued += 1
    return {
        "job_type": job_type,
        "scheduled_for": scheduled_for.isoformat(),
        "queued": queued,
    }


async def account_ids_with_open_positions() -> set[str]:
    rows = await SupabaseRest().select(
        "positions",
        columns="broker_account_id",
        filters={"status": "eq.OPEN"},
        limit=10000,
    )
    return {str(row["broker_account_id"]) for row in rows if row.get("broker_account_id")}


async def reset_stale_running_jobs(job_type: str, *, older_than_minutes: int = 15) -> int:
    cutoff = now_kst() - timedelta(minutes=older_than_minutes)
    rows = await SupabaseRest().patch(
        WATCH_JOBS_TABLE,
        filters={
            "job_type": f"eq.{job_type}",
            "status": f"eq.{JOB_RUNNING}",
            "locked_until": f"lt.{cutoff.isoformat()}",
        },
        payload={
            "status": JOB_PENDING,
            "locked_by": None,
            "locked_until": None,
            "error": "Stale running job was reset.",
        },
    )
    return len(rows)


async def process_watch_jobs(
    job_type: str,
    runner: Callable[[dict], Awaitable[dict]],
    *,
    batch_size: int,
    worker_id: str,
) -> list[dict]:
    await reset_stale_running_jobs(job_type)
    due = await SupabaseRest().select(
        WATCH_JOBS_TABLE,
        filters={
            "job_type": f"eq.{job_type}",
            "status": f"eq.{JOB_PENDING}",
            "run_after": f"lte.{now_kst().isoformat()}",
        },
        order="scheduled_for.asc,created_at.asc",
        limit=max(1, batch_size),
    )
    results: list[dict] = []
    for row in due:
        claimed = await claim_watch_job(row, worker_id)
        if not claimed:
            continue
        results.append(await process_claimed_job(claimed, runner))
    return results


async def claim_watch_job(row: dict, worker_id: str) -> dict | None:
    job_id = row.get("id")
    if not job_id:
        return None
    started_at = now_kst()
    claimed = await SupabaseRest().patch(
        WATCH_JOBS_TABLE,
        filters={"id": f"eq.{job_id}", "status": f"eq.{JOB_PENDING}"},
        payload={
            "status": JOB_RUNNING,
            "attempts": int(row.get("attempts") or 0) + 1,
            "locked_by": worker_id,
            "locked_until": (started_at + timedelta(minutes=10)).isoformat(),
            "started_at": started_at.isoformat(),
            "error": None,
        },
    )
    return claimed[0] if claimed else None


async def process_claimed_job(row: dict, runner: Callable[[dict], Awaitable[dict]]) -> dict:
    job_id = row["id"]
    account_id = row.get("broker_account_id")
    if not account_id:
        await finish_watch_job(job_id, JOB_SKIPPED, {"skip_reason": "missing_broker_account_id"})
        return {"id": job_id, "status": JOB_SKIPPED, "skip_reason": "missing_broker_account_id"}

    credentials = await get_decrypted_broker_credentials_by_account_id(str(account_id))
    if not credentials:
        await finish_watch_job(job_id, JOB_SKIPPED, {"skip_reason": "broker_account_disabled_or_missing"})
        return {"id": job_id, "status": JOB_SKIPPED, "skip_reason": "broker_account_disabled_or_missing"}

    try:
        result = await runner(credentials)
        await finish_watch_job(job_id, JOB_COMPLETED, result)
        return {"id": job_id, "status": JOB_COMPLETED, "result": result}
    except Exception as exc:
        logger.exception("Watch job failed: id=%s type=%s account_id=%s", job_id, row.get("job_type"), account_id)
        await SupabaseRest().patch(
            WATCH_JOBS_TABLE,
            filters={"id": f"eq.{job_id}"},
            payload={
                "status": JOB_FAILED,
                "error": str(exc)[:1000],
                "locked_by": None,
                "locked_until": None,
                "finished_at": now_kst().isoformat(),
            },
        )
        return {"id": job_id, "status": JOB_FAILED, "error": str(exc)}


async def finish_watch_job(job_id: int, status: str, result: dict) -> None:
    await SupabaseRest().patch(
        WATCH_JOBS_TABLE,
        filters={"id": f"eq.{job_id}"},
        payload={
            "status": status,
            "result": clean_json(result),
            "locked_by": None,
            "locked_until": None,
            "finished_at": now_kst().isoformat(),
        },
    )


def clean_json(value):
    if isinstance(value, dict):
        return {key: clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        try:
            return clean_json(value.item())
        except Exception:
            pass
    return value
