import unittest

from vice_role_catalog import (COUNTRY_DATA, COUNTRY_KEYS, COUNTRY_GROUPS,
    GROUP_SCOPES, OPTIONAL_GROUPS, OPTIONAL_ROLES, PLATFORM_SEPARATOR_KEY)


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

    def test_complete_inhabited_m49_latin_america_caribbean(self):
        expected_codes = {
            'AI', 'AG', 'AW', 'BS', 'BB', 'BQ', 'VG', 'KY', 'CU', 'CW', 'DM',
            'DO', 'GD', 'GP', 'HT', 'JM', 'MQ', 'MS', 'PR', 'BL', 'KN', 'LC',
            'MF', 'VC', 'SX', 'TT', 'TC', 'VI', 'BZ', 'CR', 'SV', 'GT', 'HN',
            'MX', 'NI', 'PA', 'AR', 'BO', 'BR', 'CL', 'CO', 'EC', 'FK', 'GF',
            'GY', 'PY', 'PE', 'SR', 'UY', 'VE',
        }
        self.assertEqual({row[1] for row in COUNTRY_DATA}, expected_codes)
        self.assertEqual(len(COUNTRY_KEYS), 50)
        self.assertEqual(COUNTRY_KEYS[0], 'pr')

    def test_selects_fit_discord_and_cannot_assign_staff_or_separators(self):
        self.assertEqual(len(OPTIONAL_GROUPS), 5)
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

    def test_country_pages_share_one_replacement_domain(self):
        pages = [set(keys) for _, keys, maximum in COUNTRY_GROUPS.values()]
        self.assertFalse(pages[0] & pages[1])
        self.assertEqual(set.union(*pages), set(COUNTRY_KEYS))
        for key, (_, choices, maximum) in COUNTRY_GROUPS.items():
            self.assertEqual(maximum, 1)
            self.assertEqual(set(GROUP_SCOPES[key]), set(COUNTRY_KEYS))
        # Selecting in either page must not remove a platform or regional role.
        self.assertFalse(set(COUNTRY_KEYS) & set(GROUP_SCOPES['region']))
        self.assertFalse(set(COUNTRY_KEYS) & set(GROUP_SCOPES['platform']))

    def test_existing_identity_roles_and_platform_separator_keep_keys(self):
        keys = {role[0] for role in OPTIONAL_ROLES}
        self.assertTrue({'pr', 'mexico', 'ps', 'xbox', 'pc', 'central',
            'caribbean', 'south', 'north', 'europe', 'news', 'events'} <= keys)
        self.assertEqual(PLATFORM_SEPARATOR_KEY, 'preferences_separator')
        roles = {role[0]: role for role in OPTIONAL_ROLES}
        self.assertIn('PLATAFORMAS', roles[PLATFORM_SEPARATOR_KEY][1])
        self.assertFalse(any('PREFERENCIAS' in role[1] for role in OPTIONAL_ROLES))


if __name__ == '__main__':
    unittest.main()
