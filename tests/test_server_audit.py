import sqlite3
import tempfile
import unittest
from pathlib import Path
from server_audit import database_summary


class AuditTests(unittest.TestCase):
    def test_audit_only_reads_aggregate_data_and_leaves_balance_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'audit.sqlite3'
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE settings(key TEXT,value TEXT); CREATE TABLE events(status TEXT); '
                                 'CREATE TABLE registrations(id INTEGER); CREATE TABLE meetings(status TEXT); '
                                 'CREATE TABLE eco_accounts(user_id INTEGER,balance INTEGER); '
                                 'INSERT INTO eco_accounts VALUES (123,500);')
            before = path.read_bytes()
            summary = database_summary(path)
            self.assertTrue(summary['integrity'])
            self.assertEqual(summary['counts']['eco_accounts'], 1)
            self.assertEqual(summary['economy_totals'], (500,500))
            self.assertNotIn('user_id', str(summary))
            self.assertEqual(path.read_bytes(), before)
