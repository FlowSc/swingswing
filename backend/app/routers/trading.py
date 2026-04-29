from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.services.broker_credentials import get_broker_credentials
from app.services.backtest import run_shared_signal_backtest
from app.services.supabase_rest import SupabaseRest


router = APIRouter(tags=["trading"])


@router.get("/signals/today")
async def today_signals(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    return await signals_by_date(today, user)


@router.get("/signals")
async def signals_by_date(
    trade_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    return await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{trade_date}"},
        order="score.desc",
    )


@router.get("/signals/dates")
async def signal_dates(user: CurrentUser = Depends(get_current_user)) -> list[str]:
    rows = await SupabaseRest().select(
        "shared_signals",
        columns="trade_date",
        order="trade_date.desc",
        limit=30,
    )
    seen = set()
    dates: list[str] = []
    for row in rows:
        value = row.get("trade_date")
        if value and value not in seen:
            seen.add(value)
            dates.append(value)
    return dates


@router.get("/positions")
async def positions(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    credentials = await get_broker_credentials(user.id)
    filters = {"user_id": f"eq.{user.id}"}
    or_filter = None
    if credentials and credentials.get("id"):
        if (credentials.get("mode") or "paper") == "paper":
            or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
        else:
            filters["broker_account_id"] = f"eq.{credentials['id']}"
    return await SupabaseRest().select(
        "positions",
        filters=filters,
        or_filter=or_filter,
        order="created_at.desc",
    )


@router.get("/trade-logs")
async def trade_logs(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    credentials = await get_broker_credentials(user.id)
    filters = {"user_id": f"eq.{user.id}"}
    or_filter = None
    if credentials and credentials.get("id"):
        if (credentials.get("mode") or "paper") == "paper":
            or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
        else:
            filters["broker_account_id"] = f"eq.{credentials['id']}"
    return await SupabaseRest().select(
        "trade_logs",
        filters=filters,
        or_filter=or_filter,
        order="created_at.desc",
        limit=100,
    )


@router.get("/trade-decisions")
async def trade_decisions(
    trade_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    credentials = await get_broker_credentials(user.id)
    target_date = trade_date or datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    filters = {"user_id": f"eq.{user.id}", "decision_date": f"eq.{target_date}"}
    or_filter = None
    if credentials and credentials.get("id"):
        if (credentials.get("mode") or "paper") == "paper":
            or_filter = f"(broker_account_id.eq.{credentials['id']},broker_account_id.is.null)"
        else:
            filters["broker_account_id"] = f"eq.{credentials['id']}"
    return await SupabaseRest().select(
        "trade_decision_logs",
        filters=filters,
        or_filter=or_filter,
        order="created_at.desc",
        limit=200,
    )


@router.get("/dashboard/daily")
async def daily_dashboard(user: CurrentUser = Depends(get_current_user)) -> dict:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    start_at = datetime.combine(today, datetime.min.time(), tzinfo=ZoneInfo(settings.timezone)).isoformat()
    credentials = await get_broker_credentials(user.id)
    account_id = credentials.get("id") if credentials else None
    account_mode = (credentials.get("mode") or "paper") if credentials else "paper"
    position_filters = {"user_id": f"eq.{user.id}"}
    log_filters = {"user_id": f"eq.{user.id}", "created_at": f"gte.{start_at}"}
    decision_filters = {"user_id": f"eq.{user.id}", "decision_date": f"eq.{today.isoformat()}"}
    position_or_filter = None
    log_or_filter = None
    decision_or_filter = None
    if account_id:
        if account_mode == "paper":
            position_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
            log_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
            decision_or_filter = f"(broker_account_id.eq.{account_id},broker_account_id.is.null)"
        else:
            position_filters["broker_account_id"] = f"eq.{account_id}"
            log_filters["broker_account_id"] = f"eq.{account_id}"
            decision_filters["broker_account_id"] = f"eq.{account_id}"

    rest = SupabaseRest()
    signals = await rest.select("shared_signals", filters={"trade_date": f"eq.{today.isoformat()}"}, limit=100)
    positions = await rest.select("positions", filters=position_filters, or_filter=position_or_filter, limit=200)
    logs = await rest.select("trade_logs", filters=log_filters, or_filter=log_or_filter, limit=200)
    decisions = await rest.select("trade_decision_logs", filters=decision_filters, or_filter=decision_or_filter, limit=300)
    scans = await rest.select("scan_runs", order="created_at.desc", limit=1)
    return {
        "date": today.isoformat(),
        "signals_count": len(signals),
        "open_positions": len([row for row in positions if row.get("status") == "OPEN"]),
        "buy_count": len([row for row in logs if row.get("action") == "BUY"]),
        "sell_count": len([row for row in logs if row.get("action") == "SELL"]),
        "skip_count": len([row for row in decisions if row.get("decision") == "SKIP"]),
        "latest_scan": scans[0] if scans else None,
        "top_skip_reasons": summarize_reasons(decisions),
    }


@router.get("/backtest/shared-signals")
async def backtest_shared_signals(
    days: int = Query(120, ge=30, le=730),
    max_signals: int = Query(200, ge=10, le=1000),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    if (user.email or "").lower() != get_settings().scan_admin_email.lower():
        raise HTTPException(status_code=403, detail="Backtest is available to admin only.")
    return await run_shared_signal_backtest(days=days, max_signals=max_signals)


def summarize_reasons(rows: list[dict]) -> list[dict]:
    counts: dict[str, dict] = {}
    for row in rows:
        key = row.get("reason_code") or "Unknown"
        item = counts.setdefault(key, {"reason_code": key, "reason": row.get("reason") or key, "count": 0})
        item["count"] += 1
    return sorted(counts.values(), key=lambda item: item["count"], reverse=True)[:5]
