from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord
from meetings import MeetingStore, MeetingSystem, GUILD_ID, STAFF_VOICE_ID, CHANNELS


class MeetingLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = str(Path(self.temp.name) / 'meeting.db')
        self.voice = Mock(id=STAFF_VOICE_ID)
        self.voice.id = STAFF_VOICE_ID
        self.voice.members = []
        self.panel = Mock()
        self.panel.delete = AsyncMock()
        self.channel = Mock()
        self.deleted = False
        async def fetch(_):
            if self.deleted:
                raise discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'Unknown message')
            return self.panel
        async def delete():
            self.deleted = True
        self.panel.delete.side_effect = delete
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.bot = Mock()
        self.bot.get_channel.side_effect = lambda channel_id: self.voice if channel_id == STAFF_VOICE_ID else self.channel
        self.summaries = Mock()
        self.summaries.update = AsyncMock()
        self.system = MeetingSystem(self.bot, path, self.summaries)
        self.system.store.initialize()
        self.system.initialized = True
        self.key = self.system.store.save(('Staff', 2000000000, f'<#{STAFF_VOICE_ID}>', 'Agenda', 'Texto'), 1, 'staff')
        self.system.store.publication(self.key, 100)
        self.system.authorized_meeting = AsyncMock(side_effect=lambda interaction, key: self.system.store.get(key))
        self.interaction = Mock()
        self.interaction.user.id = 1
        self.interaction.response.defer = AsyncMock()
        self.interaction.followup.send = AsyncMock()

    def member(self, key, bot=False, guild=GUILD_ID):
        return SimpleNamespace(id=key, bot=bot, guild=SimpleNamespace(id=guild))

    async def join(self, key, bot=False, guild=GUILD_ID):
        await self.system.voice_update(self.member(key, bot, guild), SimpleNamespace(channel=None), SimpleNamespace(channel=self.voice))

    async def test_voice_listener_records_unique_humans_only_while_scheduled(self):
        await self.join(20)
        await self.join(20)
        await self.join(21, bot=True)
        await self.join(22, guild=999)
        await self.system.voice_update(self.member(23), SimpleNamespace(channel=self.voice), SimpleNamespace(channel=self.voice))
        self.assertEqual(self.system.staff.report(self.key)['present'], [20])
        self.system.store.finish(self.key, 'finished', 1)
        await self.join(24)
        self.assertEqual(self.system.staff.report(self.key)['present'], [20])

    async def test_finish_snapshots_occupants_publishes_report_deletes_only_panel(self):
        self.system.store.respond(self.key, 10, 'yes')
        self.system.store.respond(self.key, 20, 'yes')
        self.voice.members = [self.member(10), self.member(99, bot=True)]
        await self.system.end(self.interaction, self.key, 'finished')
        self.panel.delete.assert_awaited_once()
        kinds = [call.args[0] for call in self.summaries.update.call_args_list]
        self.assertEqual(kinds, ['meeting', 'staff_report'])
        report = self.system.staff.report(self.key)
        self.assertEqual(report['present'], [10])
        self.assertEqual(report['confirmed_missing'], [20])
        self.assertEqual(self.system.store.get(self.key)['status'], 'finished')
        self.assertEqual(len(self.system.store.lists(self.key)[0]), 2)
        await self.system.end(self.interaction, self.key, 'finished')
        self.panel.delete.assert_awaited_once()

    async def test_cancel_deletes_panel_keeps_confirmations_without_final_report(self):
        self.system.store.respond(self.key, 10, 'no')
        await self.system.end(self.interaction, self.key, 'cancelled')
        self.panel.delete.assert_awaited_once()
        self.assertEqual([call.args[0] for call in self.summaries.update.call_args_list], ['meeting'])
        self.assertEqual(len(self.system.store.lists(self.key)[0]), 1)
        self.assertEqual(self.system.store.get(self.key)['status'], 'cancelled')

    async def test_failed_panel_deletion_keeps_records_and_can_retry(self):
        original = self.panel.delete.side_effect
        self.panel.delete.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing permissions')
        with unittest.mock.patch('meetings.log.exception'):
            await self.system.end(self.interaction, self.key, 'finished')
        self.assertEqual(self.system.store.get(self.key)['status'], 'finished')
        self.assertIn('No se pudo eliminar el panel', self.interaction.followup.send.call_args.args[0])
        self.panel.delete.side_effect = original
        await self.system.end(self.interaction, self.key, 'finished')
        self.assertTrue(self.deleted)

    async def test_ready_marks_possible_gap_and_snapshots_people_currently_inside(self):
        self.voice.members = [self.member(10)]
        await self.system.voice_ready()
        report = self.system.staff.report(self.key)
        self.assertEqual(report['present'], [10])
        self.assertEqual(report['tracking']['gap_detected'], 1)

    async def test_short_meeting_notifies_at_start_in_its_own_channel(self):
        from time import time
        starts = int(time()) + 90
        self.channel.send = AsyncMock()
        for kind in ('general', 'staff'):
            key = self.system.store.save(('Prueba', starts, 'Voz', 'Agenda', 'Texto'), 1, kind)
            self.system.store.publication(key, 100 + key)
            self.channel.id = CHANNELS[kind]
            await self.system.send_due_reminder(key, starts - 5)
            calls = self.channel.send.await_count
            await self.system.send_due_reminder(key, starts + 1)
            await self.system.send_due_reminder(key, starts + 2)
            self.assertEqual(self.channel.send.await_count, calls + 1)
            self.bot.get_channel.assert_called_with(CHANNELS[kind])
            embed = self.channel.send.await_args.kwargs['embed']
            self.assertIn('HA COMENZADO', embed.title)
            self.assertIn(f'/{CHANNELS[kind]}/{100 + key}', embed.description)

    async def test_failed_delivery_retries_and_recovers_an_ambiguous_send(self):
        self.channel.id = CHANNELS['staff']
        self.bot.user.id = 42
        history = []
        async def messages(**kwargs):
            for msg in history:
                yield msg
        self.channel.history = messages
        async def deliver(**kwargs):
            if self.channel.send.await_count == 1:
                raise OSError("unavailable")
            history.append(SimpleNamespace(author=self.bot.user, embeds=[kwargs['embed']]))
            raise OSError("response lost")
        self.channel.send = AsyncMock(side_effect=deliver)
        for offset in (0, 30):
            with self.assertRaises(OSError):
                await self.system.send_due_reminder(self.key, 2000000000 - 900 + offset)
        await self.system.send_due_reminder(self.key, 2000000000 - 900 + 60)
        await self.system.send_due_reminder(self.key, 2000000000 - 900 + 90)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertEqual(len(history), 1)

    async def test_move_or_cancel_a_meeting_before_the_reminder(self):
        self.channel.send = AsyncMock()
        self.system.store.save(('Movida', 2000010000, 'Voz', 'Agenda', 'Texto'), 1, 'staff', self.key)
        await self.system.send_due_reminder(self.key, 2000000000)
        self.assertNotIn('HA COMENZADO', self.channel.send.await_args.kwargs['embed'].title)
        self.system.store.finish(self.key, 'cancelled', 1)
        self.channel.send.reset_mock()
        await self.system.send_due_reminder(self.key, 2000010000)
        self.channel.send.assert_not_awaited()
