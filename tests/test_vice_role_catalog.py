import unittest

from vice_role_catalog import (COUNTRY_DATA, COUNTRY_KEYS, COUNTRY_GROUPS,
    GROUP_SCOPES, OPTIONAL_GROUPS, OPTIONAL_ROLES, PLATFORM_SEPARATOR_KEY,
    REGION_KEYS, PLATFORM_KEYS, RETIRED_KEYS, CATALOG_VERSION)


class OptionalRoleCatalogTests(unittest.TestCase):
    def test_every_optional_role_is_cosmetic(self):
        keys = [role[0] for role in OPTIONAL_ROLES]
        self.assertEqual(len(keys), len(set(keys)))
        for key, name, color, permissions, hoist, old_name in OPTIONAL_ROLES:
            with self.subTest(role=key):
                self.assertEqual(permissions, {})
                self.assertFalse(hoist)
                self.assertTrue(0 < color <= 0xFFFFFF)
                self.assertLessEqual(len(name), 100)
                self.assertIsNone(old_name)

    def test_exact_owner_corrected_hispanic_country_scope(self):
        expected_codes = {
            'PR', 'AR', 'BO', 'CL', 'CO', 'CR', 'CU', 'EC', 'SV', 'GT', 'HN',
            'MX', 'NI', 'PA', 'PY', 'PE', 'DO', 'UY', 'VE',
        }
        self.assertEqual({row[1] for row in COUNTRY_DATA}, expected_codes)
        self.assertEqual(len(COUNTRY_KEYS), 19)
        self.assertEqual(COUNTRY_KEYS[0], 'pr')
        self.assertEqual(CATALOG_VERSION, 'vice-optional-role-catalog-v2-hispano')

    def test_selects_fit_discord_and_cannot_assign_staff_or_separators(self):
        self.assertEqual(len(OPTIONAL_GROUPS), 4)
        all_keys = {role[0] for role in OPTIONAL_ROLES} | {'crew'}
        for group, (label, keys, maximum) in OPTIONAL_GROUPS.items():
            with self.subTest(group=group):
                self.assertLessEqual(len(keys), 25)
                self.assertLessEqual(maximum, len(keys))
                self.assertGreaterEqual(maximum, 1)
                self.assertLessEqual(len(label), 150)
                self.assertTrue(set(keys) <= all_keys)
                self.assertFalse(set(keys) & {'admin', 'mod', 'support', 'founder',
                    'member', 'citizen', 'veteran', 'legend', 'creator'})
                self.assertFalse(any('separator' in key for key in keys))

    def test_one_country_selector_with_isolated_replacement_domain(self):
        self.assertEqual(set(COUNTRY_GROUPS), {'country'})
        for key, (_, choices, maximum) in COUNTRY_GROUPS.items():
            self.assertEqual(maximum, 1)
            self.assertEqual(choices, list(COUNTRY_KEYS))
            self.assertEqual(set(GROUP_SCOPES[key]), set(COUNTRY_KEYS))
        # Selecting a country must not remove a platform or regional role.
        self.assertFalse(set(COUNTRY_KEYS) & set(GROUP_SCOPES['region']))
        self.assertFalse(set(COUNTRY_KEYS) & set(GROUP_SCOPES['platform']))

    def test_existing_identity_roles_and_platform_separator_keep_keys(self):
        keys = {role[0] for role in OPTIONAL_ROLES}
        self.assertTrue({'pr', 'mexico', 'ps', 'xbox', 'pc', 'central',
            'caribbean', 'south', 'north', 'news', 'events'} <= keys)
        self.assertEqual(PLATFORM_SEPARATOR_KEY, 'preferences_separator')
        roles = {role[0]: role for role in OPTIONAL_ROLES}
        self.assertIn('PLATAFORMAS', roles[PLATFORM_SEPARATOR_KEY][1])
        self.assertFalse(any('PREFERENCIAS' in role[1] for role in OPTIONAL_ROLES))

    def test_retirement_is_frozen_to_requested_countries_regions_and_platforms(self):
        expected = {
            'anguilla', 'antigua_barbuda', 'aruba', 'bahamas', 'barbados', 'belize',
            'bonaire_saba_eustatius', 'brazil', 'curacao', 'dominica', 'grenada',
            'guadeloupe', 'french_guiana', 'guyana', 'haiti', 'cayman_islands',
            'falkland_islands', 'turks_caicos', 'british_virgin_islands',
            'us_virgin_islands', 'jamaica', 'martinique', 'montserrat',
            'saint_barthelemy', 'saint_kitts_nevis', 'saint_martin',
            'saint_vincent_grenadines', 'saint_lucia', 'sint_maarten', 'suriname',
            'trinidad_tobago', 'lesser_antilles', 'guianas', 'europe',
            'nintendo', 'steam_deck', 'android', 'ios', 'macos', 'linux', 'vr',
        }
        self.assertIsInstance(RETIRED_KEYS, frozenset)
        self.assertEqual(RETIRED_KEYS, expected)
        self.assertEqual(len(RETIRED_KEYS), 41)
        self.assertFalse(RETIRED_KEYS & {role[0] for role in OPTIONAL_ROLES})
        self.assertFalse(RETIRED_KEYS & set.union(*(set(keys) for _, keys, _ in OPTIONAL_GROUPS.values())))
        self.assertEqual(set(REGION_KEYS), {'caribbean', 'central', 'south',
            'north', 'greater_antilles', 'andean', 'southern_cone', 'amazon'})
        self.assertEqual(PLATFORM_KEYS, ('ps', 'xbox', 'xbox_one_cloud'))

    def test_pc_keeps_key_only_as_unconfirmed_release_interest(self):
        roles = {role[0]: role for role in OPTIONAL_ROLES}
        self.assertEqual(len(OPTIONAL_ROLES), 37)
        self.assertEqual(roles['ps'][1], '🎮 PlayStation 5')
        self.assertEqual(roles['xbox'][1], '🎮 Xbox Series X|S')
        self.assertEqual(roles['xbox_one_cloud'][1], '☁️ Xbox One · Nube')
        self.assertEqual(roles['pc'][1], '⌛ PC · Esperando GTA VI')
        self.assertNotIn('pc', GROUP_SCOPES['platform'])
        self.assertIn('pc', GROUP_SCOPES['interests'])
        self.assertNotIn('pc', RETIRED_KEYS)
        role_order = list(roles)
        self.assertGreater(role_order.index('pc'), role_order.index('interests_separator'))


if __name__ == '__main__':
    unittest.main()
