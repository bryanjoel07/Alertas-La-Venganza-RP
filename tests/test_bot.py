import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backup import snapshot
from meetings import MeetingStore, MeetingSystem, MeetingButtons, MeetingModal, meeting_location, CHANNELS, ROLES, GUILD_ID
from storage import database_path


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'test.db')
        # Simula un esquema y registro existentes del bot original.
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, title TEXT)')
            db.execute("INSERT INTO events VALUES (77,'Evento conservado')")
        self.store = MeetingStore(self.path)
        self.store.initialize()
        self.now = int(datetime.now(timezone.utc).timestamp())

    def create(self, delay=100000):
        mid = self.store.save(('Reunión', self.now + delay, 'Voz', 'Agenda', 'Descripción'), 1, 'staff')
        self.store.publication(mid, mid + 100)
        return mid

    def test_additive_schema_and_restart(self):
        mid = self.create()
        self.store.respond(mid, 5, 'yes')
        restarted = MeetingStore(self.path)
        restarted.initialize()
        self.assertEqual(restarted.lists(mid)[0][0]['response'], 'yes')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT title FROM events WHERE id=77').fetchone()[0], 'Evento conservado')
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_response_upsert_and_attendance_are_independent(self):
        mid = self.create()
        self.store.respond(mid, 5, 'yes')
        self.store.respond(mid, 5, 'no')
        self.store.present(mid, 5, True, 9)
        responses, actual = self.store.lists(mid)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]['response'], 'no')
        self.assertEqual(actual[0]['present'], 1)
        self.assertEqual(actual[0]['recorded_by'], 9)

    def test_edit_preserves_confirmations_and_results(self):
        mid = self.create()
        self.store.respond(mid, 5, 'yes')
        self.store.present(mid, 5, True, 9)
        self.store.save(('Otro título', self.now + 200000, 'Nueva voz', 'Nueva agenda', 'Texto'), 1, 'staff', mid)
        self.assertEqual(len(self.store.lists(mid)[0]), 1)
        self.assertEqual(len(self.store.lists(mid)[1]), 1)
        self.assertEqual(self.store.get(mid)['title'], 'Otro título')

    def test_cancel_and_finish_block_responses_preserve_data(self):
        for state in ('cancelled', 'finished'):
            mid = self.create()
            self.store.respond(mid, 5, 'yes')
            self.store.finish(mid, state, 9)
            with self.assertRaises(ValueError):
                self.store.respond(mid, 6, 'maybe')
            self.assertIsNone(self.store.claim_reminder(mid, self.now + 99999))
            self.assertEqual(len(self.store.lists(mid)[0]), 1)

    def test_reminders_each_once_across_restarts(self):
        mid = self.create()
        for seconds in (86400, 3600, 900):
            now = self.now + 100000 - seconds
            self.assertEqual(self.store.claim_reminder(mid, now), seconds)
            self.assertIsNone(MeetingStore(self.path).claim_reminder(mid, now + 1))

    def test_late_restart_sends_only_latest_and_no_expired(self):
        mid = self.create()
        self.assertEqual(self.store.claim_reminder(mid, self.now + 99900), 900)
        self.assertIsNone(self.store.claim_reminder(mid, self.now + 99901))
        expired = self.create()
        self.assertIsNone(self.store.claim_reminder(expired, self.now + 100001))
        late_created = self.create(delay=600)
        self.assertIsNone(self.store.claim_reminder(late_created, self.now + 1))

    def test_reminder_claim_is_atomic(self):
        mid = self.create()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.store.claim_reminder(mid, self.now + 99900), range(5)))
        self.assertEqual(results.count(900), 1)

    def test_backup_verified_and_never_overwrites(self):
        mid = self.create()
        self.store.respond(mid, 5, 'yes')
        target = Path(self.temp.name) / 'backup.db'
        info = snapshot(self.path, target)
        self.assertEqual(info['integrity'], 'ok')
        self.assertEqual(info['rows']['meeting_responses'], 1)
        with self.assertRaises(FileExistsError):
            snapshot(self.path, target)
        with self.assertRaises(ValueError):
            snapshot(self.path, self.path)
        with self.assertRaises(ValueError):
            snapshot(Path(self.temp.name) / 'missing.db', target)

    def test_path_missing_stops_startup(self):
        with patch.dict(os.environ, {'DB_PATH': str(Path(self.temp.name) / 'missing.db'), 'ALLOW_EMPTY_DB': '0'}):
            with self.assertRaises(RuntimeError):
                database_path()
        with patch.dict(os.environ, {'DB_PATH': self.path, 'ALLOW_EMPTY_DB': '0'}):
            with self.assertRaises(RuntimeError):
                database_path()
            with sqlite3.connect(self.path) as db:
                db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT)')
                db.execute('CREATE TABLE registrations(event_id INTEGER, user_id INTEGER)')
            self.assertEqual(database_path(), self.path)


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'DISCORD_BOT_TOKEN': 'offline-placeholder', 'DISCORD_WEBHOOK_URL': 'https://example.invalid', 'DB_PATH': str(Path(self.temp.name) / 'offline.db'), 'ALLOW_EMPTY_DB': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bot = importlib.import_module('bot')
        self.bot.DB_PATH = str(Path(self.temp.name) / 'offline.db')
        self.bot.DATA_DIR = self.temp.name
        self.bot.init_db()

    async def test_original_simulation_does_not_write_outages(self):
        self.bot.simulate_cycle()
        with self.bot.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM outages').fetchone()[0], 0)
        tracker = self.bot.StateTracker('up')
        tracker.observe('down', 0)
        tracker.observe(None, 80)
        self.assertIsNone(tracker.observe('down', 90))
        self.assertEqual(tracker.observe('down', 180), 'down')

    async def test_outages_deduplicate_and_restore_state(self):
        self.bot.record_outage('down')
        self.bot.record_outage('down')
        self.bot.record_outage('up')
        with self.bot.database() as db:
            rows = db.execute('SELECT * FROM outages').fetchall()
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0]['duration_seconds'])
        self.assertEqual(self.bot.get_setting('last_state'), 'up')

    async def test_command_payloads_and_persistent_ids(self):
        import discord
        bot = self.bot.client
        commands = bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))
        self.assertEqual({c.name for c in commands}, {'evento', 'mantenimiento', 'reunion', 'testalert', 'simular-ciclo', 'historial-caidas'})
        for command in commands:
            payload = command.to_dict(bot.tree)
            self.assertLessEqual(len(payload['description']), 100)
        meeting_commands = {c.name for c in bot.meetings.group.commands}
        self.assertEqual(meeting_commands, {'crear', 'editar', 'cancelar', 'asistencia', 'presente', 'finalizar'})
        views = [self.bot.EventButtons(), MeetingButtons(bot.meetings)]
        ids = [item.custom_id for view in views for item in view.children]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(view.is_persistent() for view in views))
        self.assertEqual(CHANNELS['staff'], 1515887549678223380)
        self.assertEqual(len(ROLES), 4)

    async def test_meeting_admin_denies_unapproved_member(self):
        from types import SimpleNamespace
        import discord
        interaction = SimpleNamespace(guild_id=GUILD_ID, user=SimpleNamespace(roles=[]))
        with self.assertRaises(discord.app_commands.CheckFailure):
            self.bot.client.meetings.admin(interaction)

    async def test_role_and_private_channel_permissions(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, AsyncMock
        import discord
        member = Mock(spec=discord.Member)
        member.roles = [SimpleNamespace(id=1245008186440683530)]
        interaction = SimpleNamespace(guild_id=GUILD_ID, user=member)
        system = MeetingSystem(Mock(), self.bot.DB_PATH)
        system.admin(interaction)
        channel = Mock()
        channel.guild.id = GUILD_ID
        channel.permissions_for.return_value.view_channel = False
        system.bot.get_channel.return_value = channel
        with self.assertRaises(discord.app_commands.CheckFailure):
            await system.channel_access(interaction, CHANNELS['staff'], admin=True)
        channel.permissions_for.return_value.view_channel = True
        self.assertIs(await system.channel_access(interaction, CHANNELS['staff'], admin=True), channel)
        member.roles = []
        with self.assertRaises(discord.app_commands.CheckFailure):
            system.admin(interaction)

    async def test_meeting_modal_voice_selector_and_defaults(self):
        from unittest.mock import Mock
        import discord
        modal = MeetingModal(Mock(), 'staff')
        fields = modal.to_components()
        self.assertEqual(len(fields), 5)
        self.assertEqual(fields[2]['label'], 'Canal de voz')
        select = fields[2]['component']
        self.assertEqual(select['type'], 8)
        self.assertEqual(select['channel_types'], [2])
        self.assertTrue(select['required'])
        existing = dict(id=1, title='Reunión', starts_at=2000000000, location='<#123456789012345678>', agenda='Agenda', description='Texto')
        edited = MeetingModal(Mock(), 'staff', existing)
        self.assertEqual(edited.location.default_values[0].id, 123456789012345678)
        existing['location'] = 'Lugar anterior'
        legacy = MeetingModal(Mock(), 'staff', existing)
        self.assertEqual(legacy.location.default_values, [])
        self.assertEqual(meeting_location('<#123456789012345678>'), '<#123456789012345678>')
        self.assertIn('\u200b', meeting_location('@everyone'))

    async def test_meeting_voice_permission_validation(self):
        from unittest.mock import Mock, AsyncMock
        from types import SimpleNamespace
        import discord
        voice = Mock()
        voice.id = 123456789012345678
        voice.type = discord.ChannelType.voice
        voice.permissions_for.return_value.connect = True
        system = Mock()
        system.channel_access = AsyncMock(return_value=voice)
        modal = MeetingModal(system, 'staff')
        interaction = Mock()
        with self.assertRaises(ValueError):
            await modal.selected_location(interaction)
        modal.location._values = [SimpleNamespace(id=voice.id)]
        self.assertEqual(await modal.selected_location(interaction), '<#123456789012345678>')
        voice.permissions_for.return_value.connect = False
        with self.assertRaises(discord.app_commands.CheckFailure):
            await modal.selected_location(interaction)
        voice.type = discord.ChannelType.text
        with self.assertRaises(ValueError):
            await modal.selected_location(interaction)

    async def test_setup_initializes_once_and_syncs_without_network(self):
        from unittest.mock import AsyncMock
        bot = self.bot.LaVenganzaBot()
        bot.tree.sync = AsyncMock(return_value=[])
        with patch.object(self.bot, 'client', bot):
            async with bot:
                await bot.setup_hook()
                bot.tree.sync.assert_awaited_once()
                first = bot.meetings.task
                await bot.meetings.start()
                self.assertIs(first, bot.meetings.task)
