from __future__ import annotations

import httpx

from app.core.config import get_settings


async def send_telegram_message(chat_id: str | None, text: str) -> bool:
    settings = get_settings()
    effective_chat_id = settings.telegram_chat_id or chat_id
    return await send_telegram_message_with_bot(settings.telegram_bot_token, effective_chat_id, text)


async def send_telegram_message_with_bot(bot_token: str | None, chat_id: str | None, text: str) -> bool:
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False
