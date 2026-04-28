from __future__ import annotations

from fastapi import HTTPException

from app.core.security import decrypt_secret, encrypt_secret
from app.schemas.broker import BrokerCredentialIn
from app.services.supabase_rest import SupabaseRest


TABLE = "broker_credentials"


async def save_broker_credentials(user_id: str, payload: BrokerCredentialIn) -> dict:
    record = {
        "user_id": user_id,
        "kis_app_key_enc": encrypt_secret(payload.kis_app_key),
        "kis_app_secret_enc": encrypt_secret(payload.kis_app_secret),
        "kis_account_no": payload.kis_account_no,
        "kis_account_product_code": payload.kis_account_product_code,
        "mode": payload.mode,
        "telegram_chat_id": payload.telegram_chat_id,
        "enabled": True,
    }
    rows = await SupabaseRest().upsert(TABLE, record, on_conflict="user_id")
    return rows[0]


async def get_broker_credentials(user_id: str) -> dict | None:
    rows = await SupabaseRest().select(TABLE, filters={"user_id": f"eq.{user_id}"}, limit=1)
    return rows[0] if rows else None


async def get_decrypted_broker_credentials(user_id: str) -> dict:
    row = await get_broker_credentials(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return {
        **row,
        "kis_app_key": decrypt_secret(row["kis_app_key_enc"]),
        "kis_app_secret": decrypt_secret(row["kis_app_secret_enc"]),
    }


async def list_enabled_broker_credentials() -> list[dict]:
    rows = await SupabaseRest().select(TABLE, filters={"enabled": "eq.true"})
    return [
        {
            **row,
            "kis_app_key": decrypt_secret(row["kis_app_key_enc"]),
            "kis_app_secret": decrypt_secret(row["kis_app_secret_enc"]),
        }
        for row in rows
    ]


async def set_bot_enabled(user_id: str, enabled: bool) -> dict:
    rows = await SupabaseRest().patch(
        TABLE,
        filters={"user_id": f"eq.{user_id}"},
        payload={"enabled": enabled},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return rows[0]
