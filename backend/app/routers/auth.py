from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.services.supabase_rest import SupabaseRest


router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=6)
    invite_code: str = Field(min_length=1)


@router.post("/signup")
async def signup(payload: SignupRequest) -> dict:
    settings = get_settings()
    expected_code = settings.signup_invite_code
    if not expected_code:
        raise HTTPException(status_code=403, detail="Signup is currently disabled.")
    if payload.invite_code.strip() != expected_code:
        raise HTTPException(status_code=403, detail="Invalid signup code.")

    try:
        result = await SupabaseRest().create_auth_user(payload.email, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "user_id": result.get("id"),
        "email": payload.email,
        "message": "Signup completed.",
    }
