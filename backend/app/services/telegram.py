from __future__ import annotations

import httpx

from app.core.config import get_settings


async def send_telegram_message(chat_id: str | None, text: str) -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(url, json=payload)
    response.raise_for_status()
    return True
