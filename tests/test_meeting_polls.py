import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from meetings import CHANNELS, MeetingModal, MeetingSystem
from meeting_polls import MeetingPolls, PollView, poll_embed


class PollTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.system = MeetingSystem(Mock(), str(Path(temp.name) / "polls.sqlite3"))
        self.system.store.initialize()
        self.polls = self.system.polls
        self.polls.initialize()
        self.channel = CHANNELS["staff"]
        start = int(time.time()) + 3600
        self.data = dict(title="Prueba", location="<#123>", agenda="Agenda", description="Descripción",
                         kind="staff", slot1=start, slot2=start+3600, slot3=start+7200)
        self.polls.save(101, self.data)

    async def test_votes_replace_persist_and_withdraw(self):
        self.polls.vote(101, self.channel, 2, [1, 2, 3])
        restarted = MeetingPolls(self.system)
        for _ in range(2):
            r = restarted.vote(101, self.channel, 2, [1, 3])
            self.assertEqual(r['counts'], {1:1, 2:0, 3:1})
        self.assertIn("Más votado", poll_embed(r).fields[2].name)
        self.assertFalse(any(restarted.vote(101, self.channel, 2, [])['counts'].values()))
        with self.assertRaises(ValueError):
            restarted.choose(101, self.channel, 3)
        with self.assertRaises(ValueError):
            restarted.vote(101, CHANNELS['general'], 2, [3])

    async def test_tie_revalidated_then_exactly_one_meeting(self):
        self.polls.vote(101, self.channel, 1, [1, 2])
        key, ties = self.polls.choose(101, self.channel, 4)
        self.assertIsNone(key)
        self.assertEqual([i for i,_ in ties], [1,2])
        self.polls.vote(101, self.channel, 2, [2])
        with self.assertRaises(ValueError):
            self.polls.choose(101, self.channel, 4, choice=1)
        results = await asyncio.gather(*(asyncio.to_thread(self.polls.choose, 101, self.channel, user) for user in (4,5)))
        self.assertEqual(results[0], results[1])
        meeting = self.system.store.get(results[0][0])
        self.assertEqual((meeting["message_id"], meeting["starts_at"], meeting["status"]),
                         (101, self.data["slot2"], "scheduled"))
        self.assertEqual(self.system.store.lists(meeting["id"])[0], [])
        with self.assertRaises(ValueError):
            self.polls.vote(101, self.channel, 1, [2])

    async def test_modal_and_persistent_controls(self):
        modal = MeetingModal(self.system, 'general', poll=True)
        self.assertEqual(len(modal.children), 5)
        self.assertLessEqual(max(len(item.text) for item in modal.children), 45)
        self.assertTrue(PollView(self.polls).is_persistent())
        dates = "2099-02-02 12:00\n2099-02-02 18:00\n2099-02-03 20:00"
        self.assertEqual(len(self.polls.parse(dates)), 3)
        with self.assertRaises(ValueError):
            self.polls.parse(dates.replace("18:00", "12:00"))
        with self.assertRaises(ValueError):
            self.polls.parse(dates.replace("2099", "2001"))

    async def test_staff_button_checks_permissions_before_conversion(self):
        interaction = SimpleNamespace(response=AsyncMock(), user=Mock(id=5), channel_id=self.channel)
        self.system.channel_access = AsyncMock(side_effect=ValueError("permiso"))
        with self.assertRaisesRegex(ValueError, "permiso"):
            await self.polls.finish(interaction, 101)
        self.system.channel_access.assert_awaited_once_with(interaction, self.channel, admin=True)
        self.assertEqual(self.system.store.active(), [])

    async def test_vote_and_schedule_replace_the_poll_in_its_own_channel(self):
        interaction = Mock(channel_id=self.channel)
        interaction.message.id = 101
        interaction.user.id = 50
        interaction.data = {"values": ["1", "3"]}
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message.edit = AsyncMock()
        self.system.channel_access = AsyncMock()
        view = PollView(self.polls)
        await view.availability.callback(interaction)
        self.assertIn("**1** persona", interaction.message.edit.call_args.kwargs["embed"].fields[0].value)
        await view.schedule.callback(interaction)
        tie = interaction.followup.send.call_args.kwargs["view"]
        self.assertEqual([opt.value for opt in tie.pick.options], ["1", "3"])
        interaction.data = {"values": ["3"]}
        channel = self.system.bot.get_channel.return_value
        channel.fetch_message = AsyncMock(return_value=interaction.message)
        self.system.refresh_summary_notice = AsyncMock(return_value="")
        self.system.snapshot_notice = AsyncMock(return_value="")
        await tie.pick.callback(interaction)
        channel.fetch_message.assert_awaited_once_with(101)
        self.assertEqual(interaction.message.edit.call_args.kwargs["view"].children[0].label, "Asistiré")
        meeting = self.system.store.active()[0]
        self.assertEqual(meeting["starts_at"], self.data["slot3"])
        self.system.refresh_summary_notice.assert_awaited_once_with(meeting["id"])
