"""Categories and claims stay private, durable, and bound to registered tickets."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

import discord

from tests import test_vice_ticket_delete as deletion_fixture
from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_tickets import (CLAIM_ID, CLOSE_ID, FOOTER, KINDS, LEGACY_CLOSE_ID, LEGACY_FOOTER,
                          RELEASE_ID, OpenTicketPanel, TicketCategories, TicketCenter,
                          assignment_key, controls, panel_key)


class TicketCenterTests(unittest.IsolatedAsyncioTestCase):
    member = deletion_fixture.TicketDeletionTests.member
    message = deletion_fixture.TicketDeletionTests.message
    interaction = deletion_fixture.TicketDeletionTests.interaction

    async def asyncSetUp(self):
        await deletion_fixture.TicketDeletionTests.asyncSetUp(self)
        self.store.ticket_state(55, 'open')
        self.store.put('category:help', 88)
        self.channel.topic = 'VIce ticket owner=999'
        self.channel.mention = '<#55>'
        self.system.open_ticket = AsyncMock(return_value=self.channel)
        self.system.close_ticket = AsyncMock()
        self.manager = TicketCenter(self.system)
        self.bot.add_view.reset_mock()
        await self.manager.start()

    async def prepared(self):
        panel = await self.manager.ensure_open_panel(self.channel)
        self.channel.send.reset_mock()
        self.system.track.reset_mock()
        self.snapshots.clear()
        return panel

    def legacy(self, message_id=123, *, author=BOT_ID, component=LEGACY_CLOSE_ID):
        embed = discord.Embed(title='🎫 Te escuchamos', description='Mensaje original').set_footer(text=LEGACY_FOOTER)
        return self.message(message_id, embed, author=author, component=component)

    async def test_persistent_controls_registered_once_with_distinct_close_id(self):
        await self.manager.start()
        self.bot.add_view.assert_called_once()
        panel = self.bot.add_view.call_args.args[0]
        self.assertTrue(panel.is_persistent())
        self.assertEqual([(item.custom_id, item.disabled) for item in panel.children],
                         [(CLAIM_ID, False), (RELEASE_ID, True), (CLOSE_ID, False)])
        self.assertNotEqual(CLOSE_ID, LEGACY_CLOSE_ID)

    async def test_categories_private_owner_bound_and_only_four_allowed_inputs(self):
        interaction = self.interaction(user=self.member(999))
        view = await self.manager.show_categories(interaction)
        self.assertIsInstance(view, TicketCategories)
        self.assertEqual(view.actor_id, 999)
        kwargs = interaction.response.send_message.await_args.kwargs
        self.assertTrue(kwargs['ephemeral'])
        self.assertFalse(kwargs['allowed_mentions'].everyone)
        self.assertEqual({option.value: option.label for option in view.choose.options}, KINDS)
        for value in ('comunidad', 'admin', '', None, ['general']):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.validate_kind(value)
        with self.assertRaises(ValueError):
            await view.interaction_check(self.interaction(user=self.member(998)))
        view.choose._values = ['technical']
        await view.choose.callback(interaction)
        self.system.open_ticket.assert_awaited_once_with(interaction, kind='technical')
        self.assertIsNone(interaction.edit_original_response.await_args.kwargs['view'])
        self.assertIn('<#55>', interaction.edit_original_response.await_args.kwargs['content'])

    async def test_forged_category_rejected_before_open_and_close_routes_to_existing_system(self):
        interaction = self.interaction(user=self.member(999))
        view = TicketCategories(self.manager, 999)
        view.choose._values = ['administrator']
        with self.assertRaises(ValueError):
            await view.choose.callback(interaction)
        self.system.open_ticket.assert_not_awaited()
        await OpenTicketPanel(self.manager).close_ticket.callback(interaction)
        self.system.close_ticket.assert_awaited_once_with(interaction)

    async def test_legacy_starter_updates_in_place_and_ready_is_idempotent(self):
        old = self.legacy()
        user_copy = self.legacy(124, author=999)
        unknown_bot = self.legacy(125, component='different:control')
        self.messages.extend([old, user_copy, unknown_bot])
        self.assertEqual(await self.manager.ready(), 1)
        self.assertEqual(self.store.ticket(55)['kind'], 'comunidad')
        self.assertEqual(self.store.get(panel_key(55))['panel_id'], old.id)
        self.assertEqual(old.embeds[0].footer.text, FOOTER)
        self.assertEqual(old.embeds[0].fields[0].value, '💬 Ayuda general')
        self.assertEqual(old.embeds[0].fields[1].value, 'Sin asignar')
        self.assertEqual(len(controls(old)), 3)
        self.assertEqual(self.snapshots[0]['panel']['embeds'][0]['description'], 'Mensaje original')
        await self.manager.ready()
        old.edit.assert_awaited_once()
        user_copy.edit.assert_not_awaited()
        unknown_bot.edit.assert_not_awaited()
        self.channel.send.assert_not_awaited()

    async def test_new_panel_has_category_and_no_notification_mentions(self):
        self.store.add_ticket(56, 998, 'technical')
        panel = await self.prepared()
        self.assertEqual(panel.embeds[0].title, '🎫 Te escuchamos')
        self.assertIn('<@999>', panel.embeds[0].description)
        self.assertEqual(self.store.get(panel_key(55))['owner'], '999')
        self.assertEqual(len(self.messages), 1)
        await self.manager.ensure_open_panel(self.channel)
        self.channel.send.assert_not_awaited()
        panel.edit.assert_not_awaited()

    async def test_foreign_guild_and_changed_owner_reject_before_any_callback_or_db_mutation(self):
        panel = await self.prepared()
        self.guild.fetch_member.reset_mock()
        self.guild.fetch_channel.reset_mock()
        self.system.call.reset_mock()
        for action in (self.manager.show_categories, self.manager.claim, self.manager.release):
            interaction = self.interaction(panel=panel)
            interaction.guild_id, interaction.guild = 111, NS(id=111, owner_id=OWNER_ID)
            with self.assertRaises(ValueError):
                await action(interaction)
        self.guild.owner_id = 111
        with self.assertRaises(ValueError):
            await self.manager.ensure_open_panel(self.channel)
        self.guild.fetch_member.assert_not_awaited()
        self.guild.fetch_channel.assert_not_awaited()
        self.system.call.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_closed_deleted_wrong_topic_category_and_unregistered_cannot_claim(self):
        panel = await self.prepared()
        for case in ('closed', 'deleted', 'topic', 'category', 'unregistered'):
            self.store.ticket_state(55, 'open')
            self.channel.category_id, self.channel.topic = 88, 'VIce ticket owner=999'
            interaction = self.interaction(panel=panel)
            if case in ('closed', 'deleted'):
                self.store.ticket_state(55, case)
            elif case == 'topic':
                self.channel.topic = 'VIce ticket owner=998'
            elif case == 'category':
                self.channel.category_id = 89
            else:
                self.channel.id = 56
            with self.subTest(case=case), self.assertRaises(ValueError):
                await self.manager.claim(interaction)
            self.channel.id = 55
        self.assertIsNone(self.store.get(assignment_key(55)))
        panel.edit.assert_not_awaited()

    async def test_regular_owner_and_revoked_cached_staff_cannot_claim(self):
        panel = await self.prepared()
        for actor in (self.member(999), self.staff):
            self.current = self.member(actor.id)
            with self.subTest(actor=actor.id), self.assertRaises(ValueError):
                await self.manager.claim(self.interaction(user=actor, panel=panel))
        self.assertIsNone(self.store.get(assignment_key(55)))
        panel.edit.assert_not_awaited()
        self.guild.fetch_member.assert_awaited()

    async def test_claim_persists_responsible_and_journal_before_state_then_updates_panel(self):
        panel = await self.prepared()
        interaction = self.interaction(panel=panel)
        await self.manager.claim(interaction)
        assignment = self.store.get(assignment_key(55))
        self.assertEqual((assignment['guild'], assignment['channel'], assignment['owner'], assignment['staff_id']),
                         (GUILD_ID, 55, '999', 77))
        self.assertEqual(assignment['kind'], 'general')
        self.assertEqual(panel.embeds[0].fields[1].value, '<@77>')
        self.assertEqual(controls(panel), [(CLAIM_ID, True), (RELEASE_ID, False), (CLOSE_ID, False)])
        self.assertIsNone(self.snapshots[0]['assignment'])
        self.assertEqual(self.snapshots[0]['panel']['id'], panel.id)
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        self.assertFalse(panel.edit.await_args.kwargs['allowed_mentions'].users)
        before = deepcopy(assignment)
        await self.manager.claim(self.interaction(panel=panel))
        self.assertEqual(self.store.get(assignment_key(55)), before)
        panel.edit.assert_awaited_once()

    async def test_two_staff_claims_race_only_one_assignment_wins(self):
        panel = await self.prepared()
        members = {77: self.current, 78: self.member(78, staff=True)}
        self.guild.fetch_member.side_effect = lambda user_id: members[user_id]
        results = await asyncio.gather(*(self.manager.claim(self.interaction(user=member, panel=panel,
            interaction_id=member.id)) for member in members.values()), return_exceptions=True)
        self.assertEqual(sum(result is None for result in results), 1)
        self.assertEqual(sum(isinstance(result, ValueError) for result in results), 1)
        self.assertEqual(self.store.get(assignment_key(55))['staff_id'], 77)
        self.assertEqual(panel.embeds[0].fields[1].value, '<@77>')
        panel.edit.assert_awaited_once()

    async def test_other_moderator_cannot_release_but_fresh_admin_can(self):
        panel = await self.prepared()
        await self.manager.claim(self.interaction(panel=panel))
        other = self.member(78, staff=True)
        self.current = other
        with self.assertRaises(ValueError):
            await self.manager.release(self.interaction(user=other, panel=panel))
        self.assertEqual(self.store.get(assignment_key(55))['staff_id'], 77)
        other.roles = [NS(id=11)]
        await self.manager.release(self.interaction(user=other, panel=panel))
        assignment = self.store.get(assignment_key(55))
        self.assertIsNone(assignment['staff_id'])
        self.assertEqual(assignment['released_by'], 78)
        self.assertTrue(assignment['claimed_at'])
        self.assertEqual(panel.embeds[0].fields[1].value, 'Sin asignar')

    async def test_assignee_can_release_and_cached_admin_without_current_role_cannot(self):
        panel = await self.prepared()
        await self.manager.claim(self.interaction(panel=panel))
        cached_admin = self.member(78, staff=True)
        cached_admin.roles = [NS(id=11)]
        self.current = self.member(78, staff=True)
        with self.assertRaises(ValueError):
            await self.manager.release(self.interaction(user=cached_admin, panel=panel))
        self.current = self.member(77, staff=True)
        await self.manager.release(self.interaction(panel=panel))
        self.assertIsNone(self.store.get(assignment_key(55))['staff_id'])

    async def test_forged_panel_or_corrupt_assignment_never_changes_responsibility(self):
        panel = await self.prepared()
        fake = self.message(9999, panel.embeds[0], view=OpenTicketPanel(self.manager))
        with self.assertRaises(ValueError):
            await self.manager.claim(self.interaction(panel=fake))
        panel.author.id = 123
        with self.assertRaises(ValueError):
            await self.manager.claim(self.interaction(panel=panel))
        panel.author.id = BOT_ID
        self.store.put(assignment_key(55), dict(guild=123, channel=55, owner='999', kind='general', staff_id=78))
        with self.assertRaises(ValueError):
            await self.manager.claim(self.interaction(panel=panel))
        self.assertEqual(self.store.get(assignment_key(55))['guild'], 123)
        panel.edit.assert_not_awaited()

    async def test_failed_discord_edit_keeps_assignment_and_ready_repairs_same_panel(self):
        panel = await self.prepared()
        edit = panel.edit.side_effect
        panel.edit.side_effect = RuntimeError('network interruption')
        with self.assertRaises(RuntimeError):
            await self.manager.claim(self.interaction(panel=panel))
        self.assertEqual(self.store.get(assignment_key(55))['staff_id'], 77)
        self.assertEqual(panel.embeds[0].fields[1].value, 'Sin asignar')
        panel.edit.side_effect = edit
        await self.manager.ready()
        self.assertEqual(panel.embeds[0].fields[1].value, '<@77>')
        self.assertEqual(self.store.get(panel_key(55))['panel_id'], panel.id)
        self.assertEqual(len(self.messages), 1)
        self.channel.send.assert_not_awaited()

    async def test_accepted_send_with_failed_panel_record_recovers_without_duplicate(self):
        call = self.system.call.side_effect
        async def failing(name, *args):
            if name == 'put' and args[0] == panel_key(55):
                raise RuntimeError('database write interrupted')
            return await call(name, *args)
        self.system.call.side_effect = failing
        with self.assertRaises(RuntimeError):
            await self.manager.ensure_open_panel(self.channel)
        self.assertEqual(len(self.messages), 1)
        self.assertIsNone(self.store.get(panel_key(55)))
        self.system.call.side_effect = call
        await self.manager.ready()
        self.assertEqual(len(self.messages), 1)
        self.channel.send.assert_awaited_once()
        self.assertEqual(self.store.get(panel_key(55))['panel_id'], self.messages[0].id)
        self.messages[0].edit.assert_not_awaited()

    async def test_stored_panel_replaced_by_foreign_content_is_not_edited_or_recreated(self):
        panel = await self.prepared()
        panel.content = 'contenido ajeno'
        with self.assertRaises(ValueError):
            await self.manager.ensure_open_panel(self.channel)
        panel.edit.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.store.get(panel_key(55))['panel_id'], panel.id)

    async def test_archive_removes_only_registered_known_controls_preserving_assignment_and_history(self):
        panel = await self.prepared()
        await self.manager.claim(self.interaction(panel=panel))
        original_assignment = self.store.get(assignment_key(55))
        content = deepcopy(panel.embeds[0].to_dict())
        user_message = self.message(999, panel.embeds[0], author=999, view=OpenTicketPanel(self.manager))
        self.messages.append(user_message)
        self.store.ticket_state(55, 'closed')
        self.channel.topic = 'VIce ticket closed owner=999'
        panel.edit.reset_mock()
        self.snapshots.clear()
        await self.manager.archive_controls(self.channel)
        self.assertEqual(panel.components, [])
        self.assertEqual(panel.embeds[0].to_dict(), content)
        self.assertEqual(self.store.get(assignment_key(55)), original_assignment)
        self.assertEqual(self.snapshots[0]['panel']['controls'][0]['custom_id'], CLAIM_ID)
        await self.manager.archive_controls(self.channel)
        panel.edit.assert_awaited_once()
        user_message.edit.assert_not_awaited()
        self.channel.delete.assert_not_awaited()

    async def test_archive_rejects_open_and_unknown_controls_or_wrong_closed_topic(self):
        panel = await self.prepared()
        with self.assertRaises(ValueError):
            await self.manager.archive_controls(self.channel)
        self.store.ticket_state(55, 'closed')
        self.channel.topic = 'VIce ticket closed owner=998'
        with self.assertRaises(ValueError):
            await self.manager.archive_controls(self.channel)
        self.channel.topic = 'VIce ticket closed owner=999'
        panel.components[0].children.append(NS(custom_id='unrelated:control', disabled=False))
        with self.assertRaises(ValueError):
            await self.manager.archive_controls(self.channel)
        panel.edit.assert_not_awaited()

    async def test_ready_does_not_touch_closed_deleted_or_missing_channels(self):
        await self.prepared()
        self.store.ticket_state(55, 'closed')
        self.store.add_ticket(56, 999, 'general')
        self.store.ticket_state(56, 'deleted')
        self.store.add_ticket(57, 999, 'general')
        self.guild.fetch_channel.reset_mock()
        self.assertEqual(await self.manager.ready(), 0)
        self.guild.fetch_channel.assert_awaited_once_with(57)
        self.channel.send.assert_not_awaited()
        self.channel.delete.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
