# ============================================================
#  Telegram configuration test
# ============================================================

from __future__ import annotations

import os

from kis_client import load_env_file
from telegram_notifier import send_telegram_message


def main() -> None:
    load_env_file()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    print("=" * 64)
    print("  Telegram Test")
    print("=" * 64)
    print(f"Token configured: {bool(token)} length={len(token)}")
    print(f"Chat ID configured: {bool(chat_id)} value={chat_id}")

    ok = send_telegram_message("KOSPI Swing Bot telegram test message")
    print(f"Send result: {ok}")


if __name__ == "__main__":
    main()
