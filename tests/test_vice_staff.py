"""Staff access and private departure notifications for VIce District."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import BOT_ID, CHANNELS, GUILD_ID, OWNER_ID, ROLES, SELF_ROLES
from vice_district import ViceDistrict
from store_bot import StoreBot


async def history(messages):
    for message in messages:
        yield message


class StaffAndDepartureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(self.tmp.name) / 'vice.db')
        await self.system.start()
        self.system.ready_event.set()
        self.guild = MagicMock()
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.bot.get_guild.return_value = self.guild
        self.member = MagicMock(spec=discord.Member)
        self.member.guild = self.guild
        self.member.id, self.member.bot = 77, False
        self.member.name = 'persona'
        self.member.display_name = '@everyone Persona'
        self.member.display_avatar.url = 'https://cdn.discordapp.com/avatars/77/avatar.png'
        self.member.joined_at = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        self.member.roles = []
        self.member.guild_permissions = discord.Permissions.none()
        self.member.add_roles = AsyncMock()
        self.guild.fetch_member = AsyncMock()
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild = 33, self.guild
        self.channel.send = AsyncMock(return_value=NS(id=88))
        self.channel.overwrites_for.return_value = discord.PermissionOverwrite(view_channel=False)
        self.channel.history = lambda **kwargs: history([])
        self.guild.get_channel.side_effect = lambda cid: self.channel if cid == 33 else None
        self.system.store.put('channel:goodbye', 33)
        self.rolemap = {}
        for index, (key, name, color, permissions, *_rest) in enumerate(ROLES, 1000):
            role = MagicMock(spec=discord.Role)
            role.id, role.name, role.managed = index, name, False
            role.permissions = discord.Permissions(**permissions)
            role.guild = self.guild
            self.rolemap[key] = role
            self.system.store.put('role:' + key, index)
        self.guild.get_role.side_effect = lambda rid: next((r for r in self.rolemap.values() if r.id == rid), None)

        async def track(kind, title, operation, request, snapshot=None):
            return await operation()
        self.system.track = AsyncMock(side_effect=track)

    async def test_staff_hierarchy_and_permissions_match_responsibilities(self):
        order = [row[0] for row in ROLES]
        self.assertLess(order.index('admin'), order.index('mod'))
        self.assertLess(order.index('mod'), order.index('support'))
        admin, mod, support = (self.rolemap[key].permissions for key in ('admin', 'mod', 'support'))
        self.assertTrue(admin.administrator)
        for permission in ['manage_messages', 'manage_threads', 'moderate_members', 'kick_members',
                           'ban_members', 'manage_nicknames', 'mute_members', 'deafen_members',
                           'move_members', 'view_audit_log', 'pin_messages']:
            self.assertTrue(getattr(mod, permission), permission)
        for role in [mod, support]:
            for permission in ['administrator', 'manage_guild', 'manage_roles', 'manage_channels',
                               'manage_webhooks', 'mention_everyone']:
                self.assertFalse(getattr(role, permission), permission)
        for permission in ['manage_messages', 'manage_threads', 'moderate_members', 'kick_members',
                           'ban_members', 'manage_nicknames', 'mute_members', 'deafen_members', 'move_members']:
            self.assertFalse(getattr(support, permission), permission)

    async def test_staff_cannot_be_granted_by_public_role_menu(self):
        self.assertFalse({'admin', 'mod', 'support'} & SELF_ROLES)
        interaction = NS(id=100, guild=self.guild, guild_id=GUILD_ID, user=self.member)
        for key in ['admin', 'mod', 'support']:
            with self.subTest(role=key), self.assertRaises(ValueError):
                await self.system.select_roles(interaction, 'platform', [key])
        self.member.add_roles.assert_not_awaited()

    async def test_goodbye_is_private_read_only_for_the_staff_team(self):
        channel = next(row for row in CHANNELS if row[0] == 'goodbye')
        self.assertEqual(channel[1], 'team')
        rules = self.system.overwrites(self.guild, channel[4])
        self.assertIs(rules[self.guild.default_role].view_channel, False)
        self.assertIs(rules[self.guild.default_role].send_messages, False)
        self.assertIs(rules[self.guild.me].send_messages, True)
        for key in ['admin', 'mod', 'support']:
            self.assertIs(rules[self.rolemap[key]].view_channel, True)
            self.assertIs(rules[self.rolemap[key]].read_message_history, True)
        for key in ['mod', 'support']:
            self.assertIs(rules[self.rolemap[key]].send_messages, False)

    async def test_support_can_moderate_tickets_without_public_moderation_power(self):
        support = self.rolemap['support']
        ticket = self.system.overwrites(self.guild, 'ticket', self.member)
        self.assertIs(ticket[support].manage_messages, True)
        for policy in ['chat', 'read', 'staff', 'staffread', 'closed']:
            rules = self.system.overwrites(self.guild, policy)
            self.assertIsNot(rules[support].manage_messages, True)
        self.assertIs(self.system.overwrites(self.guild, 'read')[support].send_messages, False)

    async def test_admin_is_staff_and_does_not_need_another_staff_role(self):
        self.member.roles = [self.rolemap['admin']]
        self.assertTrue(self.system.is_staff(self.member))
        self.member.guild = NS(id=1514871828189941881)
        self.assertFalse(self.system.is_staff(self.member))

    async def test_departure_for_other_guild_or_bot_does_not_send(self):
        self.member.guild = NS(id=1514871828189941881)
        await self.system.member_remove(self.member)
        self.member.guild = self.guild
        self.member.bot = True
        await self.system.member_remove(self.member)
        self.channel.send.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_departure_is_private_neutral_and_never_pings_or_fetches_departed_user(self):
        await self.system.member_remove(self.member)
        self.channel.send.assert_awaited_once()
        values = self.channel.send.await_args.kwargs
        self.assertEqual(values['allowed_mentions'].to_dict(), {'parse': []})
        content = json.dumps(values['embed'].to_dict(), ensure_ascii=False)
        self.assertIn(str(self.member.id), content)
        self.assertNotIn('expulsad', content.lower())
        self.assertNotIn('banead', content.lower())
        self.guild.fetch_member.assert_not_awaited()
        self.system.track.assert_awaited_once()

    async def test_duplicate_departure_is_not_sent_twice_but_new_membership_is(self):
        await self.system.member_remove(self.member)
        await self.system.member_remove(self.member)
        self.channel.send.assert_awaited_once()
        self.member.joined_at += timedelta(days=1)
        await self.system.member_remove(self.member)
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_recorded_message_recovers_a_departure_without_sending_it_twice(self):
        key = f'goodbye:{self.member.id}:{self.member.joined_at.isoformat()}'
        existing = NS(id=88, author=NS(id=BOT_ID), embeds=[discord.Embed().set_footer(text='VIce District • ' + key)])
        self.channel.history = lambda **kwargs: history([existing])
        await self.system.member_remove(self.member)
        self.channel.send.assert_not_awaited()

    async def test_missing_or_public_goodbye_channel_never_receives_departure(self):
        self.guild.get_channel.side_effect = lambda cid: None
        try:
            await self.system.member_remove(self.member)
        except ValueError:
            pass
        self.guild.get_channel.side_effect = lambda cid: self.channel if cid == 33 else None
        for visibility in [True, None]:
            self.channel.overwrites_for.return_value = discord.PermissionOverwrite(view_channel=visibility)
            try:
                await self.system.member_remove(self.member)
            except ValueError:
                pass
        self.channel.send.assert_not_awaited()

    async def test_failed_send_can_retry_without_a_false_delivery_receipt(self):
        self.channel.send.side_effect = [RuntimeError('temporary delivery failure'), NS(id=88)]
        with self.assertRaises(RuntimeError):
            await self.system.member_remove(self.member)
        await self.system.member_remove(self.member)
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_uncached_user_can_be_reported_using_supplied_guild(self):
        user = MagicMock(spec=discord.User)
        user.id, user.bot = 79, False
        user.name, user.display_name = 'otra_persona', 'Otra persona'
        user.display_avatar.url = 'https://cdn.discordapp.com/avatars/79/avatar.png'
        await self.system.member_remove(user, self.guild)
        self.channel.send.assert_awaited_once()
        self.guild.fetch_member.assert_not_awaited()


class RawDepartureRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_guilds_are_not_forwarded_to_vice(self):
        bot = NS(vice=NS(member_remove=AsyncMock()), get_guild=MagicMock())
        await StoreBot.on_raw_member_remove(bot, NS(guild_id=1514871828189941881, user=NS(id=77, bot=False)))
        bot.vice.member_remove.assert_not_awaited()
        bot.get_guild.assert_not_called()

    async def test_uncached_payload_is_forwarded_with_its_authorized_guild(self):
        user = NS(id=77, bot=False)
        guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        bot = NS(vice=NS(member_remove=AsyncMock()), get_guild=MagicMock(return_value=guild))
        await StoreBot.on_raw_member_remove(bot, NS(guild_id=GUILD_ID, user=user))
        bot.vice.member_remove.assert_awaited_once()
        args, kwargs = bot.vice.member_remove.await_args
        self.assertIs(args[0], user)
        self.assertIs(args[1] if len(args) > 1 else kwargs.get('guild'), guild)


if __name__ == '__main__':
    unittest.main()

