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

    def sent_record(self, key, message_id, batch_key=None):
        row = self.add(key)
        self.store.reserve([key], batch_key or 'batch:' + key, '2026-11-18T15:00:00+00:00')
        self.store.mark_sent([(key, row['fingerprint'])], message_id)
        return self.store.get(key)

    def finish_deletes(self, version):
        for message_id in self.store.replacement(version)['message_ids']:
            self.store.mark_replacement_deleted(version, message_id)
        return self.store.set_replacement_stage(version, 'deletes_complete')

    def test_replacement_freezes_only_sent_or_reserved_rows_and_is_immutable_on_retry(self):
        published = self.sent_record('audit:published', '9001')
        self.add('audit:reserved')
        self.store.reserve(['audit:reserved'], 'batch-reserved', '2026-11-18T15:00:00+00:00')
        self.add('audit:pending')
        prepared = self.store.prepare_replacement('compact-v2')
        self.assertEqual({r['key'] for r in prepared['originals']}, {'audit:published', 'audit:reserved'})
        self.assertEqual(prepared['message_ids'], ['9001'])
        self.assertEqual(prepared['stage'], 'prepared')
        self.assertEqual(self.store.get('audit:published'), published)
        self.sent_record('audit:fresh', '9002')
        self.assertEqual(self.store.prepare_replacement('compact-v2'), prepared)
        prepared['originals'][0]['payload_json'] = 'changed in caller'
        self.assertNotEqual(self.store.replacement('compact-v2')['originals'][0]['payload_json'],
                            'changed in caller')

    def test_replacement_filter_cannot_split_existing_shared_messages_or_batches(self):
        one, two = self.add('audit:one'), self.add('audit:two')
        self.store.reserve(['audit:one', 'audit:two'], 'shared', '2026-11-18T15:00:00+00:00')
        self.store.mark_sent([(one['key'], one['fingerprint']), (two['key'], two['fingerprint'])], '9001')
        self.sent_record('audit:other', '9002')
        with self.assertRaisesRegex(ValueError, 'dividir'):
            self.store.prepare_replacement('partial', keys=['audit:one'])
        self.assertIsNone(self.store.replacement('partial'))
        result = self.store.prepare_replacement('partial', keys=['audit:one', 'audit:two'])
        self.assertEqual(result['message_ids'], ['9001'])
        self.assertNotIn('audit:other', {r['key'] for r in result['originals']})

    def test_reset_requires_complete_frozen_cleanup_and_every_compact_payload(self):
        original = self.sent_record('audit:one', '9001')
        self.store.prepare_replacement('v2')
        with self.assertRaisesRegex(ValueError, 'Confirma'):
            self.store.reset_for_replacement('v2', {'audit:one': {'title': 'Short'}})
        with self.assertRaisesRegex(ValueError, 'Faltan mensajes'):
            self.store.set_replacement_stage('v2', 'deletes_complete')
        with self.assertRaisesRegex(ValueError, 'conjunto congelado'):
            self.store.mark_replacement_deleted('v2', 'unknown')
        self.finish_deletes('v2')
        with self.assertRaisesRegex(ValueError, 'Faltan tarjetas'):
            self.store.reset_for_replacement('v2', {})
        self.assertEqual(self.store.get('audit:one'), original)
        self.assertEqual(self.store.replacement('v2')['stage'], 'deletes_complete')

    def test_reset_preserves_new_rows_newer_merged_payloads_metadata_cursor_and_backup(self):
        old_one = self.sent_record('audit:one', '9001')
        old_two = self.sent_record('audit:two', '9002')
        original_snapshot = self.store.prepare_replacement('v2')['originals']
        latest = self.add('audit:two', count=9, cursor=100, historical=False)
        fresh = self.sent_record('audit:new', '9003')
        self.finish_deletes('v2')
        result = self.store.reset_for_replacement('v2', {
            'audit:one': {'title': 'Compact one'},
            'audit:two': {'title': 'Stale compact two'},
            'audit:new': {'title': 'Must not overwrite fresh'},
        })
        self.assertEqual(result['stage'], 'queue_ready')
        self.assertEqual(result['reset_count'], 2)
        self.assertEqual(result['skipped_updated_keys'], ['audit:two'])
        one, two = self.store.get('audit:one'), self.store.get('audit:two')
        self.assertIn('Compact one', one['payload_json'])
        self.assertEqual(two['payload_json'], latest['payload_json'])
        self.assertEqual(two['fingerprint'], latest['fingerprint'])
        for row in (one, two):
            for column in ('message_id', 'sent_fingerprint', 'batch_key', 'attempted_at'):
                self.assertIsNone(row[column])
        for column in ('historical', 'source_id', 'event_type', 'event_time'):
            self.assertEqual(one[column], old_one[column])
            self.assertEqual(two[column], old_two[column])
        self.assertEqual(self.store.get('audit:new'), fresh)
        self.assertEqual(self.store.state('cursor'), 100)
        self.assertEqual(result['originals'], original_snapshot)

    def test_reset_is_once_only_after_restart_and_cannot_erase_recreated_messages(self):
        original = self.sent_record('audit:one', '9001')
        self.store.prepare_replacement('v2')
        self.finish_deletes('v2')
        first = self.store.reset_for_replacement('v2', {'audit:one': {'title': 'Compact'}})
        row = self.store.get('audit:one')
        self.store.reserve(['audit:one'], 'new-batch', '2026-11-18T16:00:00+00:00')
        self.store.mark_sent([('audit:one', row['fingerprint'])], '9101')
        recreated = self.store.get('audit:one')
        restarted = AuditStore(self.path)
        restarted.initialize()
        self.assertEqual(restarted.reset_for_replacement('v2', {}), first)
        self.assertEqual(restarted.get('audit:one'), recreated)
        restarted.set_replacement_stage('v2', 'complete')
        restarted.reset_for_replacement('v2', {'audit:one': {'title': 'Should not reset'}})
        self.assertEqual(restarted.get('audit:one'), recreated)
        self.assertEqual(restarted.replacement('v2')['originals'], [original])
        with self.assertRaisesRegex(ValueError, 'Transición'):
            restarted.set_replacement_stage('v2', 'prepared')

    def test_orphan_registration_requires_complete_frozen_batch_and_is_durable(self):
        self.add('audit:one')
        self.add('audit:two')
        self.store.reserve(['audit:one', 'audit:two'], 'unacked', '2026-11-18T15:00:00+00:00')
        self.store.prepare_replacement('v2')
        for keys in ([], ['outside'], ['audit:one']):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.store.register_replacement_message('v2', '9001', keys)
        result = self.store.register_replacement_message('v2', '9001', ['audit:two', 'audit:one'])
        self.assertEqual(result['message_ids'], ['9001'])
        self.assertEqual(result['recovered_messages'], {'9001': ['audit:one', 'audit:two']})
        self.assertEqual(self.store.register_replacement_message('v2', '9001', ['audit:one', 'audit:two']), result)
        self.finish_deletes('v2')
        with self.assertRaisesRegex(ValueError, 'preparación'):
            self.store.register_replacement_message('v2', '9002', ['audit:one', 'audit:two'])
        self.store.reset_for_replacement('v2', {'audit:one': {'title': '1'}, 'audit:two': {'title': '2'}})
        restart = AuditStore(self.path).replacement('v2')
        self.assertEqual(restart['recovered_messages'], result['recovered_messages'])
        self.assertEqual(restart['deleted_message_ids'], ['9001'])

    def test_replacement_reset_transaction_rolls_back_all_rows_if_one_write_fails(self):
        one = self.sent_record('audit:one', '9001')
        two = self.sent_record('audit:two', '9002')
        self.store.prepare_replacement('v2')
        self.finish_deletes('v2')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TRIGGER reset_failure BEFORE UPDATE ON vice_audit_outbox
                WHEN OLD.key='audit:two' BEGIN SELECT RAISE(ABORT,'storage failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.reset_for_replacement('v2', {'audit:one': {'title': '1'}, 'audit:two': {'title': '2'}})
        self.assertEqual(self.store.get('audit:one'), one)
        self.assertEqual(self.store.get('audit:two'), two)
        self.assertEqual(self.store.replacement('v2')['stage'], 'deletes_complete')


if __name__ == '__main__':
    unittest.main()
