from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.supabase_rest import SupabaseRest


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None
    access_token: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        payload = await SupabaseRest().get_user(credentials.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Supabase token") from exc

    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid Supabase user")

    return CurrentUser(
        id=user_id,
        email=payload.get("email"),
        access_token=credentials.credentials,
    )
