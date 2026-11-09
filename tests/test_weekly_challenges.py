import tempfile
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from economy_store import EconomyStore
from weekly_challenges import WeeklyChallenges,week_bounds


class WeeklyTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'test.db'
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY,status TEXT,winner1 TEXT,winner2 TEXT,winner3 TEXT,title TEXT,starts_at TEXT);
            CREATE TABLE registrations(event_id INTEGER,user_id INTEGER);
            CREATE TABLE meetings(id INTEGER PRIMARY KEY,kind TEXT,status TEXT,starts_at INTEGER);
            CREATE TABLE meeting_attendance(meeting_id INTEGER,user_id INTEGER,present INTEGER,recorded_by INTEGER);''')
        self.store=EconomyStore(self.path);self.store.initialize()
        self.now=int(datetime.fromisoformat('2026-11-12T22:00:00+00:00').timestamp())
        self.weekly=WeeklyChallenges(self.store)
        with patch('weekly_challenges.time.time',return_value=self.now-86400):
            self.weekly.initialize()

    def activity(self):
        with self.store.db() as db:
            db.execute("INSERT INTO events VALUES (1,'finished','7',NULL,NULL,'Carrera','2026-11-12T18:00:00-04:00')")
            db.execute('INSERT INTO eco_participants VALUES (1,7,99)')
            db.execute("INSERT INTO meetings VALUES (1,'general','finished',?)",(self.now,))
            db.execute('INSERT INTO meeting_attendance VALUES (1,7,1,99)')

    def test_registration_and_old_activity_never_earn_coins(self):
        with self.store.db() as db:
            db.execute("INSERT INTO events VALUES (1,'finished','8',NULL,NULL,'Viejo','2026-11-09T08:00:00+00:00')")
            db.execute('INSERT INTO registrations VALUES (1,7)')
            db.execute('INSERT INTO eco_participants VALUES (1,8,99)')
        self.assertEqual(self.weekly.claim(7,self.now),0)
        self.assertEqual(self.weekly.claim(8,self.now),0)
        self.assertEqual(self.store.account(7)['balance'],0)

    def test_claim_is_atomic_capped_and_survives_restart_and_concurrency(self):
        self.activity()
        self.assertTrue(all(g['done'] for g in self.weekly.progress(7,self.now)['goals']))
        with ThreadPoolExecutor(max_workers=4) as pool:
            amounts=list(pool.map(lambda _: WeeklyChallenges(self.store).claim(7,self.now),range(4)))
        self.assertEqual(sum(amounts),450)
        self.assertEqual(self.store.account(7)['balance'],450)
        self.assertEqual(WeeklyChallenges(self.store).claim(7,self.now),0)
        self.assertEqual(len(self.store.rows('SELECT * FROM eco_ledger')),3)

    def test_new_week_does_not_reuse_previous_week_activity(self):
        self.activity();self.weekly.claim(7,self.now)
        self.assertEqual(self.weekly.claim(7,self.now+7*86400),0)

    def test_archived_results_remain_eligible(self):
        self.activity()
        with self.store.db() as db:
            db.execute("UPDATE events SET status='closed' WHERE id=1")
        self.assertEqual(self.weekly.claim(7,self.now),450)

    def test_monday_midnight_puerto_rico_boundary(self):
        a=int(datetime.fromisoformat('2026-11-09T03:59:59+00:00').timestamp())
        self.assertEqual(week_bounds(a)[0],'2026-11-02')
        self.assertEqual(week_bounds(a+1)[0],'2026-11-09')
