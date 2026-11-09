import unittest
import discord
from server_fixes import citizen_overwrite


class CitizenFixTests(unittest.TestCase):
    def test_mention_fix_preserves_all_writing_and_visibility(self):
        before = discord.PermissionOverwrite(send_messages=True,send_messages_in_threads=True,
                                             view_channel=True,mention_everyone=True,attach_files=True)
        after = citizen_overwrite(before)
        self.assertFalse(after.mention_everyone)
        self.assertTrue(after.send_messages)
        self.assertTrue(after.send_messages_in_threads)
        self.assertTrue(after.attach_files)
        self.assertTrue(after.view_channel)
        self.assertTrue(before.mention_everyone)

    def test_shop_opens_access_without_changing_existing_send_override(self):
        for send in (True,False,None):
            before = discord.PermissionOverwrite(send_messages=send,mention_everyone=False)
            after = citizen_overwrite(before,shop=True)
            self.assertIs(after.send_messages,send)
            self.assertTrue(after.view_channel)
            self.assertTrue(after.read_message_history)
            self.assertTrue(after.use_application_commands)
            self.assertFalse(after.mention_everyone)
