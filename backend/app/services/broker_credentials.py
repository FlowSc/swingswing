from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.core.security import decrypt_secret, encrypt_secret
from app.schemas.broker import BrokerCredentialIn, TelegramSettingsIn
from app.services.memberships import can_use_live_trading_for_user_id
from app.services.supabase_rest import SupabaseRest


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
        "telegram_configured": bool(row.get("telegram_bot_token_enc") and row.get("telegram_chat_id")),
        "enabled": row.get("enabled", False),
        "live_order_enabled": row.get("live_order_enabled", False),
        "is_active": row.get("is_active", False),
    }


def _decrypt_account(row: dict) -> dict:
    decrypted = {
        **row,
        "kis_app_key": decrypt_secret(row["kis_app_key_enc"]),
        "kis_app_secret": decrypt_secret(row["kis_app_secret_enc"]),
    }
    if row.get("access_token_enc"):
        try:
            decrypted["access_token"] = decrypt_secret(row["access_token_enc"])
        except Exception:
            decrypted["access_token"] = None
    if row.get("access_token_expires_at"):
        decrypted["access_token_expires_at"] = row["access_token_expires_at"]
    if row.get("telegram_bot_token_enc"):
        try:
            decrypted["telegram_bot_token"] = decrypt_secret(row["telegram_bot_token_enc"])
        except Exception:
            decrypted["telegram_bot_token"] = None
    return decrypted


async def clear_broker_access_token(account_id: str | None) -> None:
    if not account_id:
        return
    try:
        await SupabaseRest().patch(
            ACCOUNTS_TABLE,
            filters={"id": f"eq.{account_id}"},
            payload={"access_token_enc": None, "access_token_expires_at": None},
        )
    except RuntimeError:
        # The deployment may run before the SQL migration is applied. Do not block credential saves.
        return


async def update_broker_access_token(account_id: str | None, access_token: str, expires_at: datetime) -> bool:
    if not account_id:
        return False
    try:
        await SupabaseRest().patch(
            ACCOUNTS_TABLE,
            filters={"id": f"eq.{account_id}"},
            payload={
                "access_token_enc": encrypt_secret(access_token),
                "access_token_expires_at": expires_at.isoformat(),
            },
        )
        return True
    except RuntimeError:
        return False


async def save_broker_credentials(user_id: str, payload: BrokerCredentialIn) -> dict:
    label = "실전투자" if payload.mode == "live" else "모의투자"
    rest = SupabaseRest()
    existing_rows = await rest.select(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}", "mode": f"eq.{payload.mode}"},
        limit=1,
    )
    existing = existing_rows[0] if existing_rows else {}
    record = {
        "user_id": user_id,
        "label": label,
        "kis_app_key_enc": encrypt_secret(payload.kis_app_key),
        "kis_app_secret_enc": encrypt_secret(payload.kis_app_secret),
        "kis_account_no": payload.kis_account_no,
        "kis_account_product_code": payload.kis_account_product_code,
        "mode": payload.mode,
        "telegram_bot_token_enc": existing.get("telegram_bot_token_enc"),
        "telegram_chat_id": existing.get("telegram_chat_id"),
        "live_order_enabled": payload.live_order_enabled if payload.mode == "live" else False,
        "enabled": True,
        "is_active": True,
    }
    await rest.patch(ACCOUNTS_TABLE, filters={"user_id": f"eq.{user_id}"}, payload={"is_active": False})
    rows = await rest.upsert(ACCOUNTS_TABLE, record, on_conflict="user_id,mode")
    await clear_broker_access_token(rows[0].get("id"))
    return _public_account(rows[0])


async def save_telegram_settings(user_id: str, payload: TelegramSettingsIn) -> dict:
    rest = SupabaseRest()
    rows = await rest.select(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}", "is_active": "eq.true"},
        limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")

    current = rows[0]
    bot_token = (payload.telegram_bot_token or "").strip()
    chat_id = (payload.telegram_chat_id or "").strip()
    update_payload = {
        "telegram_bot_token_enc": encrypt_secret(bot_token) if bot_token else current.get("telegram_bot_token_enc"),
        "telegram_chat_id": chat_id or None,
    }
    updated = await rest.patch(
        ACCOUNTS_TABLE,
        filters={"id": f"eq.{current['id']}", "user_id": f"eq.{user_id}"},
        payload=update_payload,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return _public_account(updated[0])


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

    return None


async def get_decrypted_broker_credentials(user_id: str) -> dict:
    row = await get_broker_credentials(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Broker credentials not configured")
    return _decrypt_account(row)


async def get_decrypted_broker_credentials_by_account_id(account_id: str) -> dict | None:
    rows = await SupabaseRest().select(ACCOUNTS_TABLE, filters={"id": f"eq.{account_id}"}, limit=1)
    if not rows:
        return None
    row = rows[0]
    if not row.get("enabled"):
        return None
    if (row.get("mode") or "paper") == "live" and not await can_use_live_trading_for_user_id(row["user_id"]):
        return None
    return _decrypt_account(row)


async def list_enabled_broker_credentials() -> list[dict]:
    rest = SupabaseRest()
    rows = await rest.select(ACCOUNTS_TABLE, filters={"enabled": "eq.true"})
    if rows:
        credentials: list[dict] = []
        for row in rows:
            if (row.get("mode") or "paper") == "live" and not await can_use_live_trading_for_user_id(row["user_id"]):
                continue
            credentials.append(_decrypt_account(row))
        return credentials
    return []


async def list_enabled_broker_accounts_for_watch() -> list[dict]:
    rows = await SupabaseRest().select(ACCOUNTS_TABLE, filters={"enabled": "eq.true"})
    accounts: list[dict] = []
    for row in rows:
        if (row.get("mode") or "paper") == "live" and not await can_use_live_trading_for_user_id(row["user_id"]):
            continue
        accounts.append(
            {
                "id": row.get("id"),
                "user_id": row.get("user_id"),
                "mode": row.get("mode") or "paper",
            }
        )
    return accounts


async def list_telegram_recipients() -> list[dict]:
    rest = SupabaseRest()
    rows = await rest.select(ACCOUNTS_TABLE, order="created_at.desc")
    recipients: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for row in rows:
        chat_id = row.get("telegram_chat_id")
        token_enc = row.get("telegram_bot_token_enc")
        if not chat_id or not token_enc:
            continue
        try:
            bot_token = decrypt_secret(token_enc)
        except Exception:
            continue
        key = (bot_token, str(chat_id))
        if key in seen:
            continue
        seen.add(key)
        recipients.append(
            {
                "user_id": row.get("user_id"),
                "broker_account_id": row.get("id"),
                "telegram_bot_token": bot_token,
                "telegram_chat_id": str(chat_id),
            }
        )
    return recipients


async def set_bot_enabled(user_id: str, enabled: bool) -> dict:
    rest = SupabaseRest()
    rows = await rest.patch(
        ACCOUNTS_TABLE,
        filters={"user_id": f"eq.{user_id}", "is_active": "eq.true"},
        payload={"enabled": enabled},
    )
    if rows:
        return _public_account(rows[0])
    raise HTTPException(status_code=404, detail="Broker credentials not configured")
