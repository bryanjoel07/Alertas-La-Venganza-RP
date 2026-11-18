"""Role icon installation never changes role identity, power or user choices."""
import copy
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from PIL import Image

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_role_icons import RoleIcons, VERSION


class Store:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)


class Role:
    def __init__(self, guild, rid, key, position, events, *, managed=False, permissions=0):
        self.guild, self.id, self.name = guild, rid, key
        self.position, self.managed = position, managed
        self.permissions = discord.Permissions(permissions)
        self.color = self.colour = discord.Colour(0x33E5E9)
        self.hoist, self.mentionable = True, False
        self.members = [OWNER_ID]
        self.icon, self.unicode_emoji = None, None
        self._icon = None
        self.events = events
        self.edit = AsyncMock(side_effect=self.update_icon)
        self.delete = AsyncMock()

    def __lt__(self, other):
        return (self.position, -self.id) < (other.position, -other.id)

    def is_default(self):
        return self.id == GUILD_ID

    def is_bot_managed(self):
        return self.managed and self.name == 'bot'

    async def update_icon(self, **kwargs):
        self.events.append(('edit', self.id))
        raw = kwargs['display_icon']
        self._icon = hashlib.md5(raw).hexdigest()
        self.icon = NS(key=self._icon)
        self.unicode_emoji = None
        return self


class RoleIconTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.assets = Path(self.temp.name)
        (self.assets / 'png').mkdir()
        self.events = []
        self.store = Store()
        self.guild = NS(id=GUILD_ID, owner_id=OWNER_ID, features=['ROLE_ICONS'], premium_tier=2)
        keys = [('member', 1572473450000000001, 1, False, 0),
                ('pr', 1572475199696404592, 5, False, 0),
                ('admin', 1572581938798272642, 10, False, 8),
                ('booster', 1572695862809853982, 12, True, 0),
                ('bot', 1572466655785652308, 20, True, 8),
                ('founder', 1572465087304700047, 25, False, 8)]
        self.by_key = {key: Role(self.guild, rid, key, position, self.events,
                                 managed=managed, permissions=permissions)
                       for key, rid, position, managed, permissions in keys}
        self.everyone = Role(self.guild, GUILD_ID, '@everyone', 0, self.events)
        self.roles = [self.everyone, *self.by_key.values()]
        self.bot_member = NS(id=BOT_ID, guild=self.guild, bot=True,
                             _roles=[self.by_key['bot'].id], roles=[self.everyone, self.by_key['bot']],
                             top_role=self.by_key['bot'],
                             guild_permissions=discord.Permissions(manage_roles=True))
        self.guild.me = self.bot_member
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.roles))
        self.guild.fetch_member = AsyncMock(return_value=self.bot_member)
        self.guild.get_role = lambda rid: next((r for r in self.roles if r.id == rid), None)
        self.guild.create_role = AsyncMock()
        self.guild.edit_role_positions = AsyncMock()
        self.bot = NS(user=NS(id=BOT_ID), fetch_guild=AsyncMock(return_value=self.guild),
                      get_guild=lambda _gid: self.guild)
        self.system = NS(bot=self.bot, store=self.store, validate_guild=self.validate_guild)
        self.system.call = AsyncMock(side_effect=lambda method, *args: getattr(self.store, method)(*args))
        self.system.track = AsyncMock(side_effect=self.track)
        self.manifest = dict(version=VERSION, guild_id=str(GUILD_ID), capability='ROLE_ICONS', roles=[])
        for key in self.by_key:
            self.store.put('role:' + key, self.by_key[key].id)
            self.add_asset(key)
        self.write_manifest()
        self.manager = RoleIcons(self.system, asset_dir=self.assets)

    def validate_guild(self, guild):
        if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('Wrong guild')

    def add_asset(self, key):
        path = self.assets / 'png' / (key + '.png')
        index = len(self.manifest['roles']) + 1
        with Image.new('RGBA', (64, 64), (0, 0, 0, 0)) as im:
            im.paste((index * 22, 100, 200, 255), (8, 8, 56, 56))
            im.save(path)
        raw = path.read_bytes()
        row = dict(key=key, id=str(self.by_key[key].id), name=key,
                   path='png/' + key + '.png', bytes=len(raw), width=64, height=64,
                   sha256=hashlib.sha256(raw).hexdigest(),
                   application='owner_session' if key in {'founder', 'bot', 'booster'} else 'bot_when_unlocked')
        self.manifest['roles'].append(row)
        return row

    def write_manifest(self):
        (self.assets / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def row(self, key):
        return next(row for row in self.manifest['roles'] if row['key'] == key)

    async def track(self, kind, title, operation, request, snapshot=None):
        before = await snapshot()
        self.events.append(('before', copy.deepcopy(before)))
        result = await operation()
        self.events.append(('after', await snapshot()))
        return result

    def assert_no_edits(self):
        for role in self.roles:
            role.edit.assert_not_awaited()
            role.delete.assert_not_awaited()
        self.guild.create_role.assert_not_awaited()
        self.guild.edit_role_positions.assert_not_awaited()

    async def test_feature_absent_never_edits_even_if_boost_tier_looks_sufficient(self):
        self.guild.features = []
        self.guild.premium_tier = 3
        await self.manager.ready()
        self.assert_no_edits()

    async def test_wrong_bot_is_rejected_before_any_discord_write(self):
        self.bot.user.id = 123
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_fresh_guild_identity_and_owner_are_validated(self):
        # The cached guild is still correct; a fresh response must be checked.
        for invalid in [NS(id=1514871828189941881, owner_id=OWNER_ID, features=['ROLE_ICONS']),
                        NS(id=GUILD_ID, owner_id=123, features=['ROLE_ICONS'])]:
            self.bot.fetch_guild.return_value = invalid
            with self.subTest(guild=invalid), self.assertRaises(ValueError):
                await self.manager.ready()
        self.assert_no_edits()

    async def test_wrong_fresh_bot_member_never_edits(self):
        self.bot_member.id = 999
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_missing_manage_roles_permission_never_edits(self):
        self.bot_member.guild_permissions = discord.Permissions.none()
        self.by_key['bot'].permissions = discord.Permissions.none()
        with self.assertRaises((ValueError, PermissionError)):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_manifest_guild_mismatch_aborts_whole_pack(self):
        self.manifest['guild_id'] = '1514871828189941881'
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_bad_later_asset_hash_prevents_earlier_icon_writes(self):
        self.row('pr')['sha256'] = '0' * 64
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_duplicate_manifest_role_id_aborts_without_adopting_names(self):
        self.row('pr')['id'] = self.row('member')['id']
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_manifest_path_cannot_escape_asset_directory(self):
        self.row('pr')['path'] = '../outside.png'
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_asset_byte_limit_is_checked_before_mutation(self):
        path = self.assets / self.row('pr')['path']
        raw = path.read_bytes() + b'X' * (256 * 1024)
        path.write_bytes(raw)
        self.row('pr').update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_png_dimensions_are_checked_even_when_hash_matches(self):
        path = self.assets / self.row('pr')['path']
        with Image.new('RGBA', (65, 64), (100, 200, 50, 255)) as im:
            im.save(path)
        raw = path.read_bytes()
        self.row('pr').update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_manifest()
        with self.assertRaises(ValueError):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_png_encoding_is_checked_even_when_hash_matches(self):
        path = self.assets / self.row('pr')['path']
        raw = b'not a png image'
        path.write_bytes(raw)
        self.row('pr').update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        self.write_manifest()
        with self.assertRaises((ValueError, OSError)):
            await self.manager.ready()
        self.assert_no_edits()

    async def test_feature_present_is_authoritative_for_supported_roles(self):
        self.guild.premium_tier = 0
        await self.manager.ready()
        for key in ('member', 'pr', 'admin'):
            self.by_key[key].edit.assert_awaited_once()

    async def test_only_display_icon_changes_and_every_edit_has_prior_durable_snapshot(self):
        before = {key: (role.name, role.position, role.permissions.value, role.color.value,
                        role.hoist, role.mentionable, list(role.members))
                  for key, role in self.by_key.items()}
        await self.manager.ready()
        after = {key: (role.name, role.position, role.permissions.value, role.color.value,
                       role.hoist, role.mentionable, list(role.members))
                 for key, role in self.by_key.items()}
        self.assertEqual(before, after)
        for role in self.by_key.values():
            for call in role.edit.await_args_list:
                self.assertEqual(set(call.kwargs), {'display_icon', 'reason'})
                self.assertIsInstance(call.kwargs['display_icon'], bytes)
            role.delete.assert_not_awaited()
        self.guild.create_role.assert_not_awaited()
        self.guild.edit_role_positions.assert_not_awaited()
        self.assertTrue(any(kind == 'edit' for kind, *_ in self.events))
        for index, event in enumerate(self.events):
            if event[0] == 'edit':
                self.assertGreater(index, 0)
                self.assertEqual(self.events[index - 1][0], 'before')

    async def test_founder_bot_and_booster_are_left_for_owner_session(self):
        await self.manager.ready()
        for key in ('founder', 'bot', 'booster'):
            self.by_key[key].edit.assert_not_awaited()

    async def test_missing_exact_role_never_uses_an_identically_named_replacement(self):
        self.roles.remove(self.by_key['pr'])
        replacement = Role(self.guild, 999999, 'pr', 5, self.events)
        self.roles.append(replacement)
        await self.manager.ready()
        replacement.edit.assert_not_awaited()
        self.by_key['pr'].edit.assert_not_awaited()
        self.guild.create_role.assert_not_awaited()

    async def test_newly_managed_or_higher_role_is_skipped(self):
        self.by_key['pr'].managed = True
        self.by_key['admin'].position = 21
        await self.manager.ready()
        self.by_key['pr'].edit.assert_not_awaited()
        self.by_key['admin'].edit.assert_not_awaited()
        self.by_key['member'].edit.assert_awaited_once()

    async def test_completed_receipts_prevent_repeat_and_preserve_later_owner_icon(self):
        await self.manager.ready()
        counts = {key: role.edit.await_count for key, role in self.by_key.items()}
        self.by_key['pr'].icon = NS(key='later-owner-choice')
        self.by_key['pr']._icon = 'later-owner-choice'
        self.manager = RoleIcons(self.system, asset_dir=self.assets)
        await self.manager.ready()
        self.assertEqual({key: role.edit.await_count for key, role in self.by_key.items()}, counts)
        self.assertEqual(self.by_key['pr'].icon.key, 'later-owner-choice')

    async def test_one_api_failure_is_isolated_and_retried_without_repeating_successes(self):
        role = self.by_key['pr']
        role.edit.side_effect = discord.HTTPException(NS(status=503, reason='Unavailable'), 'Try later')
        await self.manager.ready()
        self.by_key['member'].edit.assert_awaited_once()
        self.by_key['admin'].edit.assert_awaited_once()
        self.assertIsNone(role.icon)
        role.edit.side_effect = role.update_icon
        await self.manager.ready()
        self.assertEqual(role.edit.await_count, 2)
        self.by_key['member'].edit.assert_awaited_once()
        self.by_key['admin'].edit.assert_awaited_once()
        self.assertIsNotNone(role.icon)

    async def test_lost_response_does_not_overwrite_a_later_custom_icon(self):
        role = self.by_key['pr']
        async def lost_response(**kwargs):
            await role.update_icon(**kwargs)
            raise ConnectionError('response lost')
        role.edit.side_effect = lost_response
        await self.manager.ready()
        role.icon, role._icon = NS(key='owner-after-interruption'), 'owner-after-interruption'
        role.edit.side_effect = role.update_icon
        self.manager = RoleIcons(self.system, asset_dir=self.assets)
        await self.manager.ready()
        role.edit.assert_awaited_once()
        self.assertEqual(role.icon.key, 'owner-after-interruption')

    async def test_overlapping_ready_calls_do_not_duplicate_icon_updates(self):
        await asyncio.gather(self.manager.ready(), self.manager.ready())
        for key in ('member', 'pr', 'admin'):
            self.by_key[key].edit.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
