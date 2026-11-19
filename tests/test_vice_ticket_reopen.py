"""Reopening preserves the same private case and recovers only saved intents."""
from copy import deepcopy
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from tests import test_vice_ticket_delete as deletion_fixture
from vice_channel_style import format_name
from vice_design import BOT_ID, GUILD_ID, TICKET_OPEN_PREFIX, TICKET_CLOSED_PREFIX
from vice_ticket_delete import REOPEN_CUSTOM_ID, REOPEN_TITLE
from vice_ticket_feedback import TicketFeedback
from vice_ticket_reopen import TicketReopen, record_key
from vice_tickets import TicketCenter, OpenTicketPanel, panel_key, assignment_key, controls, VERSION


class TicketReopenTests(unittest.IsolatedAsyncioTestCase):
    # Reuse setup/helpers without inheriting and rerunning the deletion suite.
    member = deletion_fixture.TicketDeletionTests.member
    message = deletion_fixture.TicketDeletionTests.message
    interaction = deletion_fixture.TicketDeletionTests.interaction

    async def asyncSetUp(self):
        await deletion_fixture.TicketDeletionTests.asyncSetUp(self)
        self.deletion = self.manager
        self.bot.fetch_guild = AsyncMock(return_value=self.guild)
        self.owner = self.member(999)
        self.assignee = self.member(78, staff=True)
        async def fetch_member(user_id):
            if int(user_id) == self.staff.id:
                return self.current
            if int(user_id) == self.assignee.id:
                return self.assignee
            if int(user_id) == self.owner.id:
                return self.owner
            raise discord.NotFound(NS(status=404, reason='Not Found'),
                                   {'code': 10007, 'message': 'Unknown Member'})
        self.guild.fetch_member.side_effect = fetch_member
        self.help_category = MagicMock(spec=discord.CategoryChannel)
        self.help_category.id, self.help_category.guild = 80, self.guild
        self.channels[80] = self.help_category
        self.store.put('category:help', 80)
        self.roles = {}
        for role_id in (10, 11, 12, 13):
            role = MagicMock(spec=discord.Role)
            role.id, role.guild = role_id, self.guild
            self.roles[role_id] = role
        self.guild.get_role.side_effect = self.roles.get
        def overwrites(guild, policy, owner):
            rules = {guild.default_role: discord.PermissionOverwrite(view_channel=False,
                read_message_history=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=True, manage_messages=True)}
            for role in self.roles.values():
                rules[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=policy != 'closed')
            rules[owner] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                send_messages=policy != 'closed', attach_files=True, embed_links=True)
            return rules
        self.system.overwrites = overwrites
        self.channel.overwrites = overwrites(self.guild, 'closed', self.owner)
        async def edit_channel(**kwargs):
            self.assertTrue(self.store.get(record_key(55)), 'Intent must be durable before Discord edit')
            self.assertTrue(self.snapshots, 'Before-state must be journaled before Discord edit')
            for key in ('name', 'topic', 'overwrites'):
                if key in kwargs:
                    setattr(self.channel, key, kwargs[key])
            if 'category' in kwargs:
                self.channel.category, self.channel.category_id = kwargs['category'], kwargs['category'].id
            return self.channel
        self.channel.edit = AsyncMock(side_effect=edit_channel)
        self.system.ticket_deletion = self.deletion
        self.system.tickets = TicketCenter(self.system)
        self.system.ticket_feedback = TicketFeedback(self.system)
        self.addAsyncCleanup(self.system.ticket_feedback.close)
        self.system.ticket_reminders = NS(reopened=AsyncMock())
        self.system.ticket_dashboard = NS(tick=AsyncMock())
        self.reopen = TicketReopen(self.system)
        self.system.ticket_reopen = self.reopen
        self.system.ready_event = asyncio.Event()
        self.addAsyncCleanup(self.reopen.close)
        assignment = dict(guild=GUILD_ID, channel=55, owner='999', kind='general',
                          staff_id=78, staff_name='Responsable', claimed_at='2026-11-17T01:00:00+00:00')
        self.store.put(assignment_key(55), assignment)
        self.starter = self.message(101, self.system.tickets.starter_embed(self.store.ticket(55), assignment))
        self.store.put(panel_key(55), dict(guild=GUILD_ID, channel=55, owner='999', panel_id=101, version=VERSION))
        self.user_message = self.message(102, author=999)
        self.user_message.content = 'Consulta original que debe conservarse.'
        self.messages.extend([self.starter, self.user_message])
        self.closed_panel = await self.deletion.ensure_closed_panel(self.channel)
        self.channel.send.reset_mock()
        self.snapshots.clear()
        self.system.track.reset_mock()

    async def run_reopen(self, **kwargs):
        interaction = self.interaction(panel=self.closed_panel, **kwargs)
        await self.reopen.request(interaction)
        return interaction

    async def close_again(self):
        self.channel.name = format_name(TICKET_CLOSED_PREFIX + str(self.owner.id)[-6:])
        self.channel.category, self.channel.category_id = self.category, self.category.id
        self.channel.topic = 'VIce ticket closed owner=999'
        self.channel.overwrites = self.system.overwrites(self.guild, 'closed', self.owner)
        self.store.ticket_state(55, 'closed')
        row = self.store.ticket(55)
        await self.system.ticket_feedback.capture_close(self.channel, row, self.staff.id)
        await self.system.tickets.archive_controls(self.channel, row)
        await self.deletion.ensure_closed_panel(self.channel, row)

    async def test_same_channel_history_created_and_responsible_are_preserved(self):
        before_row, before_assignment = self.store.ticket(55), self.store.get(assignment_key(55))
        before_ids = [message.id for message in self.messages]
        interaction = await self.run_reopen()
        after = self.store.ticket(55)
        self.assertEqual(after['state'], 'open')
        self.assertEqual({k: v for k, v in after.items() if k != 'state'},
                         {k: v for k, v in before_row.items() if k != 'state'})
        self.assertEqual(self.store.get(assignment_key(55)), before_assignment)
        self.assertEqual([message.id for message in self.messages], before_ids)
        self.assertEqual(self.user_message.content, 'Consulta original que debe conservarse.')
        self.user_message.edit.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        self.channel.delete.assert_not_awaited()
        self.assertEqual(self.channel.category_id, 80)
        self.assertEqual(self.channel.topic, 'VIce ticket owner=999')
        self.assertEqual(self.channel.name, format_name(TICKET_OPEN_PREFIX + '999'))
        self.assertFalse(self.channel.overwrites[self.guild.default_role].view_channel)
        self.assertTrue(self.channel.overwrites[self.owner].send_messages)
        self.assertEqual(self.closed_panel.embeds[0].title, REOPEN_TITLE)
        self.assertEqual(self.closed_panel.components, [])
        self.assertEqual({key for key, _ in controls(self.starter)},
                         {child.custom_id for child in OpenTicketPanel(self.system.tickets).children})
        self.assertEqual(self.store.get(record_key(55))['state'], 'completed')
        self.system.ticket_reminders.reopened.assert_awaited_once()
        self.system.ticket_dashboard.tick.assert_awaited_once()
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])

    async def test_duplicate_request_does_not_edit_again_or_reset_timing(self):
        await self.run_reopen()
        before = deepcopy(self.store.get(record_key(55)))
        with self.assertRaisesRegex(ValueError, 'ya está abierto'):
            await self.run_reopen(interaction_id=1235)
        self.channel.edit.assert_awaited_once()
        self.system.ticket_reminders.reopened.assert_awaited_once()
        self.assertEqual(self.store.get(record_key(55)), before)

    async def test_lost_channel_edit_response_recovers_without_second_edit(self):
        real_edit = self.channel.edit.side_effect
        async def lost(**kwargs):
            await real_edit(**kwargs)
            raise OSError('response lost after accepted Discord edit')
        self.channel.edit.side_effect = lost
        with self.assertRaises(OSError):
            await self.run_reopen()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.assertEqual(self.store.get(record_key(55))['state'], 'pending')
        self.assertEqual(self.channel.category_id, 80)
        self.channel.edit.side_effect = real_edit
        restarted = TicketReopen(self.system)
        self.assertEqual(await restarted.ready(), 1)
        self.channel.edit.assert_awaited_once()
        self.assertEqual(self.store.ticket(55)['state'], 'open')
        self.assertEqual(self.store.get(record_key(55))['state'], 'completed')
        self.assertEqual(await restarted.ready(), 0)
        self.system.ticket_reminders.reopened.assert_awaited_once()

    async def test_pending_recovery_respects_manual_edits_and_never_recreates_missing_channel(self):
        self.channel.edit.side_effect = OSError('failed before Discord accepted the edit')
        with self.assertRaises(OSError):
            await self.run_reopen()
        self.channel.name = 'Nombre cambiado manualmente'
        restarted = TicketReopen(self.system)
        with self.assertLogs('ViceDistrict.ticket_reopen', level='WARNING'):
            self.assertEqual(await restarted.ready(), 0)
        self.assertEqual(self.channel.name, 'Nombre cambiado manualmente')
        self.channel.edit.assert_awaited_once()
        self.channels.pop(55)
        with self.assertLogs('ViceDistrict.ticket_reopen', level='WARNING'):
            self.assertEqual(await restarted.ready(), 0)
        self.guild.create_text_channel.assert_not_called()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.assertEqual(self.store.get(record_key(55))['state'], 'pending')

    async def test_recovery_revalidates_actor_before_retrying_saved_edit(self):
        self.channel.edit.side_effect = OSError('failed before Discord accepted the edit')
        with self.assertRaises(OSError):
            await self.run_reopen()
        self.current = self.member(77)
        with self.assertLogs('ViceDistrict.ticket_reopen', level='WARNING'):
            self.assertEqual(await TicketReopen(self.system).ready(), 0)
        self.channel.edit.assert_awaited_once()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.system.ticket_reminders.reopened.assert_not_awaited()

    async def test_reclose_then_reopen_reuses_both_panels_and_keeps_previous_cycle(self):
        await self.run_reopen()
        first = deepcopy(self.store.get(record_key(55)))
        await self.close_again()
        self.assertIn(REOPEN_CUSTOM_ID, {key for key, _ in controls(self.closed_panel)})
        self.assertEqual(self.starter.components, [])
        await self.run_reopen(interaction_id=1235)
        second = self.store.get(record_key(55))
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual(self.store.get(f'ticket_reopen:history:55:{first["revision"]}'), first)
        self.assertEqual(second['panel_id'], first['panel_id'])
        self.assertEqual(self.store.get(panel_key(55))['panel_id'], self.starter.id)
        self.assertEqual(len(self.messages), 3)
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.channel.edit.await_count, 2)

    async def test_old_delete_confirmation_cannot_delete_after_reopen_and_reclose(self):
        view = await self.deletion.request(self.interaction(panel=self.closed_panel))
        await self.run_reopen(interaction_id=1235)
        await self.close_again()
        with self.assertRaises(ValueError):
            await self.deletion.confirm(self.interaction(panel=self.message(8888), interaction_id=1236), view)
        self.channel.delete.assert_not_awaited()
        self.system.ticket_archive.backup.assert_not_awaited()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')

    async def test_missing_owner_and_demoted_actor_block_without_rename(self):
        actual_fetch = self.guild.fetch_member.side_effect
        async def missing_owner(user_id):
            if int(user_id) == 999:
                raise discord.NotFound(NS(status=404, reason='Not Found'),
                                       {'code': 10007, 'message': 'Unknown Member'})
            return await actual_fetch(user_id)
        self.guild.fetch_member.side_effect = missing_owner
        with self.assertRaisesRegex(ValueError, 'ya no está'):
            await self.run_reopen()
        self.guild.fetch_member.side_effect = actual_fetch
        self.current = self.member(77)
        with self.assertRaises(ValueError):
            await self.run_reopen()
        self.channel.edit.assert_not_awaited()
        self.assertIsNone(self.store.get(record_key(55)))

    async def test_demoted_assignee_is_retained_in_history_without_restoring_access(self):
        previous = self.store.get(assignment_key(55))
        self.assignee.roles = []
        await self.run_reopen()
        receipt = self.store.get(record_key(55))
        self.assertEqual(self.store.get(f'ticket_reopen:assignment:55:{receipt["revision"]}'), previous)
        self.assertIsNone(self.store.get(assignment_key(55))['staff_id'])
        self.assertNotIn(self.assignee.id, [target.id for target in self.channel.overwrites])
        self.assertIn('Sin asignar', self.closed_panel.embeds[0].description)

    async def test_foreign_interaction_public_channel_and_tampered_source_block(self):
        interaction = self.interaction(panel=self.closed_panel)
        interaction.guild_id = 123
        self.guild.fetch_channel.reset_mock()
        with self.assertRaises(ValueError):
            await self.reopen.request(interaction)
        self.guild.fetch_channel.assert_not_awaited()
        self.channel.overwrites[self.guild.default_role].view_channel = True
        with self.assertRaises(ValueError):
            await self.run_reopen()
        self.channel.overwrites[self.guild.default_role].view_channel = False
        for source in (self.message(self.closed_panel.id, author=999), self.message(99999)):
            with self.assertRaises(ValueError):
                await self.reopen.request(self.interaction(panel=source))
        self.closed_panel.embeds[0].title = 'Unrelated card'
        with self.assertRaises(ValueError):
            await self.run_reopen()
        self.channel.edit.assert_not_awaited()
        self.assertIsNone(self.store.get(record_key(55)))

    async def test_other_open_case_or_missing_help_role_prevents_reopen(self):
        self.store.add_ticket(56, 999, 'general')
        with self.assertRaisesRegex(ValueError, 'otro ticket abierto'):
            await self.run_reopen()
        self.store.ticket_state(56, 'closed')
        self.roles.pop(13)
        with self.assertRaisesRegex(ValueError, 'Falta un rol'):
            await self.run_reopen()
        self.channel.edit.assert_not_awaited()

    async def test_partial_reopen_suppresses_notices_claims_and_delete_until_recovered(self):
        self.system.ticket_reminders.reopened.side_effect = TimeoutError('temporary lookup failure')
        with self.assertRaises(TimeoutError):
            await self.run_reopen()
        self.assertEqual(self.store.ticket(55)['state'], 'open')
        self.assertEqual(self.store.get(record_key(55))['state'], 'pending')
        row = self.store.ticket(55)
        self.assertFalse(await self.system.tickets.pending_notice(row))
        self.assertIsNone(await self.system.tickets.claim_notice(self.channel, row))
        with self.assertRaises(ValueError):
            await self.system.tickets.action_context(self.interaction(panel=self.starter))
        with self.assertRaises(ValueError):
            await self.deletion.request(self.interaction(panel=self.closed_panel))
        self.channel.send.assert_not_awaited()
        self.system.ticket_reminders.reopened.side_effect = None
        await self.reopen.ready()
        self.assertEqual(self.store.get(record_key(55))['state'], 'completed')
        self.channel.edit.assert_awaited_once()

    async def test_closed_panel_reopen_button_calls_authorized_handler(self):
        from vice_ticket_delete import DeleteTicketPanel
        interaction = self.interaction(panel=self.closed_panel)
        handler = AsyncMock()
        self.system.ticket_reopen = NS(request=handler)
        button = next(item for item in DeleteTicketPanel(self.deletion).children
                      if item.custom_id == REOPEN_CUSTOM_ID)
        await button.callback(interaction)
        handler.assert_awaited_once_with(interaction)
        self.channel.edit.assert_not_awaited()

    async def test_delayed_retry_of_still_closed_channel_starts_a_fresh_wait(self):
        apply_edit = self.channel.edit.side_effect
        self.channel.edit.side_effect = OSError('edit never reached Discord')
        with self.assertRaises(OSError):
            await self.run_reopen()
        record = self.store.get(record_key(55))
        old = datetime.now(timezone.utc) - timedelta(days=2)
        record.update(reopened_at=old.isoformat(), attempted_at=old.isoformat())
        self.store.put(record_key(55), record)
        self.channel.edit.side_effect = apply_edit
        await self.reopen.ready()
        recovered = self.store.get(record_key(55))
        self.assertEqual(recovered['state'], 'completed')
        self.assertGreater(datetime.fromisoformat(recovered['reopened_at']), old + timedelta(days=1))
        self.assertEqual(recovered['reopened_at'], recovered['attempted_at'])


if __name__ == '__main__':
    unittest.main()
