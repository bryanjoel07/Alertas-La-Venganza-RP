from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backup import snapshot
from bot_settings import SettingsStore
from bug_store import BugStore
from economy_store import EconomyStore
from feedback_store import FeedbackStore
from meetings import MeetingStore
from minigame_store import MinigameStore
from photo_store import PhotoStore
from recruitment_store import RecruitmentStore
from sqlite_runtime import configure_database, transaction
from suggestion_store import SuggestionStore
from tickets_store import TicketStore


class SQLiteRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'active.db'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO sample VALUES (1,'original')")

    def test_wal_is_enabled_only_after_a_verified_backup_and_is_not_repeated(self):
        info=configure_database(self.path)
        self.assertEqual(info['journal_mode'],'wal')
        self.assertEqual(info['synchronous'],2)
        backup=info['backup']
        self.assertEqual(backup['integrity'],'ok')
        self.assertEqual(backup['rows']['sample'],1)
        self.assertTrue(Path(backup['file']+'.manifest.json').is_file())
        with transaction(backup['file'],readonly=True) as db:
            self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0],'original')
        self.assertIsNone(configure_database(self.path)['backup'])
        self.assertEqual(len(list(self.path.parent.glob('backups/before-wal-*.sqlite3'))),1)

    def test_failed_backup_leaves_original_database_and_journal_mode_unchanged(self):
        with patch('backup.snapshot',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):configure_database(self.path)
        with transaction(self.path,readonly=True) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'delete')
            self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0],'original')

    def test_reader_snapshot_and_writer_commit_can_run_at_the_same_time(self):
        configure_database(self.path)
        with transaction(self.path,readonly=True,timeout=.05) as reader:
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],'original')
            with transaction(self.path,timeout=.05) as writer:
                writer.execute("UPDATE sample SET value='changed' WHERE id=1")
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],'original')
        with transaction(self.path,readonly=True) as reader:
            self.assertEqual(reader.execute('SELECT value FROM sample').fetchone()[0],'changed')

    def test_snapshot_includes_committed_wal_records_and_rollback_preserves_them(self):
        configure_database(self.path)
        with closing(sqlite3.connect(self.path)) as anchor:
            anchor.execute('PRAGMA wal_autocheckpoint=0')
            anchor.execute("INSERT INTO sample VALUES (2,'in WAL')");anchor.commit()
            self.assertGreater(Path(str(self.path)+'-wal').stat().st_size,32)
            info=snapshot(self.path,self.path.parent/'wal-backup.db')
            self.assertEqual(info['rows']['sample'],2)
            with self.assertRaises(ValueError):
                with transaction(self.path) as db:
                    db.execute('DELETE FROM sample')
                    raise ValueError('abort')
            with transaction(info['file'],readonly=True) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sample').fetchone()[0],2)
            self.assertEqual(anchor.execute('SELECT COUNT(*) FROM sample').fetchone()[0],2)

    def test_readonly_connection_cannot_write_or_create_a_missing_database(self):
        with transaction(self.path,readonly=True) as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM sample')
        missing=self.path.parent/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):
            with transaction(missing,readonly=True):pass
        self.assertFalse(missing.exists())

    def test_audited_store_reads_do_not_take_the_writer_lock(self):
        with transaction(self.path) as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,status TEXT,winner1 TEXT,winner2 TEXT,winner3 TEXT)')
            db.execute('CREATE TABLE registrations(event_id INTEGER,user_id INTEGER)')
        stores=[TicketStore(self.path),EconomyStore(self.path),PhotoStore(self.path),FeedbackStore(self.path),
                BugStore(self.path),RecruitmentStore(self.path),MinigameStore(self.path),SuggestionStore(self.path),
                SettingsStore(self.path),MeetingStore(self.path)]
        for store in stores:
            if isinstance(store,MinigameStore):store.initialize([])
            else:store.initialize()
        # The legacy DELETE journal is supported too. A pending writer must not
        # prevent any of these independent, committed-state reads.
        with transaction(self.path) as writer:
            writer.execute("UPDATE sample SET value='uncommitted' WHERE id=1")
            for store in stores:
                with self.subTest(store=type(store).__name__):
                    with store.db(readonly=True) as db:
                        self.assertEqual(db.execute('SELECT value FROM sample').fetchone()[0],'original')
                    if hasattr(store,'config'):store.config('missing')
            tickets,economy,photos,feedback,bugs,recruitment,minigames,suggestions,settings,meetings=stores
            for read in (lambda:tickets.get(1),tickets.followup_candidates,tickets.recovery_candidates,
                         lambda:economy.account(1),economy.products,lambda:photos.entry(1),
                         lambda:feedback.summary(),lambda:bugs.get(1,include_video=False),
                         lambda:recruitment.rows(),lambda:minigames.availability(1),suggestions.list,
                         settings.snapshot,meetings.active):
                read()

    def test_economy_sql_helper_preserves_write_support_and_fresh_reads(self):
        store=EconomyStore(self.path)
        store.rows("UPDATE sample SET value='new' WHERE id=?",(1,))
        self.assertEqual(store.rows('SELECT value FROM sample')[0]['value'],'new')
        self.assertEqual(store.rows(''),[])
