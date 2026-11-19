"""Boost notice routing preserves welcome content and verifies copies first."""
import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import GUILD_ID, BOT_ID, OWNER_ID
import vice_boost_notices as module
from vice_boost_notices import BoostNotices, SOURCE_CHANNEL_ID, BOOST_TYPES, DESTINATION_KEY, MIGRATION_KEY
from vice_readonly import WRITE_FLAGS


async def history(items):
    for item in items:
        yield item


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)


class BoostNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store, self.events = Store(), []
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.guild.name = 'GTA VI Latino | VIce District'
        self.guild.system_channel_flags = discord.SystemChannelFlags._from_value(42)
        self.guild.default_role = MagicMock(spec=discord.Role)
        self.guild.default_role.id, self.guild.default_role.guild = GUILD_ID, self.guild
        self.guild.default_role.permissions = discord.Permissions.none()
        self.bot_role = MagicMock(spec=discord.Role)
        self.bot_role.id, self.bot_role.guild = 7777, self.guild
        self.bot_role.permissions = discord.Permissions(administrator=True)
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id, self.guild.me.guild = BOT_ID, self.guild
        self.guild.me._roles = [self.bot_role.id]
        self.guild.me.guild_permissions = discord.Permissions(administrator=True)
        self.source = MagicMock(spec=discord.TextChannel)
        self.source.id, self.source.guild = SOURCE_CHANNEL_ID, self.guild
        self.source.name, self.source.topic = 'bienvenida', 'Panel de bienvenida'
        self.source.category_id, self.source.position = 50, 0
        self.source.type, self.source._overwrites = discord.ChannelType.text, []
        self.source.delete = AsyncMock()
        self.source.edit = AsyncMock()
        self.guild.system_channel = self.source
        self.guild.system_channel_id = self.source.id
        self.guild._system_channel_id = self.source.id
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild, self.category.name = 80, self.guild, 'CORILLO LATINO'
        self.category.position, self.category.category_id = 3, None
        self.category.type, self.category._overwrites = discord.ChannelType.category, []
        self.destination = MagicMock(spec=discord.TextChannel)
        self.destination.id, self.destination.guild, self.destination.category_id = 70, self.guild, 80
        self.destination.name = module.NAME
        self.destination.topic = getattr(module, 'TOPIC', '')
        self.destination.position, self.destination.type = 5, discord.ChannelType.text
        self.destination._overwrites = []
        self.destination.edit = AsyncMock(return_value=self.destination)
        self.channels = {self.source.id: self.source, 70: self.destination, 80: self.category}
        self.guild.fetch_channel = AsyncMock(side_effect=lambda cid: self.channels[cid])
        self.guild.get_channel.side_effect = self.channels.get
        self.guild.fetch_channels = AsyncMock(side_effect=lambda: list(self.channels.values()))
        self.guild.fetch_member = AsyncMock(return_value=self.guild.me)
        self.guild.fetch_roles = AsyncMock(return_value=[self.guild.default_role, self.bot_role])
        self.guild.edit = AsyncMock(side_effect=self.edit_guild)
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        self.audit_entries = []
        self.guild.audit_logs.side_effect = lambda **kwargs: history(self.audit_entries)
        self.source_messages, self.payloads, self.sent, self.deletions = {}, {}, [], []
        self.source.history.side_effect = lambda **kwargs: history(list(self.source_messages.values()))
        self.source.fetch_message = AsyncMock(side_effect=self.fetch_source)
        self.destination.history.side_effect = lambda **kwargs: history(list(self.sent))
        self.destination.fetch_message = AsyncMock(side_effect=self.fetch_copy)
        self.destination.send = AsyncMock(side_effect=self.send)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=lambda gid: self.guild,
                      fetch_guild=AsyncMock(return_value=self.guild),
                      http=NS(get_message=AsyncMock(side_effect=self.raw_source),
                              delete_message=AsyncMock(side_effect=self.delete_source)))
        for key, value in [('channel:welcome', self.source.id), ('category:community', 80),
                           ('channel:boost_notices', 70)]:
            self.store.put(key, value)
        self.system = NS(bot=self.bot, store=self.store, channel_cache={},
            validate_guild=self.validate, channel_id=lambda key: self.store.get('channel:' + key),
            overwrites=self.overwrites,
            embed=lambda title, description, color=0xFF258D: discord.Embed(
                title=title, description=description, color=color))
        self.system.channel = lambda guild, key: self.channels.get(self.system.channel_id(key))
        self.system.call = AsyncMock(side_effect=lambda method, *args: getattr(self.store, method)(*args))
        self.system.track = AsyncMock(side_effect=self.track)
        self.manager = BoostNotices(self.system)
        self.destination.overwrites = self.overwrites(self.guild, 'read')
        self.store.put(DESTINATION_KEY, dict(guild=GUILD_ID, channel=70, nonce='test-created'))

    def validate(self, guild):
        if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('Wrong guild')

    async def test_name_migration_accepts_v5_and_v6_without_weakening_identity(self):
        record = self.store.get(DESTINATION_KEY)
        for name in (module.stylize(module.NAME).replace('│', '╎'), module.format_name(module.NAME)):
            self.destination.name = name
            self.assertIs(self.manager.validate_destination(self.destination, record), self.destination)
        self.destination.category_id = 999
        with self.assertRaises(ValueError):
            self.manager.validate_destination(self.destination, record)

    def overwrites(self, guild, policy):
        readonly = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                                                **{flag: False for flag in WRITE_FLAGS})
        return {guild.default_role: readonly,
                guild.me: discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=True, embed_links=True, attach_files=True, manage_messages=True)}

    async def edit_guild(self, **kwargs):
        self.events.append(('route', dict(kwargs)))
        if 'system_channel' in kwargs:
            self.guild.system_channel = kwargs['system_channel']
            self.guild.system_channel_id = kwargs['system_channel'].id
            self.guild._system_channel_id = kwargs['system_channel'].id
        return self.guild

    async def track(self, kind, title, operation, request, snapshot=None):
        before = await snapshot() if snapshot else {}
        self.events.append(('before', kind, copy.deepcopy(before)))
        return await operation()

    def add_source(self, mid=1001, kind=8, *, content='', author=OWNER_ID):
        message = NS(id=mid, channel=self.source, guild=self.guild, type=discord.MessageType(kind),
            author=NS(id=author, bot=False, name='esschino', display_name='esschino',
                      mention=f'<@{author}>', display_avatar=NS(url='https://cdn.discordapp.com/embed/avatars/0.png')),
            content=content, system_content='esschino ha mejorado el servidor.', embeds=[], attachments=[],
            created_at=datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc), pinned=False,
            jump_url=f'https://discord.com/channels/{GUILD_ID}/{SOURCE_CHANNEL_ID}/{mid}')
        async def remove(**kwargs):
            await self.delete_source(SOURCE_CHANNEL_ID, mid, **kwargs)
        message.delete = AsyncMock(side_effect=remove)
        self.source_messages[mid] = message
        self.payloads[mid] = dict(id=str(mid), channel_id=str(SOURCE_CHANNEL_ID), type=kind, content=content,
            author=dict(id=str(author), username='esschino', global_name='esschino', avatar=None, discriminator='0'),
            timestamp='2026-11-18T14:00:00+00:00', edited_timestamp=None, attachments=[], embeds=[],
            flags=0, pinned=False, mention_everyone=False, mentions=[], mention_roles=[])
        return message

    async def fetch_source(self, mid):
        if mid not in self.source_messages:
            raise discord.NotFound(NS(status=404, reason='Not Found'), 'Unknown Message')
        return self.source_messages[mid]

    async def raw_source(self, cid, mid):
        if cid != SOURCE_CHANNEL_ID or mid not in self.payloads:
            raise discord.NotFound(NS(status=404, reason='Not Found'), 'Unknown Message')
        return copy.deepcopy(self.payloads[mid])

    async def delete_source(self, cid, mid, **kwargs):
        receipt = self.store.get('boost_notices:receipt:' + str(mid))
        retained = self.store.get('boost_notices:source:' + str(mid))
        self.assertTrue(receipt and receipt.get('verified'))
        self.assertTrue(retained and retained.get('before_delete_raw'))
        self.events.append(('delete', cid, mid))
        self.deletions.append((cid, mid))
        self.source_messages.pop(mid, None)
        self.payloads.pop(mid, None)

    async def send(self, **kwargs):
        self.events.append(('send', kwargs))
        embeds = kwargs.get('embeds') or ([kwargs['embed']] if 'embed' in kwargs else [])
        embeds = [discord.Embed.from_dict(embed.to_dict()) for embed in embeds]
        message = NS(id=2000+len(self.sent), channel=self.destination, guild=self.guild,
                     author=NS(id=BOT_ID), content=kwargs.get('content', ''), embeds=embeds,
                     attachments=[], components=[])
        self.sent.append(message)
        return message

    async def fetch_copy(self, mid):
        for message in self.sent:
            if message.id == mid:
                return message
        raise discord.NotFound(NS(status=404, reason='Not Found'), 'Unknown Message')

    async def prepare(self, mid=1001, kind=8):
        message = self.add_source(mid, kind)
        await self.manager.freeze_history(self.source)
        return message

    def assert_source_preserved(self, mid=1001):
        self.assertIn(mid, self.source_messages)
        self.assertNotIn((SOURCE_CHANNEL_ID, mid), self.deletions)

    async def test_boost_filter_is_exactly_native_types_eight_to_eleven(self):
        self.assertEqual(BOOST_TYPES, frozenset({8, 9, 10, 11}))
        for index, kind in enumerate([0, 7, 8, 9, 10, 11], 1001):
            self.add_source(index, kind)
        await self.manager.freeze_history(self.source)
        frozen = json.dumps(self.store.get(MIGRATION_KEY))
        for mid in [1003, 1004, 1005, 1006]:
            self.assertIn(str(mid), frozen)
        for mid in [1001, 1002]:
            self.assertNotIn(str(mid), frozen)
        self.assertEqual(self.deletions, [])

    async def test_routing_preserves_every_system_flag_and_welcome_configuration(self):
        before = self.guild.system_channel_flags.value
        await self.manager.route_system_channel(self.destination)
        self.assertEqual(self.guild.system_channel_id, self.destination.id)
        self.assertEqual(self.guild.system_channel_flags.value, before)
        self.assertEqual(self.store.get('channel:welcome'), SOURCE_CHANNEL_ID)
        for call in self.guild.edit.await_args_list:
            self.assertNotIn('system_channel_flags', call.kwargs)
            self.assertEqual(set(call.kwargs), {'system_channel', 'reason'})
        self.source.edit.assert_not_awaited()
        self.source.delete.assert_not_awaited()

    async def test_copy_is_verified_and_saved_before_exact_source_deletion(self):
        await self.prepare()
        await self.manager.migrate_message(1001, self.destination)
        self.assertEqual(self.deletions, [(SOURCE_CHANNEL_ID, 1001)])
        self.assertEqual(len(self.sent), 1)
        self.assertIsNotNone(self.store.get('boost_notices:source:1001'))
        self.assertIsNotNone(self.store.get('boost_notices:receipt:1001'))
        self.destination.fetch_message.assert_awaited()
        self.assertEqual(self.destination.send.await_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        kinds = [event[0] for event in self.events]
        self.assertLess(kinds.index('send'), kinds.index('delete'))
        self.source.delete.assert_not_awaited()

    async def test_copy_failure_keeps_original_and_can_retry(self):
        await self.prepare()
        self.destination.send.side_effect = discord.Forbidden(NS(status=403, reason='Forbidden'), 'No permission')
        with self.assertRaises(discord.HTTPException):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.destination.send.side_effect = self.send
        await self.manager.migrate_message(1001, self.destination)
        self.assertEqual(self.deletions, [(SOURCE_CHANNEL_ID, 1001)])
        self.assertEqual(len(self.sent), 1)

    async def test_ambiguous_send_failure_preserves_source_without_blind_retry(self):
        await self.prepare()
        self.destination.send.side_effect = discord.HTTPException(NS(status=503, reason='Unavailable'), 'Unknown result')
        with self.assertRaises(discord.HTTPException):
            await self.manager.migrate_message(1001, self.destination)
        self.destination.send.side_effect = self.send
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.destination.send.assert_awaited_once()

    async def test_lost_send_response_recovers_copy_without_duplicate_or_lost_source(self):
        await self.prepare()
        async def lost_response(**kwargs):
            await self.send(**kwargs)
            raise ConnectionError('response lost')
        self.destination.send.side_effect = lost_response
        with self.assertRaises(ConnectionError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.destination.send.side_effect = self.send
        self.manager = BoostNotices(self.system)
        await self.manager.migrate_message(1001, self.destination)
        self.assertEqual(len(self.sent), 1)
        self.destination.send.assert_awaited_once()
        self.assertEqual(self.deletions, [(SOURCE_CHANNEL_ID, 1001)])

    async def test_receipt_write_failure_keeps_source_and_recovers_existing_copy(self):
        await self.prepare()
        failed = False
        def fail_after_send(method, *args):
            nonlocal failed
            if method == 'put' and args[0] == 'boost_notices:receipt:1001' and self.sent and not failed:
                failed = True
                raise OSError('durable receipt temporarily unavailable')
            return getattr(self.store, method)(*args)
        self.system.call.side_effect = fail_after_send
        with self.assertRaises(OSError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.manager = BoostNotices(self.system)
        await self.manager.migrate_message(1001, self.destination)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.deletions, [(SOURCE_CHANNEL_ID, 1001)])

    async def test_copy_verification_failure_never_deletes_original(self):
        await self.prepare()
        self.destination.fetch_message.side_effect = discord.HTTPException(NS(status=503, reason='Unavailable'), 'Retry')
        with self.assertRaises(discord.HTTPException):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()

    async def test_foreign_guild_or_owner_context_never_copies_or_deletes(self):
        for target, attr, invalid in [(self.guild, 'id', 1514871828189941881),
                                      (self.guild, 'owner_id', 99), (self.bot.user, 'id', 99)]:
            original = getattr(target, attr)
            setattr(target, attr, invalid)
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                await self.manager.context()
            setattr(target, attr, original)
        self.destination.send.assert_not_awaited()
        self.assertEqual(self.deletions, [])

    async def test_native_join_and_regular_welcome_are_never_migrated(self):
        for mid, kind in [(1001, 0), (1002, 7)]:
            self.add_source(mid, kind)
        await self.manager.freeze_history(self.source)
        for mid in [1001, 1002]:
            try:
                await self.manager.migrate_message(mid, self.destination)
            except ValueError:
                pass
            self.assert_source_preserved(mid)
        self.destination.send.assert_not_awaited()

    async def test_frozen_history_does_not_expand_when_retried(self):
        await self.prepare()
        first = self.store.get(MIGRATION_KEY)
        self.add_source(1002, 8)
        await self.manager.freeze_history(self.source)
        self.assertEqual(self.store.get(MIGRATION_KEY), first)

    async def test_historical_copy_preserves_native_quantity_and_achieved_level(self):
        self.add_source(1001, 10, content='3')
        await self.manager.freeze_history(self.source)
        await self.manager.migrate_message(1001, self.destination)
        embed = self.sent[0].embeds[0]
        self.assertIn('3 mejoras', embed.description)
        self.assertIn('nivel 2', embed.description)
        self.assertEqual(embed.timestamp, datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc))
        self.assertEqual(self.store.get('boost_notices:source:1001')['raw']['content'], '3')

    async def test_copy_from_wrong_author_or_with_changed_information_cannot_authorize_deletion(self):
        await self.prepare()
        async def altered(**kwargs):
            result = await self.send(**kwargs)
            result.embeds[0].description = 'Changed boost information'
            return result
        self.destination.send.side_effect = altered
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()

    async def test_extra_source_media_is_retained_without_loss_or_republication(self):
        await self.prepare()
        self.payloads[1001]['attachments'] = [dict(id='999', filename='proof.png', url='https://example.invalid/proof.png')]
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.destination.send.assert_not_awaited()

    async def test_source_changed_after_copy_is_not_deleted(self):
        await self.prepare()
        async def copy_then_change(**kwargs):
            copied = await self.send(**kwargs)
            self.payloads[1001]['content'] = '2'
            return copied
        self.destination.send.side_effect = copy_then_change
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.assertEqual(len(self.sent), 1)

    async def test_unrecognized_native_content_is_preserved_for_review(self):
        self.add_source(1001, 8, content='unexpected native information')
        await self.manager.freeze_history(self.source)
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.assert_source_preserved()
        self.destination.send.assert_not_awaited()

    async def test_destination_must_remain_read_only_before_any_publication(self):
        await self.prepare()
        self.destination.overwrites[self.guild.default_role].send_messages = True
        with self.assertRaises(ValueError):
            await self.manager.migrate_message(1001, self.destination)
        self.destination.send.assert_not_awaited()
        self.assert_source_preserved()

    async def test_finished_migration_does_not_repeat_copy_or_delete(self):
        self.add_source(1001, 8)
        welcome = self.add_source(1002, 0)
        await self.manager.ready()
        first_flags = self.guild.system_channel_flags.value
        await BoostNotices(self.system).ready()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.deletions, [(SOURCE_CHANNEL_ID, 1001)])
        self.assertIn(welcome.id, self.source_messages)
        self.assertEqual(self.guild.system_channel_flags.value, first_flags)
        self.guild.create_text_channel.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
