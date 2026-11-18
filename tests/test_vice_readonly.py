"""Read-only panel privacy, publication and interaction regression coverage."""
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_district import ViceDistrict, WelcomePanel, RolesPanel, SupportPanel
from vice_readonly import READONLY_VERSION, ReadOnlyChannels, lock_overwrites
from store_bot import StoreBot


WRITE_FLAGS = ('send_messages', 'send_messages_in_threads', 'send_tts_messages',
    'send_voice_messages', 'send_polls', 'embed_links', 'attach_files', 'add_reactions',
    'external_emojis', 'external_stickers', 'create_public_threads',
    'create_private_threads', 'use_external_apps', 'use_application_commands')


async def entries(values):
    for value in values:
        yield value


class ReadOnlyPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(self.tmp.name) / 'vice.db')
        await self.system.call('initialize')
        self.guild = MagicMock()
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.default_role.id = GUILD_ID
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id, self.guild.me.guild = BOT_ID, self.guild
        self.bot.get_guild.return_value = self.guild
        self.roles = {}
        for index, key in enumerate(('founder', 'admin', 'mod', 'support'), 100):
            role = MagicMock(spec=discord.Role)
            role.id, role.guild = index, self.guild
            role.permissions = discord.Permissions(administrator=key == 'admin')
            self.roles[key] = role
            self.system.store.put('role:' + key, role.id)
        self.guild.get_role.side_effect = lambda rid: next((r for r in self.roles.values() if r.id == rid), None)
        self.owner = MagicMock(spec=discord.Member)
        self.owner.id, self.owner.guild = 777, self.guild

    async def test_every_non_bot_overwrite_denies_posting_and_reactions_on_readonly_policies(self):
        for policy in ('read', 'staffread', 'adminread', 'closed'):
            rules = self.system.overwrites(self.guild, policy, self.owner if policy == 'closed' else None)
            for target, overwrite in rules.items():
                if target.id == BOT_ID:
                    continue
                for flag in WRITE_FLAGS:
                    with self.subTest(policy=policy, target=target.id, flag=flag):
                        self.assertIs(getattr(overwrite, flag), False)

    async def test_public_panels_remain_readable(self):
        rules = self.system.overwrites(self.guild, 'read')
        self.assertIs(rules[self.guild.default_role].view_channel, True)
        self.assertIs(rules[self.guild.default_role].read_message_history, True)

    async def test_only_bot_can_publish_without_administrator_bypass(self):
        for policy in ('read', 'staffread', 'adminread', 'closed'):
            rules = self.system.overwrites(self.guild, policy)
            for flag in ('view_channel', 'read_message_history', 'send_messages', 'attach_files', 'embed_links'):
                self.assertIs(getattr(rules[self.guild.me], flag), True, (policy, flag))
            for key in ('mod', 'support'):
                self.assertIs(rules[self.roles[key]].send_messages, False)

    async def test_departures_never_become_visible_to_moderation_or_support(self):
        rules = self.system.overwrites(self.guild, 'adminread')
        for target in (self.guild.default_role, self.roles['mod'], self.roles['support']):
            self.assertIs(rules[target].view_channel, False)
            self.assertIs(rules[target].read_message_history, False)
        for key in ('founder', 'admin'):
            self.assertIs(rules[self.roles[key]].view_channel, True)

    async def test_closed_ticket_keeps_requester_history_private_and_readable(self):
        rules = self.system.overwrites(self.guild, 'closed', self.owner)
        self.assertIs(rules[self.guild.default_role].view_channel, False)
        self.assertIs(rules[self.owner].view_channel, True)
        self.assertIs(rules[self.owner].read_message_history, True)
        self.assertIs(rules[self.owner].send_messages, False)
        self.assertIs(rules[self.owner].add_reactions, False)

    async def test_chat_and_open_ticket_conversation_stays_enabled(self):
        chat = self.system.overwrites(self.guild, 'chat')
        self.assertIs(chat[self.guild.default_role].send_messages, True)
        self.assertIsNot(chat[self.guild.default_role].add_reactions, False)
        ticket = self.system.overwrites(self.guild, 'ticket', self.owner)
        self.assertIs(ticket[self.owner].send_messages, True)
        self.assertIsNot(ticket[self.owner].add_reactions, False)
        self.assertIs(ticket[self.roles['support']].manage_messages, True)

    async def test_slash_output_is_blocked_but_persistent_member_components_stay_enabled(self):
        rules = self.system.overwrites(self.guild, 'read')
        self.assertIs(rules[self.guild.default_role].use_application_commands, False)
        for view in (WelcomePanel(self.system, links=False), RolesPanel(self.system), SupportPanel(self.system)):
            self.assertTrue(view.is_persistent())
            self.assertTrue(view.children)
            self.assertTrue(all(not item.disabled for item in view.children))

    async def test_foreign_guild_is_rejected_before_constructing_permissions(self):
        self.guild.id = 1514871828189941881
        with self.assertRaises(ValueError):
            self.system.overwrites(self.guild, 'read')

    async def test_lock_preserves_visibility_and_unrelated_bits_and_copies_inputs(self):
        unlisted_role = MagicMock(spec=discord.Role)
        unlisted_role.id = 9001
        custom_member = MagicMock(spec=discord.Member)
        custom_member.id = 9002
        original = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False, read_message_history=False),
            unlisted_role: discord.PermissionOverwrite(view_channel=False, connect=True, mute_members=True,
                send_messages=True, add_reactions=True, use_external_apps=True),
            custom_member: discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                connect=False, send_messages=True, send_messages_in_threads=True, add_reactions=True),
        }
        before = {target: overwrite.pair() for target, overwrite in original.items()}
        locked = lock_overwrites(self.guild, original)
        self.assertIsNot(locked, original)
        for target in original:
            self.assertEqual(before[target], original[target].pair(), 'Caller overwrite was mutated')
            for flag in ('view_channel', 'read_message_history', 'connect', 'mute_members'):
                self.assertIs(getattr(locked[target], flag), getattr(original[target], flag), (target.id, flag))
            for flag in WRITE_FLAGS:
                self.assertIs(getattr(locked[target], flag), False, (target.id, flag))
        self.assertIs(locked[self.guild.me].send_messages, True)

    async def test_member_specific_bot_allow_survives_managed_role_denial(self):
        managed_bot_role = MagicMock(spec=discord.Role)
        managed_bot_role.id = 8001
        locked = lock_overwrites(self.guild, {
            self.guild.default_role: discord.PermissionOverwrite(send_messages=True),
            managed_bot_role: discord.PermissionOverwrite(send_messages=True, add_reactions=True),
            self.guild.me: discord.PermissionOverwrite(send_messages=False, attach_files=False),
        })
        self.assertIs(locked[managed_bot_role].send_messages, False)
        for flag in ('send_messages', 'attach_files', 'embed_links', 'view_channel', 'read_message_history'):
            self.assertIs(getattr(locked[self.guild.me], flag), True, flag)

    async def test_target_registry_uses_saved_ids_and_only_closed_tickets(self):
        self.system.store.put('channel:welcome', 10101)
        self.system.store.put('channel:voicepanel', 10102)
        self.system.store.put('channel:general', 10103)
        self.system.store.put('channel:ticket_archive', 10106)
        self.system.store.put('channel:ticket_feedback', 10107)
        self.system.store.add_ticket(10104, self.owner.id, 'comunidad')
        self.system.store.add_ticket(10105, self.owner.id, 'comunidad')
        self.system.store.ticket_state(10105, 'closed')
        guard = ReadOnlyChannels(self.system)
        ids = guard.target_ids()
        self.assertTrue({10101, 10102, 10105, 10106, 10107} <= ids)
        self.assertFalse({10103, 10104} & ids)

    async def test_targets_include_threads_of_registered_panels_but_not_similar_names(self):
        self.system.store.put('channel:welcome', 10101)
        guard = ReadOnlyChannels(self.system)
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.guild = 10101, self.guild
        self.assertTrue(guard.is_target(channel))
        channel.id, channel.name = 99999, '╭・👋│bienvenida'
        self.assertFalse(guard.is_target(channel))
        thread = MagicMock(spec=discord.Thread)
        thread.id, thread.guild, thread.parent_id = 20202, self.guild, 10101
        self.assertTrue(guard.is_target(thread))
        thread.parent_id = 99999
        self.assertFalse(guard.is_target(thread))
        foreign = MagicMock(spec=discord.TextChannel)
        foreign.id, foreign.guild = 10101, NS(id=1514871828189941881, owner_id=OWNER_ID)
        self.assertFalse(guard.is_target(foreign))

    def reaction_fixture(self, *, thread=False, count=2):
        self.system.store.put('channel:welcome', 10101)
        channel = MagicMock(spec=discord.Thread if thread else discord.TextChannel)
        channel.id, channel.guild = (20202 if thread else 10101), self.guild
        if thread:
            channel.parent_id = 10101
        message = MagicMock(spec=discord.Message)
        message.id, message.channel = 30303, channel
        message.reactions = [NS(emoji='🔥', count=count)] if count else []
        async def clear():
            message.reactions = []
        message.clear_reactions = AsyncMock(side_effect=clear)
        channel.fetch_message = AsyncMock(return_value=message)
        channel.delete = AsyncMock()
        self.snapshots = []
        async def track(kind, title, operation, request, snapshot=None):
            before = await snapshot() if snapshot else None
            result = await operation()
            after = await snapshot() if snapshot else None
            self.snapshots.append((kind, before, after))
            return result
        self.system.track = AsyncMock(side_effect=track)
        self.guild.get_channel_or_thread.return_value = channel
        self.guild.fetch_channel = AsyncMock(return_value=channel)
        return ReadOnlyChannels(self.system), channel, message

    async def test_existing_reactions_are_cleared_with_durable_count_snapshot_not_messages(self):
        guard, channel, message = self.reaction_fixture()
        self.assertTrue(await guard.clear_message(channel, message))
        message.clear_reactions.assert_awaited_once()
        message.delete.assert_not_called()
        channel.delete.assert_not_awaited()
        kind, before, after = self.snapshots[0]
        self.assertEqual(kind, 'READONLY_REACTIONS')
        self.assertEqual(before['reactions'], [dict(emoji='🔥', count=2)])
        self.assertEqual(after['reactions'], [])
        self.assertEqual(before['guild'], GUILD_ID)

    async def test_empty_messages_and_mismatched_channel_messages_are_not_mutated(self):
        guard, channel, message = self.reaction_fixture(count=0)
        self.assertFalse(await guard.clear_message(channel, message))
        message.reactions = [NS(emoji='🔥', count=1)]
        message.channel = NS(id=9999)
        self.assertFalse(await guard.clear_message(channel, message))
        self.system.track.assert_not_awaited()
        message.clear_reactions.assert_not_awaited()

    async def test_raw_reactions_on_registered_thread_are_cleared_including_bot_seeds(self):
        guard, channel, message = self.reaction_fixture(thread=True)
        payload = NS(guild_id=GUILD_ID, channel_id=channel.id, message_id=message.id, user_id=BOT_ID)
        await guard.reaction_add(payload)
        message.clear_reactions.assert_awaited_once()
        self.assertEqual(self.snapshots[0][1]['channel'], channel.id)

    async def test_foreign_guild_reaction_does_not_fetch_any_discord_data(self):
        guard, channel, message = self.reaction_fixture()
        self.bot.get_guild.reset_mock()
        await guard.reaction_add(NS(guild_id=1514871828189941881, channel_id=channel.id, message_id=message.id))
        self.bot.get_guild.assert_not_called()
        channel.fetch_message.assert_not_awaited()
        self.guild.fetch_channel.assert_not_awaited()

    async def test_chat_reactions_are_left_untouched(self):
        guard, channel, message = self.reaction_fixture()
        channel.id = 99999
        await guard.reaction_add(NS(guild_id=GUILD_ID, channel_id=channel.id, message_id=message.id))
        channel.fetch_message.assert_not_awaited()
        message.clear_reactions.assert_not_awaited()

    async def test_uncached_readonly_channel_is_safely_resolved(self):
        guard, channel, message = self.reaction_fixture()
        self.guild.get_channel_or_thread.return_value = None
        await guard.reaction_add(NS(guild_id=GUILD_ID, channel_id=channel.id, message_id=message.id))
        self.guild.fetch_channel.assert_awaited_once_with(channel.id)
        message.clear_reactions.assert_awaited_once()

    async def test_raw_reaction_router_never_reaches_studio_or_foreign_guild(self):
        bot = NS(vice=NS(readonly=NS(reaction_add=AsyncMock())))
        for gid in (None, 1514871828189941881, 1244988345327550565):
            await StoreBot.on_raw_reaction_add(bot, NS(guild_id=gid))
        bot.vice.readonly.reaction_add.assert_not_awaited()
        payload = NS(guild_id=GUILD_ID)
        await StoreBot.on_raw_reaction_add(bot, payload)
        bot.vice.readonly.reaction_add.assert_awaited_once_with(payload)

    def migration_fixture(self):
        guard, panel, message = self.reaction_fixture(count=0)
        panel.type = discord.ChannelType.text
        panel.history = lambda **kwargs: entries([message])
        panel.archived_threads = lambda **kwargs: entries([])
        panel.overwrites = self.system.overwrites(self.guild, 'read')
        panel.edit = AsyncMock()
        self.guild.threads = []
        category = MagicMock(spec=discord.CategoryChannel)
        category.id, category.guild = 40404, self.guild
        category.overwrites = {self.guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        category.edit = AsyncMock()
        self.system.store.put('category:info', category.id)
        chat = MagicMock(spec=discord.TextChannel)
        chat.id, chat.guild = 50505, self.guild
        chat.edit = AsyncMock()
        self.system.store.put('channel:general', chat.id)
        self.guild.fetch_channels = AsyncMock(return_value=[panel, category, chat])
        return guard, panel, category, chat

    async def test_migration_touches_only_registered_panels_categories_and_is_idempotent(self):
        guard, panel, category, chat = self.migration_fixture()
        await guard.ready()
        await guard.ready()
        panel.edit.assert_awaited_once()
        category.edit.assert_awaited_once()
        chat.edit.assert_not_awaited()
        self.guild.fetch_channels.assert_awaited_once()
        self.assertEqual(self.system.store.get('readonly_release'), READONLY_VERSION)
        self.assertIs(category.edit.await_args.kwargs['overwrites'][self.guild.default_role].view_channel, False)
        self.assertEqual(self.system.track.await_args.args[0], 'READONLY_SETUP')

    async def test_missing_registered_target_aborts_before_any_mutation_or_release_marker(self):
        guard, panel, category, chat = self.migration_fixture()
        self.system.store.put('channel:rules', 60606)
        with self.assertRaises(ValueError):
            await guard.ready()
        for channel in (panel, category, chat):
            channel.edit.assert_not_awaited()
        self.system.track.assert_not_awaited()
        self.assertIsNone(self.system.store.get('readonly_release'))

    async def test_reactions_in_active_and_archived_threads_are_cleaned_without_deleting_threads(self):
        guard, panel, category, chat = self.migration_fixture()
        threads = []
        messages = []
        for index in range(3):
            thread = MagicMock(spec=discord.Thread)
            thread.id, thread.guild, thread.parent_id = 70000 + index, self.guild, panel.id
            msg = MagicMock(spec=discord.Message)
            msg.id, msg.channel = 80000 + index, thread
            msg.reactions = [NS(emoji='✅', count=3)]
            msg.clear_reactions = AsyncMock()
            thread.fetch_message = AsyncMock(return_value=msg)
            thread.history = lambda *, limit, message=msg: entries([message])
            threads.append(thread)
            messages.append(msg)
        self.guild.threads = [threads[0]]
        panel.archived_threads = lambda **kwargs: entries([threads[2] if kwargs.get('private') else threads[1]])
        await guard.ready()
        for thread, message in zip(threads, messages):
            message.clear_reactions.assert_awaited_once()
            message.delete.assert_not_called()
            thread.delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
