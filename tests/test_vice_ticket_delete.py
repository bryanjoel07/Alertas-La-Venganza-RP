"""Closed-ticket deletion requires current staff and an explicit bound confirmation."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import discord

from esschino import StudioStore
from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_ticket_delete import ConfirmDeleteView, DeleteTicketPanel, TicketDeletion


FOOTER = 'GTA VI Latino • Puerto Rico + Latinoamérica • Fans no oficiales'
CLOSE = 'vice:v1:ticket:close'
DELETE = 'vice:v1:ticket:delete'


def missing():
    return discord.NotFound(NS(status=404, reason='Not Found'),
                            {'code': 10003, 'message': 'Unknown Channel'})


class TicketDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StudioStore(Path(self.tmp.name) / 'vice.sqlite3')
        self.store.initialize()
        self.store.put('category:closed', 88)
        for key, value in (('founder', 10), ('admin', 11), ('mod', 12), ('support', 13)):
            self.store.put('role:' + key, value)
        self.store.add_ticket(55, 999, 'comunidad')
        self.store.ticket_state(55, 'closed')
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id, self.guild.me.guild = BOT_ID, self.guild
        self.guild.me.guild_permissions = discord.Permissions(administrator=True, manage_channels=True)
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.default_role.id = GUILD_ID
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild = 88, self.guild
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.category = 55, self.guild, self.category
        self.channel.category_id = 88
        self.channel.name, self.channel.topic = '┊・🔒│cerrado-000999', 'VIce ticket closed owner=999'
        self.channel.position, self.channel.nsfw = 1, False
        self.channel.slowmode_delay = 0
        self.channel.overwrites = {self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
        self.channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, read_message_history=True, send_messages=True,
            embed_links=True, manage_channels=True)
        self.channels = {55: self.channel, 88: self.category}
        self.guild.get_channel.side_effect = self.channels.get
        async def fetch_channel(channel_id):
            if channel_id not in self.channels:
                raise missing()
            return self.channels[channel_id]
        self.guild.fetch_channel = AsyncMock(side_effect=fetch_channel)
        self.staff = self.member(77, staff=True)
        self.current = self.member(77, staff=True)
        self.guild.fetch_member = AsyncMock(side_effect=lambda user_id: self.current)
        self.bot = NS(user=NS(id=BOT_ID), add_view=Mock(), get_guild=Mock(return_value=self.guild),
                      fetch_channel=AsyncMock(side_effect=fetch_channel))
        self.messages, self.snapshots, self.deleted = [], [], []
        async def history(**kwargs):
            for message in (self.messages if kwargs.get('oldest_first') else list(reversed(self.messages))):
                yield message
        async def fetch_message(message_id):
            value = next((message for message in self.messages if message.id == message_id), None)
            if value is None:
                raise discord.NotFound(NS(status=404, reason='Not Found'),
                                       {'code': 10008, 'message': 'Unknown Message'})
            return value
        async def send(**kwargs):
            message = self.message(200 + len(self.messages), kwargs.get('embed'), view=kwargs.get('view'))
            self.messages.append(message)
            return message
        self.channel.history = Mock(side_effect=history)
        self.channel.fetch_message = AsyncMock(side_effect=fetch_message)
        self.channel.send = AsyncMock(side_effect=send)
        async def delete(**kwargs):
            self.deleted.append(dict(channel=self.channel.id, snapshots=deepcopy(self.snapshots)))
            self.channels.pop(self.channel.id, None)
        self.channel.delete = AsyncMock(side_effect=delete)
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
            return guild
        def is_staff(member):
            return (member.guild.id == GUILD_ID and (member.id == OWNER_ID
                or member.guild_permissions.administrator
                or any(role.id in {10, 11, 12, 13} for role in member.roles)))
        def authorize(i, staff=False):
            validate(i.guild)
            if i.guild_id != GUILD_ID or not isinstance(i.user, discord.Member) or i.user.bot:
                raise ValueError('wrong interaction')
            if staff and not is_staff(i.user):
                raise ValueError('staff required')
        async def call(name, *args):
            return getattr(self.store, name)(*args)
        async def track(kind, title, operation, request, snapshot=None):
            self.snapshots.append(await snapshot() if snapshot else {'kind': kind})
            return await operation()
        self.system = NS(path=self.store.path, store=self.store, bot=self.bot,
            validate_guild=validate, is_staff=is_staff, authorize=authorize,
            call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track),
            ticket_lock=asyncio.Lock(), configured=True,
            embed=lambda title, description, color=0x00D9E8: discord.Embed(
                title=title, description=description, color=color).set_footer(text=FOOTER))
        self.manager = TicketDeletion(self.system)
        await self.manager.start()

    def member(self, user_id, *, staff=False):
        member = MagicMock(spec=discord.Member)
        member.id, member.guild, member.bot = user_id, self.guild, False
        member.name, member.display_name, member.mention = 'staff', 'Staff', f'<@{user_id}>'
        member.roles = [NS(id=12)] if staff else []
        member.guild_permissions = discord.Permissions.none()
        return member

    def message(self, message_id, embed=None, *, author=BOT_ID, view=None, component=None):
        message = NS(id=message_id, channel=self.channel, guild=self.guild,
            author=NS(id=author), content='', attachments=[],
            embeds=[discord.Embed.from_dict(embed.to_dict())] if embed else [],
            components=[], created_at=datetime.now(timezone.utc), pinned=False)
        def components(value):
            if value is None:
                return []
            return [NS(children=[NS(custom_id=getattr(c, 'custom_id', None), disabled=getattr(c, 'disabled', False))
                                 for c in value.children])]
        message.components = components(view)
        if component:
            message.components = [NS(children=[NS(custom_id=component, disabled=False)])]
        async def edit(**kwargs):
            if 'embed' in kwargs:
                message.embeds = [discord.Embed.from_dict(kwargs['embed'].to_dict())]
            if 'embeds' in kwargs:
                message.embeds = [discord.Embed.from_dict(e.to_dict()) for e in kwargs['embeds']]
            if 'view' in kwargs:
                message.components = components(kwargs['view'])
            return message
        message.edit = AsyncMock(side_effect=edit)
        return message

    def interaction(self, *, user=None, panel=None, channel=None, interaction_id=1234):
        channel = channel or self.channel
        return NS(id=interaction_id, guild=self.guild, guild_id=GUILD_ID,
            user=user or self.staff, channel=channel, channel_id=channel.id,
            message=panel, response=NS(is_done=Mock(return_value=False),
                send_message=AsyncMock(), edit_message=AsyncMock(), defer=AsyncMock()),
            followup=NS(send=AsyncMock()), edit_original_response=AsyncMock())

    async def prepared(self):
        panel = await self.manager.ensure_closed_panel(self.channel)
        self.channel.send.reset_mock()
        self.system.track.reset_mock()
        self.snapshots.clear()
        return panel

    async def requested(self):
        panel = await self.prepared()
        interaction = self.interaction(panel=panel)
        view = await self.manager.request(interaction)
        self.assertIsInstance(view, ConfirmDeleteView)
        return interaction, view

    async def test_persistent_delete_view_and_request_do_not_delete_without_confirmation(self):
        self.assertTrue(DeleteTicketPanel(self.manager).is_persistent())
        self.assertEqual([c.custom_id for c in DeleteTicketPanel(self.manager).children], [DELETE])
        self.bot.add_view.assert_called_once()
        interaction, view = await self.requested()
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.followup.send.assert_awaited_once()
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])
        self.assertIs(interaction.followup.send.await_args.kwargs['view'], view)
        self.assertEqual((view.actor_id, view.channel_id, view.panel_id),
                         (self.staff.id, self.channel.id, interaction.message.id))
        self.assertEqual(view.timeout, 60)
        self.channel.delete.assert_not_awaited()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')

    async def test_regular_ticket_owner_and_stale_cached_staff_cannot_request_delete(self):
        panel = await self.prepared()
        for member in (self.member(999), self.staff):
            self.current = self.member(member.id)
            with self.subTest(user=member.id), self.assertRaises(ValueError):
                await self.manager.request(self.interaction(user=member, panel=panel))
        self.channel.delete.assert_not_awaited()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')

    async def test_foreign_guild_interaction_cannot_fetch_or_delete(self):
        panel = await self.prepared()
        interaction = self.interaction(panel=panel)
        interaction.guild, interaction.guild_id = NS(id=123, owner_id=OWNER_ID), 123
        self.guild.fetch_channel.reset_mock()
        self.guild.fetch_member.reset_mock()
        with self.assertRaises(ValueError):
            await self.manager.request(interaction)
        self.guild.fetch_channel.assert_not_awaited()
        self.guild.fetch_member.assert_not_awaited()
        self.channel.delete.assert_not_awaited()

    async def test_unregistered_open_deleted_wrong_category_or_topic_channels_rejected(self):
        panel = await self.prepared()
        cases = ('unregistered', 'open', 'deleted', 'category', 'topic')
        for case in cases:
            self.store.ticket_state(55, 'closed')
            self.channel.category_id, self.channel.topic = 88, 'VIce ticket closed owner=999'
            interaction = self.interaction(panel=panel)
            if case == 'unregistered':
                interaction.channel_id = 56
                interaction.channel = MagicMock(spec=discord.TextChannel)
                interaction.channel.id, interaction.channel.guild = 56, self.guild
                self.channels[56] = interaction.channel
            elif case in ('open', 'deleted'):
                self.store.ticket_state(55, case)
            elif case == 'category':
                self.channel.category_id = 89
            else:
                self.channel.topic = 'VIce ticket closed owner=888'
            with self.subTest(case=case), self.assertRaises(ValueError):
                await self.manager.request(interaction)
        self.channel.delete.assert_not_awaited()

    async def test_fake_non_text_channel_cannot_use_ticket_record(self):
        panel = await self.prepared()
        fake = MagicMock(spec=discord.VoiceChannel)
        fake.id, fake.guild, fake.category_id, fake.topic = 55, self.guild, 88, self.channel.topic
        self.channels[55] = fake
        with self.assertRaises(ValueError):
            await self.manager.request(self.interaction(panel=panel))
        self.channel.delete.assert_not_awaited()

    async def test_cancel_changes_nothing_and_confirmation_cannot_be_reused(self):
        interaction, view = await self.requested()
        original = deepcopy(self.store.ticket(55))
        await self.manager.cancel(interaction, view)
        self.assertTrue(view.finished)
        self.channel.delete.assert_not_awaited()
        self.assertEqual(self.store.ticket(55), original)
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        self.channel.delete.assert_not_awaited()

    async def test_expired_confirmation_cannot_delete(self):
        interaction, view = await self.requested()
        await view.on_timeout()
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        self.channel.delete.assert_not_awaited()

    async def test_cancel_cannot_claim_success_while_confirmed_delete_is_in_progress(self):
        interaction, view = await self.requested()
        started, release = asyncio.Event(), asyncio.Event()
        real_delete = self.channel.delete.side_effect
        async def paused_delete(**kwargs):
            started.set()
            await release.wait()
            return await real_delete(**kwargs)
        self.channel.delete.side_effect = paused_delete
        confirmation = self.interaction(panel=self.message(9999), interaction_id=1235)
        cancellation = self.interaction(panel=self.message(9999), interaction_id=1236)
        tasks = []
        try:
            tasks.append(asyncio.create_task(self.manager.confirm(confirmation, view)))
            await asyncio.wait_for(started.wait(), timeout=2)
            tasks.append(asyncio.create_task(self.manager.cancel(cancellation, view)))
            await asyncio.sleep(0)
            self.assertFalse(tasks[1].done())
            cancellation.response.edit_message.assert_not_awaited()
            cancellation.edit_original_response.assert_not_awaited()
            release.set()
            await asyncio.wait_for(tasks[0], timeout=2)
            with self.assertRaises(ValueError):
                await asyncio.wait_for(tasks[1], timeout=2)
            cancellation.response.edit_message.assert_not_awaited()
            cancellation.edit_original_response.assert_not_awaited()
            self.channel.delete.assert_awaited_once()
            self.assertEqual(self.store.ticket(55)['state'], 'deleted')
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_forged_or_unregistered_delete_panel_is_rejected(self):
        panel = await self.prepared()
        for message in (self.message(panel.id, panel.embeds[0], author=OWNER_ID, component=DELETE),
                        self.message(panel.id + 100, panel.embeds[0], component=DELETE)):
            with self.subTest(author=message.author.id, panel=message.id), self.assertRaises(ValueError):
                await self.manager.request(self.interaction(panel=message))
        self.channel.delete.assert_not_awaited()

    async def test_only_same_staff_confirmer_can_confirm_or_cancel(self):
        interaction, view = await self.requested()
        other = self.member(78, staff=True)
        self.current = other
        other_interaction = self.interaction(user=other, panel=interaction.message, interaction_id=1235)
        with self.assertRaises(ValueError):
            await self.manager.confirm(other_interaction, view)
        with self.assertRaises(ValueError):
            await self.manager.cancel(other_interaction, view)
        self.channel.delete.assert_not_awaited()
        self.assertFalse(view.finished)

    async def test_staff_revoked_or_ticket_reopened_after_request_aborts_confirmation(self):
        interaction, view = await self.requested()
        self.current = self.member(self.staff.id)
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        self.current = self.member(self.staff.id, staff=True)
        self.store.ticket_state(55, 'open')
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        self.channel.delete.assert_not_awaited()

    async def test_confirmation_is_bound_to_original_channel_and_panel(self):
        interaction, view = await self.requested()
        interaction.channel_id = 56
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        interaction.channel_id = 55
        record = self.store.get('ticket_delete:55')
        record['panel_id'] = 777
        self.store.put('ticket_delete:55', record)
        with self.assertRaises(ValueError):
            await self.manager.confirm(interaction, view)
        self.channel.delete.assert_not_awaited()

    async def test_confirm_tracks_before_delete_marks_tombstone_and_preserves_ticket_row(self):
        interaction, view = await self.requested()
        original = deepcopy(self.store.ticket(55))
        # Confirmation arrives from the separate ephemeral message, not the
        # original archive panel. The view binds the original panel identity.
        confirmation = self.interaction(panel=self.message(9999), interaction_id=1235)
        await self.manager.confirm(confirmation, view)
        self.channel.delete.assert_awaited_once()
        self.assertTrue(self.deleted[0]['snapshots'])
        snapshot_text = json.dumps(self.deleted[0]['snapshots'], default=str)
        self.assertIn('55', snapshot_text)
        self.assertIn('999', snapshot_text)
        self.assertIn('closed', snapshot_text)
        after = self.store.ticket(55)
        self.assertEqual(after['state'], 'deleted')
        for field in ('channel', 'owner', 'kind', 'created'):
            self.assertEqual(after[field], original[field])
        self.assertEqual(self.store.get('ticket_delete:55')['state'], 'deleted')
        self.assertTrue(view.finished)

    async def test_ready_updates_only_bot_archive_and_removes_obsolete_bot_close_button_once(self):
        starter = self.message(101, self.system.embed('🎫 Te escuchamos', 'Consulta'), component=CLOSE)
        archive = self.message(102, self.system.embed('🔒 Conversación archivada', 'Historial privado'))
        user_starter = self.message(103, starter.embeds[0], author=999, component=CLOSE)
        unrelated = self.message(104, self.system.embed('Otra tarjeta', 'No modificar'), component=CLOSE)
        self.messages.extend([starter, archive, user_starter, unrelated])
        await self.manager.ready()
        starter.edit.assert_awaited_once()
        archive.edit.assert_awaited_once()
        user_starter.edit.assert_not_awaited()
        unrelated.edit.assert_not_awaited()
        self.assertEqual(starter.components, [])
        self.assertTrue(any(c.custom_id == DELETE for row in archive.components for c in row.children))
        self.assertEqual(self.store.get('ticket_delete:55')['panel_id'], archive.id)
        self.channel.send.assert_not_awaited()
        await self.manager.ready()
        starter.edit.assert_awaited_once()
        archive.edit.assert_awaited_once()
        self.channel.delete.assert_not_awaited()

    async def test_ready_never_deletes_open_or_unregistered_archive_channels(self):
        self.store.ticket_state(55, 'open')
        await self.manager.ready()
        self.channel.send.assert_not_awaited()
        self.channel.delete.assert_not_awaited()
        self.assertIsNone(self.store.get('ticket_delete:55'))

    async def test_ready_preserves_starter_with_unknown_additional_control(self):
        starter = self.message(101, self.system.embed('🎫 Te escuchamos', 'Consulta'), component=CLOSE)
        starter.components[0].children.append(NS(custom_id='other:unrelated-control', disabled=False))
        archive = self.message(102, self.system.embed('🔒 Conversación archivada', 'Historial privado'))
        self.messages.extend([starter, archive])
        await self.manager.ready()
        starter.edit.assert_not_awaited()
        self.assertEqual([c.custom_id for c in starter.components[0].children],
                         [CLOSE, 'other:unrelated-control'])
        archive.edit.assert_awaited_once()
        self.channel.delete.assert_not_awaited()

    async def test_plain_missing_channel_is_not_treated_as_completed_delete(self):
        self.channels.pop(55)
        await self.manager.ready()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.channel.delete.assert_not_awaited()

    async def test_missing_channel_with_incomplete_intent_is_not_acknowledged_as_deleted(self):
        await self.prepared()
        record = self.store.get('ticket_delete:55')
        record.update(state='deleting', actor=77, request_id='1234', confirmation_token='token')
        # A state label and nonce without the validated pre-delete snapshot are insufficient.
        self.store.put('ticket_delete:55', record)
        self.channels.pop(55)
        await self.manager.ready()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.assertEqual(self.store.get('ticket_delete:55')['state'], 'deleting')
        self.system.track.assert_not_awaited()
        self.channel.delete.assert_not_awaited()

    async def test_delete_then_db_failure_reconciles_only_saved_pending_intent_after_404(self):
        interaction, view = await self.requested()
        real_call = self.system.call.side_effect
        failed = False
        async def interrupted(name, *args):
            nonlocal failed
            if (name == 'put' and args[0] == 'ticket_delete:55'
                    and args[1].get('state') == 'deleted' and not failed):
                failed = True
                raise OSError('crash after channel deletion')
            return await real_call(name, *args)
        self.system.call.side_effect = interrupted
        with self.assertRaises(OSError):
            await self.manager.confirm(interaction, view)
        self.channel.delete.assert_awaited_once()
        self.assertNotIn(55, self.channels)
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.assertEqual(self.store.get('ticket_delete:55')['state'], 'deleting')
        self.system.call.side_effect = real_call
        restarted = TicketDeletion(self.system)
        await restarted.start()
        await restarted.ready()
        self.assertEqual(self.store.ticket(55)['state'], 'deleted')
        self.assertEqual(self.store.get('ticket_delete:55')['state'], 'deleted')
        self.channel.delete.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
