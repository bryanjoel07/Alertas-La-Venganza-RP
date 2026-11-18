from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

import discord

from vice_design import BOT_ID, GUILD_ID
from vice_identity_panels import KEYS, refresh_identity_panels


class IdentityGuidanceTests(IsolatedAsyncioTestCase):
    def make_system(self):
        guild = NS(id=GUILD_ID, fetch_channel=AsyncMock())
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.guild = 987, guild
        guild.fetch_channel.return_value = channel
        messages = []
        for key in KEYS:
            embed = discord.Embed(title='Previous', description='Old copy', colour=123)
            embed.set_footer(text='VIce District • panel:' + key)
            embed.set_image(url='attachment://unchanged.jpg')
            messages.append(NS(id=len(messages)+100, author=NS(id=BOT_ID), embeds=[embed],
                               components=[], attachments=[], edit=AsyncMock()))
        async def tracked(_kind, _title, apply, _receipt, snapshot):
            self.assertIn('embeds', await snapshot())
            return await apply()
        system = NS(bot=NS(user=NS(id=BOT_ID), get_guild=lambda _:guild),
                    validate_guild=lambda g:None, store={}, channel_id=lambda _:987,
                    find_panel=AsyncMock(side_effect=messages), call=AsyncMock(),
                    track=AsyncMock(side_effect=tracked))
        return system, messages

    async def test_refresh_preserves_images_buttons_and_attachments(self):
        system, messages = self.make_system()
        await refresh_identity_panels(system)
        for message in messages:
            args = message.edit.call_args.kwargs
            self.assertEqual(set(args), {'embed', 'allowed_mentions'})
            self.assertEqual(args['embed'].image.url, 'attachment://unchanged.jpg')
            self.assertFalse(args['allowed_mentions'].everyone)
        self.assertEqual(system.track.await_count, 3)

    async def test_wrong_author_cannot_be_replaced_or_republished(self):
        system, messages = self.make_system()
        messages[0].author.id = 1
        with self.assertRaises(ValueError):
            await refresh_identity_panels(system)
        system.track.assert_not_awaited()
        system.call.assert_not_awaited()
