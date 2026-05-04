from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.config import get_settings
from app.services.supabase_rest import SupabaseRest


TABLE = "user_memberships"
ROLES = {"admin", "free", "paid"}


def _now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def _is_admin_email(email: str | None) -> bool:
    return (email or "").lower() == get_settings().scan_admin_email.lower()


def _normalize_role(role: str | None) -> str:
    value = (role or "free").lower()
    return value if value in ROLES else "free"


def _paid_active(row: dict | None) -> bool:
    if not row:
        return False
    paid_until = row.get("paid_until")
    if not paid_until:
        return False
    try:
        expires_at = datetime.fromisoformat(str(paid_until).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=ZoneInfo(get_settings().timezone))
        return expires_at > _now()
    except (TypeError, ValueError):
        return False


def build_entitlements(user_id: str, email: str | None, row: dict | None) -> dict:
    role = "admin" if _is_admin_email(email) else _normalize_role(row.get("role") if row else None)
    if role == "paid" and not _paid_active(row):
        role = "free"

    can_use_reports = role == "admin" or bool(row and row.get("report_enabled") and role == "paid")
    return {
        "user_id": user_id,
        "email": email,
        "role": role,
        "paid_until": row.get("paid_until") if row else None,
        "report_enabled": bool(row.get("report_enabled")) if row else False,
        "can_use_paper_trading": True,
        "can_use_live_trading": role in {"admin", "paid"},
        "can_use_reports": can_use_reports,
        "can_run_admin_scan": role == "admin",
        "can_run_backtest": role == "admin",
    }


async def ensure_user_membership(user_id: str, email: str | None = None) -> dict:
    role = "admin" if _is_admin_email(email) else "free"
    rows = await SupabaseRest().upsert(
        TABLE,
        {
            "user_id": user_id,
            "role": role,
            "report_enabled": role == "admin",
        },
        on_conflict="user_id",
    )
    return rows[0]


async def get_membership_row(user_id: str) -> dict | None:
    try:
        rows = await SupabaseRest().select(TABLE, filters={"user_id": f"eq.{user_id}"}, limit=1)
    except RuntimeError:
        # Deployments may briefly run before the SQL migration is applied.
        return None
    return rows[0] if rows else None


async def get_entitlements(user_id: str, email: str | None) -> dict:
    row = await get_membership_row(user_id)
    if not row:
        try:
            row = await ensure_user_membership(user_id, email)
        except RuntimeError:
            row = None
    elif _is_admin_email(email) and row.get("role") != "admin":
        try:
            rows = await SupabaseRest().patch(
                TABLE,
                filters={"user_id": f"eq.{user_id}"},
                payload={"role": "admin", "report_enabled": True},
            )
            row = rows[0] if rows else row
        except RuntimeError:
            pass
    return build_entitlements(user_id, email, row)


async def require_live_trading_access(user_id: str, email: str | None) -> dict:
    entitlements = await get_entitlements(user_id, email)
    if not entitlements["can_use_live_trading"]:
        raise HTTPException(status_code=403, detail="실전투자는 유료회원 또는 관리자만 사용할 수 있습니다.")
    return entitlements


async def can_use_live_trading_for_user_id(user_id: str) -> bool:
    row = await get_membership_row(user_id)
    if not row:
        return False
    role = _normalize_role(row.get("role"))
    if role == "admin":
        return True
    return role == "paid" and _paid_active(row)


async def require_report_access(user_id: str, email: str | None) -> dict:
    entitlements = await get_entitlements(user_id, email)
    if not entitlements["can_use_reports"]:
        raise HTTPException(status_code=403, detail="리포트 기능은 관리자만 사용할 수 있습니다.")
    return entitlements


async def require_admin_access(user_id: str, email: str | None) -> dict:
    entitlements = await get_entitlements(user_id, email)
    if not entitlements["can_run_admin_scan"]:
        raise HTTPException(status_code=403, detail="관리자만 실행할 수 있습니다.")
    return entitlements
