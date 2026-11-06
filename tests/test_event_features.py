from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from event_features import EventFeatureStore, EVENT_THRESHOLDS


class EventFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'test.db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,message_id INTEGER,channel_id INTEGER,title TEXT,starts_at TEXT,status TEXT,winner1 TEXT,winner2 TEXT,winner3 TEXT)')
            db.execute('CREATE TABLE registrations(event_id INTEGER,user_id INTEGER,PRIMARY KEY(event_id,user_id))')
        self.store = EventFeatureStore(self.path)
        self.store.initialize()
        self.base = 1800000000

    def event(self, key=1, delay=100000, status='open', winners=(None, None, None), users=()):
        starts = datetime.fromtimestamp(self.base + delay, timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            db.execute('INSERT INTO events VALUES (?,?,99,?,?,?,?,?,?)', (key, key + 100, f'Evento {key}', starts, status, *winners))
            db.executemany('INSERT INTO registrations VALUES (?,?)', [(key, u) for u in users])
        return key

    def test_all_thresholds_including_start_once_and_restart(self):
        key = self.event()
        self.store.schedule(key, self.base)
        self.assertEqual(EVENT_THRESHOLDS, (86400, 43200, 21600, 3600, 900, 0))
        for seconds in EVENT_THRESHOLDS:
            now = self.base + 100000 - seconds
            current, revision, claimed = self.store.claim(key, now)
            self.assertEqual(claimed, seconds)
            self.store.result(key, revision, claimed, 'sent')
            self.assertIsNone(EventFeatureStore(self.path).claim(key, now + 1))

    def test_late_restart_only_latest_and_none_after_start_or_closed(self):
        key = self.event()
        self.store.schedule(key, self.base)
        self.assertEqual(self.store.claim(key, self.base + 99900)[2], 900)
        self.assertIsNone(self.store.claim(key, self.base + 99910))
        expired = self.event(2)
        self.store.schedule(expired, self.base)
        self.assertIsNone(self.store.claim(expired, self.base + 100090))
        self.assertEqual(self.store.claim(key, self.base + 100029)[2], 0)
        self.assertIsNone(EventFeatureStore(self.path).claim(key, self.base + 100059))
        for index, state in enumerate(('finished', 'closed'), 3):
            key = self.event(index, status=state)
            self.assertIsNone(self.store.claim(key, self.base + 99900))

    def test_new_or_legacy_event_does_not_send_old_thresholds(self):
        key = self.event(delay=2000)
        self.assertIsNone(self.store.claim(key, self.base))
        self.assertEqual(self.store.claim(key, self.base + 1100)[2], 900)

    def test_claim_is_atomic_across_connections(self):
        key = self.event()
        self.store.schedule(key, self.base)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.claim(key, self.base + 99900), range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_date_edit_revisions_keep_old_ledger(self):
        key = self.event()
        self.store.schedule(key, self.base)
        first = self.store.claim(key, self.base + 13600)
        self.assertEqual(first[1:], (1, 86400))
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE events SET starts_at=? WHERE id=?', (datetime.fromtimestamp(self.base + 300000, timezone.utc).isoformat(), key))
        self.store.schedule(key, self.base + 14000)
        second = self.store.claim(key, self.base + 213600)
        self.assertEqual(second[1:], (2, 86400))
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM event_reminders WHERE event_id=?', (key,)).fetchone()[0], 2)

    def test_history_and_ranking_include_old_results_and_closed_podium(self):
        self.event(1, status='finished', winners=('10', '20', '30'), users=(10, 20, 30, 40))
        self.event(2, status='closed', winners=('40', '10', '20'), users=(10, 40))
        self.event(3, status='finished', winners=('50', '60', '70'), users=(10,))
        self.event(4, status='open', users=(90,))
        self.event(5, status='closed', users=(90,))
        players, completed = self.store.ranking()
        self.assertEqual(completed, 3)
        self.assertEqual(players[0]['user_id'], 10)
        self.assertEqual(players[0]['participations'], 3)
        self.assertEqual(players[0]['first'], 1)
        self.assertEqual(players[0]['second'], 1)
        self.assertNotIn(90, [p['user_id'] for p in players])
        self.assertIn(50, [p['user_id'] for p in players])  # Ganador seleccionado aunque no se inscribió.
        rows, total = self.store.history()
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.store.history(2)[0], [])
        self.store.initialize()
        self.assertEqual(self.store.ranking(), (players, completed))

    def test_ranking_top_ten_and_one_participation_per_event(self):
        self.event(1, status='finished', winners=('100', '101', '102'), users=range(100, 125))
        players, _ = self.store.ranking()
        self.assertEqual(len(players), 10)
        self.assertTrue(all(p['participations'] == 1 for p in players))
        self.assertEqual(players[0]['user_id'], 100)

    def test_profile_full_rank_beyond_top_ten(self):
        self.event(1, status='finished', users=range(10, 30))
        profile = self.store.profile(29)
        self.assertEqual(profile['rank'], 20)
        self.assertEqual(profile['ranked_players'], 20)
        self.assertEqual(profile['stats']['participations'], 1)
        self.assertEqual(profile['total_events'], 1)
        self.assertNotIn(29, [row['user_id'] for row in self.store.ranking()[0]])

    def test_profile_all_events_and_completed_stats_match_ranking(self):
        self.event(1, status='finished', winners=('20', '10', '11'), users=(10, 11))
        self.event(2, status='closed', winners=('10', '20', '12'), users=(10,))
        self.event(3, status='open', users=(10,))
        self.event(4, status='closed', users=(10,))
        profile = self.store.profile(10)
        self.assertEqual(profile['total_events'], 4)
        self.assertEqual(profile['stats']['participations'], 2)
        self.assertEqual(profile['stats']['first'], 1)
        self.assertEqual(profile['stats']['second'], 1)
        ranking = self.store.ranking()[0]
        self.assertEqual(profile['rank'], next(i for i, row in enumerate(ranking, 1) if row['user_id'] == 10))
        self.assertEqual(len(self.store.profile_history(10)), 4)
        self.assertEqual(self.store.profile(1)['total_events'], 0)

    def test_profile_pagination_and_no_records(self):
        for key in range(1, 14):
            self.event(key, status='finished', users=(50,))
        self.assertEqual(self.store.profile(50)['pages'], 3)
        self.assertEqual(len(self.store.profile(50, 2)['events']), 5)
        last = self.store.profile(50, 999)
        self.assertEqual(last['page'], 3)
        self.assertEqual(len(last['events']), 3)
        self.assertEqual(len(self.store.profile_history(50)), 13)
        empty = self.store.profile(999)
        self.assertIsNone(empty['rank'])
        self.assertEqual(empty['stats']['participations'], 0)
        self.assertEqual(empty['events'], [])

    def test_profile_reads_never_create_a_missing_database(self):
        missing = Path(self.temp.name) / 'not-there.db'
        with self.assertRaises(sqlite3.OperationalError):
            EventFeatureStore(str(missing)).profile(50)
        self.assertFalse(missing.exists())
