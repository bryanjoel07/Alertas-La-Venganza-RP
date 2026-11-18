"""The staff queue stays private, navigable, durable and truthful."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock

import discord

from esschino import StudioStore
from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_readonly import WRITE_FLAGS
from vice_tickets import TicketCenter, assignment_key
from vice_ticket_dashboard import (BUTTONS, DashboardView, FOOTER, KEY, NAME,
                                  PAGE_SIZE, TITLE, TOPIC, TicketDashboard)


async def history(items):
    for item in items:
        yield item


def missing(code=10003):
    return discord.NotFound(NS(status=404, reason='Not Found'), {'code': code, 'message': 'missing'})


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StudioStore(Path(self.tmp.name) / 'vice.sqlite3')
        self.store.initialize()
        for key, value in [('category:team', 80), ('category:help', 88),
                           ('role:founder', 10), ('role:admin', 11), ('role:mod', 12), ('role:support', 13)]:
            self.store.put(key, value)
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.roles = {}
        for role_id in (GUILD_ID, 10, 11, 12, 13):
            role = MagicMock(spec=discord.Role)
            role.id, role.guild = role_id, self.guild
            self.roles[role_id] = role
        self.guild.default_role = self.roles[GUILD_ID]
        self.guild.get_role.side_effect = self.roles.get
        self.guild.me = self.member(BOT_ID)
        self.guild.me.bot = True
        self.members = {77: self.member(77, staff=True), 999: self.member(999)}
        self.guild.fetch_member = AsyncMock(side_effect=lambda key: self.members[key])
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild = 80, self.guild
        self.channels, self.sent, self.entries, self.snapshots = {80: self.category}, [], [], []
        async def fetch_channel(key):
            if key not in self.channels:
                raise missing()
            return self.channels[key]
        self.guild.fetch_channel = AsyncMock(side_effect=fetch_channel)
        self.guild.fetch_channels = AsyncMock(side_effect=lambda: list(self.channels.values()))
        self.guild.audit_logs.side_effect = lambda **kwargs: history(self.entries)
        async def create(name, **kwargs):
            channel = self.channel(70, name, category=kwargs['category'].id, topic=kwargs['topic'])
            channel.overwrites = kwargs['overwrites']
            self.channels[channel.id] = channel
            self.entries.append(NS(user=NS(id=BOT_ID), reason=kwargs['reason'], target=NS(id=channel.id)))
            return channel
        self.create = create
        self.guild.create_text_channel = AsyncMock(side_effect=create)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=Mock(return_value=self.guild), add_view=Mock())
        def validate(guild):
            if not guild or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
        def is_staff(member):
            return member.guild.id == GUILD_ID and (member.id == OWNER_ID or any(r.id == 12 for r in member.roles))
        async def call(method, *args):
            return getattr(self.store, method)(*args)
        async def track(kind, title, operation, request, snapshot=None):
            self.snapshots.append(dict(kind=kind, state=await snapshot()))
            return await operation()
        self.system = NS(store=self.store, path=self.store.path, bot=self.bot, configured=True,
            ready_event=asyncio.Event(), ticket_lock=asyncio.Lock(), is_staff=is_staff,
            validate_guild=validate, call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track))
        self.system.ready_event.set()
        self.system.tickets = TicketCenter(self.system)
        self.states = {}
        self.system.ticket_reminders = NS(
            load=AsyncMock(side_effect=lambda row: dict(self.states[int(row['channel'])])),
            reconcile=AsyncMock(side_effect=lambda channel, row, state: (state, True)))
        self.dashboard = TicketDashboard(self.system)
        self.addAsyncCleanup(self.dashboard.close)
        await self.dashboard.start()

    def member(self, user_id, staff=False):
        member = MagicMock(spec=discord.Member)
        member.id, member.guild, member.bot = user_id, self.guild, False
        member.roles = [self.roles[12]] if staff else []
        member.guild_permissions = discord.Permissions.none()
        return member

    def channel(self, channel_id, name, *, category=88, topic='VIce ticket owner=999'):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.guild, channel.category_id = channel_id, self.guild, category
        channel.name, channel.topic = name, topic
        channel.overwrites = {self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                              self.guild.me: discord.PermissionOverwrite(view_channel=True)}
        channel.permissions_for.return_value = discord.Permissions(view_channel=True,
            read_message_history=True, send_messages=True, embed_links=True)
        channel.history.side_effect = lambda **kwargs: history([m for m in self.sent if m.channel.id == channel_id])
        async def fetch_message(key):
            message = next((m for m in self.sent if m.id == key and m.channel.id == channel_id), None)
            if message is None:
                raise missing(10008)
            return message
        channel.fetch_message = AsyncMock(side_effect=fetch_message)
        async def send(**kwargs):
            message = self.message(channel, 1000 + len(self.sent), kwargs['embed'], kwargs['view'])
            self.sent.append(message)
            return message
        channel.send = AsyncMock(side_effect=send)
        return channel

    def message(self, channel, message_id, embed, view):
        message = NS(id=message_id, channel=channel, author=NS(id=BOT_ID), content='', attachments=[],
                     embeds=[discord.Embed.from_dict(deepcopy(embed.to_dict()))], created_at=datetime.now(timezone.utc))
        def components(current):
            return [NS(children=[NS(custom_id=c.custom_id, disabled=c.disabled) for c in current.children])]
        message.components = components(view)
        async def edit(**kwargs):
            message.embeds = [discord.Embed.from_dict(deepcopy(kwargs['embed'].to_dict()))]
            message.components = components(kwargs['view'])
            return message
        message.edit = AsyncMock(side_effect=edit)
        return message

    def case(self, channel_id=55, *, staff=77, awaiting='2026-11-18T10:00:00+00:00'):
        self.store.add_ticket(channel_id, 999, 'general')
        self.channels[channel_id] = self.channel(channel_id, f'ticket-{channel_id}')
        self.store.put(assignment_key(channel_id), dict(guild=GUILD_ID, channel=channel_id,
            owner='999', kind='general', staff_id=staff))
        self.states[channel_id] = dict(awaiting_since=awaiting,
            last_staff_reply_at='2026-11-18T09:00:00+00:00')
        return self.channels[channel_id]

    def interaction(self, message, *, actor=77):
        return NS(guild_id=GUILD_ID, guild=self.guild, user=self.members[actor],
            channel_id=message.channel.id, message=message,
            response=NS(defer=AsyncMock(), is_done=Mock(return_value=True)), followup=NS(send=AsyncMock()))

    async def test_one_private_readonly_channel_and_message_with_empty_state(self):
        message = await self.dashboard.tick()
        record = self.store.get(KEY)
        self.assertEqual(record['channel'], 70)
        self.assertEqual(record['message'], message.id)
        self.assertEqual(message.embeds[0].title, TITLE)
        self.assertIn('No hay tickets abiertos', message.embeds[0].description)
        self.assertEqual(self.guild.create_text_channel.call_args.args[0], NAME)
        self.assertEqual(self.guild.create_text_channel.call_args.kwargs['category'].id, 80)
        rules = {target.id: rule for target, rule in self.channels[70].overwrites.items()}
        self.assertEqual(set(rules), {GUILD_ID, BOT_ID, OWNER_ID, 10, 11, 12, 13})
        self.assertFalse(rules[GUILD_ID].view_channel)
        for target in (OWNER_ID, 10, 11, 12, 13):
            self.assertTrue(rules[target].view_channel)
            self.assertTrue(all(getattr(rules[target], name) is False for name in WRITE_FLAGS))
        self.assertEqual([s['kind'] for s in self.snapshots], ['TICKET_DASHBOARD_SETUP', 'TICKET_DASHBOARD_PANEL'])
        self.assertFalse(self.channels[70].send.call_args.kwargs['allowed_mentions'].everyone)

    async def test_unchanged_state_and_restart_never_repost_or_edit(self):
        message = await self.dashboard.tick()
        await self.dashboard.tick()
        restarted = TicketDashboard(self.system)
        self.assertIs(await restarted.tick(), message)
        self.assertEqual(len(self.sent), 1)
        message.edit.assert_not_awaited()
        self.guild.create_text_channel.assert_awaited_once()

    async def test_same_message_updates_with_direct_link_responsible_and_real_wait(self):
        message = await self.dashboard.tick()
        self.case()
        self.assertIs(await self.dashboard.tick(), message)
        field = message.embeds[0].fields[0]
        self.assertIn(f'https://discord.com/channels/{GUILD_ID}/55', field.value)
        self.assertIn('<@77>', field.value)
        self.assertIn('Esperando al equipo', field.value)
        self.assertIn('<t:1794996000:R>', field.value)
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.system.ticket_reminders.reconcile.await_count)
        self.assertEqual(self.snapshots[-1]['state']['before_message']['id'], message.id)
        self.assertIn('No hay tickets abiertos', self.snapshots[-1]['state']['before_message']['embeds'][0]['description'])

    async def test_waiting_user_and_unassigned_are_distinguished(self):
        self.case(staff=None, awaiting=None)
        message = await self.dashboard.tick()
        value = message.embeds[0].fields[0].value
        self.assertIn('Sin asignar', value)
        self.assertIn('Esperando al usuario', value)
        self.assertIn('<t:1794992400:R>', value)

    async def test_missing_history_or_incomplete_page_remains_honestly_unverified(self):
        self.case()
        self.system.ticket_reminders.reconcile.side_effect = ValueError('unavailable')
        message = await self.dashboard.tick()
        self.assertIn('Por verificar', message.embeds[0].fields[0].value)
        self.assertNotIn('Esperando al equipo', message.embeds[0].fields[0].value)
        self.system.ticket_reminders.reconcile.side_effect = lambda channel, row, state: (state, False)
        await self.dashboard.tick()
        self.assertIn('Por verificar', message.embeds[0].fields[0].value)

    async def test_closed_deleted_and_missing_cases_are_omitted(self):
        for channel_id, state in ((55, 'closed'), (56, 'deleted'), (57, 'open')):
            self.case(channel_id)
            self.store.ticket_state(channel_id, state)
        self.channels.pop(57)
        message = await self.dashboard.tick()
        self.assertFalse(message.embeds[0].fields)
        self.assertEqual(self.system.ticket_reminders.reconcile.await_count, 0)

    async def test_public_source_not_exposed_and_public_destination_blocks_mutation(self):
        self.case()
        self.channels[55].overwrites[self.guild.default_role].view_channel = True
        message = await self.dashboard.tick()
        self.assertFalse(message.embeds[0].fields)
        self.assertIn('necesitan revisión de acceso', message.embeds[0].description)
        self.channels[70].overwrites[self.guild.default_role].view_channel = True
        with self.assertRaises(ValueError):
            await self.dashboard.tick()
        message.edit.assert_not_awaited()

    async def test_forged_or_modified_panel_never_overwritten(self):
        message = await self.dashboard.tick()
        for change in ('author', 'content', 'marker'):
            original = (message.author.id, message.content, message.embeds[0].url)
            if change == 'author': message.author.id = 999
            if change == 'content': message.content = 'private unrelated text'
            if change == 'marker': message.embeds[0].url = 'https://example.com/'
            with self.subTest(change=change), self.assertRaises(ValueError):
                await self.dashboard.tick()
            message.author.id, message.content, message.embeds[0].url = original
        message.edit.assert_not_awaited()
        self.assertEqual(len(self.sent), 1)

    async def test_narrower_ticket_audience_is_not_disclosed_to_all_staff(self):
        channel = self.case()
        channel.permissions_for.side_effect = lambda target: discord.Permissions(
            view_channel=target.id != 13, read_message_history=target.id != 13,
            send_messages=True, embed_links=True)
        message = await self.dashboard.tick()
        self.assertFalse(message.embeds[0].fields)
        self.assertIn('1 ticket(s) necesitan revisión de acceso', message.embeds[0].description)
        self.system.ticket_reminders.reconcile.assert_not_awaited()

    async def test_invalid_wait_date_has_no_invented_elapsed_time(self):
        self.case(awaiting='not a date')
        message = await self.dashboard.tick()
        self.assertIn('Por verificar', message.embeds[0].fields[0].value)
        self.assertNotIn('not a date', str(message.embeds[0].to_dict()))

    async def test_stale_nonce_body_is_not_acknowledged_and_recovers_in_place(self):
        self.case()
        async with self.dashboard.lock:
            channel, record = await self.dashboard.ensure_destination()
        original = channel.send.side_effect
        async def stale(**kwargs):
            message = await original(**kwargs)
            message.embeds[0].clear_fields()
            return message
        channel.send.side_effect = stale
        with self.assertRaises(ValueError):
            await self.dashboard.tick()
        self.assertIsNone(self.store.get(KEY).get('message'))
        channel.send.side_effect = original
        recovered = await self.dashboard.tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(recovered.embeds[0].fields), 1)
        recovered.edit.assert_awaited_once()

    async def test_twenty_three_cases_reachable_through_same_message(self):
        for channel_id in range(100, 123): self.case(channel_id)
        message = await self.dashboard.tick()
        interaction = self.interaction(message)
        self.assertEqual(len(message.embeds[0].fields), PAGE_SIZE)
        self.assertIn('Página 1/3', message.embeds[0].footer.text)
        await self.dashboard.navigate(interaction, 1)
        self.assertIn('Página 2/3', message.embeds[0].footer.text)
        await self.dashboard.navigate(interaction, 1)
        self.assertEqual(len(message.embeds[0].fields), 3)
        self.assertIn('/122)', message.embeds[0].fields[-1].value)
        self.assertEqual(len(self.sent), 1)
        await self.dashboard.tick()
        self.assertEqual(self.store.get(KEY)['page'], 2)
        self.assertLess(len(message.embeds[0]), 6000)

    async def test_nonstaff_foreign_guild_wrong_message_and_revoked_access_cannot_navigate(self):
        message = await self.dashboard.tick()
        with self.assertRaises(ValueError): await self.dashboard.navigate(self.interaction(message, actor=999), 1)
        interaction = self.interaction(message)
        interaction.guild_id = 123
        with self.assertRaises(ValueError): await self.dashboard.navigate(interaction, 1)
        interaction = self.interaction(message)
        interaction.message = NS(id=123)
        with self.assertRaises(ValueError): await self.dashboard.navigate(interaction, 1)
        self.members[77].roles = []
        with self.assertRaises(ValueError): await self.dashboard.navigate(self.interaction(message), 1)
        message.edit.assert_not_awaited()

    async def test_creation_lost_response_recovers_exact_audit_channel_without_duplicate(self):
        async def lost(name, **kwargs):
            await self.create(name, **kwargs)
            raise OSError('lost response')
        self.guild.create_text_channel.side_effect = lost
        with self.assertRaises(OSError): await self.dashboard.tick()
        self.guild.create_text_channel.side_effect = self.create
        message = await self.dashboard.tick()
        self.assertEqual(message.channel.id, 70)
        self.guild.create_text_channel.assert_awaited_once()

    async def test_unproven_pending_creation_never_creates_another_channel(self):
        self.store.put(KEY, dict(guild=GUILD_ID, nonce='a' * 32, started_at=datetime.now(timezone.utc).isoformat(),
            attempted_at=datetime.now(timezone.utc).isoformat()))
        with self.assertRaises(ValueError): await self.dashboard.tick()
        self.guild.create_text_channel.assert_not_awaited()

    async def test_lost_message_response_recovers_existing_panel_without_duplicate(self):
        async with self.dashboard.lock:
            channel, record = await self.dashboard.ensure_destination()
        original = channel.send.side_effect
        async def lost(**kwargs):
            await original(**kwargs)
            raise OSError('lost response')
        channel.send.side_effect = lost
        with self.assertRaises(OSError): await self.dashboard.tick()
        channel.send.side_effect = original
        message = await TicketDashboard(self.system).tick()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.store.get(KEY)['message'], message.id)
        message.edit.assert_not_awaited()

    async def test_ready_failure_retains_retry_worker_and_shutdown_cancels_it(self):
        self.dashboard.tick = AsyncMock(side_effect=OSError('temporary failure'))
        with self.assertRaises(OSError): await self.dashboard.ready()
        self.assertIsNotNone(self.dashboard.task)
        await self.dashboard.close()
        self.assertIsNone(self.dashboard.task)

    async def test_foreign_owner_or_bot_rejected_before_destination_creation(self):
        for change in ('owner', 'bot'):
            if change == 'owner': self.guild.owner_id = 123
            else: self.bot.user.id = 123
            with self.subTest(change=change), self.assertRaises(ValueError): await self.dashboard.tick()
            self.guild.owner_id, self.bot.user.id = OWNER_ID, BOT_ID
        self.guild.create_text_channel.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
