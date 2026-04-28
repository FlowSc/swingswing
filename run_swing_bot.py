# ============================================================
#  Unified KOSPI swing bot runner
#  Runs scanner first, then starts KIS intraday watcher.
# ============================================================

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import os
import subprocess
import sys
import time as time_module
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram_notifier import send_status, send_top5_signals, telegram_configured

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except AttributeError:
    pass


ROOT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = ROOT_DIR / "kis_config.local.env"
OUTPUT_DIR = ROOT_DIR / "output"
SEOUL = ZoneInfo("Asia/Seoul")
SCAN_TIME = time(8, 45)
WATCH_START_TIME = time(9, 20)
WATCH_END_TIME = time(15, 20)


def today_signal_file() -> Path:
    return OUTPUT_DIR / f"swing_signals_{datetime.today().strftime('%Y%m%d')}.json"


def run_step(command: list[str], name: str, *, allow_failure: bool = False) -> bool:
    print("=" * 64)
    print(f"  {name}")
    print("=" * 64)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(command, cwd=ROOT_DIR, env=env)
    if result.returncode != 0:
        if allow_failure:
            print(f"{name} failed with exit code {result.returncode}.")
            return False
        raise SystemExit(result.returncode)
    return True


def now_seoul() -> datetime:
    return datetime.now(SEOUL)


def is_weekday(day: datetime) -> bool:
    return day.weekday() < 5


def next_weekday_at(target_time: time) -> datetime:
    current = now_seoul()
    target = current.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=0,
        microsecond=0,
    )
    if current >= target:
        target += timedelta(days=1)
    while not is_weekday(target):
        target += timedelta(days=1)
    return target


def current_or_next_scan_time() -> datetime:
    current = now_seoul()
    today_scan = current.replace(
        hour=SCAN_TIME.hour,
        minute=SCAN_TIME.minute,
        second=0,
        microsecond=0,
    )
    if is_weekday(current) and current.time() <= WATCH_END_TIME:
        return today_scan
    return next_weekday_at(SCAN_TIME)


def sleep_until(target: datetime, label: str) -> None:
    while True:
        current = now_seoul()
        seconds = (target - current).total_seconds()
        if seconds <= 0:
            return
        print(f"Waiting for {label}: {target.strftime('%Y-%m-%d %H:%M:%S %Z')} ({int(seconds)}s)", flush=True)
        time_module.sleep(min(seconds, 300))


def run_scan(python: str) -> None:
    scan_ok = run_step([python, "kospi_swing.py"], "Step 1: Generate swing signals", allow_failure=True)
    if not scan_ok:
        signal_file = today_signal_file()
        if signal_file.exists():
            print(f"Using existing signal file: {signal_file}")
        else:
            rebuilt_ok = run_step(
                [python, "rebuild_signals_from_excel.py"],
                "Fallback: Rebuild signals from latest Excel",
                allow_failure=True,
            )
            if rebuilt_ok and signal_file.exists():
                print(f"Using rebuilt signal file: {signal_file}")
            else:
                print("No signal file for today. Stop before starting watcher.")
                print("Check network access to KRX/FinanceDataReader and run again.")
                raise SystemExit(1)
    if telegram_configured():
        send_top5_signals(today_signal_file())


def run_watcher(python: str, *, interval: int, once: bool = False, test_mode: bool = False, allow_test_orders: bool = False) -> None:
    watcher_command = [python, "kis_intraday_watcher.py", "--interval", str(interval)]
    if once:
        watcher_command.append("--once")
    if test_mode:
        watcher_command.append("--test-mode")
    if allow_test_orders:
        watcher_command.append("--allow-test-orders")

    if telegram_configured():
        send_status("Intraday watcher started.")
    run_step(watcher_command, "Step 2: Start intraday watcher")


def run_daemon(python: str, interval: int) -> None:
    print("=" * 64)
    print("  KOSPI Swing Bot daemon mode")
    print("=" * 64)

    while True:
        scan_at = current_or_next_scan_time()
        if now_seoul() < scan_at:
            sleep_until(scan_at, "daily scan")
        else:
            print("Scan time has passed, running today's scan immediately.", flush=True)
        run_scan(python)

        watch_at = now_seoul().replace(
            hour=WATCH_START_TIME.hour,
            minute=WATCH_START_TIME.minute,
            second=0,
            microsecond=0,
        )
        if now_seoul().time() < WATCH_START_TIME:
            sleep_until(watch_at, "watcher start")

        if now_seoul().time() <= WATCH_END_TIME and is_weekday(now_seoul()):
            run_watcher(python, interval=interval)

        if telegram_configured():
            send_status("Trading day cycle completed. Waiting for next weekday.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run KOSPI swing scanner and KIS paper watcher.")
    parser.add_argument("--scan-only", action="store_true", help="Run only kospi_swing.py.")
    parser.add_argument("--watch-only", action="store_true", help="Run only kis_intraday_watcher.py.")
    parser.add_argument("--once", action="store_true", help="Run one watcher tick and exit.")
    parser.add_argument("--interval", type=int, default=300, help="Watcher interval in seconds.")
    parser.add_argument("--test-mode", action="store_true", help="Ignore market time windows in watcher and avoid orders by default.")
    parser.add_argument("--allow-test-orders", action="store_true", help="Allow KIS paper orders while in test mode.")
    parser.add_argument("--daemon", action="store_true", help="Keep running and repeat the weekday scan/watch cycle.")
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        print("Missing kis_config.local.env")
        print("Run setup_kis_config.command first.")
        raise SystemExit(1)

    python = sys.executable

    if args.daemon:
        run_daemon(python, args.interval)
        return

    if not args.watch_only:
        run_scan(python)

    if args.scan_only:
        if telegram_configured():
            send_status("Scan-only run completed.")
        return

    run_watcher(
        python,
        interval=args.interval,
        once=args.once,
        test_mode=args.test_mode,
        allow_test_orders=args.allow_test_orders,
    )


if __name__ == "__main__":
    main()
