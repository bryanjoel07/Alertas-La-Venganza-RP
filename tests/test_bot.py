import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
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
        with closing(sqlite3.connect(self.path)) as db, db:
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
        for seconds in (86400, 43200, 21600, 3600, 900, 300, 0):
            now = self.now + 100000 - seconds
            self.assertEqual(self.store.claim_reminder(mid, now), seconds)
            self.assertIsNone(MeetingStore(self.path).claim_reminder(mid, now + 1))

    def test_late_restart_sends_only_latest_and_no_expired(self):
        mid = self.create()
        self.assertEqual(self.store.claim_reminder(mid, self.now + 99900), 300)
        self.assertIsNone(self.store.claim_reminder(mid, self.now + 99901))
        expired = self.create()
        self.assertIsNone(self.store.claim_reminder(expired, self.now + 100300))
        late_created = self.create(delay=600)
        self.assertIsNone(self.store.claim_reminder(late_created, self.now + 1))

    def test_reminder_claim_is_atomic(self):
        mid = self.create()
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.store.claim_reminder(mid, self.now + 99900), range(5)))
        self.assertEqual(results.count(300), 1)

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

    async def test_daily_up_banner_and_outage_alerts_use_separate_channels(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        daily = SimpleNamespace(name="🟢︱Server-Up", id=123, send=AsyncMock())
        alerts = SimpleNamespace(id=self.bot.ALERT_CHANNEL_ID, send=AsyncMock())
        guild = SimpleNamespace(text_channels=[daily, SimpleNamespace(name="alertas")])
        with patch.object(self.bot.client, 'get_guild', return_value=guild), \
             patch.object(self.bot.client, 'get_channel', return_value=alerts), \
             patch.object(self.bot, 'post_webhook', AsyncMock()) as webhook:
            await self.bot.send_daily_up()
            daily.send.assert_awaited_once()
            kwargs = daily.send.call_args.kwargs
            self.assertEqual(kwargs['content'], '@everyone')
            self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'], ['everyone'])
            self.assertEqual(kwargs['embed'].image.url, 'attachment://server-up.jpg')
            self.assertEqual(kwargs['file'].filename, 'server-up.jpg')
            banner = Path(self.bot.__file__).parent / 'assets/banners/server-up.jpg'
            self.assertEqual(kwargs['file'].fp.read(), banner.read_bytes())
            kwargs['file'].close()
            for state in ('down', 'up'):
                await self.bot.send_alert(state)
            self.assertEqual(alerts.send.await_count, 2)
            for call in alerts.send.call_args_list:
                self.assertEqual(call.kwargs['content'], '@everyone')
                self.assertEqual(call.kwargs['allowed_mentions'].to_dict()['parse'], ['everyone'])
            daily.send.assert_awaited_once()
            webhook.assert_not_awaited()

    async def test_manual_up_request_survives_reconnect_without_changing_daily_slot(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        with patch.dict(os.environ, {'SERVER_UP_REQUEST_ID': 'test-manual-1'}), \
             patch.object(self.bot, 'daily_up_channel'), \
             patch.object(self.bot, 'send_daily_up', AsyncMock(return_value=SimpleNamespace(id=77))) as send:
            await self.bot.requested_server_up()
            await self.bot.requested_server_up()
            send.assert_awaited_once()
            self.assertEqual(self.bot.get_setting('manual_server_up_request'), 'test-manual-1')
            self.assertEqual(self.bot.get_setting('daily_server_up_slot'), '')

    async def test_maintenance_webhook_mentions_everyone(self):
        from unittest.mock import MagicMock
        import discord
        with patch.object(self.bot.aiohttp, 'ClientSession') as factory:
            session = factory.return_value.__aenter__.return_value
            session.post = MagicMock()
            session.post.return_value.__aenter__.return_value.status = 204
            await self.bot.post_webhook(discord.Embed(title='Mantenimiento'))
            payload = session.post.call_args.kwargs['json']
            self.assertEqual(payload['content'], '@everyone')
            self.assertEqual(payload['allowed_mentions'], {'parse': ['everyone']})

    async def test_daily_destination_requires_unique_server_up_channel(self):
        from types import SimpleNamespace
        for names in ([], ['alertas'], ['Server-Up', 'server_up']):
            guild = SimpleNamespace(text_channels=[SimpleNamespace(name=n) for n in names])
            with patch.object(self.bot.client, 'get_guild', return_value=guild):
                with self.assertRaises(RuntimeError):
                    self.bot.daily_up_channel()

    async def test_original_simulation_does_not_write_outages(self):
        self.bot.simulate_cycle()
        with self.bot.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM outages').fetchone()[0], 0)
        tracker = self.bot.StateTracker('up')
        tracker.observe('down', 0)
        tracker.observe(None, 80)
        self.assertIsNone(tracker.observe('down', 90))
        self.assertEqual(tracker.observe('down', 180), 'down')

    async def test_stale_online_panel_does_not_hide_outage_or_trigger_false_recovery(self):
        from types import SimpleNamespace
        import discord
        from datetime import timedelta
        from unittest.mock import AsyncMock
        current = datetime.now(timezone.utc)
        panel = SimpleNamespace(created_at=current-timedelta(days=10),edited_at=current-timedelta(minutes=15),
                                embeds=[discord.Embed().add_field(name='STATUS',value='Online')])
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=panel))
        with patch.object(self.bot.client,'fetch_channel',AsyncMock(return_value=channel)):
            self.assertEqual(await self.bot.read_connect_panel(),'stale')
            panel.edited_at=current
            self.assertEqual(await self.bot.read_connect_panel(),'up')
        resolve=self.bot.resolve_server_state
        for previous in ('up',None):
            tracker=self.bot.StateTracker(previous)
            state=resolve('unreachable','stale')
            self.assertIsNone(tracker.observe(state,0))
            self.assertIsNone(tracker.observe(state,45))
            self.assertEqual(tracker.observe(state,90),'down')
            tracker.confirmed('down')
            self.assertIsNone(tracker.observe(state,120))
            self.assertIsNone(tracker.observe(resolve('up','stale'),150))
            self.assertEqual(tracker.observe(resolve('up','stale'),240),'up')
        self.assertIsNone(resolve('unknown','stale'))
        self.assertIsNone(resolve('unreachable','unavailable'))
        self.assertEqual(resolve('unreachable','up'),'up')

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
        self.assertEqual({c.name for c in commands}, {'evento', 'mantenimiento', 'reunion', 'testalert', 'simular-ciclo', 'historial-caidas', 'perfil', 'estado-bot', 'respaldo', 'streamer', 'economia', 'saldo', 'tienda', 'comprar', 'regalar', 'inventario', 'equipar', 'quitar', 'trofeo', 'movimientos', 'deseos', 'sala'})
        for command in commands:
            payload = command.to_dict(bot.tree)
            self.assertLessEqual(len(payload['description']), 100)
        event_commands = {c.name for c in self.bot.event_group.commands}
        self.assertTrue({'historial', 'ranking', 'crear', 'cerrar', 'finalizar'}.issubset(event_commands))
        self.assertTrue(self.bot.intents.voice_states)
        meeting_commands = {c.name for c in bot.meetings.group.commands}
        self.assertEqual(meeting_commands, {'crear', 'encuesta', 'editar', 'cancelar', 'asistencia', 'presente', 'finalizar', 'informe'})
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
        self.assertEqual(select['channel_types'], [2, 13])
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
        system = MeetingSystem(Mock(), self.bot.DB_PATH)
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

    async def test_staff_voice_is_preselected_and_announcement_destination_preserved(self):
        from unittest.mock import Mock, AsyncMock
        from types import SimpleNamespace
        import discord
        staff_id = 1515887667298963579
        system = MeetingSystem(Mock(), self.bot.DB_PATH)
        voice = Mock(id=staff_id)
        voice.id = staff_id
        voice.type = discord.ChannelType.stage_voice
        voice.permissions_for.return_value.connect = True
        system.channel_access = AsyncMock(return_value=voice)
        interaction = Mock()
        preferred = await system.preferred_voice(interaction, 'staff')
        self.assertEqual(preferred, staff_id)
        modal = MeetingModal(system, 'staff', preferred_voice_id=preferred)
        self.assertEqual(modal.location.default_values[0].id, staff_id)
        self.assertEqual(CHANNELS['staff'], 1515887549678223380)
        modal.location._values = [SimpleNamespace(id=staff_id)]
        self.assertEqual(await modal.selected_location(interaction), f'<#{staff_id}>')
        voice.permissions_for.return_value.connect = False
        with self.assertRaises(discord.app_commands.CheckFailure):
            await system.preferred_voice(interaction, 'staff')
        system.channel_access.reset_mock()
        self.assertIsNone(await system.preferred_voice(interaction, 'general'))
        system.channel_access.assert_not_awaited()

    async def test_edit_retains_existing_voice_instead_of_staff_default(self):
        from unittest.mock import Mock
        system = MeetingSystem(Mock(), self.bot.DB_PATH)
        existing = dict(id=1, title='Reunión', starts_at=2000000000, location='<#123456789012345678>', agenda='Agenda', description='Texto')
        self.assertIsNone(await system.preferred_voice(Mock(), 'staff', existing))
        modal = MeetingModal(system, 'staff', existing, preferred_voice_id=1515887667298963579)
        self.assertEqual(modal.location.default_values[0].id, 123456789012345678)

    async def test_meeting_command_reports_actual_validation_error(self):
        from unittest.mock import Mock, AsyncMock
        import discord
        command = self.bot.client.meetings.group.get_command('crear')
        interaction = Mock()
        interaction.command = command
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        cause = ValueError('El canal elegido no es de voz.')
        error = discord.app_commands.CommandInvokeError(command, cause)
        with patch('meetings.log.error'):
            await self.bot.command_error(interaction, error)
        interaction.response.send_message.assert_awaited_once_with('❌ El canal elegido no es de voz.', ephemeral=True)

    async def test_create_opens_modal_without_waiting_for_attachment(self):
        from unittest.mock import AsyncMock, Mock
        interaction = Mock()
        interaction.response.send_modal = AsyncMock()
        await self.bot.evento_crear.callback(interaction)
        interaction.response.send_modal.assert_awaited_once()
        self.assertIsInstance(interaction.response.send_modal.call_args.args[0], self.bot.DetailsModal)
        self.assertEqual(self.bot.evento_crear.parameters, [])
        modal = self.bot.PrizesModal(42)
        fields = modal.to_components()
        self.assertEqual(len(fields), 5)
        upload = fields[4]['component']
        self.assertEqual(upload['type'], 19)
        self.assertFalse(upload['required'])
        self.assertEqual(upload['max_values'], 1)

    async def prepare_event_preview(self, attachment=None):
        from unittest.mock import AsyncMock, Mock
        self.bot.DRAFTS.clear()
        self.bot.DRAFTS[42] = dict(created=0, title='Prueba', description='Texto', location='Ciudad', starts_at='2030-01-01T23:00:00+00:00', banner=None)
        interaction = Mock()
        interaction.user.id = 42
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        modal = self.bot.PrizesModal(42)
        modal.capacity._value = '30'
        modal.first._value = 'Oro'
        modal.second._value = 'Plata'
        modal.third._value = 'Bronce'
        if attachment:
            modal.banner._values = [attachment]
        return modal, interaction

    async def test_banner_download_happens_after_ack_and_preview_is_private(self):
        from unittest.mock import AsyncMock, Mock
        image = Mock(filename='foto.jpg', content_type='image/jpeg', size=100)
        modal, interaction = await self.prepare_event_preview(image)
        async def read():
            interaction.response.defer.assert_awaited_once()
            return b'banner-bytes'
        image.read = AsyncMock(side_effect=read)
        await modal.on_submit(interaction)
        self.assertEqual(self.bot.DRAFTS[42]['banner'], (b'banner-bytes', 'evento.jpg'))
        kwargs = interaction.followup.send.call_args.kwargs
        self.assertTrue(kwargs['ephemeral'])
        self.assertEqual(kwargs['file'].fp.read(), b'banner-bytes')
        self.assertIsInstance(kwargs['view'], self.bot.PublishView)
        with self.bot.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    async def test_preview_without_banner_still_works(self):
        modal, interaction = await self.prepare_event_preview()
        await modal.on_submit(interaction)
        self.assertNotIn('file', interaction.followup.send.call_args.kwargs)
        self.assertIsNone(self.bot.DRAFTS[42]['banner'])

    async def test_bad_banner_keeps_draft_and_does_not_download(self):
        from unittest.mock import AsyncMock, Mock
        image = Mock(filename='huge.jpg', content_type='image/jpeg', size=9 * 1024 * 1024)
        image.read = AsyncMock()
        modal, interaction = await self.prepare_event_preview(image)
        await modal.on_submit(interaction)
        image.read.assert_not_awaited()
        self.assertIn(42, self.bot.DRAFTS)
        self.assertIn('8 MB', interaction.followup.send.call_args.args[0])

    async def test_banner_timeout_returns_actionable_error(self):
        from unittest.mock import AsyncMock, Mock
        image = Mock(filename='foto.jpg', content_type='image/jpeg', size=100)
        image.read = AsyncMock(return_value=b'image')
        modal, interaction = await self.prepare_event_preview(image)
        async def timeout(awaitable, timeout):
            self.assertEqual(timeout, 15)
            await awaitable
            raise asyncio.TimeoutError()
        with patch.object(self.bot.asyncio, 'wait_for', side_effect=timeout):
            await modal.on_submit(interaction)
        self.assertIn('tardó demasiado', interaction.followup.send.call_args.args[0])
        self.assertIn(42, self.bot.DRAFTS)

    async def test_registration_and_cancel_refresh_public_list_without_losing_rows(self):
        from unittest.mock import Mock, AsyncMock
        with self.bot.database() as db:
            key = db.execute("INSERT INTO events(message_id,channel_id,title,description,location,starts_at,capacity,prizes,status,created_by) VALUES (101,99,'Carrera','Texto','Ciudad','2030-01-01T00:00:00+00:00',30,'Premios','open','1')").lastrowid
        interaction = Mock()
        interaction.guild_id = self.bot.GUILD_ID
        interaction.user.id = 123
        interaction.message.id = 101
        interaction.message.edit = AsyncMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        summaries = Mock()
        summaries.update = AsyncMock()
        summaries.remove = AsyncMock()
        with patch.object(self.bot.client, 'summaries', summaries):
            buttons = self.bot.EventButtons()
            await buttons.registration(interaction, True)
            embed = summaries.update.call_args.args[3]
            self.assertIn('<@123>', embed.description)
            self.assertEqual(self.bot.registered_count(key), 1)
            await buttons.registration(interaction, True)
            self.assertEqual(self.bot.registered_count(key), 1)
            await buttons.registration(interaction, False)
            self.assertNotIn('<@123>', summaries.update.call_args.args[3].description)
            self.assertEqual(self.bot.registered_count(key), 0)
            self.assertIsNotNone(self.bot.fetch_event(key))

    async def test_meeting_response_updates_same_summary_and_preserves_status_groups(self):
        from unittest.mock import Mock, AsyncMock
        summaries = Mock()
        summaries.update = AsyncMock()
        system = MeetingSystem(Mock(), self.bot.DB_PATH, summaries)
        system.store.initialize()
        key = system.store.save(('Staff', 2000000000, '<#123456789012345678>', 'Agenda', 'Texto'), 1, 'staff')
        system.store.publication(key, 202)
        system.channel_access = AsyncMock()
        system.refresh = AsyncMock()
        interaction = Mock()
        interaction.user.id = 456
        interaction.message.id = 202
        interaction.channel_id = CHANNELS['staff']
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        buttons = MeetingButtons(system)
        await buttons.respond(interaction, 'yes')
        await buttons.respond(interaction, 'no')
        await buttons.respond(interaction, 'maybe')
        self.assertEqual(summaries.update.await_count, 3)
        self.assertTrue(all(call.args[:3] == ('meeting', key, CHANNELS['staff']) for call in summaries.update.call_args_list))
        embed = summaries.update.call_args.args[3]
        self.assertNotIn('<@456>', embed.fields[0].value)
        self.assertNotIn('<@456>', embed.fields[1].value)
        self.assertIn('<@456>', embed.fields[2].value)
        self.assertEqual(len(system.store.lists(key)[0]), 1)
        system.authorized_meeting = AsyncMock(return_value=system.store.get(key))
        panel = Mock()
        panel.delete = AsyncMock()
        channel = Mock()
        channel.members = []
        channel.fetch_message = AsyncMock(return_value=panel)
        system.bot.get_channel.return_value = channel
        await system.end(interaction, key, 'cancelled')
        self.assertIn('cancelada', summaries.update.call_args.args[3].description)
        self.assertEqual(len(system.store.lists(key)[0]), 1)

    async def test_status_command_is_private_and_admin_checked(self):
        from unittest.mock import AsyncMock, Mock
        interaction = Mock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await self.bot.estado_bot.callback(interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        self.assertTrue(interaction.followup.send.call_args.kwargs['ephemeral'])
        self.assertIn(self.bot.only_admin, self.bot.estado_bot.checks)
        self.assertTrue(self.bot.estado_bot.default_permissions.administrator)
        embed = interaction.followup.send.call_args.kwargs['embed']
        self.assertNotIn('offline-placeholder', str(embed.to_dict()))
        self.assertNotIn('example.invalid', str(embed.to_dict()))

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
                event_task = bot.event_features.task
                await bot.event_features.start()
                self.assertIs(event_task, bot.event_features.task)
