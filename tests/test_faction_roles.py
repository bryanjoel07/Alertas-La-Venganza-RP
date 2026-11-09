import unittest
import discord
from faction_roles import ROLE_NAME,RED,access_overwrite
from navigation import key


class VistaHermosaTests(unittest.TestCase):
    def test_access_changes_only_needed_permissions(self):
        before=discord.PermissionOverwrite(view_channel=False,manage_messages=False,mention_everyone=False)
        after=access_overwrite(before)
        for p in ('view_channel','send_messages','read_message_history','use_application_commands','connect','speak'):
            self.assertTrue(getattr(after,p))
        self.assertFalse(after.manage_messages)
        self.assertFalse(after.mention_everyone)
        self.assertFalse(before.view_channel)

    def test_role_matches_category_and_uses_pure_red(self):
        self.assertEqual(key(ROLE_NAME),'vistahermosa')
        self.assertEqual(RED,0xFF0000)

    def test_access_is_idempotent(self):
        first=access_overwrite(discord.PermissionOverwrite())
        self.assertEqual(access_overwrite(first),first)
