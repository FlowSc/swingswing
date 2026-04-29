from __future__ import annotations

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.security import decrypt_secret, encrypt_secret
from app.schemas.broker import BrokerCredentialIn
from app.services.supabase_rest import SupabaseRest


TABLE = "broker_credentials"
ACCOUNTS_TABLE = "broker_accounts"


def _public_account(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "user_id": row["user_id"],
        "label": row.get("label"),
        "kis_account_no": row["kis_account_no"],
        "kis_account_product_code": row.get("kis_account_product_code") or "01",
        "mode": row.get("mode") or "paper",
        "telegram_chat_id": row.get("telegram_chat_id"),
        "enabled": row.get("enabled", False),
        "live_order_enabled": row.get("live_order_enabled", False),
        "is_active": row.get("is_active", False),
    }


def _decrypt_account(row: dict) -> dict:
    return {
        **row,
        "kis_app_key": decrypt_secret(row["kis_app_key_enc"]),
        "kis_app_secret": decrypt_secret(row["kis_app_secret_enc"]),
    }


async def save_broker_credentials(user_id: str, payload: BrokerCredentialIn) -> dict:
    settings = get_settings()
    label = "실전투자" if payload.mode == "live" else "모의투자"
    record = {
        "user_id": user_id,
        "label": label,
        "kis_app_key_enc": encrypt_secret(payload.kis_app_key),
        "kis_app_secret_enc": encrypt_secret(payload.kis_app_secret),
        "kis_account_no": payload.kis_account_no,
        "kis_account_product_code": payload.kis_account_product_code,
        "mode": payload.mode,
        "telegram_chat_id": settings.telegram_chat_id,
        "live_order_enabled": payload.live_order_enabled if payload.mode == "live" else False,
        "enabled": True,
        "is_active": True,
    }
    rest = SupabaseRest()
    await rest.patch(ACCOUNTS_TABLE, filters={"user_id": f"eq.{user_id}"}, payload={"is_active": False})
    rows = await rest.upsert(ACCOUNTS_TABLE, record, on_conflict="user_id,mode")
    return _public_account(rows[0])


async def list_broker_accounts(user_id: str) -> list[dict]:
    rows = await SupabaseRest().select(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}"},
        order="mode.desc",
    )
    return [_public_account(row) for row in rows]


async def set_active_broker_account(user_id: str, account_id: str) -> dict:
    rest = SupabaseRest()
    rows = await rest.select(
        ACCOUNTS_TABLE,
        filters={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Broker account not found")
    await rest.patch(ACCOUNTS_TABLE, filters={"user_id": f"eq.{user_id}"}, payload={"is_active": False})
    activated = await rest.patch(
        ACCOUNTS_TABLE,
        filters={"id": f"eq.{account_id}", "user_id": f"eq.{user_id}"},
        payload={"is_active": True},
    )
    if not activated:
        raise HTTPException(status_code=404, detail="Broker account not found")
    return _public_account(activated[0])


async def get_broker_credentials(user_id: str) -> dict | None:
    rest = SupabaseRest()
    rows = await rest.select(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}", "is_active": "eq.true"},
        limit=1,
    )
    if rows:
        return rows[0]

    rows = await rest.select(ACCOUNTS_TABLE, filters={"user_id": f"eq.{user_id}"}, limit=1)
    if rows:
        return rows[0]

    legacy_rows = await rest.select(TABLE, filters={"user_id": f"eq.{user_id}"}, limit=1)
    return legacy_rows[0] if legacy_rows else None


async def get_decrypted_broker_credentials(user_id: str) -> dict:
    row = await get_broker_credentials(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return _decrypt_account(row)


async def list_enabled_broker_credentials() -> list[dict]:
    rest = SupabaseRest()
    rows = await rest.select(ACCOUNTS_TABLE, filters={"enabled": "eq.true", "is_active": "eq.true"})
    if rows:
        return [_decrypt_account(row) for row in rows]
    legacy_rows = await rest.select(TABLE, filters={"enabled": "eq.true"})
    return [_decrypt_account(row) for row in legacy_rows]


async def set_bot_enabled(user_id: str, enabled: bool) -> dict:
    rest = SupabaseRest()
    rows = await rest.patch(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}", "is_active": "eq.true"},
        payload={"enabled": enabled},
    )
    if rows:
        return _public_account(rows[0])
    legacy_rows = await rest.patch(
        TABLE,
        filters={"user_id": f"eq.{user_id}"},
        payload={"enabled": enabled},
    )
    if not legacy_rows:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return legacy_rows[0]
