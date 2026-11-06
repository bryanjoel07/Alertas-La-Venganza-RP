import asyncio
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord
from meetings import MeetingStore
from summaries import SummaryMessages, event_summary, meeting_summary, mention_list, with_countdown


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'lists.db')
        MeetingStore(self.path).initialize()
        self.messages = {}
        self.channel = Mock()
        self.next_id = 800
        async def send(**kwargs):
            self.next_id += 1
            msg = Mock(id=self.next_id)
            msg.id = self.next_id
            msg.edit = AsyncMock()
            async def delete():
                self.messages.pop(msg.id, None)
            msg.delete = AsyncMock(side_effect=delete)
            self.messages[msg.id] = msg
            return msg
        async def fetch(message_id):
            if message_id not in self.messages:
                raise discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'Unknown message')
            return self.messages[message_id]
        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.bot = Mock()
        self.bot.get_channel.return_value = self.channel
        self.summaries = SummaryMessages(self.bot, self.path)
        self.embed = discord.Embed(title='Prueba', description='<@123>')

    async def test_reuses_one_message_after_update_and_restart_without_pings(self):
        await self.summaries.update('event', 1, 99, self.embed)
        self.channel.send.assert_awaited_once()
        msg = next(iter(self.messages.values()))
        restarted = SummaryMessages(self.bot, self.path)
        await restarted.update('event', 1, 99, discord.Embed(title='Editado'))
        self.channel.send.assert_awaited_once()
        msg.edit.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.assertEqual(msg.edit.call_args.kwargs['allowed_mentions'].to_dict()['parse'], [])
        self.assertEqual(len(self.messages), 1)

    async def test_concurrent_updates_create_one_message(self):
        await asyncio.gather(*(self.summaries.update('meeting', 2, 99, self.embed) for _ in range(8)))
        self.channel.send.assert_awaited_once()
        self.assertEqual(next(iter(self.messages.values())).edit.await_count, 7)

    async def test_different_entities_do_not_share_message(self):
        for kind, key in [('event', 1), ('event', 2), ('meeting', 1)]:
            await self.summaries.update(kind, key, 99, self.embed)
        self.assertEqual(self.channel.send.await_count, 3)
        self.assertEqual(len(self.messages), 3)

    async def test_deleted_message_is_recreated_once(self):
        await self.summaries.update('event', 1, 99, self.embed)
        self.messages.clear()
        await self.summaries.update('event', 1, 99, self.embed)
        await self.summaries.update('event', 1, 99, self.embed)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertEqual(len(self.messages), 1)

    async def test_uncertain_delivery_does_not_send_duplicate_on_retry(self):
        self.channel.send.side_effect = RuntimeError('connection lost after send')
        with self.assertRaises(RuntimeError):
            await self.summaries.update('meeting', 1, 99, self.embed)
        restarted = SummaryMessages(self.bot, self.path)
        with self.assertRaises(RuntimeError):
            await restarted.update('meeting', 1, 99, self.embed)
        self.channel.send.assert_awaited_once()

    async def test_known_permission_failure_can_be_retried(self):
        original = self.channel.send.side_effect
        self.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'Missing permissions')
        with self.assertRaises(discord.Forbidden):
            await self.summaries.update('event', 1, 99, self.embed)
        self.channel.send.side_effect = original
        await self.summaries.update('event', 1, 99, self.embed)
        self.assertEqual(len(self.messages), 1)

    async def test_close_removes_list_and_cannot_recreate_it(self):
        await self.summaries.update('event', 1, 99, self.embed)
        msg = next(iter(self.messages.values()))
        await self.summaries.remove('event', 1, 99)
        await self.summaries.remove('event', 1, 99)
        await self.summaries.update('event', 1, 99, self.embed)
        msg.delete.assert_awaited_once()
        self.channel.send.assert_awaited_once()
        self.assertEqual(len(self.messages), 0)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT state FROM public_summaries').fetchone()[0], 'removed')

    async def test_summary_formats_mentions_group_changes_and_discord_limits(self):
        event = dict(id=1, title='Carrera', capacity=500, status='open', starts_at='2027-01-01T00:00:00-04:00')
        embed = event_summary(event, list(range(100000000000000000, 100000000000000500)))
        self.assertLessEqual(len(embed.description), 4096)
        self.assertLessEqual(len(embed), 6000)
        self.assertIn('500/500', embed.description)
        for kind in ('event', 'meeting'):
            timed = with_countdown(embed, kind, 1798776000, 1798776000 - 90061)
            self.assertIn('<t:1798776000:F>', timed.fields[-1].value)
            self.assertIn('25 h · 01 min · 01 s', timed.fields[-1].value)
            self.assertIn('Ya comenzó', with_countdown(embed, kind, 1, 1).fields[-1].value)
        self.assertFalse(event_summary(dict(event, status='finished'), []).fields)
        self.assertIn('más.', embed.description)
        meeting = dict(id=1, title='Staff', status='scheduled')
        original = [{'user_id': 123, 'response': 'yes'}]
        before = meeting_summary(meeting, original)
        after = meeting_summary(meeting, [{'user_id': 123, 'response': 'no'}])
        self.assertIn('<@123>', before.fields[0].value)
        self.assertNotIn('<@123>', after.fields[0].value)
        self.assertIn('<@123>', after.fields[1].value)
        rows = [dict(user_id=100000000000000000 + i, response=('yes', 'no', 'maybe')[i % 3]) for i in range(2000)]
        large = meeting_summary(meeting, rows)
        self.assertLessEqual(len(large), 6000)
        self.assertTrue(all(len(field.value) <= 1024 for field in large.fields))
        self.assertNotIn('@everyone', mention_list([]))

    async def test_clock_edits_same_list_and_stops_after_start(self):
        self.bot.wait_until_ready = AsyncMock()
        start = int(time.time()) + 2
        await self.summaries.update('meeting', 9, 99, self.embed, starts_at=start)
        task = self.summaries.countdowns['meeting', 9]
        message = next(iter(self.messages.values()))
        await asyncio.wait_for(task, timeout=5)
        self.channel.send.assert_awaited_once()
        self.assertIn('Ya comenzó', message.edit.call_args.kwargs['embed'].fields[-1].value)
        self.assertFalse(self.summaries.countdowns)
