from fastapi import APIRouter, Depends
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.auth import CurrentUser, get_current_user
from app.core.config import get_settings
from app.services.supabase_rest import SupabaseRest


router = APIRouter(tags=["trading"])


@router.get("/signals/today")
async def today_signals(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    today = datetime.now(ZoneInfo(get_settings().timezone)).date().isoformat()
    return await SupabaseRest().select(
        "signals",
        filters={"user_id": f"eq.{user.id}", "trade_date": f"eq.{today}"},
        order="score.desc",
    )


@router.get("/positions")
async def positions(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return await SupabaseRest().select(
        "positions",
        filters={"user_id": f"eq.{user.id}"},
        order="created_at.desc",
    )


@router.get("/trade-logs")
async def trade_logs(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return await SupabaseRest().select(
        "trade_logs",
        filters={"user_id": f"eq.{user.id}"},
        order="created_at.desc",
        limit=100,
    )
