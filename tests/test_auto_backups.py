import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord
from backup import snapshot
from backup_meta import read_backup, record_backup
from backup_service import BackupService
from drive_backups import BackupFailure, DriveBackupClient, recovery_probe

GUILD = 1244988345327550565


class FakeDrive:
    files = {}
    uploads = 0
    folders = 0
    corrupt_download = False
    uncertain_upload = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def folder(self, folder_id=None):
        if not folder_id:
            type(self).folders += 1
        return folder_id or 'folder-owned-by-user'

    def upload(self, path, folder):
        type(self).uploads += 1
        key = f'file-{type(self).uploads}'
        self.files[key] = Path(path).read_bytes()
        if self.uncertain_upload:
            raise BackupFailure('upload', 'Entrega incierta de prueba')
        return key

    def download(self, file_id, path, manifest):
        Path(path).write_bytes(b'corrupt' if self.corrupt_download else self.files[file_id])


class AutoBackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'lavenganza.sqlite3'
        with sqlite3.connect(self.source) as db:
            db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,title TEXT)')
            db.execute("INSERT INTO events VALUES(42,'Evento preservado')")
            db.execute('CREATE TABLE registrations(event_id INTEGER,user_id INTEGER)')
            db.execute('INSERT INTO registrations VALUES(42,123)')
        self.original = self.source.read_bytes()
        self.channel = Mock()
        self.channel.guild.id = GUILD
        self.channel.send = AsyncMock()
        self.bot = Mock()
        self.bot.get_channel.return_value = self.channel
        self.bot.wait_until_ready = AsyncMock()
        self.bot.is_closed.return_value = True
        self.env = patch.dict('os.environ', dict(AUTO_BACKUP_ENABLED='0', BACKUP_TIME_PR='03:00', BACKUP_DIR=str(Path(self.temp.name) / 'backups'), BACKUP_STATE_PATH=str(Path(self.temp.name) / 'backup-schedule.json'), BACKUP_STATUS_PATH=str(Path(self.temp.name) / 'backup-status.json'), GOOGLE_DRIVE_BACKUP_FOLDER_ID=''))
        self.env.start()
        self.addCleanup(self.env.stop)
        FakeDrive.files = {}
        FakeDrive.uploads = FakeDrive.folders = 0
        FakeDrive.corrupt_download = FakeDrive.uncertain_upload = False
        self.client = patch('backup_service.DriveBackupClient', FakeDrive)
        self.client.start()
        self.addCleanup(self.client.stop)
        self.service = BackupService(self.bot, self.source, GUILD)
        await self.service.start()

    async def asyncTearDown(self):
        for task in (self.service.task, self.service.manual_task):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_disabled_by_default_does_not_upload_or_alter_source(self):
        await self.service.tick()
        self.assertIsNone(self.service.task)
        self.assertEqual(FakeDrive.uploads, 0)
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_upload_download_restore_and_metadata_verified(self):
        result = await self.service.execute()
        self.assertEqual(result['drive_state'], 'verified')
        self.assertEqual(result['restore_state'], 'verified')
        self.assertEqual(FakeDrive.uploads, 1)
        self.assertEqual(FakeDrive.folders, 1)
        self.assertEqual(read_backup(self.source)['restore_state'], 'verified')
        self.assertTrue(Path(result['file']).is_file())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.channel.send.assert_not_awaited()
        self.assertFalse(list(self.service.directory.glob('drive-probe-*')))
        self.assertEqual((await self.service.describe())['phase'], 'complete')

    async def test_daily_slot_survives_restart_and_late_reconnect_no_burst(self):
        self.service.enabled = True
        now = datetime(2026, 11, 7, 7, 1, tzinfo=timezone.utc)
        await self.service.tick(now)
        self.assertEqual(FakeDrive.uploads, 1)
        restart = BackupService(self.bot, self.source, GUILD)
        await restart.start()
        restart.enabled = True
        await restart.tick(now)
        self.assertEqual(FakeDrive.uploads, 1)
        await restart.tick(datetime(2026, 11, 10, 7, 1, tzinfo=timezone.utc))
        self.assertEqual(FakeDrive.uploads, 2)
        self.assertEqual(FakeDrive.folders, 1)
        self.assertEqual(len(list(self.service.directory.glob('*.sqlite3'))), 2)

    async def test_pr_timezone_cutoff(self):
        self.assertEqual(self.service.slot(datetime(2026, 11, 7, 6, 59, tzinfo=timezone.utc)), '2026-11-06')
        self.assertEqual(self.service.slot(datetime(2026, 11, 7, 7, 0, tzinfo=timezone.utc)), '2026-11-07')

    async def test_failed_auth_alert_once_and_same_slot_not_retried(self):
        self.service.enabled = True
        now = datetime(2026, 11, 7, 7, 1, tzinfo=timezone.utc)
        with patch('backup_service.DriveBackupClient', side_effect=BackupFailure('authentication', 'Autenticación no disponible')), patch('backup_service.log.error'):
            with self.assertRaises(BackupFailure):
                await self.service.tick(now)
            await self.service.tick(now)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.assertNotIn('file', self.channel.send.call_args.kwargs)
        self.assertEqual(read_backup(self.source)['drive_state'], 'failed')
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_uncertain_upload_not_automatically_duplicated(self):
        self.service.enabled = True
        FakeDrive.uncertain_upload = True
        now = datetime(2026, 11, 7, 7, 1, tzinfo=timezone.utc)
        with patch('backup_service.log.error'):
            with self.assertRaises(BackupFailure):
                await self.service.tick(now)
        await self.service.tick(now)
        self.assertEqual(FakeDrive.uploads, 1)
        self.channel.send.assert_awaited_once()

    async def test_bad_download_fails_recovery_and_probe_can_retry_without_new_upload(self):
        FakeDrive.corrupt_download = True
        with patch('backup_service.log.error'):
            with self.assertRaises(BackupFailure):
                await self.service.execute()
        self.assertEqual(read_backup(self.source)['drive_state'], 'verified')
        self.assertEqual(read_backup(self.source)['restore_state'], 'failed')
        self.assertEqual(self.source.read_bytes(), self.original)
        FakeDrive.corrupt_download = False
        result = await self.service.execute(probe_only=True)
        self.assertEqual(result['restore_state'], 'verified')
        self.assertEqual(FakeDrive.uploads, 1)
        self.assertEqual(read_backup(self.source)['restore_state'], 'verified')
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_interrupted_job_not_repeated_but_alerted_once(self):
        now = datetime(2026, 11, 7, 7, 1, tzinfo=timezone.utc)
        self.service._change(phase='running', operation='unfinished', last_slot=self.service.slot(now))
        restart = BackupService(self.bot, self.source, GUILD)
        await restart.start()
        restart.enabled = True
        await restart.tick(now)
        await restart.tick(now)
        self.assertEqual((await restart.describe())['phase'], 'interrupted')
        self.assertEqual(FakeDrive.uploads, 0)
        self.channel.send.assert_awaited_once()

    async def test_busy_job_rejects_second_and_preserves_source(self):
        entered, release = threading.Event(), threading.Event()
        upload = FakeDrive.upload
        def slow_upload(instance, *args):
            entered.set()
            release.wait(3)
            return upload(instance, *args)
        with patch.object(FakeDrive, 'upload', slow_upload):
            first = asyncio.create_task(self.service.execute())
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                with self.assertRaises(BackupFailure) as error:
                    await self.service.execute()
                self.assertEqual(error.exception.stage, 'busy')
            finally:
                release.set()
            await first
        self.assertEqual(FakeDrive.uploads, 1)
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_enabled_start_does_not_duplicate_background_task(self):
        ready = asyncio.Event()
        self.bot.wait_until_ready = ready.wait
        with patch.dict('os.environ', {'AUTO_BACKUP_ENABLED': '1'}):
            service = BackupService(self.bot, self.source, GUILD)
        await service.start()
        task = service.task
        try:
            await service.start()
            self.assertIs(service.task, task)
            self.assertFalse(task.done())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_admin_commands_private_and_players_rejected(self):
        interaction = Mock()
        interaction.guild_id = GUILD
        interaction.user = Mock(spec=discord.Member)
        interaction.user.bot = False
        interaction.user.roles = []
        interaction.user.guild_permissions.administrator = False
        with self.assertRaises(discord.app_commands.CheckFailure):
            await self.service.admin(interaction)
        interaction.user.guild_permissions.administrator = True
        self.assertTrue(await self.service.admin(interaction))
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        with patch.object(self.service, 'launch'):
            await self.service.group.get_command('crear').callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertTrue(self.service.group.default_permissions.administrator)
        self.assertIn(self.service.admin, self.service.group.get_command('crear').checks)

    async def test_storage_failure_still_attempts_one_alert_without_upload(self):
        with patch.object(self.service, '_change', side_effect=BackupFailure('storage', 'No se pudo guardar')), patch('backup_service.log.error'):
            with self.assertRaises(BackupFailure):
                await self.service.execute()
            operation = next(iter(self.service.notice_operations))
            await self.service.failure_notice(operation, BackupFailure('storage', 'No se pudo guardar'))
        self.channel.send.assert_awaited_once()
        self.assertEqual(FakeDrive.uploads, 0)
        self.assertEqual(self.source.read_bytes(), self.original)

    async def test_invalid_registry_does_not_overwrite_database(self):
        with patch.dict('os.environ', {'BACKUP_STATE_PATH': str(self.source)}):
            service = BackupService(self.bot, self.source, GUILD)
            await service.start()
            with self.assertRaises(BackupFailure):
                await service.execute()
        self.assertEqual(self.source.read_bytes(), self.original)
        with patch.dict('os.environ', {'BACKUP_STATUS_PATH': str(self.source)}):
            with self.assertRaises(ValueError):
                record_backup(self.source, {})
        self.assertEqual(self.source.read_bytes(), self.original)


