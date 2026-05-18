from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service")
os.environ.setdefault("BROKER_ENCRYPTION_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.auth import CurrentUser
from app.routers import bot


class LatestScanRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_latest_scan_run_prefers_today_all_running_scan(self) -> None:
        rest = AsyncMock()
        rest.select.side_effect = [
            [{"id": 23, "status": "running", "trade_date": "2026-05-18", "universe_scope": "all"}],
        ]

        class FixedDateTime(bot.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 5, 18, 15, 0, tzinfo=tz)

        with (
            patch.object(bot, "SupabaseRest", return_value=rest),
            patch.object(bot, "datetime", FixedDateTime),
        ):
            result = await bot.latest_scan_run(CurrentUser(id="user-1", email="user@example.com", access_token="token"))

        self.assertEqual(result["id"], 23)
        rest.select.assert_awaited_once()
        self.assertEqual(rest.select.await_args.kwargs["filters"]["trade_date"], "eq.2026-05-18")
        self.assertEqual(rest.select.await_args.kwargs["filters"]["universe_scope"], "eq.all")


if __name__ == "__main__":
    unittest.main()
