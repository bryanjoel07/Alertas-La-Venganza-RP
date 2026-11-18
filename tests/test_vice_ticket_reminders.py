"""Real ticket state, clocks and Discord receipts exercise private reminder delivery."""
import asyncio
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord

from tests import test_vice_ticket_delete as deletion_fixture
from vice_design import BOT_ID, GUILD_ID
from vice_tickets import TicketCenter, assignment_key
from vice_ticket_reminders import TicketReminders


class TicketReminderTests(unittest.IsolatedAsyncioTestCase):
    member = deletion_fixture.TicketDeletionTests.member

    async def asyncSetUp(self):
        await deletion_fixture.TicketDeletionTests.asyncSetUp(self)
        self.now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self.clock = patch('vice_ticket_reminders.utcnow', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.store.ticket_state(55, 'open')
        with closing(self.store.db()) as db, db:
            db.execute('UPDATE esschino_tickets SET created=? WHERE channel=?',
                       (int(self.now.timestamp()), '55'))
        self.store.put('category:help', 88)
        self.channel.topic = 'VIce ticket owner=999'
        self.channel.last_message_id = None
        self.system.ready_event = asyncio.Event()
        self.system.ready_event.set()
        self.system.tickets = TicketCenter(self.system)
        self.owner = self.member(999)
        self.staff = self.member(77, staff=True)
        self.other_staff = self.member(78, staff=True)
        self.members = {999: self.owner, 77: self.staff, 78: self.other_staff}
        async def fetch_member(identifier):
            if identifier not in self.members:
                raise discord.NotFound(NS(status=404, reason='Not Found'),
                                       {'code': 10007, 'message': 'Unknown Member'})
            return self.members[identifier]
        self.guild.fetch_member = AsyncMock(side_effect=fetch_member)
        self.support = MagicMock(spec=discord.Role)
        self.support.id, self.support.guild = 13, self.guild
        self.support.name, self.support.mentionable = 'Soporte', True
        self.support.permissions = discord.Permissions(view_channel=True, read_message_history=True)
        self.guild.get_role.side_effect = lambda identifier: self.support if identifier == 13 else None
        self.guild.fetch_roles = AsyncMock(return_value=[self.support])
        self.channel.overwrites[self.support] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True)
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, mention_everyone=True)
        self.sequence = 0
        self.messages.clear()
        self.snapshots.clear()
        self.assign(77)
        async def history(**kwargs):
            messages = list(self.messages)
            for key, comparison in (('after', lambda a, b: a > b), ('before', lambda a, b: a < b)):
                bound = kwargs.get(key)
                if bound is None:
                    continue
                value = discord.utils.time_snowflake(bound, high=key == 'after') if isinstance(bound, datetime) else int(bound.id)
                messages = [m for m in messages if comparison(m.id, value)]
            messages.sort(key=lambda m: m.id, reverse=not kwargs.get('oldest_first', False))
            limit = kwargs.get('limit')
            if limit is not None:
                messages = messages[:limit]
            for message in messages:
                yield message
        self.channel.history = Mock(side_effect=history)
        self.sent_kwargs = []
        async def send(**kwargs):
            self.sent_kwargs.append(kwargs)
            message = self.add_message(BOT_ID, when=self.now, bot=True,
                                       text=kwargs.get('content', ''))
            message.embeds = [discord.Embed.from_dict(kwargs['embed'].to_dict())] if kwargs.get('embed') else []
            return message
        self.send_impl = send
        self.channel.send = AsyncMock(side_effect=send)
        self.manager = TicketReminders(self.system)
        await self.manager.start()

    async def asyncTearDown(self):
        await self.manager.close()
        await self.system.tickets.close()

    def assign(self, identifier):
        self.store.put(assignment_key(55), dict(guild=GUILD_ID, channel=55, owner='999', kind='general',
            staff_id=identifier, claimed_at=self.now.isoformat(), notice_revision='a' * 32))

    def add_message(self, author=999, *, when=None, bot=False, webhook=False,
                    kind=discord.MessageType.default, text='private question'):
        when = when or self.now
        self.sequence += 1
        identifier = discord.utils.time_snowflake(when) + self.sequence
        member = self.members.get(author) or NS(id=author, bot=bot, guild=self.guild)
        message = NS(id=identifier, channel=self.channel, guild=self.guild, author=member,
            type=kind, webhook_id=123 if webhook else None, created_at=when,
            content=text, attachments=[], embeds=[], components=[],
            is_system=lambda: kind not in (discord.MessageType.default, discord.MessageType.reply))
        self.messages.append(message)
        self.channel.last_message_id = max(m.id for m in self.messages)
        return message

    async def advance(self, *, hours=0, minutes=0, seconds=0):
        self.now += timedelta(hours=hours, minutes=minutes, seconds=seconds)
        return await self.manager.tick()

    def assert_only_user_ping(self, identifier, index=-1):
        kwargs = self.sent_kwargs[index]
        self.assertEqual(kwargs['content'], f'<@{identifier}>')
        allowed = kwargs['allowed_mentions'].to_dict()
        self.assertEqual(allowed.get('users'), [identifier])
        self.assertNotIn('everyone', allowed.get('parse', []))
        self.assertNotIn('roles', allowed.get('parse', []))

    async def test_first_response_deadline_is_two_hours_then_one_per_day(self):
        await self.manager.tick()
        await self.advance(hours=1, minutes=59, seconds=59)
        self.channel.send.assert_not_awaited()
        await self.advance(seconds=1)
        self.assertEqual(self.channel.send.await_count, 1)
        self.assert_only_user_ping(77)
        await self.advance(hours=23, minutes=59, seconds=59)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(seconds=1)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertTrue(all(call.args[0] == 'TICKET_REMINDER' for call in self.system.track.await_args_list))
        self.assertTrue(self.snapshots)

    async def test_staff_reply_stops_notices_and_followup_waits_twenty_four_hours(self):
        self.add_message(999)
        await self.manager.tick()
        self.now += timedelta(hours=1)
        self.add_message(78, kind=discord.MessageType.reply, text='staff response')
        await self.manager.tick()
        await self.advance(hours=48)
        self.channel.send.assert_not_awaited()
        self.add_message(999, text='followup question')
        await self.manager.tick()
        await self.advance(hours=23, minutes=59, seconds=59)
        self.channel.send.assert_not_awaited()
        await self.advance(seconds=1)
        self.assertEqual(self.channel.send.await_count, 1)
        self.assert_only_user_ping(77)

    async def test_owner_bumps_and_claim_are_not_staff_replies_or_clock_resets(self):
        self.add_message()
        await self.manager.tick()
        self.now += timedelta(hours=1, minutes=50)
        self.add_message(text='another bump')
        self.assign(77)
        await self.manager.tick()
        await self.advance(minutes=10)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_owner_with_staff_role_remains_the_requester(self):
        self.owner.roles = [NS(id=13)]
        self.add_message(999)
        await self.manager.tick()
        await self.advance(hours=2)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_bots_webhooks_and_system_messages_never_answer_a_ticket(self):
        self.add_message()
        self.add_message(BOT_ID, bot=True)
        self.add_message(78, webhook=True)
        self.add_message(78, kind=discord.MessageType.pins_add)
        await self.manager.tick()
        await self.advance(hours=2)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_unassigned_case_mentions_only_registered_support_role(self):
        self.assign(None)
        await self.advance(hours=2)
        self.assertEqual(self.channel.send.await_count, 1)
        kwargs = self.sent_kwargs[0]
        self.assertEqual(kwargs['content'], '<@&13>')
        allowed = kwargs['allowed_mentions'].to_dict()
        self.assertEqual(allowed.get('roles'), [13])
        self.assertNotIn('users', allowed.get('parse', []))
        self.assertNotIn('everyone', allowed.get('parse', []))

    async def test_reassignment_and_release_do_not_bypass_daily_interval(self):
        await self.advance(hours=2)
        self.assign(78)
        await self.advance(hours=1)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(hours=24)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assert_only_user_ping(78)
        self.assign(None)
        await self.advance(hours=1)
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_long_downtime_produces_one_notice_and_no_catchup_burst(self):
        await self.advance(hours=24 * 10)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.manager.tick()
        await self.manager.tick()
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(hours=23)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_closed_deleted_and_unregistered_cases_are_never_sent(self):
        for state in ('closed', 'deleted'):
            self.store.ticket_state(55, state)
            await self.advance(hours=3)
        with closing(self.store.db()) as db, db:
            db.execute('DELETE FROM esschino_tickets WHERE channel=?', ('55',))
        await self.manager.tick()
        self.channel.send.assert_not_awaited()

    async def test_public_ticket_and_foreign_extra_access_are_rejected(self):
        self.now += timedelta(hours=2)
        self.channel.overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True)
        await self.manager.tick()
        self.channel.send.assert_not_awaited()
        self.channel.overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
        stranger = MagicMock(spec=discord.Role)
        stranger.id = 500
        self.channel.overwrites[stranger] = discord.PermissionOverwrite(view_channel=True)
        await self.manager.tick()
        self.channel.send.assert_not_awaited()

    async def test_revoked_assignee_or_missing_channel_access_is_not_pinged(self):
        self.staff.roles = []
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()
        self.staff.roles = [NS(id=12)]
        self.channel.permissions_for.side_effect = lambda actor: discord.Permissions.none() if actor.id == 77 else discord.Permissions.all()
        await self.manager.tick()
        self.channel.send.assert_not_awaited()

    async def test_ticket_owner_can_never_be_the_reminder_recipient(self):
        self.owner.roles = [NS(id=13)]
        self.assign(999)
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()

    async def test_history_failure_prevents_guessing_or_notifications(self):
        async def failed(**kwargs):
            raise RuntimeError('unavailable')
            yield
        self.channel.history.side_effect = failed
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()

    async def test_foreign_guild_message_is_ignored_without_reading_ticket(self):
        foreign = NS(guild=NS(id=987654321), channel=NS(id=55), author=NS(id=999, bot=False))
        self.system.call.reset_mock()
        await self.manager.message(foreign)
        self.system.call.assert_not_awaited()
        self.channel.send.assert_not_awaited()

    async def test_restart_keeps_cooldown_and_never_persists_private_content(self):
        self.add_message(text='SECRET_PRIVATE_CASE_CONTENT')
        await self.advance(hours=2)
        await self.manager.close()
        self.manager = TicketReminders(self.system)
        await self.manager.start()
        await self.advance(hours=1)
        self.assertEqual(self.channel.send.await_count, 1)
        with closing(self.store.db()) as db:
            state = json.dumps(db.execute('SELECT key,value FROM esschino_config').fetchall())
        self.assertNotIn('SECRET_PRIVATE_CASE_CONTENT', state)

    async def test_lost_send_response_recovers_exact_message_without_duplicate(self):
        async def lost(**kwargs):
            await self.send_impl(**kwargs)
            raise asyncio.TimeoutError('response lost')
        self.channel.send.side_effect = lost
        await self.advance(hours=2)
        self.assertEqual(self.channel.send.await_count, 1)
        self.channel.send.side_effect = self.send_impl
        await self.manager.close()
        self.manager = TicketReminders(self.system)
        await self.manager.start()
        await self.advance(minutes=1)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(hours=23, minutes=58)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_discord_millisecond_timestamp_normalization_is_acknowledged(self):
        self.now = self.now.replace(microsecond=123456)
        async def normalized(**kwargs):
            result = await self.send_impl(**kwargs)
            stamp = result.embeds[0].timestamp
            result.embeds[0].timestamp = stamp.replace(microsecond=stamp.microsecond // 1000 * 1000)
            return result
        self.channel.send.side_effect = normalized
        self.assertEqual(await self.advance(hours=2), 1)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(minutes=1)
        self.assertEqual(self.channel.send.await_count, 1)

    async def test_lost_normalized_receipt_preserves_new_episode_and_daily_cooldown(self):
        self.now = self.now.replace(microsecond=123456)
        async def normalized_and_lost(**kwargs):
            result = await self.send_impl(**kwargs)
            stamp = result.embeds[0].timestamp
            result.embeds[0].timestamp = stamp.replace(microsecond=stamp.microsecond // 1000 * 1000)
            raise asyncio.TimeoutError('response lost')
        self.channel.send.side_effect = normalized_and_lost
        await self.advance(hours=2)
        self.assertEqual(self.channel.send.await_count, 1)
        self.channel.send.side_effect = self.send_impl
        self.now += timedelta(minutes=3)
        self.add_message(78, text='staff answered during disconnect')
        self.add_message(999, text='new followup during disconnect')
        await self.manager.close()
        self.manager = TicketReminders(self.system)
        await self.manager.start()
        await self.manager.tick()
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(hours=23, minutes=57)
        self.assertEqual(self.channel.send.await_count, 1)
        await self.advance(minutes=3)
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_close_at_tracked_mutation_boundary_prevents_send(self):
        async def close_before_send(kind, title, operation, request, snapshot=None):
            self.snapshots.append(deepcopy(await snapshot()))
            self.store.ticket_state(55, 'closed')
            return await operation()
        self.system.track.side_effect = close_before_send
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()

    async def test_staff_reply_at_mutation_boundary_prevents_obsolete_notice(self):
        async def reply_before_send(kind, title, operation, request, snapshot=None):
            self.snapshots.append(deepcopy(await snapshot()))
            self.add_message(78, text='Already answered')
            return await operation()
        self.system.track.side_effect = reply_before_send
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()

    async def test_assignment_change_at_mutation_boundary_never_pings_old_assignee(self):
        async def reassign_before_send(kind, title, operation, request, snapshot=None):
            self.snapshots.append(deepcopy(await snapshot()))
            self.assign(78)
            return await operation()
        self.system.track.side_effect = reassign_before_send
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()

    async def test_bounded_history_catches_up_before_deciding_a_notice_is_due(self):
        for _ in range(1001):
            self.add_message(BOT_ID, bot=True)
        self.add_message(78, when=self.now + timedelta(hours=1), text='Answered after a long history')
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()
        await self.manager.tick()
        self.channel.send.assert_not_awaited()

    async def test_ambiguous_former_staff_reply_suppresses_guessing_initial_deadline(self):
        self.other_staff.roles = []
        self.add_message(78, text='An earlier reply whose staff identity cannot be verified')
        await self.advance(hours=2)
        self.channel.send.assert_not_awaited()
        await self.advance(hours=24)
        self.channel.send.assert_not_awaited()

    async def test_reply_during_final_recipient_lookup_is_seen_before_send(self):
        self.add_message(999)
        original = self.guild.fetch_member.side_effect
        lookups = 0
        async def fetch_member(identifier):
            nonlocal lookups
            if identifier == 77:
                lookups += 1
                if lookups == 2:
                    self.add_message(78, text='Answered while the recipient was being revalidated')
            return await original(identifier)
        self.guild.fetch_member.side_effect = fetch_member
        await self.advance(hours=2)
        self.assertEqual(lookups, 2)
        self.channel.send.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
