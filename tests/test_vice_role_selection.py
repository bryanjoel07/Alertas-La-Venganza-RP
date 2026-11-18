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

    async def test_country_switch_preserves_regions_platforms_and_staff(self):
        self.member.roles = [self.rolemap[key] for key in ['pr', 'caribbean', 'ps', 'pc', 'crew', 'support']]
        await self.system.select_roles(self.interaction, 'country', ['mexico'])
        self.member.remove_roles.assert_awaited_once_with(
            self.rolemap['pr'], reason='Roles opcionales elegidos por el miembro')
        self.member.add_roles.assert_awaited_once_with(
            self.rolemap['mexico'], reason='Roles opcionales elegidos por el miembro')
        self.system.role_snapshot.assert_awaited_once_with(self.guild, 77)

    async def test_selecting_country_replaces_previous_country(self):
        self.member.roles = [self.rolemap['mexico'], self.rolemap['xbox']]
        await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['mexico'],))
        self.assertEqual(self.member.add_roles.await_args.args, (self.rolemap['pr'],))

    async def test_clearing_country_menu_clears_only_country(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['caribbean'], self.rolemap['crew']]
        await self.system.select_roles(self.interaction, 'country', [])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['pr'],))
        self.member.add_roles.assert_not_awaited()

    async def test_regions_accept_overlapping_choices_without_changing_country(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['south'], self.rolemap['ps']]
        await self.system.select_roles(self.interaction, 'region', ['caribbean', 'central'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['south'],))
        self.assertEqual(set(self.member.add_roles.await_args.args),
                         {self.rolemap['caribbean'], self.rolemap['central']})

    async def test_current_selection_does_not_write_member_roles_again(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['ps']]
        await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_not_awaited()

    async def test_staff_removed_country_duplicate_and_excess_country_inputs_are_rejected(self):
        invalid = [('country', ['admin']), ('country', ['brazil']), ('country', ['jamaica']),
                   ('country', ['pr', 'pr']), ('country', ['pr', 'argentina']),
                   ('platform', ['mod']), ('platform', ['ps', 'ps'])]
        for group, selected in invalid:
            with self.subTest(group=group, selected=selected), self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction, group, selected)
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_legacy_region_country_selection_requests_refreshed_panel(self):
        with self.assertRaisesRegex(ValueError, 'panel actualizado'):
            await self.system.select_roles(self.interaction, 'region', ['pr'])
        self.assert_no_mutation()

    async def test_retired_country_menus_cannot_assign_even_a_still_supported_country(self):
        for obsolete in ['country_a', 'country_b']:
            with self.subTest(group=obsolete), self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction, obsolete, ['pr'])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_retired_platform_values_require_current_menu(self):
        for obsolete in ['nintendo', 'steam_deck', 'android', 'ios', 'macos', 'linux', 'vr']:
            with self.subTest(value=obsolete), self.assertRaisesRegex(ValueError, 'panel actualizado'):
                await self.system.select_roles(self.interaction, 'platform', [obsolete])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_pc_waiting_platform_can_be_chosen_alongside_console_without_changing_other_groups(self):
        self.member.roles = [self.rolemap['ps'], self.rolemap['pr'], self.rolemap['caribbean'],
                             self.rolemap['crew']]
        await self.system.select_roles(self.interaction, 'platform', ['ps', 'pc'])
        self.member.remove_roles.assert_not_awaited()
        self.member.add_roles.assert_awaited_once_with(
            self.rolemap['pc'], reason='Roles opcionales elegidos por el miembro')

    async def test_platform_change_keeps_selected_pc_and_preserves_interests(self):
        self.member.roles = [self.rolemap['ps'], self.rolemap['pc'], self.rolemap['crew']]
        await self.system.select_roles(self.interaction, 'platform', ['xbox', 'xbox_one_cloud', 'pc'])
        self.assertEqual(self.member.remove_roles.await_args.args, (self.rolemap['ps'],))
        self.assertEqual(set(self.member.add_roles.await_args.args),
                         {self.rolemap['xbox'], self.rolemap['xbox_one_cloud']})

    async def test_pc_cannot_be_assigned_from_interest_menu(self):
        with self.assertRaisesRegex(ValueError, 'panel actualizado'):
            await self.system.select_roles(self.interaction, 'interests', ['pc'])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_owner_removed_region_and_notice_values_cannot_be_reassigned(self):
        removed = [('region', key) for key in ['andean', 'southern_cone', 'amazon']]
        removed += [('interests', key) for key in ['news', 'events']]
        for group, key in removed:
            with self.subTest(group=group, key=key), self.assertRaisesRegex(ValueError, 'panel actualizado'):
                await self.system.select_roles(self.interaction, group, [key])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_crew_can_be_added_without_changing_country_region_or_platform(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['caribbean'], self.rolemap['pc']]
        await self.system.select_roles(self.interaction, 'interests', ['crew'])
        self.member.remove_roles.assert_not_awaited()
        self.member.add_roles.assert_awaited_once_with(
            self.rolemap['crew'], reason='Roles opcionales elegidos por el miembro')

    async def test_clearing_crew_preserves_country_region_and_platform(self):
        self.member.roles = [self.rolemap['pr'], self.rolemap['caribbean'], self.rolemap['pc'],
                             self.rolemap['crew']]
        await self.system.select_roles(self.interaction, 'interests', [])
        self.member.add_roles.assert_not_awaited()
        self.member.remove_roles.assert_awaited_once_with(
            self.rolemap['crew'], reason='Roles opcionales elegidos por el miembro')

    async def test_permission_drift_is_rejected_using_fresh_role_definitions(self):
        changed = MagicMock(spec=discord.Role)
        changed.id, changed.guild, changed.managed = self.rolemap['ps'].id, self.guild, False
        changed.permissions = discord.Permissions(administrator=True)
        fresh = [changed if role.id == changed.id else role for role in self.rolemap.values()]
        self.guild.fetch_roles.side_effect = None
        self.guild.fetch_roles.return_value = fresh
        self.assertEqual(self.rolemap['ps'].permissions.value, 0)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        self.assert_no_mutation()

    async def test_managed_missing_or_foreign_role_is_rejected(self):
        role = self.rolemap['ps']
        role.managed = True
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        role.managed = False
        role.guild = NS(id=123)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        role.guild = self.guild
        self.values['role:ps'] = -1
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        self.assert_no_mutation()

    async def test_missing_country_role_cannot_leave_two_countries(self):
        self.values['role:venezuela'] = -1
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.assert_no_mutation()

    async def test_aliased_optional_role_cannot_assign_protected_or_duplicate_role(self):
        self.rolemap['support'].permissions = discord.Permissions.none()
        self.values['role:ps'] = self.rolemap['support'].id
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        self.values['role:ps'] = self.rolemap['xbox'].id
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'platform', ['ps'])
        self.assert_no_mutation()

    async def test_corrupt_scope_cannot_remove_or_add_a_staff_role(self):
        with patch.object(vice_district, 'GROUP_SCOPES', {'platform': ('ps', 'xbox', 'xbox_one_cloud', 'pc', 'admin')}):
            with self.assertRaises(ValueError):
                await self.system.select_roles(self.interaction, 'platform', ['ps'])
        self.assert_no_mutation()

    async def test_wrong_guild_owner_or_bot_member_is_rejected_before_rest(self):
        self.guild.id = 123
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.guild.id, self.guild.owner_id = GUILD_ID, 123
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.guild.owner_id, self.member.bot = OWNER_ID, True
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.guild.fetch_roles.assert_not_awaited()
        self.assert_no_mutation()

    async def test_wrong_fresh_member_is_rejected_before_mutation(self):
        self.guild.fetch_member.return_value = NS(id=999, guild=self.guild, bot=False)
        with self.assertRaises(ValueError):
            await self.system.select_roles(self.interaction, 'country', ['pr'])
        self.assert_no_mutation()

    async def test_panel_has_four_rows_and_single_country_menu(self):
        view = RolesPanel(self.system)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children), 4)
        self.assertEqual(len({item.custom_id for item in view.children}), 4)
        countries = []
        for item in view.children:
            self.assertLessEqual(len(item.options), 25)
            self.assertLessEqual(item.max_values, len(item.options))
            if item.group == 'country':
                self.assertEqual(item.max_values, 1)
                countries.extend(option.value for option in item.options)
            elif item.group == 'platform':
                self.assertEqual({option.value for option in item.options},
                                 {'ps', 'xbox', 'xbox_one_cloud', 'pc'})
                self.assertEqual(item.max_values, 4)
            elif item.group == 'region':
                self.assertEqual({option.value for option in item.options},
                                 {'caribbean', 'central', 'south', 'north', 'greater_antilles'})
                self.assertEqual(item.max_values, 5)
            elif item.group == 'interests':
                self.assertEqual({option.value for option in item.options}, {'crew'})
                self.assertEqual(item.max_values, 1)
        self.assertEqual(len(countries), 19)
        self.assertEqual(countries, list(COUNTRY_KEYS))
        self.assertEqual(len(countries), len(set(countries)))


if __name__ == '__main__':
    unittest.main()
