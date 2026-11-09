import sqlite3
import unittest
from datetime import datetime
from unittest.mock import AsyncMock

from daily_up import announce_daily_up


class DailyUpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)")
        self.send = AsyncMock()

    def get(self, key, default=""):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def put(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self.db.commit()

    async def tick(self, when="2026-11-08T22:30:15+00:00", state="up",
                   confirmed="up", maintenance=False):
        return await announce_daily_up(datetime.fromisoformat(when), state,
                                       confirmed, maintenance, self.get,
                                       self.put, self.send)

    async def test_pr_timezone_and_only_target_minute(self):
        for when in ("2026-11-08T18:30:00+00:00", "2026-11-08T22:29:59+00:00",
                     "2026-11-08T22:31:00+00:00", "2026-11-09T01:00:00+00:00"):
            self.assertEqual(await self.tick(when), "outside_schedule")
        self.send.assert_not_awaited()
        self.assertEqual(await self.tick(), "sent")
        self.send.assert_awaited_once()

    async def test_persistent_slot_once_per_day_without_in_memory_state(self):
        self.assertEqual(await self.tick(), "sent")
        self.assertEqual(await self.tick(), "already_checked")
        self.assertEqual(await self.tick("2026-11-09T22:30:00+00:00"), "sent")
        self.assertEqual(self.send.await_count, 2)

    async def test_unavailable_and_unconfirmed_are_silent(self):
        for day, state, confirmed, maintenance in (
            (8, "down", "down", False), (9, "partial", "up", False),
            (10, "unknown", "up", False), (11, "unavailable", "up", False),
            (12, "up", "down", False), (13, "up", "up", True),
        ):
            with self.subTest(state=state, maintenance=maintenance):
                when = f"2026-11-{day:02d}T22:30:00+00:00"
                self.assertEqual(await self.tick(when, state, confirmed, maintenance),
                                 "skipped_unavailable")
                self.assertEqual(await self.tick(when), "already_checked")
        self.send.assert_not_awaited()

    async def test_uncertain_delivery_does_not_duplicate_on_restart(self):
        self.send.side_effect = TimeoutError("ambiguous delivery")
        with self.assertRaises(TimeoutError):
            await self.tick()
        self.assertEqual(await self.tick(), "already_checked")
        self.send.assert_awaited_once()

    async def test_new_hour_is_used_without_replaying_the_same_days_slot(self):
        self.put('daily_server_up_time','19:10')
        self.assertEqual(await self.tick(), 'outside_schedule')
        self.assertEqual(await self.tick('2026-11-08T23:10:00+00:00'),'sent')
        self.put('daily_server_up_time','20:00')
        self.assertEqual(await self.tick('2026-11-09T00:00:00+00:00'),'already_checked')
        self.assertEqual(await self.tick('2026-11-10T00:00:00+00:00'),'sent')
        self.assertEqual(self.send.await_count,2)

    async def test_storage_failure_does_not_publish_without_reservation(self):
        def failed_write(*args):
            raise sqlite3.OperationalError("read only")
        with self.assertRaises(sqlite3.OperationalError):
            await announce_daily_up(datetime.fromisoformat("2026-11-08T22:30:00+00:00"),
                                    "up", "up", False, self.get, failed_write, self.send)
        self.send.assert_not_awaited()
