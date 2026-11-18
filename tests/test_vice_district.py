import asyncio
from datetime import datetime, timezone
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from PIL import Image

from vice_design import GUILD_ID, OWNER_ID, BOT_ID, ROLES, GROUPS, SELF_ROLES, CHANNELS, panel_copy
from vice_district import ViceDistrict, WelcomePanel, RolesPanel, SupportPanel, CloseTicketPanel
from vice_welcome import render_card, render_cover, fit_name
import studio_guard


def avatar_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (128, 128), '#10F050').save(buf, 'PNG')
    return buf.getvalue()


async def history(messages):
    for message in messages:
        yield message


class ArtworkTests(unittest.TestCase):
    def test_avatar_is_inside_the_actual_banner_and_card_is_small(self):
        data = render_card('esschino · José', 'esschino', avatar_bytes())
        self.assertLess(len(data), 1_000_000)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (1280, 720))
            r,g,b = image.getpixel((116,645))
            self.assertGreater(g, 220)
            self.assertLess(r, 40)
            self.assertLess(b, 110)
        with Image.open(io.BytesIO(render_cover())) as image:
            self.assertEqual(image.size, (1280, 720))

    def test_long_and_control_character_names_fit(self):
        value, font = fit_name('W' * 100 + '\x00\n\u200e')
        self.assertLessEqual(font.getlength(value), 995)
        self.assertFalse(any(c in value for c in ['\x00', '\n', '\u200e']))
        with self.assertRaises(ValueError):
            render_card('name','user',b'')

    def test_panel_copy_fits_and_contains_only_real_channel_links(self):
        for key,*_ in CHANNELS:
            copy = panel_copy(key, lambda _: 123456789012345678)
            if copy:
                title, body, _ = copy
                self.assertLessEqual(len(title), 256)
                self.assertLessEqual(len(body), 4096)
                self.assertNotIn('<#None>', body)


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(self.tmp.name) / 'vice.db')
        await self.system.start()
        self.guild = MagicMock()
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.bot.get_guild.return_value = self.guild
        self.member = MagicMock(spec=discord.Member)
        self.member.guild = self.guild
        self.member.id, self.member.bot = 77, False
        self.member.roles = []
        self.member.guild_permissions = discord.Permissions.none()
        self.member.add_roles = AsyncMock()
        self.member.remove_roles = AsyncMock()
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.interaction = NS(id=100, guild=self.guild, guild_id=GUILD_ID, user=self.member,
                              channel_id=55)
        self.rolemap = {}
        for index, (key, name, color, permissions, *_rest) in enumerate(ROLES, 1000):
            role = MagicMock(spec=discord.Role)
            role.id, role.name, role.managed = index, name, False
            role.permissions = discord.Permissions(**permissions)
            role.guild = self.guild
            self.rolemap[key] = role
            self.system.store.put('role:' + key, index)
        self.guild.get_role.side_effect = lambda rid: next((r for r in self.rolemap.values() if r.id == rid), None)
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.rolemap.values()))
        async def track(kind, title, operation, request, snapshot=None):
            return await operation()
        self.system.track = AsyncMock(side_effect=track)

    async def test_persistent_views_survive_restart_and_have_unique_custom_ids(self):
        ids = []
        for view in [WelcomePanel(self.system, links=False), RolesPanel(self.system), SupportPanel(self.system), CloseTicketPanel(self.system)]:
            self.assertTrue(view.is_persistent())
            for child in view.children:
                ids.append(child.custom_id)
                self.assertLessEqual(len(child.custom_id), 100)
        self.assertEqual(len(ids), len(set(ids)))

    async def test_welcome_has_no_role_menu_or_role_menu_button(self):
        view = WelcomePanel(self.system, links=False)
        self.assertTrue(all(isinstance(child, discord.ui.Button) for child in view.children))
        self.assertNotIn('vice:v1:roles', [child.custom_id for child in view.children])

    async def test_member_is_lowest_and_all_roles_have_solid_colors(self):
        self.assertEqual(ROLES[-1][0], 'member')
        self.assertTrue(all(0 < spec[2] <= 0xFFFFFF for spec in ROLES))
        separators = {row[0]: row for row in ROLES if row[0].endswith('separator')}
        self.assertEqual(set(separators), {
            'team_separator', 'community_separator', 'country_separator',
            'region_separator', 'preferences_separator', 'entry_separator'})
        self.assertTrue(all(not row[3] and row[4] is False for row in separators.values()))
        self.assertIn('PLATAFORMAS', separators['preferences_separator'][1])
        self.assertNotIn('PREFERENCIAS', separators['preferences_separator'][1])
        for key in ['member','citizen','veteran','legend']:
            self.assertEqual(self.rolemap[key].permissions.value,0)

    async def test_new_member_gets_lowest_role_before_personal_welcome(self):
        self.system.ready_event.set()
        self.member.joined_at = datetime.now(timezone.utc)
        calls=[]
        async def add(*roles, **kwargs):
            calls.append('role')
            self.assertEqual(roles,(self.rolemap['member'],))
        async def welcome(member):
            calls.append('welcome')
        self.member.add_roles.side_effect=add
        self.system.welcome.joined=AsyncMock(side_effect=welcome)
        await self.system.member_join(self.member)
        self.assertEqual(calls,['role','welcome'])
        self.system.track.assert_awaited_once()

    async def test_accepting_rules_promotes_only_the_entry_rank(self):
        self.member.roles=[self.rolemap['member'],self.rolemap['pc']]
        await self.system.join_community(self.interaction)
        self.assertEqual(self.member.add_roles.await_args.args,(self.rolemap['citizen'],))
        self.assertEqual(self.member.remove_roles.await_args.args,(self.rolemap['member'],))

    async def test_wrong_guild_owner_and_bots_are_rejected(self):
        self.system.authorize(self.interaction)
        self.guild.id = 1514871828189941881
        with self.assertRaises(ValueError):
            self.system.authorize(self.interaction)
        self.guild.id = GUILD_ID
        self.guild.owner_id = 42
        with self.assertRaises(ValueError):
            self.system.authorize(self.interaction)
        self.guild.owner_id = OWNER_ID
        self.member.bot = True
        with self.assertRaises(ValueError):
            self.system.authorize(self.interaction)

    async def test_self_selection_cannot_grant_staff_or_other_groups(self):
        for invalid in ['mod','support','creator','member','mexico']:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction,'platform',[invalid])
        self.member.add_roles.assert_not_awaited()

    async def test_role_selection_preserves_staff_and_other_groups(self):
        self.member.roles = [self.rolemap['mod'],self.rolemap['mexico'],self.rolemap['ps']]
        await self.system.select_roles(self.interaction,'platform',['xbox'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['ps'],))
        self.assertEqual(self.member.add_roles.await_args.args, (self.rolemap['xbox'],))
        self.system.track.assert_awaited_once()

    async def test_empty_selection_removes_only_its_group(self):
        self.member.roles = [self.rolemap['crew'],self.rolemap['ps']]
        await self.system.select_roles(self.interaction,'interests',[])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['crew'],))
        self.member.add_roles.assert_not_awaited()

    async def test_role_accidentally_given_power_cannot_be_self_assigned(self):
        self.rolemap['xbox'].permissions = discord.Permissions(administrator=True)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction,'platform',['xbox'])
        self.member.add_roles.assert_not_awaited()

    async def test_staff_is_not_self_selectable_and_all_optional_roles_have_zero_permissions(self):
        self.assertFalse({'mod','support','creator','member'} & SELF_ROLES)
        for key in SELF_ROLES:
            self.assertEqual(self.rolemap[key].permissions.value, 0)
        self.assertFalse(self.rolemap['mod'].permissions.administrator)

    async def test_private_channel_and_ticket_overwrites_are_private(self):
        for policy in ['staff','staffread','ticket','closed']:
            rules = self.system.overwrites(self.guild, policy, self.member if policy in {'ticket','closed'} else None)
            self.assertIs(rules[self.guild.default_role].view_channel, False)
            self.assertIs(rules[self.guild.me].view_channel, True)
            self.assertIs(rules[self.rolemap['mod']].view_channel, True)
            if policy in {'ticket','closed'}:
                self.assertIs(rules[self.member].view_channel, True)
                self.assertEqual(rules[self.member].send_messages, policy == 'ticket')

    async def test_information_is_read_only_and_support_cannot_publish(self):
        rules = self.system.overwrites(self.guild, 'read')
        self.assertIs(rules[self.guild.default_role].send_messages, False)
        self.assertIs(rules[self.guild.default_role].send_messages_in_threads, False)
        self.assertIs(rules[self.rolemap['support']].send_messages, False)
        self.assertIs(rules[self.rolemap['mod']].send_messages, False)

    async def test_existing_open_ticket_is_reused(self):
        self.system.store.add_ticket(99,77,'comunidad')
        channel = NS(id=99)
        self.guild.get_channel.return_value = channel
        self.system.tickets.ensure_open_panel = AsyncMock()
        self.assertIs(await self.system.open_ticket(self.interaction), channel)
        self.system.tickets.ensure_open_panel.assert_awaited_once_with(channel, self.system.store.ticket(99))
        self.guild.create_text_channel.assert_not_called()

    async def test_unknown_category_cannot_create_or_reuse_ticket(self):
        self.system.store.add_ticket(99,77,'general')
        self.system.tickets.ensure_open_panel = AsyncMock()
        with self.assertRaises(ValueError):
            await self.system.open_ticket(self.interaction, kind='administrator')
        self.system.tickets.ensure_open_panel.assert_not_awaited()
        self.guild.create_text_channel.assert_not_called()

    async def test_initial_closed_copies_are_frozen_once_and_never_delete_sources(self):
        self.system.store.add_ticket(55,77,'general')
        self.system.store.ticket_state(55,'closed')
        channel = NS(id=55, delete=AsyncMock())
        self.guild.fetch_channel = AsyncMock(return_value=channel)
        self.system.ticket_archive.backup = AsyncMock()
        await self.system.backfill_ticket_copies()
        self.system.ticket_archive.backup.assert_awaited_once_with(channel, self.system.store.ticket(55), BOT_ID)
        self.system.store.add_ticket(56,78,'report')
        self.system.store.ticket_state(56,'closed')
        await self.system.backfill_ticket_copies()
        self.assertEqual(self.system.ticket_archive.backup.await_count,1)
        self.assertEqual(self.system.store.get('ticket_archive_initial_closed_v1')['completed'],['55'])
        self.assertEqual(self.system.store.ticket(55)['state'],'closed')
        channel.delete.assert_not_awaited()

    async def test_initial_copy_failure_preserves_ticket_and_retries_same_frozen_source(self):
        self.system.store.add_ticket(55,77,'technical')
        self.system.store.ticket_state(55,'closed')
        channel = NS(id=55, delete=AsyncMock())
        self.guild.fetch_channel = AsyncMock(return_value=channel)
        self.system.ticket_archive.backup = AsyncMock(side_effect=ValueError('Incomplete copy'))
        with self.assertLogs('ViceDistrict',level='ERROR'):
            await self.system.backfill_ticket_copies()
        self.assertEqual(self.system.store.get('ticket_archive_initial_closed_v1')['completed'],[])
        self.system.ticket_archive.backup.side_effect=None
        await self.system.backfill_ticket_copies()
        self.assertEqual(self.system.ticket_archive.backup.await_count,2)
        self.assertEqual(self.system.store.ticket(55)['state'],'closed')
        channel.delete.assert_not_awaited()

    async def test_archive_start_failure_does_not_block_antispam_audit_or_ticket_panel(self):
        for service in (self.system.tickets, self.system.ticket_archive,
                        self.system.ticket_feedback, self.system.ticket_deletion, self.system.audit, self.system.antispam):
            service.ready = AsyncMock()
        self.system.optional_roles.ready=AsyncMock(side_effect=ValueError('Role catalog not available'))
        self.system.ticket_archive.ready.side_effect=ValueError('Archive not available')
        self.system.refresh_ticket_panel=AsyncMock()
        self.system.start_ticket_backfill=MagicMock()
        with self.assertLogs('ViceDistrict',level='ERROR'):
            await self.system.ready_community_services()
        for service in (self.system.tickets, self.system.ticket_deletion,
                        self.system.ticket_feedback, self.system.audit, self.system.antispam):
            service.ready.assert_awaited_once()
        self.system.refresh_ticket_panel.assert_awaited_once()
        self.system.optional_roles.ready.assert_awaited_once()
        self.system.start_ticket_backfill.assert_not_called()

    async def test_non_owner_cannot_close_another_members_ticket(self):
        self.system.store.add_ticket(55,999,'comunidad')
        with self.assertRaises(ValueError):
            await self.system.close_ticket(self.interaction)
        self.system.track.assert_not_awaited()

    async def test_close_preserves_channel_and_owner_access(self):
        self.system.store.add_ticket(55,77,'comunidad')
        closed_channel = NS(id=55)
        channel = NS(edit=AsyncMock(return_value=closed_channel), send=AsyncMock(), delete=AsyncMock())
        self.interaction.channel = channel
        self.system.ticket_deletion.ensure_closed_panel = AsyncMock()
        self.system.ticket_feedback.capture_close = AsyncMock()
        self.system.tickets.archive_controls = AsyncMock()
        self.guild.get_channel.return_value = NS(id=200)
        await self.system.close_ticket(self.interaction)
        self.assertEqual(self.system.store.ticket(55)['state'], 'closed')
        rules = channel.edit.await_args.kwargs['overwrites']
        self.assertFalse(rules[self.guild.default_role].view_channel)
        self.assertTrue(rules[self.member].view_channel)
        self.assertFalse(rules[self.member].send_messages)
        self.system.ticket_deletion.ensure_closed_panel.assert_awaited_once_with(closed_channel)
        self.system.tickets.archive_controls.assert_awaited_once_with(closed_channel)
        self.system.ticket_feedback.capture_close.assert_awaited_once_with(
            closed_channel, self.system.store.ticket(55), self.member.id)
        channel.delete.assert_not_awaited()

    async def test_welcome_receipt_prevents_double_send_and_survives_restart(self):
        self.member.joined_at = datetime.now(timezone.utc)
        self.member.display_name, self.member.name = 'Chino','esschino'
        self.member.mention = '<@77>'
        self.member.display_avatar.url = 'https://cdn.discordapp.com/avatar.png'
        channel = NS(id=33, guild=self.guild, send=AsyncMock(return_value=NS(id=88)),
                     history=lambda **kw: history([]))
        self.system.store.put('channel:welcome',33)
        self.guild.get_channel.return_value = channel
        self.system.welcome.card = AsyncMock(return_value=render_card('Chino','esschino',avatar_bytes()))
        first = await self.system.welcome.joined(self.member)
        again = await self.system.welcome.joined(self.member)
        self.assertEqual(str(first),str(again))
        channel.send.assert_awaited_once()
        self.assertEqual(channel.send.await_args.kwargs['allowed_mentions'].to_dict(), {'parse':[]})

    async def test_welcome_for_other_guild_never_reads_avatar_or_sends(self):
        self.member.guild = NS(id=1514871828189941881)
        self.system.welcome.card = AsyncMock()
        await self.system.welcome.joined(self.member)
        self.system.welcome.card.assert_not_awaited()


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_guard_accepts_only_both_authorized_guilds(self):
        original = AsyncMock(return_value={})
        original._studio_guard = False
        with patch.object(discord.http.HTTPClient, 'request', original):
            studio_guard.install()
            wrapped = discord.http.HTTPClient.request
            for gid in [GUILD_ID,1514871828189941881]:
                await wrapped(None, NS(guild_id=gid,url=f'https://discord.com/api/v10/guilds/{gid}'))
            for gid in [1244988345327550565,123]:
                with self.assertRaises(ValueError):
                    await wrapped(None, NS(guild_id=gid,url=f'https://discord.com/api/v10/guilds/{gid}'))
            self.assertEqual(original.await_count,2)


if __name__ == '__main__':
    unittest.main()
