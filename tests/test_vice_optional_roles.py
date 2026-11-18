"""Role catalog migration preserves hierarchy, identities and guild boundaries."""
import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_optional_roles import OptionalRoles, RELEASE_KEY, ROLES_TOPIC, REASON
from vice_role_catalog import CATALOG_VERSION, OPTIONAL_ROLES


class Role:
    def __init__(self, guild, rid, name, position, *, managed=False, permissions=0, color=0x123456):
        self.guild, self.id, self.name, self.position = guild, rid, name, position
        self.managed, self.permissions = managed, discord.Permissions(permissions)
        self.colour, self.hoist, self.mentionable = discord.Colour(color), False, False
        self.color = self.colour
        self.edit = AsyncMock(side_effect=self.update)
        self.members = [777]

    def __lt__(self, other):
        return (self.position, -self.id) < (other.position, -other.id)

    def is_default(self):
        return self.id == GUILD_ID

    async def update(self, **values):
        for key, value in values.items():
            if key != 'reason':
                setattr(self, key, value)
        self.color = self.colour
        return self


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        self.values[key] = value


async def entries(values):
    for value in values:
        yield value


class OptionalRoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID)
        self.roles = []
        self.store = Store()
        self.specs = {spec[0]: spec for spec in OPTIONAL_ROLES}
        keys = ['member', 'entry_separator', 'events', 'news', 'europe', 'north', 'south',
                'caribbean', 'central', 'mexico', 'pr', 'pc', 'xbox', 'ps',
                'preferences_separator', 'crew', 'citizen', 'veteran', 'legend',
                'community_separator', 'creator', 'support', 'mod', 'admin',
                'team_separator', 'bot', 'founder']
        self.roles.append(Role(self.guild, GUILD_ID, '@everyone', 0))
        self.by_key = {}
        for position, key in enumerate(keys, 1):
            spec = self.specs.get(key)
            name = spec[1] if spec else key
            if key == 'preferences_separator':
                name = '━━ 🎮 PREFERENCIAS ━━'
            role = Role(self.guild, 1000 + position, name, position, managed=key == 'bot',
                        permissions=8 if key in {'bot', 'admin', 'founder'} else 0)
            self.roles.append(role)
            self.by_key[key] = role
            self.store.put('role:' + key, role.id)
        self.guild.me = NS(id=BOT_ID, roles=[self.roles[0], self.by_key['bot']])
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild = 555, self.guild
        self.channel.name, self.channel.topic = 'elige-tus-roles', 'Old topic'
        self.channel.position, self.channel.category_id = 1, 333
        self.channel.type, self.channel._overwrites = discord.ChannelType.text, []
        self.channel.edit = AsyncMock(side_effect=self.edit_channel)
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles))
        self.guild.fetch_channels = AsyncMock(return_value=[self.channel])
        self.guild.fetch_channel = AsyncMock(return_value=self.channel)
        self.guild.create_role = AsyncMock(side_effect=self.create_role)
        self.guild.edit_role_positions = AsyncMock(side_effect=self.reorder)
        self.guild.audit_logs = MagicMock(side_effect=lambda **kwargs: entries([]))
        self.system = NS(store=self.store, role_cache={}, roles_lock=asyncio.Lock())
        self.system.bot = NS(user=NS(id=BOT_ID), get_guild=lambda _gid: self.guild)
        self.system.validate_guild = self.validate_guild
        self.system.channel_id = lambda key: 555 if key == 'roles' else None
        self.system.call = AsyncMock(side_effect=lambda method, *args: getattr(self.store, method)(*args))
        self.system.find_panel = AsyncMock(return_value=NS(id=444, content='', embeds=[], components=[], pinned=True))
        self.snapshots = []
        self.system.track = AsyncMock(side_effect=self.track)
        self.manager = OptionalRoles(self.system)
        self.refresh = AsyncMock()

    def validate_guild(self, guild):
        if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('Wrong guild')

    async def track(self, kind, title, operation, request, snapshot=None):
        self.snapshots.append(await snapshot())
        result = await operation()
        self.snapshots.append(await snapshot())
        return result

    async def create_role(self, **values):
        for role in self.roles[1:]:
            role.position += 1
        role = Role(self.guild, 5000 + len(self.roles), values['name'], 1)
        await role.update(**values)
        role.edit.reset_mock()
        self.roles.append(role)
        return role

    async def reorder(self, positions, **kwargs):
        remaining = sorted(role for role in self.roles if role not in positions)
        targets = sorted(positions, key=positions.get)
        base = min(positions.values())
        ordered = remaining[:base] + targets + remaining[base:]
        for index, role in enumerate(ordered):
            role.position = index
        return ordered

    async def edit_channel(self, **values):
        self.channel.topic = values['topic']
        return self.channel

    async def test_additive_migration_reuses_legacy_ids_and_keeps_assignments(self):
        previous = {key: role.id for key, role in self.by_key.items()}
        original_member_lists = {role.id: list(role.members) for role in self.roles}
        remaining_before = [role.id for role in sorted(self.roles) if role.id not in {
            previous[key] for key in self.specs if key in previous}]
        await self.manager.ready(self.refresh)
        self.assertEqual(self.store.get(RELEASE_KEY), CATALOG_VERSION)
        self.assertEqual(self.store.get('release'), None)
        for key, rid in previous.items():
            self.assertEqual(self.store.get('role:' + key), rid)
        for role in self.roles:
            if role.id in original_member_lists:
                self.assertEqual(role.members, original_member_lists[role.id])
        self.assertEqual(self.by_key['preferences_separator'].name, '━━ 🎮 PLATAFORMAS ━━')
        ordered_ids = [self.store.get('role:' + key) for key, *_ in OPTIONAL_ROLES]
        self.assertEqual([role.id for role in sorted(self.roles, reverse=True) if role.id in ordered_ids], ordered_ids)
        self.assertEqual([role.id for role in sorted(self.roles) if role.id not in ordered_ids], remaining_before)
        self.assertLess(self.by_key['entry_separator'].position, min(role.position for role in self.roles if role.id in ordered_ids))
        self.assertGreater(self.by_key['crew'].position, max(role.position for role in self.roles if role.id in ordered_ids))
        self.assertEqual(self.channel.topic, ROLES_TOPIC)
        self.refresh.assert_awaited_once()
        self.assertEqual(self.snapshots[0]['roles_panel']['id'], '444')
        self.assertEqual(self.snapshots[0]['catalog_release'], None)
        self.assertTrue(all(call.kwargs['permissions'].value == 0 for call in self.guild.create_role.await_args_list))
        for key in ('admin', 'mod', 'support', 'member', 'citizen', 'crew', 'founder'):
            self.by_key[key].edit.assert_not_awaited()
        changed = self.guild.edit_role_positions.await_args.kwargs['positions']
        self.assertEqual({role.id for role in changed}, set(ordered_ids))

    async def test_completed_migration_does_not_repeat_any_writes(self):
        await self.manager.ready(self.refresh)
        creates, moves = self.guild.create_role.await_count, self.guild.edit_role_positions.await_count
        await self.manager.ready(self.refresh)
        self.assertEqual(self.guild.create_role.await_count, creates)
        self.assertEqual(self.guild.edit_role_positions.await_count, moves)
        self.system.track.assert_awaited_once()
        self.refresh.assert_awaited_once()

    async def test_wrong_guild_owner_or_bot_rejected_before_tracking(self):
        for target, attr, invalid in [(self.guild, 'id', 1514871828189941881),
                                      (self.guild, 'owner_id', 2),
                                      (self.system.bot.user, 'id', 3),
                                      (self.guild.me, 'id', 4)]:
            before = getattr(target, attr)
            setattr(target, attr, invalid)
            with self.assertRaises(ValueError):
                await self.manager.ready(self.refresh)
            setattr(target, attr, before)
        self.system.track.assert_not_awaited()
        self.guild.create_role.assert_not_awaited()

    async def test_powered_existing_optional_role_blocks_preflight_without_mutations(self):
        self.by_key['pr'].permissions = discord.Permissions(administrator=True)
        with self.assertRaises(ValueError):
            await self.manager.ready(self.refresh)
        self.guild.create_role.assert_not_awaited()
        self.guild.edit_role_positions.assert_not_awaited()
        for role in self.roles:
            role.edit.assert_not_awaited()
        self.assertIsNone(self.store.get(RELEASE_KEY))

    async def test_missing_duplicate_or_protected_registry_ids_block_preflight(self):
        original = self.store.get('role:pr')
        for invalid in (999999, self.by_key['mexico'].id, self.by_key['member'].id):
            self.store.put('role:pr', invalid)
            with self.assertRaises(ValueError):
                await self.manager.ready(self.refresh)
        self.store.put('role:pr', original)
        self.guild.create_role.assert_not_awaited()

    async def test_same_named_foreign_role_is_not_adopted(self):
        key, name, color, *_ = next(spec for spec in OPTIONAL_ROLES if not self.store.get('role:' + spec[0]))
        foreign = Role(self.guild, 999999, name, len(self.roles) + 1)
        self.roles.append(foreign)
        await self.manager.ready(self.refresh)
        self.assertNotEqual(self.store.get('role:' + key), foreign.id)
        foreign.edit.assert_not_awaited()

    async def test_role_capacity_is_checked_before_any_create(self):
        for offset in range(200):
            self.roles.append(Role(self.guild, 80000 + offset, 'existing', 100 + offset))
        with self.assertRaises(ValueError):
            await self.manager.ready(self.refresh)
        self.guild.create_role.assert_not_awaited()

    async def test_revalidates_permissions_after_creation_before_reordering(self):
        calls = 0
        def current_roles():
            nonlocal calls
            calls += 1
            # snapshot, preflight, then fresh read after the creation loop.
            if calls == 3:
                self.by_key['pr'].permissions = discord.Permissions(administrator=True)
            return list(self.roles)
        self.guild.fetch_roles.side_effect = current_roles
        with self.assertRaises(ValueError):
            await self.manager.ready(self.refresh)
        self.guild.edit_role_positions.assert_not_awaited()
        self.refresh.assert_not_awaited()
        self.assertIsNone(self.store.get(RELEASE_KEY))

    async def test_interrupted_creation_recovers_only_exact_bot_audit_nonce(self):
        spec = next(spec for spec in OPTIONAL_ROLES if not self.store.get('role:' + spec[0]))
        role = await self.create_role(name=spec[1], colour=discord.Colour(spec[2]), permissions=discord.Permissions.none())
        self.store.put('optional_roles:create:' + spec[0], dict(nonce='safe123', attempted=True))
        self.guild.audit_logs.side_effect = lambda **kwargs: entries([
            NS(user=NS(id=BOT_ID), reason=REASON + ' • nonce:safe123', target=NS(id=role.id))])
        roles = {item.id: item for item in self.roles}
        result = await self.manager.ensure_role(self.guild, spec, roles, self.by_key['bot'], set())
        self.assertEqual(result.id, role.id)
        self.assertEqual(self.store.get('role:' + spec[0]), role.id)
        self.guild.create_role.assert_not_awaited()

    async def test_ambiguous_create_never_blindly_retries_or_adopts_by_name(self):
        spec = next(spec for spec in OPTIONAL_ROLES if not self.store.get('role:' + spec[0]))
        self.store.put('optional_roles:create:' + spec[0], dict(nonce='pending', attempted=True))
        with self.assertRaises(ValueError):
            await self.manager.ensure_role(self.guild, spec, {role.id: role for role in self.roles}, self.by_key['bot'], set())
        self.guild.create_role.assert_not_awaited()

    async def test_panel_failure_can_resume_without_recreating_roles(self):
        self.refresh.side_effect = RuntimeError('temporary panel failure')
        with self.assertRaises(RuntimeError):
            await self.manager.ready(self.refresh)
        self.assertIsNone(self.store.get(RELEASE_KEY))
        count = self.guild.create_role.await_count
        self.refresh.side_effect = None
        await self.manager.ready(self.refresh)
        self.assertEqual(self.guild.create_role.await_count, count)
        self.assertEqual(self.store.get(RELEASE_KEY), CATALOG_VERSION)


if __name__ == '__main__':
    unittest.main()
