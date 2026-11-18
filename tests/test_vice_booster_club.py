import asyncio
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_booster_club import (BoosterClub, BOOSTER_ID, SUPPORT_ID, CREATOR_ID, STAFF_IDS,
    COMMUNITY_CATEGORY_ID, ROLE_NAME, ROLE_COLOR, VERSION, RELEASE_KEY, ROLE_RECEIPT,
    PANEL_RECEIPT, benefits_copy)


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)


class Role:
    def __init__(self, guild, rid, name, position, permissions=0):
        self.guild, self.id, self.name, self.position = guild, rid, name, position
        self.permissions = discord.Permissions(permissions)
        self.colour = self.color = discord.Colour(0xF47FFF)
        self.hoist = self.mentionable = False
        self.managed = rid == BOOSTER_ID
        self.icon = NS(key='existing-owner-icon', url='https://cdn.discordapp.com/existing.png')
        self.unicode_emoji = self.secondary_colour = self.tertiary_colour = None
        self.edit = AsyncMock(side_effect=self.update)

    def __lt__(self, other):
        return (self.position, -self.id) < (other.position, -other.id)

    def is_premium_subscriber(self):
        return self.id == BOOSTER_ID and self.managed

    async def update(self, **values):
        for key, value in values.items():
            if key != 'reason':
                setattr(self, key, value)
        self.color = self.colour
        return self


async def items(values):
    for value in values:
        yield value


class BoosterClubTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store()
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID, bitrate_limit=256000)
        specs = [(GUILD_ID, '@everyone', 0, 0), (BOOSTER_ID, 'Server Booster', 1, 0),
                 (CREATOR_ID, 'creator', 45, 0), (SUPPORT_ID, 'support', 46, 0),
                 (STAFF_IDS[2], 'mod', 47, 0), (STAFF_IDS[1], 'admin', 48, 8),
                 (9000, 'bot', 50, 8), (STAFF_IDS[0], 'founder', 51, 8)]
        self.roles = {rid: Role(self.guild, rid, name, position, permissions)
                      for rid, name, position, permissions in specs}
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles.values()))
        self.member = MagicMock(spec=discord.Member)
        self.member.id, self.member.guild, self.member._roles = BOT_ID, self.guild, [9000]
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.channels = {}
        self.audit_entries = []
        self.messages = []
        self.community = self.make_channel(discord.CategoryChannel, COMMUNITY_CATEGORY_ID,
                                           'Corillo Latino', position=1)
        self.channels[self.community.id] = self.community
        self.guild.fetch_channel = AsyncMock(side_effect=lambda cid:self.channels[cid])
        self.guild.audit_logs = MagicMock(side_effect=lambda **kwargs:items(self.audit_entries))
        self.guild.edit_role_positions = AsyncMock(side_effect=self.move_role)
        self.guild.create_category = AsyncMock(side_effect=lambda name, **kwargs:
            self.create_channel(discord.CategoryChannel, name, **kwargs))
        self.guild.create_text_channel = AsyncMock(side_effect=lambda name, **kwargs:
            self.create_channel(discord.TextChannel, name, **kwargs))
        self.guild.create_voice_channel = AsyncMock(side_effect=lambda name, **kwargs:
            self.create_channel(discord.VoiceChannel, name, **kwargs))
        self.system = NS(store=self.store, roles_lock=asyncio.Lock())
        self.system.bot = NS(user=NS(id=BOT_ID), fetch_guild=AsyncMock(return_value=self.guild))
        self.system.validate_guild = self.validate
        self.system.call = AsyncMock(side_effect=lambda method,*args:getattr(self.store,method)(*args))
        self.snapshots = []
        self.system.track = AsyncMock(side_effect=self.track)
        self.club = BoosterClub(self.system)

    def validate(self, guild):
        if guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('wrong guild or owner')

    def make_channel(self, cls, cid, name, **kwargs):
        channel = MagicMock(spec=cls)
        channel.id, channel.guild, channel.name = cid, self.guild, name
        channel.position = kwargs.get('position', 0)
        channel.overwrites = kwargs.get('overwrites', {})
        channel.category_id = getattr(kwargs.get('category'), 'id', None)
        channel.topic = kwargs.get('topic')
        channel.bitrate = kwargs.get('bitrate', 64000)
        channel.history = MagicMock(side_effect=lambda **kw:items(self.messages))
        channel.send = AsyncMock(side_effect=self.send)
        return channel

    def create_channel(self, cls, name, **kwargs):
        channel = self.make_channel(cls, 10000 + len(self.channels), name, **kwargs)
        self.channels[channel.id] = channel
        self.audit_entries.append(NS(user=NS(id=BOT_ID), target=NS(id=channel.id), reason=kwargs['reason']))
        return channel

    async def send(self, **kwargs):
        message = NS(id=40000 + len(self.messages), author=NS(id=BOT_ID), embeds=[kwargs['embed']])
        self.messages.append(message)
        return message

    async def move_role(self, positions, **kwargs):
        for role, position in positions.items():
            role.position = position
        return sorted(self.roles.values())

    async def track(self, kind, title, operation, request, snapshot):
        self.snapshots.append(await snapshot())
        result = await operation()
        self.snapshots.append(await snapshot())
        return result

    async def test_full_setup_private_access_role_style_and_restart(self):
        before_order = [role.id for role in sorted(self.roles.values()) if role.id != BOOSTER_ID]
        before_permissions = {rid: role.permissions.value for rid, role in self.roles.items()}
        await self.club.ready()
        self.assertEqual(self.store.get(RELEASE_KEY), VERSION)
        vip = self.roles[BOOSTER_ID]
        self.assertEqual(vip.name, ROLE_NAME)
        self.assertEqual(vip.colour.value, ROLE_COLOR)
        self.assertTrue(vip.hoist)
        self.assertEqual(vip.icon.key, 'existing-owner-icon')
        self.assertEqual(set(vip.edit.call_args.kwargs), {'name','colour','hoist','reason'})
        self.assertEqual({rid: role.permissions.value for rid, role in self.roles.items()}, before_permissions)
        ordered = sorted(self.roles.values())
        self.assertEqual(ordered[ordered.index(vip)+1].id, SUPPORT_ID)
        self.assertLess(self.roles[CREATOR_ID], vip)
        self.assertEqual([role.id for role in ordered if role.id != BOOSTER_ID], before_order)
        self.assertEqual(set(self.guild.edit_role_positions.call_args.kwargs['positions']), {vip})
        self.assertEqual(self.guild.create_category.call_args.kwargs['position'], 2)
        expected_ids = {GUILD_ID, BOOSTER_ID, *STAFF_IDS, OWNER_ID, BOT_ID}
        for channel in self.channels.values():
            if channel.id == COMMUNITY_CATEGORY_ID:
                continue
            overrides = {target.id: rule for target, rule in channel.overwrites.items()}
            self.assertEqual(set(overrides), expected_ids)
            self.assertIs(overrides[GUILD_ID].view_channel, False)
            self.assertIs(overrides[GUILD_ID].connect, False)
            for rid in expected_ids - {GUILD_ID}:
                self.assertIs(overrides[rid].view_channel, True)
                self.assertIs(overrides[rid].connect, True)
        lounge = self.channels[self.store.get('channel:booster_lounge')]
        self.assertEqual(lounge.send.call_args.kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.assertIn('256 kbps', self.messages[0].embeds[0].description)
        creates = self.guild.create_category.await_count + self.guild.create_text_channel.await_count + self.guild.create_voice_channel.await_count
        await BoosterClub(self.system).ready()
        self.assertEqual(creates, 3)
        self.assertEqual(self.guild.create_category.await_count + self.guild.create_text_channel.await_count + self.guild.create_voice_channel.await_count, 3)
        lounge.send.assert_awaited_once()

    async def test_wrong_owner_or_bot_never_mutates(self):
        self.guild.owner_id = 123
        with self.assertRaises(ValueError):
            await self.club.ready()
        self.guild.create_category.assert_not_awaited()
        self.roles[BOOSTER_ID].edit.assert_not_awaited()
        self.guild.owner_id = OWNER_ID
        self.system.bot.user.id = 123
        with self.assertRaises(ValueError):
            await self.club.ready()
        self.roles[BOOSTER_ID].edit.assert_not_awaited()

    async def test_privileged_or_unrecognized_booster_rejected(self):
        self.roles[BOOSTER_ID].permissions = discord.Permissions(administrator=True)
        with self.assertRaises(ValueError):
            await self.club.ready()
        self.roles[BOOSTER_ID].permissions = discord.Permissions.none()
        self.roles[BOOSTER_ID].managed = False
        with self.assertRaises(ValueError):
            await self.club.ready()
        self.guild.create_category.assert_not_awaited()

    async def test_managed_role_forbidden_is_reported_without_bypass(self):
        self.roles[BOOSTER_ID].edit.side_effect = discord.Forbidden(NS(status=403,reason='Forbidden'),'managed role')
        await self.club.ready()
        self.assertEqual(self.store.get(ROLE_RECEIPT)['state'], 'owner_ui_required')
        self.roles[BOOSTER_ID].edit.assert_awaited_once()
        self.guild.edit_role_positions.assert_not_awaited()
        self.assertEqual(len(self.messages), 1)

    async def test_registered_channel_with_unexpected_viewer_blocks_publication(self):
        category = await self.club.ensure_channel('category')
        lounge = await self.club.ensure_channel('lounge', category)
        await self.club.ensure_channel('terrace', category)
        lounge.overwrites[discord.Object(id=222, type=discord.Role)] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaises(ValueError):
            await self.club.ensure_panel()
        lounge.send.assert_not_awaited()

    async def test_removed_registered_channel_is_not_recreated(self):
        self.store.put('category:booster_club', 999999)
        with self.assertRaises(KeyError):
            await self.club.ensure_channel('category')
        self.guild.create_category.assert_not_awaited()

    async def test_interrupted_creation_recovers_only_exact_audit_entry(self):
        def interrupted(name, **kwargs):
            self.create_channel(discord.CategoryChannel, name, **kwargs)
            raise RuntimeError('lost response')
        self.guild.create_category.side_effect = interrupted
        with self.assertRaises(RuntimeError):
            await self.club.ensure_channel('category')
        channel = await self.club.ensure_channel('category')
        self.assertEqual(channel.id, self.store.get('category:booster_club'))
        self.guild.create_category.assert_awaited_once()

    async def test_ambiguous_creation_without_audit_does_not_duplicate_by_name(self):
        self.guild.create_category.side_effect = RuntimeError('unknown response')
        with self.assertRaises(RuntimeError):
            await self.club.ensure_channel('category')
        self.channels[777] = self.make_channel(discord.CategoryChannel, 777, '━━ 💎 CLUB BOOSTER ━━')
        with self.assertRaises(ValueError):
            await self.club.ensure_channel('category')
        self.guild.create_category.assert_awaited_once()

    async def test_bitrate_uses_live_limit_and_copy_does_not_overpromise(self):
        self.guild.bitrate_limit = 96000
        await self.club.ready()
        self.assertEqual(self.guild.create_voice_channel.call_args.kwargs['bitrate'], 96000)
        self.assertEqual(self.store.get('channel:booster_terrace_bitrate'), 96000)
        self.assertNotIn('256 kbps', self.messages[0].embeds[0].description)
        self.assertIn('voz privada', benefits_copy(1,2))

    async def test_interrupted_panel_send_recovers_without_duplicate(self):
        category = await self.club.ensure_channel('category')
        lounge = await self.club.ensure_channel('lounge', category)
        await self.club.ensure_channel('terrace', category)
        async def interrupted(**kwargs):
            await self.send(**kwargs)
            raise RuntimeError('lost send acknowledgement')
        lounge.send.side_effect = interrupted
        with self.assertRaises(RuntimeError):
            await self.club.ensure_panel()
        self.assertFalse(self.store.get(PANEL_RECEIPT)['complete'])
        await self.club.ensure_panel()
        self.assertTrue(self.store.get(PANEL_RECEIPT)['complete'])
        lounge.send.assert_awaited_once()

    async def test_definitive_send_rejection_can_retry_after_permission_fix(self):
        category = await self.club.ensure_channel('category')
        lounge = await self.club.ensure_channel('lounge', category)
        await self.club.ensure_channel('terrace', category)
        lounge.send.side_effect = discord.Forbidden(NS(status=403,reason='Forbidden'),'no send permission')
        with self.assertRaises(discord.Forbidden):
            await self.club.ensure_panel()
        self.assertFalse(self.store.get(PANEL_RECEIPT)['attempted'])
        lounge.send.side_effect = self.send
        await self.club.ensure_panel()
        self.assertEqual(len(self.messages), 1)
        self.assertTrue(self.store.get(PANEL_RECEIPT)['complete'])


if __name__ == '__main__':
    unittest.main()
