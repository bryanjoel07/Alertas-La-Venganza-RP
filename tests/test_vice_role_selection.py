import asyncio
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import vice_district
from vice_design import GUILD_ID, OWNER_ID, ROLES
from vice_district import ViceDistrict, RolesPanel
from vice_role_catalog import COUNTRY_KEYS, GROUP_SCOPES, OPTIONAL_GROUPS, OPTIONAL_ROLES


class OptionalRoleSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        specs = {row[0]: row for row in ROLES}
        specs.update({row[0]: row for row in OPTIONAL_ROLES})
        self.specs = list(specs.values())
        self.self_roles = frozenset(key for _, keys, _ in OPTIONAL_GROUPS.values() for key in keys)
        for name, value in [('ROLES', self.specs), ('GROUPS', OPTIONAL_GROUPS),
                            ('SELF_ROLES', self.self_roles), ('GROUP_SCOPES', GROUP_SCOPES)]:
            change = patch.object(vice_district, name, value)
            change.start()
            self.addCleanup(change.stop)
        self.guild = MagicMock()
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.member = MagicMock(spec=discord.Member)
        self.member.id, self.member.bot, self.member.guild = 77, False, self.guild
        self.member.roles = []
        self.member.add_roles, self.member.remove_roles = AsyncMock(), AsyncMock()
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.rolemap, self.values = {}, {}
        for role_id, (key, name, color, permissions, *_rest) in enumerate(self.specs, 1000):
            role = MagicMock(spec=discord.Role)
            role.id, role.name, role.guild, role.managed = role_id, name, self.guild, False
            role.permissions = discord.Permissions(**permissions)
            self.rolemap[key] = role
            self.values['role:' + key] = role_id
        self.guild.fetch_roles = AsyncMock(side_effect=lambda: list(self.rolemap.values()))
        self.system = ViceDistrict.__new__(ViceDistrict)
        self.system.store = NS(get=self.values.get)
        self.system.roles_lock = asyncio.Lock()
        self.system.role_snapshot = AsyncMock(return_value={'roles': []})
        async def tracked(kind, title, action, request, snapshot):
            await snapshot()
            return await action()
        self.system.track = AsyncMock(side_effect=tracked)
        self.interaction = NS(id=888, guild=self.guild, guild_id=GUILD_ID, user=self.member)

    def assert_no_mutation(self):
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_country_switch_across_pages_preserves_regions_platforms_and_staff(self):
        self.member.roles = [self.rolemap[key] for key in ['pr', 'caribbean', 'pc', 'events', 'support']]
        await self.system.select_roles(self.interaction, 'country_b', ['mexico'])
        self.member.remove_roles.assert_awaited_once_with(
            self.rolemap['pr'], reason='Roles opcionales elegidos por el miembro')
        self.member.add_roles.assert_awaited_once_with(
            self.rolemap['mexico'], reason='Roles opcionales elegidos por el miembro')
        self.system.role_snapshot.assert_awaited_once_with(self.guild, 77)

    async def test_first_country_page_replaces_country_on_second_page(self):
        self.member.roles = [self.rolemap['mexico'], self.rolemap['xbox']]
        await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['mexico'],))
        self.assertEqual(self.member.add_roles.await_args.args, (self.rolemap['pr'],))

    async def test_clearing_either_country_menu_clears_only_country(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['caribbean'], self.rolemap['news']]
        await self.system.select_roles(self.interaction, 'country_b', [])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['pr'],))
        self.member.add_roles.assert_not_awaited()

    async def test_regions_accept_overlapping_choices_without_changing_country(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['central'], self.rolemap['ps']]
        await self.system.select_roles(self.interaction, 'region', ['caribbean', 'greater_antilles'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['central'],))
        self.assertEqual(set(self.member.add_roles.await_args.args),
                         {self.rolemap['caribbean'], self.rolemap['greater_antilles']})

    async def test_current_selection_does_not_write_member_roles_again(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['pc']]
        await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()

    async def test_staff_cross_page_duplicate_and_excess_country_inputs_are_rejected(self):
        invalid = [('country_a', ['admin']), ('country_a', ['mexico']),
                   ('country_a', ['pr', 'pr']), ('country_a', ['pr', 'argentina']),
                   ('platform', ['mod']), ('platform', ['pc', 'pc'])]
        for group, selected in invalid:
            with self.subTest(group=group, selected=selected), self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction, group, selected)
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_legacy_region_country_selection_requests_refreshed_panel(self):
        with self.assertRaisesRegex(ValueError, 'panel actualizado'):
            await self.system.select_roles(self.interaction, 'region', ['pr'])
        self.assert_no_mutation()

    async def test_permission_drift_is_rejected_using_fresh_role_definitions(self):
        changed = MagicMock(spec=discord.Role)
        changed.id, changed.guild, changed.managed = self.rolemap['pc'].id, self.guild, False
        changed.permissions = discord.Permissions(administrator=True)
        fresh = [changed if role.id == changed.id else role for role in self.rolemap.values()]
        self.guild.fetch_roles.side_effect = None
        self.guild.fetch_roles.return_value = fresh
        self.assertEqual(self.rolemap['pc'].permissions.value, 0)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        self.assert_no_mutation()

    async def test_managed_missing_or_foreign_role_is_rejected(self):
        role = self.rolemap['pc']
        role.managed = True
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        role.managed = False
        role.guild = NS(id=123)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        role.guild = self.guild
        self.values['role:pc'] = -1
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        self.assert_no_mutation()

    async def test_missing_role_on_other_country_page_cannot_leave_two_countries(self):
        self.values['role:venezuela'] = -1
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.assert_no_mutation()

    async def test_aliased_optional_role_cannot_assign_protected_or_duplicate_role(self):
        self.rolemap['support'].permissions = discord.Permissions.none()
        self.values['role:pc'] = self.rolemap['support'].id
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        self.values['role:pc'] = self.rolemap['ps'].id
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['pc'])
        self.assert_no_mutation()

    async def test_corrupt_scope_cannot_remove_or_add_a_staff_role(self):
        with patch.object(vice_district, 'GROUP_SCOPES', {'platform': ('pc', 'ps', 'xbox', 'admin')}):
            with self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction, 'platform', ['pc'])
        self.assert_no_mutation()

    async def test_wrong_guild_owner_or_bot_member_is_rejected_before_rest(self):
        self.guild.id = 123
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.guild.id, self.guild.owner_id = GUILD_ID, 123
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.guild.owner_id, self.member.bot = OWNER_ID, True
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_wrong_fresh_member_is_rejected_before_mutation(self):
        self.guild.fetch_member.return_value = NS(id=999, guild=self.guild, bot=False)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country_a', ['pr'])
        self.assert_no_mutation()

    async def test_panel_fits_five_discord_rows_and_all_countries_are_available_once(self):
        view = RolesPanel(self.system)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 5)
        self.assertEqual(len({item.custom_id for item in view.children}), 5)
        countries = []
        for item in view.children:
            self.assertLessEqual(len(item.options), 25)
            self.assertLessEqual(item.max_values, len(item.options))
            if item.group.startswith('country_'):
                self.assertEqual(item.max_values, 1)
                countries.extend(option.value for option in item.options)
        self.assertEqual(countries, list(COUNTRY_KEYS))
        self.assertEqual(len(countries), len(set(countries)))


if __name__ == '__main__':
    unittest.main()
