# ============================================================
#  Telegram notifier for KOSPI swing bot
# ============================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from kis_client import load_env_file
import paper_trader


def telegram_configured() -> bool:
    load_env_file()
    return bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip())


def send_telegram_message(text: str) -> bool:
    load_env_file()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            print(f"telegram HTTP {response.status_code}: {response.text[:1000]}")
            return False
        return True
    except Exception as exc:
        print(f"telegram failed: {exc}")
        return False


def format_money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def send_top5_signals(signal_file: Path | None = None) -> bool:
    if signal_file is None:
        signal_file = paper_trader.latest_signal_file()
    payload = paper_trader.load_json(signal_file, {})
    signals = payload.get("signals", [])[:5]
    date_text = payload.get("date", paper_trader.today_text())

    if not signals:
        return send_telegram_message(f"[KOSPI Swing Bot]\n{date_text}\nNo swing signals found.")

    lines = [f"[KOSPI Swing Bot] Top 5 signals", f"Date: {date_text}", ""]
    for index, item in enumerate(signals, start=1):
        lines.append(
            f"{index}. {item.get('Name')} ({item.get('Code')})\n"
            f"Entry {format_money(item.get('Entry'))} / Stop {format_money(item.get('StopLoss'))} / TP2 {format_money(item.get('TakeProfit2'))}\n"
            f"Score {item.get('Score')} / BBExp {item.get('BBExpansion(%)')} / Cross {item.get('DaysAfterIchimokuCross')}"
        )
    return send_telegram_message("\n".join(lines))


def send_trade_events(log_rows: list[dict]) -> None:
    for row in log_rows:
        send_telegram_message(
            "[KOSPI Swing Bot] Trade event\n"
            f"Action: {row.get('Action')}\n"
            f"Name: {row.get('Name')} ({row.get('Code')})\n"
            f"Price: {format_money(row.get('Price'))}\n"
            f"Qty: {row.get('Qty')}\n"
            f"Reason: {row.get('Reason')}"
        )


def send_status(text: str) -> bool:
    return send_telegram_message(f"[KOSPI Swing Bot]\n{text}")


if __name__ == "__main__":
    send_top5_signals()
