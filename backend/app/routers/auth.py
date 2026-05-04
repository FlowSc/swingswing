from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, get_current_user
from app.services.memberships import ensure_user_membership, get_entitlements
from app.services.supabase_rest import SupabaseRest


router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=6)


@router.post("/signup")
async def signup(payload: SignupRequest) -> dict:
    try:
        result = await SupabaseRest().create_auth_user(payload.email, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await ensure_user_membership(result["id"], payload.email)

    return {
        "ok": True,
        "user_id": result.get("id"),
        "email": payload.email,
        "message": "Signup completed.",
    }


@router.get("/me/entitlements")
async def me_entitlements(user: CurrentUser = Depends(get_current_user)) -> dict:
    return await get_entitlements(user.id, user.email)
