"""Staff access and private departure notifications for VIce District."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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
        self.guild.me.guild_permissions = discord.Permissions(administrator=True, view_audit_log=True)
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
        self.system.resolve_departure = AsyncMock(return_value=(
            'Salida del servidor',
            'No se detectó una expulsión ni un baneo en el registro de auditoría.', None))
        self.system.departure_card = AsyncMock(return_value=b'test-only-jpeg-payload')
        self.rolemap = {}
        for index, (key, name, color, permissions, *_rest) in enumerate(ROLES, 1000):
            role = MagicMock(spec=discord.Role)
            role.id, role.name, role.managed = index, name, False
            role.permissions = discord.Permissions(**permissions)
            role.guild = self.guild
            self.rolemap[key] = role
            self.system.store.put('role:' + key, index)
        founder = MagicMock(spec=discord.Role)
        founder.id, founder.name, founder.managed = 999, '👑 Fundador', False
        founder.permissions = discord.Permissions.none()
        self.rolemap['founder'] = founder
        self.system.store.put('role:founder', founder.id)
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

    async def test_goodbye_is_private_to_founder_and_administrator_only(self):
        channel = next(row for row in CHANNELS if row[0] == 'goodbye')
        self.assertEqual(channel[1], 'team')
        rules = self.system.overwrites(self.guild, channel[4])
        self.assertIs(rules[self.guild.default_role].view_channel, False)
        self.assertIs(rules[self.guild.default_role].send_messages, False)
        self.assertIs(rules[self.guild.me].send_messages, True)
        for key in ['founder', 'admin']:
            self.assertIs(rules[self.rolemap[key]].view_channel, True)
            self.assertIs(rules[self.rolemap[key]].read_message_history, True)
        for key in ['mod', 'support']:
            self.assertIs(rules[self.rolemap[key]].view_channel, False)
            self.assertIs(rules[self.rolemap[key]].read_message_history, False)
            self.assertIs(rules[self.rolemap[key]].send_messages, False)

    async def test_other_staff_channels_remain_available_to_moderation_and_support(self):
        for policy in ['staff', 'staffread', 'ticket', 'closed']:
            rules = self.system.overwrites(self.guild, policy)
            for key in ['founder', 'admin', 'mod', 'support']:
                self.assertIs(rules[self.rolemap[key]].view_channel, True)

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

    async def test_departure_embeds_personal_banner_and_never_pings_or_fetches_departed_user(self):
        await self.system.member_remove(self.member)
        self.channel.send.assert_awaited_once()
        values = self.channel.send.await_args.kwargs
        self.assertEqual(values['allowed_mentions'].to_dict(), {'parse': []})
        content = json.dumps(values['embed'].to_dict(), ensure_ascii=False)
        self.assertIn(str(self.member.id), content)
        self.assertIn('Salida del servidor', content)
        self.assertIn('No se detectó', content)
        self.assertTrue(values['embed'].image.url.startswith('attachment://'))
        files = values.get('files') or ([values['file']] if values.get('file') else [])
        self.assertEqual(len(files), 1)
        self.assertEqual(values['embed'].image.url, 'attachment://' + files[0].filename)
        self.system.departure_card.assert_awaited_once_with(self.member)
        self.system.resolve_departure.assert_awaited_once()
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

    async def test_explicit_non_admin_access_blocks_departure_and_avatar_processing(self):
        for target in [self.rolemap['mod'], self.rolemap['support'], discord.Object(id=7788)]:
            self.channel.overwrites = {target: discord.PermissionOverwrite(view_channel=True)}
            with self.subTest(target=target.id), self.assertRaises(ValueError):
                await self.system.member_remove(self.member)
        self.channel.send.assert_not_awaited()
        self.system.resolve_departure.assert_not_awaited()
        self.system.departure_card.assert_not_awaited()

    async def test_startup_wait_does_not_shift_the_departure_audit_window(self):
        observed = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        clock_value = [observed]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock_value[0]
        async def finish_starting():
            clock_value[0] = observed + timedelta(minutes=1)
        self.system.ready_event.wait = AsyncMock(side_effect=finish_starting)
        with patch('vice_district.datetime', Clock):
            await self.system.member_remove(self.member)
        self.assertEqual(self.system.resolve_departure.await_args.args[2], observed)
        self.assertEqual(self.channel.send.await_args.kwargs['embed'].timestamp, observed)

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

    async def test_departure_includes_only_the_confirmed_moderation_reason_and_actor(self):
        actor = NS(id=123, display_name='Administrador', name='admin', mention='<@123>')
        self.system.resolve_departure.return_value = ('Baneo', 'Spam reiterado', actor)
        await self.system.member_remove(self.member)
        values = self.channel.send.await_args.kwargs
        content = json.dumps(values['embed'].to_dict(), ensure_ascii=False)
        self.assertIn('Baneo', content)
        self.assertIn('Spam reiterado', content)
        self.assertIn(str(actor.id), content)
        self.assertEqual(values['allowed_mentions'].to_dict(), {'parse': []})

    def audit_entry(self, action, when, *, target=77, reason='Spam reiterado'):
        return NS(id=discord.utils.time_snowflake(when), action=action, target=NS(id=target),
                  created_at=when, reason=reason,
                  user=NS(id=123, display_name='Administrador', name='admin', mention='<@123>'))

    def audit_history(self, entries):
        def stream(**kwargs):
            action = kwargs.get('action')
            return history([entry for entry in entries if action is None or entry.action == action])
        self.guild.audit_logs.side_effect = stream

    @patch('vice_district.asyncio.sleep', new_callable=AsyncMock)
    async def test_recent_matching_kick_and_ban_use_the_recorded_reason_and_actor(self, sleep):
        left = datetime.now(timezone.utc)
        for action, label_fragment in [(discord.AuditLogAction.kick, 'expuls'),
                                       (discord.AuditLogAction.ban, 'ban')]:
            with self.subTest(action=action):
                entry = self.audit_entry(action, left - timedelta(seconds=2))
                self.audit_history([entry])
                label, reason, actor = await ViceDistrict.resolve_departure(self.system, self.guild, self.member, left)
                self.assertIn(label_fragment, label.lower())
                self.assertEqual(reason, entry.reason)
                self.assertEqual(actor.id, entry.user.id)

    @patch('vice_district.asyncio.sleep', new_callable=AsyncMock)
    async def test_unrelated_old_and_future_audit_entries_do_not_invent_a_cause(self, sleep):
        left = datetime.now(timezone.utc)
        self.audit_history([
            self.audit_entry(discord.AuditLogAction.ban, left, target=999),
            self.audit_entry(discord.AuditLogAction.kick, left - timedelta(seconds=16)),
            self.audit_entry(discord.AuditLogAction.ban, left + timedelta(seconds=11)),
            self.audit_entry(discord.AuditLogAction.unban, left),
        ])
        label, reason, actor = await ViceDistrict.resolve_departure(self.system, self.guild, self.member, left)
        self.assertEqual(label, 'Salida del servidor')
        self.assertIn('No se detectó', reason)
        self.assertIsNone(actor)

    @patch('vice_district.asyncio.sleep', new_callable=AsyncMock)
    async def test_delayed_audit_entry_can_be_resolved_without_a_false_voluntary_claim(self, sleep):
        left = datetime.now(timezone.utc)
        entry = self.audit_entry(discord.AuditLogAction.kick, left + timedelta(seconds=1))
        calls = []
        def stream(**kwargs):
            calls.append(kwargs)
            if len(calls) <= 2:
                return history([])
            action = kwargs.get('action')
            return history([entry] if action is None or action == entry.action else [])
        self.guild.audit_logs.side_effect = stream
        label, reason, actor = await ViceDistrict.resolve_departure(self.system, self.guild, self.member, left)
        self.assertIn('expuls', label.lower())
        self.assertEqual(reason, entry.reason)
        self.assertEqual(actor.id, entry.user.id)

    @patch('vice_district.asyncio.sleep', new_callable=AsyncMock)
    async def test_unavailable_audit_is_reported_as_unconfirmed(self, sleep):
        async def unavailable():
            raise discord.Forbidden(NS(status=403, reason='Forbidden'), 'Missing Permissions')
            yield  # Make the failure occur while consuming the audit iterator.
        self.guild.audit_logs.side_effect = lambda **kwargs: unavailable()
        label, reason, actor = await ViceDistrict.resolve_departure(
            self.system, self.guild, self.member, datetime.now(timezone.utc))
        self.assertEqual(label, 'Salida del servidor')
        self.assertIsNone(actor)
        self.assertNotEqual(reason, 'No se detectó una expulsión ni un baneo en el registro de auditoría.')
        self.assertTrue(reason)

    async def test_audit_resolution_never_reads_an_unrelated_guild(self):
        foreign = MagicMock()
        foreign.id, foreign.owner_id = 1514871828189941881, OWNER_ID
        with self.assertRaises(ValueError):
            await ViceDistrict.resolve_departure(self.system, foreign, self.member, datetime.now(timezone.utc))
        foreign.audit_logs.assert_not_called()


class RawDepartureRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_guilds_are_not_forwarded_to_vice(self):
        bot = NS(vice=NS(member_remove=AsyncMock()), get_guild=MagicMock())
        await StoreBot.on_raw_member_remove(bot, NS(guild_id=1514871828189941881, user=NS(id=77, bot=False)))
        bot.vice.member_remove.assert_not_awaited()
        bot.get_guild.assert_not_called()

    async def test_uncached_payload_is_forwarded_with_its_authorized_guild(self):
        user = NS(id=77, bot=False)
        guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        bot = NS(vice=NS(member_remove=AsyncMock(), activity=NS(member_remove=AsyncMock())),
                 get_guild=MagicMock(return_value=guild))
        await StoreBot.on_raw_member_remove(bot, NS(guild_id=GUILD_ID, user=user))
        bot.vice.member_remove.assert_awaited_once()
        args, kwargs = bot.vice.member_remove.await_args
        self.assertIs(args[0], user)
        self.assertIs(args[1] if len(args) > 1 else kwargs.get('guild'), guild)


if __name__ == '__main__':
    unittest.main()
