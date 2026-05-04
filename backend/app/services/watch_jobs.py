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
RETRYABLE_ERROR_MARKERS = (
    "EGW00201",
    "접근토큰 발급 잠시 후 다시 시도",
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectError",
    "RemoteProtocolError",
    "HTTP error 500",
    "HTTP error 502",
    "HTTP error 503",
    "HTTP error 504",
    "Server Error",
    "temporarily unavailable",
)
NON_RETRYABLE_ERROR_MARKERS = (
    "Broker credentials not configured",
    "broker_account_disabled_or_missing",
    "실전투자는 유료회원",
    "APBK0952",
    "주문가능금액을 초과",
    "모의투자 계좌번호",
    "계좌번호",
)


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
        return await handle_failed_job(row, exc)


async def handle_failed_job(row: dict, exc: Exception) -> dict:
    job_id = row["id"]
    error = str(exc)
    attempts = int(row.get("attempts") or 1)
    max_attempts = max(1, int(get_settings().watch_job_max_attempts))
    if is_retryable_error(error) and attempts < max_attempts:
        delay_seconds = min(900, 60 * (2 ** max(0, attempts - 1)))
        run_after = now_kst() + timedelta(seconds=delay_seconds)
        await SupabaseRest().patch(
            WATCH_JOBS_TABLE,
            filters={"id": f"eq.{job_id}"},
            payload={
                "status": JOB_PENDING,
                "run_after": run_after.isoformat(),
                "error": f"Retry scheduled after {delay_seconds}s: {error[:900]}",
                "locked_by": None,
                "locked_until": None,
                "finished_at": None,
            },
        )
        return {
            "id": job_id,
            "status": JOB_PENDING,
            "retry": True,
            "attempts": attempts,
            "run_after": run_after.isoformat(),
            "error": error,
        }

    final_status = JOB_SKIPPED if is_non_retryable_error(error) else JOB_FAILED
    await SupabaseRest().patch(
        WATCH_JOBS_TABLE,
        filters={"id": f"eq.{job_id}"},
        payload={
            "status": final_status,
            "error": error[:1000],
            "locked_by": None,
            "locked_until": None,
            "finished_at": now_kst().isoformat(),
        },
    )
    return {"id": job_id, "status": final_status, "retry": False, "attempts": attempts, "error": error}


def is_retryable_error(error: str) -> bool:
    if is_non_retryable_error(error):
        return False
    return any(marker in error for marker in RETRYABLE_ERROR_MARKERS)


def is_non_retryable_error(error: str) -> bool:
    return any(marker in error for marker in NON_RETRYABLE_ERROR_MARKERS)


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


async def get_watch_job_overview(limit: int = 200) -> dict:
    rows = await SupabaseRest().select(
        WATCH_JOBS_TABLE,
        order="created_at.desc",
        limit=max(1, min(limit, 1000)),
    )
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    failure_counts: dict[str, dict] = {}
    now = now_kst()
    oldest_pending_seconds: int | None = None
    running_overdue = 0
    for row in rows:
        status = row.get("status") or "unknown"
        job_type = row.get("job_type") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        type_counts[job_type] = type_counts.get(job_type, 0) + 1
        if status == JOB_PENDING:
            age = seconds_since(row.get("created_at"), now)
            if age is not None:
                oldest_pending_seconds = age if oldest_pending_seconds is None else max(oldest_pending_seconds, age)
        if status == JOB_RUNNING and is_locked_overdue(row.get("locked_until"), now):
            running_overdue += 1
        if status in {JOB_FAILED, JOB_SKIPPED}:
            key = normalize_error_key(row.get("error") or status)
            item = failure_counts.setdefault(key, {"reason": key, "count": 0})
            item["count"] += 1
    return {
        "status_counts": status_counts,
        "type_counts": type_counts,
        "oldest_pending_seconds": oldest_pending_seconds,
        "running_overdue": running_overdue,
        "failures": sorted(failure_counts.values(), key=lambda item: item["count"], reverse=True)[:8],
        "jobs": rows,
    }


async def retry_failed_watch_jobs(job_type: str | None = None) -> dict:
    filters = {"status": f"eq.{JOB_FAILED}"}
    if job_type:
        filters["job_type"] = f"eq.{job_type}"
    rows = await SupabaseRest().patch(
        WATCH_JOBS_TABLE,
        filters=filters,
        payload={
            "status": JOB_PENDING,
            "run_after": now_kst().isoformat(),
            "locked_by": None,
            "locked_until": None,
            "error": "Manually retried by super admin.",
            "finished_at": None,
        },
    )
    return {"retried": len(rows), "job_type": job_type or "all"}


def parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=ZoneInfo(get_settings().timezone))
        return parsed.astimezone(ZoneInfo(get_settings().timezone))
    except ValueError:
        return None


def seconds_since(value: object, now: datetime) -> int | None:
    parsed = parse_dt(value)
    if not parsed:
        return None
    return max(0, int((now - parsed).total_seconds()))


def is_locked_overdue(value: object, now: datetime) -> bool:
    parsed = parse_dt(value)
    return bool(parsed and parsed < now)


def normalize_error_key(error: str) -> str:
    text = str(error or "").strip()
    if not text:
        return "Unknown"
    for marker in (*NON_RETRYABLE_ERROR_MARKERS, *RETRYABLE_ERROR_MARKERS):
        if marker in text:
            return marker
    return text[:80]
