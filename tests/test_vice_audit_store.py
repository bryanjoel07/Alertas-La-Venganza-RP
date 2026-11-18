"""Crash recovery, merged events and atomic catch-up state for the audit outbox."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from vice_audit_store import AuditStore


class AuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'district.sqlite3'
        self.store = AuditStore(self.path)
        self.store.initialize()

    def add(self, key='audit:1', *, count=1, cursor=None, historical=True,
            when='2026-11-18T14:00:00+00:00'):
        return self.store.enqueue(key, {'title': 'Movidos', 'fields': [{'value': str(count)}]},
                                  'audit', when, source_id=key.split(':')[-1],
                                  historical=historical, cursor=cursor)

    def test_identical_event_is_deduplicated_and_canonical_json_is_stable(self):
        a = self.store.enqueue('x', {'title': 'Entrada', 'color': 42}, 'voice',
                               '2026-11-18T12:00:00+00:00')
        b = self.store.enqueue('x', {'color': 42, 'title': 'Entrada'}, 'voice',
                               '2026-11-18T12:00:00+00:00')
        self.assertEqual(a['fingerprint'], b['fingerprint'])
        self.assertEqual(len(self.store.pending()), 1)
        self.store.mark_sent([('x', a['fingerprint'])], 9001)
        self.store.enqueue('x', {'title': 'Entrada', 'color': 42}, 'voice',
                           '2026-11-18T12:00:00+00:00')
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(self.store.stats(), {'total': 1, 'pending': 0, 'sent': 1, 'published': 1})

    def test_cursor_and_enqueue_commit_atomically_and_never_rewind(self):
        self.add(cursor=100)
        self.add('audit:2', cursor=50)
        self.assertEqual(self.store.state('cursor'), 100)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TRIGGER cursor_failure BEFORE INSERT ON vice_audit_state
                WHEN NEW.key='cursor' BEGIN SELECT RAISE(ABORT,'cursor unavailable'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.add('audit:3', cursor=200)
        self.assertIsNone(self.store.get('audit:3'))
        self.assertEqual(self.store.state('cursor'), 100)

    def test_merged_event_preserves_original_history_message_and_reservation(self):
        first = self.add(cursor=100)
        self.store.reserve(['audit:1'], 'batch-one', '2026-11-18T14:05:00+00:00')
        self.store.mark_sent([('audit:1', first['fingerprint'])], 9001)
        updated = self.add(count=3, cursor=100, historical=False)
        self.assertEqual(updated['historical'], 1)
        self.assertEqual(updated['batch_key'], 'batch-one')
        self.assertEqual(updated['message_id'], '9001')
        self.assertNotEqual(updated['fingerprint'], updated['sent_fingerprint'])
        self.assertEqual(len(self.store.pending()), 1)
        self.assertEqual(self.store.for_message(9001)[0]['key'], 'audit:1')
        self.store.mark_sent([('audit:1', updated['fingerprint'])], 9001)
        self.assertFalse(self.store.pending())

    def test_update_during_discord_send_stays_pending(self):
        sending = self.add(count=1)
        latest = self.add(count=2)
        self.store.mark_sent([('audit:1', sending['fingerprint'])], 9001)
        pending = self.store.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['fingerprint'], latest['fingerprint'])
        self.assertEqual(pending[0]['sent_fingerprint'], sending['fingerprint'])
        self.assertEqual(self.store.stats()['published'], 1)
        self.assertEqual(self.store.stats()['sent'], 0)

    def test_reservation_and_payload_survive_restart_without_regrouping(self):
        self.add('audit:2', when='2026-11-18T14:02:00+00:00')
        self.add('audit:1', when='2026-11-18T14:01:00+00:00')
        self.store.reserve(['audit:2', 'audit:1'], 'batch-original', '2026-11-18T14:03:00+00:00')
        restarted = AuditStore(self.path)
        restarted.initialize()
        rows = restarted.reserve(['audit:1'], 'batch-new', '2026-11-18T14:04:00+00:00')
        self.assertEqual(rows, [])
        original = restarted.batch('batch-original')
        self.assertEqual([r['key'] for r in original], ['audit:1', 'audit:2'])
        self.assertTrue(all(r['attempted_at'] == '2026-11-18T14:03:00+00:00' for r in original))
        restarted.mark_sent([(r['key'], r['fingerprint']) for r in original], 9002)
        self.assertEqual(len(restarted.for_message(9002)), 2)
        self.assertEqual(restarted.stats()['pending'], 0)

    def test_order_and_pagination_are_deterministic(self):
        self.add('audit:z', when='2026-11-18T14:02:00+00:00')
        self.add('audit:b', when='2026-11-18T14:01:00+00:00')
        self.add('audit:a', when='2026-11-18T14:01:00+00:00')
        self.assertEqual([r['key'] for r in self.store.pending(2)], ['audit:a', 'audit:b'])
        self.assertEqual(self.store.pending(0), [])
        self.assertEqual(self.store.pending(-1), [])

    def test_concurrent_enqueue_preserves_monotonic_cursor_and_all_events(self):
        values = list(range(30, 0, -1))
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(workers.map(lambda i: self.add(f'audit:{i}', cursor=i), values))
        self.assertEqual(self.store.state('cursor'), 30)
        self.assertEqual(self.store.stats()['total'], 30)
        self.assertEqual(len(self.store.pending(100)), 30)

    def test_state_json_roundtrip_and_empty_counts(self):
        self.assertIsNone(self.store.get('unknown'))
        self.assertEqual(self.store.state('unknown', 'fallback'), 'fallback')
        self.assertEqual(self.store.stats(), {'total': 0, 'pending': 0, 'sent': 0, 'published': 0})
        self.store.set_state('activation', {'date': '2026-11-18', 'active': True})
        self.assertEqual(AuditStore(self.path).state('activation'),
                         {'date': '2026-11-18', 'active': True})


if __name__ == '__main__':
    unittest.main()
