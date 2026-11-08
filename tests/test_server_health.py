from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import discord

from server_health import AUTHOR_ID, OriginalPanel, status_change


class PanelTests(IsolatedAsyncioTestCase):
    def message(self, age=600, author=AUTHOR_ID):
        embed = discord.Embed(title="La Venganza RP",timestamp=datetime.now(timezone.utc)-timedelta(seconds=age))
        embed.add_field(name="> STATUS",value="```\n🟢 Online\n```")
        embed.add_field(name="> PLAYERS",value="6/64")
        return SimpleNamespace(author=SimpleNamespace(id=author),embeds=[embed])

    def test_changes_only_the_stale_status_without_refreshing_the_heartbeat(self):
        message = self.message()
        original = message.embeds[0].to_dict()
        changed = status_change(message,"down",180)[0]
        self.assertEqual(original,message.embeds[0].to_dict())
        self.assertEqual(changed["fields"][0]["value"],"```\n🔴 Offline\n```")
        changed["fields"][0]["value"]=original["fields"][0]["value"]
        self.assertEqual(changed,original)
        self.assertIsNone(status_change(message,"up",180))
        self.assertIsNone(status_change(self.message(10),"down",180))
        self.assertIsNone(status_change(self.message(author=123),"down",180))

    async def test_no_owner_credential_never_contacts_discord(self):
        with patch("server_health.aiohttp.ClientSession") as session:
            await OriginalPanel(None,1,2).update(self.message(),"down",180)
            session.assert_not_called()
