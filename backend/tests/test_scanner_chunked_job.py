from __future__ import annotations

import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch


os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "anon")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service")
os.environ.setdefault("BROKER_ENCRYPTION_KEY", "test")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import scanner


class ChunkedScanJobTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_or_resume_scan_reuses_running_scan_for_date_and_scope(self) -> None:
        existing = {
            "id": 7,
            "status": "running",
            "trade_date": "2026-05-18",
            "universe_scope": "all",
            "result": {"offset": 100, "total": 300, "done": False},
        }
        rest = AsyncMock()
        rest.select.return_value = [existing]

        with (
            patch.object(scanner, "SupabaseRest", return_value=rest),
            patch.object(scanner, "get_scan_market_status", return_value={"is_open": True, "trade_date": "2026-05-18"}),
            patch.object(scanner, "prepare_chunked_scan_state", new_callable=AsyncMock) as prepare,
        ):
            row = await scanner.start_or_resume_chunked_scan("user-1", date(2026, 5, 18), scanner.SCAN_UNIVERSE_ALL)

        self.assertEqual(row, existing)
        rest.insert.assert_not_called()
        prepare.assert_not_called()

    async def test_run_chunked_scan_to_completion_patches_progress_and_finalizes(self) -> None:
        rest = AsyncMock()
        rest.patch.side_effect = lambda table, *, filters, payload: [{**payload, "id": 9}]
        states = [
            {"offset": 100, "total": 200, "done": False, "candidates": [{"Code": "000001"}]},
            {"offset": 200, "total": 200, "done": True, "candidates": [{"Code": "000001"}, {"Code": "000002"}]},
        ]

        with (
            patch.object(scanner, "SupabaseRest", return_value=rest),
            patch.object(scanner, "process_scan_chunk", new_callable=AsyncMock, side_effect=states),
            patch.object(
                scanner,
                "finalize_chunked_scan",
                new_callable=AsyncMock,
                return_value={"trade_date": "2026-05-18", "signals": 2, "shared_saved": 2},
            ),
        ):
            result = await scanner.run_chunked_scan_to_completion(
                "user-1",
                {
                    "id": 9,
                    "status": "running",
                    "trade_date": "2026-05-18",
                    "result": {"offset": 0, "total": 200, "done": False},
                },
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(rest.patch.await_count, 2)
        first_payload = rest.patch.await_args_list[0].kwargs["payload"]
        final_payload = rest.patch.await_args_list[1].kwargs["payload"]
        self.assertEqual(first_payload["status"], "running")
        self.assertEqual(first_payload["signals_count"], 1)
        self.assertEqual(final_payload["status"], "completed")
        self.assertEqual(final_payload["signals_count"], 2)
        self.assertEqual(final_payload["shared_saved"], 2)


if __name__ == "__main__":
    unittest.main()
