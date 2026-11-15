import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from PIL import Image

from esschino import EssChino
from studio_journal import ChangeLog
from welcome_cards import WelcomeCards, WelcomeStore, render_card, name_font, clean_name, GUILD_ID


def avatar_bytes():
    data = io.BytesIO()
    Image.new('RGB', (256, 256), (245, 15, 25)).save(data, 'PNG')
    return data.getvalue()


async def history(messages):
    for message in list(messages):
        yield message


class RenderTests(unittest.TestCase):
    def test_card_uses_avatar_and_produces_a_small_landscape_image(self):
        data = render_card('Chino · José', 'esschino_', avatar_bytes())
        self.assertLess(len(data), 2 * 1024 * 1024)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (1280, 720))
            self.assertEqual(image.format, 'JPEG')
            red, green, blue = image.getpixel((130, 642))
            self.assertGreater(red, 220)
            self.assertLess(green, 40)
            self.assertLess(blue, 40)

    def test_long_names_fit_without_newlines_or_hidden_controls(self):
        name = clean_name('W' * 100 + '\n\x00\u200e')
        fitted, font = name_font(name)
        self.assertLessEqual(font.getlength(fitted), 930)
        self.assertNotIn('\n', fitted)
        self.assertNotIn('\x00', fitted)
        self.assertNotIn('\u200e', fitted)

    def test_avatar_input_is_validated_and_localized_cards_render(self):
        with self.assertRaises(ValueError):
            render_card('Chino', 'chino', b'')
        for language in ('en','pt-BR','fr','de'):
            with self.subTest(language=language):
                data = render_card('Chino', 'chino', avatar_bytes(), language)
                self.assertGreater(len(data), 10_000)


class WelcomeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'store.db'
        self.bot = MagicMock()
        self.bot.user.id = 500
        self.system = EssChino(self.bot, path)
        await self.system.start()
        self.system.store.put('guild', GUILD_ID)
        self.system.store.put('channel:welcome', 100)
        self.system.store.put('channel:rules', 101)
        self.system.store.put('channel:catalog', 102)
        self.system.store.put('channel:support', 103)
        self.bot.changes = ChangeLog(self.bot, path, GUILD_ID)
        self.bot.changes.journal.initialize()
        self.channel = NS(id=100)
        self.guild = NS(id=GUILD_ID, get_channel=lambda cid: self.channel)
        self.channel.guild = self.guild
        self.bot.get_guild.return_value = self.guild
        self.member = MagicMock(spec=discord.Member)
        self.member.guild = self.guild
        self.member.id = 70
        self.member.bot = False
        self.member.joined_at = datetime(2026,11,15,20,0,tzinfo=timezone.utc)
        self.member.display_name = 'Chino'
        self.member.name = 'esschino_'
        self.member.mention = '<@70>'
        self.member.display_avatar.url = 'https://cdn.discordapp.com/avatar.png'
        self.cards = WelcomeCards(self.system, path)
        await self.cards.start()
        self.cards.card = AsyncMock(return_value=b'jpeg-preview')
        self.messages = []

        async def send(**kwargs):
            # A durable before-state and pending receipt must precede delivery.
            row = self.bot.changes.journal.rows()[0]
            self.assertEqual(row['status'], 'iniciado')
            self.assertEqual(json.loads(row['before_json'])['member']['member'], self.member.id)
            message = NS(id=900+len(self.messages), author=self.bot.user,
                attachments=[NS(filename=kwargs['file'].filename)], embeds=[kwargs['embed']])
            self.messages.append(message)
            return message
        self.channel.send = AsyncMock(side_effect=send)
        self.channel.history = lambda limit: history(self.messages)

    async def test_same_join_is_sent_once_and_receipt_survives_restart(self):
        first = await self.cards.joined(self.member)
        second = await self.cards.joined(self.member)
        self.assertEqual(str(first), str(second))
        self.channel.send.assert_awaited_once()
        fresh = WelcomeStore(self.cards.store.path)
        fresh.initialize()
        event,_ = self.cards.event(self.member)
        self.assertEqual(fresh.get(event)['state'], 'sent')
        self.assertEqual(fresh.get(event)['message'], str(first))
        self.assertEqual(self.bot.changes.journal.rows()[0]['status'], 'completado')

    async def test_ambiguous_send_is_reconciled_without_posting_a_duplicate(self):
        original = self.channel.send.side_effect
        async def timeout(**kwargs):
            await original(**kwargs)
            raise OSError('response lost after delivery')
        self.channel.send.side_effect = timeout
        with self.assertRaises(OSError):
            await self.cards.joined(self.member)
        result = await self.cards.joined(self.member)
        self.channel.send.assert_awaited_once()
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(result, self.messages[0].id)
        event,_ = self.cards.event(self.member)
        self.assertEqual(self.cards.store.get(event)['state'], 'sent')

    async def test_actual_rejoin_gets_its_own_welcome(self):
        await self.cards.joined(self.member)
        self.member.joined_at += timedelta(seconds=20)
        await self.cards.joined(self.member)
        self.assertEqual(self.channel.send.await_count, 2)
        self.assertNotEqual(self.messages[0].attachments[0].filename, self.messages[1].attachments[0].filename)

    async def test_other_guilds_and_bot_accounts_never_get_announced(self):
        self.member.guild = NS(id=1244988345327550565)
        await self.cards.joined(self.member)
        self.member.guild = self.guild
        self.member.bot = True
        await self.cards.joined(self.member)
        self.channel.send.assert_not_awaited()
        self.cards.card.assert_not_awaited()
        self.assertFalse(self.cards.store.pending())

    async def test_existing_member_gets_their_card_privately_without_fake_join(self):
        i = NS(guild_id=GUILD_ID, user=self.member, channel_id=100,
            response=NS(defer=AsyncMock()), followup=NS(send=AsyncMock()))
        await self.cards.preview(i, 'fr')
        self.assertTrue(i.followup.send.await_args.kwargs['ephemeral'])
        self.assertIn('Votre', i.followup.send.await_args.kwargs['embed'].title)
        self.cards.card.assert_awaited_once_with(self.member, 'fr')
        self.channel.send.assert_not_awaited()
        self.assertFalse(self.cards.store.pending())
        with self.assertRaises(ValueError):
            await self.cards.preview(i, 'fr')

    async def test_avatar_download_uses_discord_profile_asset_and_cache(self):
        cards = WelcomeCards(self.system, self.cards.store.path)
        asset = MagicMock()
        asset.with_format.return_value = asset
        asset.with_size.return_value = asset
        asset.read = AsyncMock(return_value=avatar_bytes())
        self.member.display_avatar = asset
        first = await cards.card(self.member)
        second = await cards.card(self.member)
        self.assertEqual(first, second)
        asset.read.assert_awaited_once()
        self.member.display_name = 'Nuevo nombre'
        await cards.card(self.member)
        self.assertEqual(asset.read.await_count, 2)