class RecoveryTests(unittest.TestCase):
    def test_probe_never_replaces_active_database_and_detects_wrong_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'live.db'
            with sqlite3.connect(source) as db:
                db.execute('CREATE TABLE data(id INTEGER PRIMARY KEY,value TEXT)')
                db.execute("INSERT INTO data VALUES(1,'conservar')")
            original = source.read_bytes()
            manifest = snapshot(source, Path(folder) / 'copy.db')
            self.assertTrue(recovery_probe(manifest['file'], manifest, folder))
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(BackupFailure):
                recovery_probe(source, manifest, folder)
            Path(manifest['file']).write_bytes(b'invalid')
            with self.assertRaises(BackupFailure):
                recovery_probe(manifest['file'], manifest, folder)
            self.assertEqual(source.read_bytes(), original)

class DriveProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict('os.environ', {'GOOGLE_DRIVE_CREDENTIALS_JSON': json.dumps(dict(type='authorized_user', client_id='test-client', client_secret='fixture-private-value', refresh_token='fixture-refresh-value'))})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.session = Mock()
        self.transport = patch('google.auth.transport.requests.AuthorizedSession', return_value=self.session)
        self.transport.start()
        self.addCleanup(self.transport.stop)
        self.drive = DriveBackupClient()
        self.addCleanup(self.drive.close)

    def response(self, data=None, status=200, headers=None, chunks=()):
        result = Mock()
        result.status_code = status
        result.json.return_value = data
        result.headers = headers or {}
        result.iter_content.return_value = iter(chunks)
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock()
        return result

    def test_oauth_creates_private_app_folder_and_checks_upload(self):
        path = Path(self.temp.name) / 'copy.db'
        path.write_bytes(b'sqlite-test-content')
        self.session.request.side_effect = [self.response({'id': 'own-folder'}), self.response(headers={'Location': 'https://www.googleapis.com/upload/drive/v3/files?upload_id=private-session'}), self.response({'id': 'copy-id', 'size': str(path.stat().st_size), 'md5Checksum': hashlib.md5(path.read_bytes()).hexdigest()})]
        folder = self.drive.folder()
        self.assertEqual(folder, 'own-folder')
        self.assertEqual(self.drive.upload(path, folder), 'copy-id')
        body = self.session.request.call_args_list[0].kwargs['json']
        self.assertEqual(body['mimeType'], 'application/vnd.google-apps.folder')
        self.assertNotIn('permissions', body)

    def test_download_verifies_sha_size_and_rejects_excess(self):
        body = b'expected-data'
        manifest = dict(size_bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        self.session.request.return_value = self.response(chunks=[body[:3], body[3:]])
        output = Path(self.temp.name) / 'download.db'
        self.drive.download('copy-id', output, manifest)
        self.assertEqual(output.read_bytes(), body)
        self.session.request.return_value = self.response(chunks=[body + b'excess'])
        with self.assertRaises(BackupFailure):
            self.drive.download('copy-id', Path(self.temp.name) / 'too-big.db', manifest)

    def test_transport_errors_do_not_expose_tokens_or_session_url(self):
        self.session.request.side_effect = RuntimeError('https://private/session?secret=fixture-private-value')
        with self.assertRaises(BackupFailure) as error:
            self.drive.request('GET', 'https://www.googleapis.com/drive/v3/files/copy-id')
        self.assertNotIn('fixture-private-value', str(error.exception))
        self.assertNotIn('private/session', str(error.exception))
        self.session.request.side_effect = None
        self.session.request.return_value = self.response(status=403)
        with self.assertRaises(BackupFailure) as forbidden:
            self.drive.request('GET', 'https://www.googleapis.com/drive/v3/files/copy-id')
        self.assertIn('403', str(forbidden.exception))

    def test_service_account_requires_shared_drive_folder(self):
        self.drive.service_account = True
        with self.assertRaises(BackupFailure) as error:
            self.drive.folder()
        self.assertEqual(error.exception.stage, 'configuration')
        self.session.request.assert_not_called()

    def test_bad_credentials_error_never_echoes_json(self):
        with patch.dict('os.environ', {'GOOGLE_DRIVE_CREDENTIALS_JSON': '{invalid-fixture-private-value'}):
            with self.assertRaises(BackupFailure) as error:
                DriveBackupClient()
        self.assertNotIn('fixture-private-value', str(error.exception))

    def test_snapshot_timeout_removes_only_its_partial_output(self):
        source = Path(self.temp.name) / 'live.db'
        with sqlite3.connect(source) as db:
            db.execute('CREATE TABLE keep(id INTEGER)')
            db.execute('INSERT INTO keep VALUES(1)')
        original = source.read_bytes()
        output = Path(self.temp.name) / 'partial.db'
        with self.assertRaises(TimeoutError):
            snapshot(source, output, timeout_seconds=-1)
        self.assertFalse(output.exists())
        self.assertEqual(source.read_bytes(), original)
