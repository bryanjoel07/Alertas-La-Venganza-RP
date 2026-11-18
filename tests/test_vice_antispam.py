"""Threshold, authority, privacy and concurrency checks for community anti-spam."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

import discord

from vice_antispam import AntiSpam, MAX_MEMBERS
from vice_design import BOT_ID, GUILD_ID, OWNER_ID


class AntiSpamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tick = 1000.0
        self.now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        self.me = NS(id=BOT_ID, top_role=10,
                     guild_permissions=discord.Permissions.all())
        self.guild.me = self.me
        self.member = self.make_member(333)
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.channel = NS(id=100, guild=self.guild,
            permissions_for=lambda member: member.guild_permissions,
            send=AsyncMock(return_value=NS(id=9999)))
        self.bot = NS(user=NS(id=BOT_ID), get_guild=lambda guild_id: self.guild,
                      intents=NS(message_content=True))
        self.snapshots = []
        self.operations = []
        async def track(kind, title, operation, request, snapshot=None):
            self.operations.append((kind, request))
            self.snapshots.append(await snapshot())
            value = await operation()
            self.snapshots.append(await snapshot())
            return value
        self.system = NS(bot=self.bot, configured=True, validate_guild=Mock(),
                         is_staff=lambda member: member.staff or member.id == OWNER_ID,
                         track=AsyncMock(side_effect=track), audit=NS(publish=AsyncMock()))
        self.protection = AntiSpam(self.system)
        self.protection._clock = lambda: self.tick
        self.protection._now = lambda: self.now
        await self.protection.start()
        await self.protection.ready()

    def make_member(self, ident, **kwargs):
        values = dict(id=ident, guild=self.guild, bot=False, staff=False, top_role=2,
                      guild_permissions=discord.Permissions.none(), display_name='Corillo',
                      created_at=self.now - timedelta(days=10), joined_at=self.now,
                      display_avatar=NS(url='https://cdn.discordapp.com/avatars/333/hash.png'),
                      timed_out_until=None, timeout=AsyncMock())
        values.update(kwargs)
        return NS(**values)

    def message(self, ident, **kwargs):
        values = dict(id=ident, guild=self.guild, author=self.member, channel=self.channel,
                      content=f'mensaje privado {ident}', mentions=[], role_mentions=[],
                      mention_everyone=False, webhook_id=None, delete=AsyncMock())
        values.update(kwargs)
        return NS(**values)

    async def offending(self, ident):
        message = self.message(ident, mentions=[NS(id=500 + n) for n in range(6)])
        result = await self.protection.message(message)
        return message, result

    def alert_text(self):
        embed = self.system.audit.publish.await_args.args[1]
        return '\n'.join([embed.description] + [field.value for field in embed.fields])

    async def test_normal_activity_and_slow_messages_are_not_punished(self):
        messages = []
        for i in range(20):
            self.tick += 3
            message = self.message(i)
            messages.append(message)
            self.assertFalse(await self.protection.message(message))
        self.system.track.assert_not_awaited()
        self.system.audit.publish.assert_not_awaited()
        self.guild.fetch_member.assert_not_awaited()
        self.assertTrue(all(not message.delete.called for message in messages))

    async def test_flood_only_offending_messages_removed_and_single_episode_warns(self):
        messages = [self.message(i) for i in range(7)]
        for i, message in enumerate(messages):
            self.tick += 1
            self.assertEqual(await self.protection.message(message), i >= 5)
        self.assertEqual([message.id for message in messages if message.delete.called], [5, 6])
        self.member.timeout.assert_not_awaited()
        self.assertEqual(self.channel.send.await_count, 1)
        self.assertIn('mensajes demasiado seguidos', self.alert_text())

    async def test_duplicates_require_content_intent_and_three_within_fifteen_seconds(self):
        for i in range(3):
            self.tick += 5
            result = await self.protection.message(self.message(i, content='  PRIVADO  repetido  '))
        self.assertTrue(result)
        self.assertIn('mensajes repetidos', self.alert_text())
        self.bot.intents.message_content = False
        for i in range(3, 6):
            self.tick += 5
            self.assertFalse(await self.protection.message(self.message(i, content='PRIVADO repetido')))
        self.assertEqual(sum(kind == 'ANTISPAM_DELETE' for kind, _ in self.operations), 1)

    async def test_distinct_mentions_include_roles_without_counting_duplicates(self):
        message = self.message(1, mentions=[NS(id=20)] * 10, role_mentions=[NS(id=30)] * 10)
        self.assertFalse(await self.protection.message(message))
        message = self.message(2, mentions=[NS(id=i) for i in range(3)],
                               role_mentions=[NS(id=i) for i in range(3, 6)])
        self.assertTrue(await self.protection.message(message))
        self.assertIn('menciones masivas', self.alert_text())

    async def test_everyone_checks_fresh_channel_permissions(self):
        self.member.guild_permissions.mention_everyone = True
        self.assertFalse(await self.protection.message(self.message(1, mention_everyone=True)))
        self.member.guild_permissions.mention_everyone = False
        self.assertTrue(await self.protection.message(self.message(2, mention_everyone=True)))
        self.assertIn('global no autorizada', self.alert_text())

    async def test_literal_unauthorized_everyone_attempt_with_no_actual_ping(self):
        self.assertTrue(await self.protection.message(self.message(1, content='@everyone ven',
                                                                  mention_everyone=False)))
        self.assertFalse(await self.protection.message(self.message(2, content=r'\@everyone')))
        self.bot.intents.message_content = False
        self.assertFalse(await self.protection.message(self.message(3, content='@here')))

    async def test_reoffense_timeout_progression_reset_and_no_shortening(self):
        await self.offending(1)
        self.member.timeout.assert_not_awaited()
        self.tick += 11
        await self.offending(2)
        self.assertEqual(self.member.timeout.await_args.args[0], self.now + timedelta(seconds=60))
        self.tick += 11
        await self.offending(3)
        self.assertEqual(self.member.timeout.await_args.args[0], self.now + timedelta(seconds=300))
        self.member.timed_out_until = self.now + timedelta(hours=1)
        self.tick += 11
        await self.offending(4)
        self.assertEqual(self.member.timeout.await_count, 2)
        self.tick += 301
        await self.offending(5)
        self.assertEqual(self.member.timeout.await_count, 2)
        self.assertEqual(self.protection._state(333).violations, 1)

    async def test_many_messages_in_one_episode_never_escalate_or_extend_timeout(self):
        for i in range(20):
            await self.offending(i)
        self.member.timeout.assert_not_awaited()
        self.assertEqual(self.protection._state(333).violations, 1)
        self.tick += 10
        await self.offending(20)
        self.member.timeout.assert_awaited_once()
        for i in range(21, 40):
            await self.offending(i)
        self.member.timeout.assert_awaited_once()
        self.assertEqual(self.protection._state(333).violations, 2)

    async def test_fresh_staff_owner_and_higher_member_are_exempt(self):
        for index, changes in enumerate(({'staff': True}, {'id': OWNER_ID}, {'top_role': 10})):
            self.guild.fetch_member.return_value = self.make_member(333, **changes) if 'id' not in changes else self.make_member(OWNER_ID)
            message, result = await self.offending(index)
            self.assertFalse(result)
            message.delete.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.system.audit.publish.assert_not_awaited()

    async def test_wrong_guild_owner_bot_identity_dm_webhook_and_bot_are_untouched(self):
        variants = [dict(guild=None), dict(guild=NS(id=1514871828189941881, owner_id=OWNER_ID)),
                    dict(author=self.make_member(444, bot=True)), dict(webhook_id=777),
                    dict(channel=NS(id=9, guild=NS(id=999)))]
        for i, variant in enumerate(variants):
            message = self.message(i, mention_everyone=True, **variant)
            self.assertFalse(await self.protection.message(message))
            message.delete.assert_not_awaited()
        self.guild.owner_id = 999
        self.assertFalse((await self.offending(20))[1])
        self.guild.owner_id = OWNER_ID
        self.bot.user.id = 999
        self.assertFalse((await self.offending(21))[1])
        self.guild.fetch_member.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_readiness_and_fetch_failure_fail_closed_without_callback_errors(self):
        self.system.configured = False
        await self.protection.ready()
        self.assertFalse((await self.offending(1))[1])
        self.system.configured = True
        await self.protection.ready()
        self.guild.fetch_member.side_effect = RuntimeError('private failure details')
        self.assertFalse((await self.offending(2))[1])
        self.system.track.assert_not_awaited()

    async def test_warning_and_staff_alert_cooldown_and_metadata_privacy(self):
        for i in range(3):
            await self.offending(i)
            self.tick += 1
        self.assertEqual(self.channel.send.await_count, 1)
        self.assertEqual(self.system.audit.publish.await_count, 1)
        kwargs = self.channel.send.await_args.kwargs
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.assertNotIn('delete_after', kwargs)
        self.assertNotIn('<@', self.channel.send.await_args.args[0])
        serialized = json.dumps(self.snapshots)
        self.assertNotIn('mensaje privado', serialized)
        self.assertNotIn('content', serialized)
        self.assertIn('message_removed', serialized)
        self.assertTrue(any(kind == 'ANTISPAM_WARNING' for kind, _ in self.operations))
        self.assertEqual(self.system.audit.publish.await_args.kwargs['event_type'], 'antispam')
        self.assertNotIn('<@', self.alert_text())
        self.tick += 31
        await self.offending(10)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertEqual(self.system.audit.publish.await_count, 2)

    async def test_concurrent_duplicate_delivery_has_only_one_moderation_action(self):
        message = self.message(1, mention_everyone=True)
        results = await asyncio.gather(*(self.protection.message(message) for _ in range(5)))
        self.assertEqual(sum(results), 1)
        message.delete.assert_awaited_once()
        self.member.timeout.assert_not_awaited()

    async def test_missing_permissions_and_http_failure_do_not_cascade(self):
        self.me.guild_permissions = discord.Permissions.none()
        await self.protection.ready()
        self.assertTrue(self.protection.configured)
        await self.offending(1)
        await self.offending(2)
        self.system.track.assert_not_awaited()
        self.assertIn('faltan permisos', self.alert_text())
        self.me.guild_permissions = discord.Permissions.all()
        message = self.message(3, mention_everyone=True)
        message.delete.side_effect = RuntimeError('private body')
        self.assertFalse(await self.protection.message(message))
        self.channel.send.assert_not_awaited()

    async def test_young_account_and_join_burst_are_private_alerts_only(self):
        member = self.make_member(400, created_at=self.now - timedelta(hours=2))
        await self.protection.member_join(member)
        self.assertIn('menos de 24 h', self.alert_text())
        await self.protection.member_join(member)
        self.assertEqual(self.system.audit.publish.await_count, 1)
        for i in range(4):
            self.tick += 1
            await self.protection.member_join(self.make_member(500 + i))
        self.assertEqual(self.system.audit.publish.await_count, 2)
        self.assertIn('5 en 10 s', self.alert_text())
        self.assertIn('no se aplicó ninguna sanción', self.alert_text())
        self.system.track.assert_not_awaited()
        self.channel.send.assert_not_awaited()
        member.timeout.assert_not_awaited()

    async def test_join_scope_age_boundary_and_rejoin_cooldown(self):
        for member in (self.make_member(400, created_at=self.now - timedelta(hours=24)),
                       self.make_member(401, bot=True),
                       self.make_member(402, guild=NS(id=999, owner_id=OWNER_ID))):
            await self.protection.member_join(member)
        self.system.audit.publish.assert_not_awaited()
        member = self.make_member(403, created_at=self.now - timedelta(hours=1))
        await self.protection.member_join(member)
        member.joined_at += timedelta(seconds=2)
        await self.protection.member_join(member)
        self.assertEqual(self.system.audit.publish.await_count, 1)

    async def test_memory_is_bounded_and_only_digests_are_kept(self):
        for i in range(MAX_MEMBERS + 20):
            self.protection._state(i)
        self.assertEqual(len(self.protection._states), MAX_MEMBERS)
        state = self.protection._state(333)
        for i in range(100):
            self.protection._observe(self.message(i, content='very private text'), state, self.tick)
        self.assertEqual(len(state.messages), 32)
        self.assertEqual(len(state.seen), 32)
        self.assertTrue(all(isinstance(digest, bytes) and len(digest) == 32 for _, digest in state.messages))


if __name__ == '__main__':
    unittest.main()
