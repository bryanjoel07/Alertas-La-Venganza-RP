from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from meetings import MeetingStore
from staff_reports import StaffReports, report_embed, report_text


class StaffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'test.db')
        self.store = MeetingStore(self.path)
        self.store.initialize()
        self.staff = StaffReports(self.path)
        self.staff.initialize()
        self.voice_id = 1515887667298963579
        self.created = int(time.time()) - 120
        self.key = self.store.save(('Staff', self.created, f'<#{self.voice_id}>', 'Agenda', 'Texto'), 1, 'staff')
        self.store.publication(self.key, 200)

    def test_voice_entries_distinct_and_compare_responses(self):
        for user, response in ((10, 'yes'), (20, 'yes'), (30, 'no'), (40, 'maybe')):
            self.store.respond(self.key, user, response)
        self.staff.observe(self.key, self.voice_id, [10, 10, 30, 50], now=self.created + 1)
        self.staff.observe(self.key, self.voice_id, [10], now=self.created + 2)
        report = self.staff.report(self.key)
        self.assertEqual(report['present'], [10, 30, 50])
        self.assertEqual(report['confirmed_present'], [10])
        self.assertEqual(report['confirmed_missing'], [20])
        self.assertEqual(report['declined'], [30])
        self.assertEqual(report['maybe'], [40])
        self.assertEqual(report['unconfirmed_present'], [50])
        self.assertEqual(report['declined_present'], [30])
        self.assertEqual(report['visits'][10]['first_seen'], self.created + 1)
        self.assertEqual(report['visits'][10]['last_seen'], self.created + 2)

    def test_closed_window_wrong_channel_and_general_do_not_record(self):
        self.staff.observe(self.key, self.voice_id, [1], now=self.created - 1)
        self.staff.observe(self.key, 999, [2], now=self.created + 1)
        self.staff.observe(self.key, self.voice_id, [3], now=self.created + 2)
        self.store.finish(self.key, 'finished', 1)
        self.staff.observe(self.key, self.voice_id, [4], now=self.created + 3)
        self.assertEqual(self.staff.report(self.key)['present'], [3])
        key = self.store.save(('General', 2000000000, f'<#{self.voice_id}>', 'Agenda', 'Texto'), 1, 'general')
        self.store.publication(key, 201)
        self.staff.observe(key, self.voice_id, [5])
        self.assertEqual(self.staff.report(key)['present'], [])

    def test_manual_adjustments_preserve_voice_evidence(self):
        self.staff.observe(self.key, self.voice_id, [10], now=self.created + 1)
        self.store.present(self.key, 10, False, 8)
        self.store.present(self.key, 20, True, 8)
        report = self.staff.report(self.key)
        self.assertEqual(report['present'], [20])
        self.assertIn(10, report['visits'])
        self.assertEqual(report['manual'][10]['recorded_by'], 8)

    def test_rescheduled_report_excludes_visits_outside_the_new_window(self):
        self.staff.observe(self.key, self.voice_id, [10], now=self.created + 1)
        self.staff.gap()
        self.store.initialize()
        self.staff.observe(self.key, self.voice_id, [20], source='snapshot', now=self.created + 5, resume=True)
        with patch('meetings.datetime') as clock:
            from datetime import datetime, timezone
            clock.now.return_value = datetime.fromtimestamp(self.created + 10, timezone.utc)
            self.store.save(('Cambio', 2000001000, f'<#{self.voice_id}>', 'Agenda', 'Texto'), 1, 'staff', self.key)
        self.staff.observe(self.key, self.voice_id, [30], now=self.created + 11)
        report = self.staff.report(self.key)
        self.assertEqual(report['tracking']['started_at'], self.created)
        self.assertEqual(report['tracking']['gap_detected'], 1)
        self.assertEqual(report['present'], [])

    def test_legacy_observations_before_start_do_not_count(self):
        with self.staff.connection() as db:
            for user,last in [(11,self.created-100),(22,self.created+5)]:
                db.execute('INSERT INTO meeting_voice_visits VALUES(?,?,?,?,?,?)',
                           (self.key,user,self.voice_id,self.created-3600,last,'snapshot'))
        db.close()
        self.staff.observe(self.key,self.voice_id,[33],now=self.created-1)
        result=self.staff.report(self.key)
        self.assertIsNone(result['tracking'])
        self.assertEqual(result['present'],[22])
        self.assertEqual(result['visits'][22]['first_seen'],self.created+5)
        embed=report_embed(self.store.get(self.key),result)
        self.assertIn(f'<t:{self.created}:F>',embed.description)

    def test_large_report_within_discord_limits_and_full_export(self):
        for user in range(100000000000000000, 100000000000000150):
            self.store.respond(self.key, user, 'yes')
        self.staff.observe(self.key, self.voice_id, list(range(100000000000000000, 100000000000000100)), now=self.created + 1)
        self.store.finish(self.key, 'finished', 1)
        meeting = self.store.get(self.key)
        report = self.staff.report(self.key)
        embed = report_embed(meeting, report)
        self.assertLessEqual(len(embed), 6000)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        self.assertIn('100000000000000149', report_text(meeting, report))
        self.assertIn('50', embed.fields[2].name)
