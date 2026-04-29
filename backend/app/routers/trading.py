from fastapi import APIRouter, Depends
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.services.broker_credentials import get_broker_credentials
from app.services.supabase_rest import SupabaseRest


router = APIRouter(tags=["trading"])


@router.get("/signals/today")
async def today_signals(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    return await SupabaseRest().select(
        "shared_signals",
        filters={"trade_date": f"eq.{today}"},
        order="score.desc",
    )


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
