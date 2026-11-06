import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backup import main, snapshot
from backup_meta import read_backup, record_backup, status_path
from diagnostics import read_database, status_embed, task_state


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'bot.db'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO settings VALUES ('last_state','up')")
            db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY)')
            db.execute('INSERT INTO events VALUES (1)')
            db.execute('CREATE TABLE registrations(event_id INTEGER,user_id INTEGER)')
            db.execute('CREATE TABLE meetings(id INTEGER PRIMARY KEY)')
        self.env = patch.dict('os.environ', {'BACKUP_STATUS_PATH': str(Path(self.temp.name) / 'backup-status.json')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_database_read_only_and_unknown_backup_is_honest(self):
        before = self.path.read_bytes()
        info = read_database(self.path)
        self.assertTrue(info['ok'])
        self.assertEqual(info['counts']['events'], 1)
        self.assertEqual(info['settings']['last_state'], 'up')
        self.assertEqual(before, self.path.read_bytes())
        backup = read_backup(self.path)
        self.assertFalse(backup['known'])
        missing = Path(self.temp.name) / 'missing.db'
        self.assertFalse(read_database(missing)['ok'])
        self.assertFalse(missing.exists())

    def test_backup_registry_separates_local_external_and_wrong_source(self):
        manifest = snapshot(self.path, Path(self.temp.name) / 'copy.db')
        record_backup(self.path, manifest)
        self.assertEqual(status_path(self.path).stat().st_mode & 0o777, 0o600)
        record = read_backup(self.path)
        self.assertTrue(record['known'])
        self.assertTrue(record['local_available'])
        self.assertEqual(record['drive_state'], 'not_requested')
        self.assertFalse(read_backup(Path(self.temp.name) / 'other.db')['known'])
        manifest['drive_state'] = 'verified'
        record_backup(self.path, manifest)
        self.assertEqual(read_backup(self.path)['drive_state'], 'verified')
        Path(manifest['file']).unlink()
        record = read_backup(self.path)
        self.assertFalse(record['local_available'])
        self.assertEqual(record['drive_state'], 'verified')

    def test_corrupt_or_unverified_registry_is_not_a_verified_backup(self):
        status_path(self.path).write_text('{invalid')
        self.assertFalse(read_backup(self.path)['known'])
        status_path(self.path).write_text(json.dumps(dict(source=str(self.path), created_at=datetime.now(timezone.utc).isoformat(), integrity='unknown', sha256='0' * 64)))
        self.assertFalse(read_backup(self.path)['known'])

    def test_backup_cli_records_success_and_failed_drive_without_credentials(self):
        output = Path(self.temp.name) / 'cli.db'
        args = ['backup.py', '--source', str(self.path), '--output', str(output)]
        with patch('sys.argv', args), patch('builtins.print'):
            main()
        self.assertTrue(read_backup(self.path)['known'])
        self.assertEqual(read_backup(self.path)['drive_state'], 'not_requested')
        drive_output = Path(self.temp.name) / 'drive.db'
        args = ['backup.py', '--source', str(self.path), '--output', str(drive_output), '--drive-folder', 'folder']
        with patch('sys.argv', args), patch('backup.upload_drive', side_effect=RuntimeError('upload failed')), patch('builtins.print'):
            with self.assertRaises(RuntimeError):
                main()
        self.assertEqual(read_backup(self.path)['drive_state'], 'failed')
        self.assertTrue(drive_output.exists())
        text = status_path(self.path).read_text()
        self.assertNotIn('credentials', text)
        self.assertNotIn('upload failed', text)

    def test_status_embed_counts_tasks_and_no_credentials(self):
        task = Mock()
        task.cancelled.return_value = False
        task.done.return_value = False
        bot = SimpleNamespace(is_ready=lambda: True, latency=0.12, started_monotonic=time.monotonic() - 200, monitor_last_read=1800000000, monitor_last_error=None, tracker=None, monitor_task=task, meetings=SimpleNamespace(task=task, last_check_at=1800000001), event_features=SimpleNamespace(task=task, last_check_at=1800000002))
        embed = status_embed(bot, str(self.path), read_database(self.path), read_backup(self.path))
        self.assertLessEqual(len(embed), 6000)
        self.assertIn('120 ms', embed.description)
        text = str(embed.to_dict())
        self.assertIn('No hay respaldo', text)
        self.assertNotIn('DISCORD_BOT_TOKEN', text)
        self.assertNotIn('DISCORD_WEBHOOK_URL', text)
        self.assertEqual(task_state(None), '⚪ No iniciada')
        task.done.return_value = True
        task.exception.return_value = ValueError('private detail')
        self.assertEqual(task_state(task), '🔴 Terminada con error')
        self.assertNotIn('private detail', task_state(task))
