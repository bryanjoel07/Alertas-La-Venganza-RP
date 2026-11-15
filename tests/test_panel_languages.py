from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from esschino import EssChino, CHANNELS, EntryView, SupportView, AdminView, ManagementView
from store_community import StoreCommunity
from panel_languages import LANGUAGES, LanguageButton, GUILD_ID
from panel_translations import TRANSLATIONS


class PanelLanguageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = 500
        self.system = EssChino(self.bot, Path(self.tmp.name) / 'store.db')
        await self.system.start()
        self.system.community = StoreCommunity(self.system, self.system.store.path)
        await self.system.community.start()
        for index, row in enumerate(CHANNELS, 100):
            self.system.store.put('channel:' + row[0], index)
        self.system.store.put('guild', GUILD_ID)
        self.system.store.put('panel:welcome', 1000)
        self.system.store.put('panel:staff', 1001)
        self.channel = MagicMock()
        self.channel.id = self.system.channel_id('welcome')
        self.channel.guild = NS(id=GUILD_ID)
        self.channel.permissions_for.return_value = NS(view_channel=True, read_message_history=True)
        self.source = NS(id=1000, author=NS(id=500),
            embeds=[discord.Embed(title='Título original en español', description='Información original', color=0xA535F5)],
            attachments=[], edit=AsyncMock())
        self.channel.fetch_message = AsyncMock(return_value=self.source)
        self.guild = NS(id=GUILD_ID, get_channel=MagicMock(return_value=self.channel))
        self.member = MagicMock(spec=discord.Member)
        self.member.id = 70
        self.member.bot = False

    def interaction(self, private=False):
        return NS(guild_id=GUILD_ID, guild=self.guild, user=self.member,
            channel_id=self.system.channel_id('welcome'),
            message=NS(id=2000 if private else 1000, author=NS(id=500), flags=NS(ephemeral=private)),
            response=NS(defer=AsyncMock(), is_done=lambda: False), followup=NS(send=AsyncMock()),
            edit_original_response=AsyncMock())

    async def test_buttons_exactly_match_script_languages_excluding_spanish_on_every_panel(self):
        self.assertEqual([row['code'] for row in LANGUAGES], ['en','pt-BR','fr','de'])
        self.assertEqual([row['name'] for row in LANGUAGES], ['English','Português (Brasil)','Français','Deutsch'])
        for key in [row[0] for row in CHANNELS] + ['direction','setup']:
            with self.subTest(panel=key):
                view = self.system.languages.attach(self.system.panel_view(key), key)
                controls = view.to_components()
                ids = [item.get('custom_id') for row in controls for item in row['components'] if item.get('custom_id','').startswith('ec:lang:')]
                self.assertEqual(ids, [f'ec:lang:{key}:{lang["code"]}' for lang in LANGUAGES])
                self.assertFalse(any(value.endswith(':es') for value in ids))
                self.assertLessEqual(len(controls), 5)
                self.assertTrue(view.is_persistent())

    async def test_all_translations_render_with_links_and_remain_within_discord_limits(self):
        source = NS(embeds=[discord.Embed(color=0xA535F5)], attachments=[])
        for url in ('', 'https://studio.example.tebex.io/category/scripts'):
            self.system.store.put('shop_url', url)
            for language in TRANSLATIONS:
                for key in [row[0] for row in CHANNELS] + ['direction','setup']:
                    with self.subTest(language=language, panel=key, configured=bool(url)):
                        embed = self.system.languages.translated_embed(key, language, source)
                        self.assertLessEqual(len(embed.title), 256)
                        self.assertLessEqual(len(embed.description), 4096)
                        self.assertNotIn('{', embed.description)
                        self.assertNotIn('<#None>', embed.description)
                        self.assertEqual(embed.color.value, 0xA535F5)
                        if key == 'shop' and url:
                            self.assertIn(url, embed.description)

    async def test_translation_is_private_and_never_edits_the_public_spanish_panel(self):
        i = self.interaction()
        original = self.source.embeds[0].to_dict()
        await self.system.languages.show(i, 'welcome', 'en')
        i.followup.send.assert_awaited_once()
        self.assertTrue(i.followup.send.await_args.kwargs['ephemeral'])
        self.assertEqual(i.followup.send.await_args.kwargs['embed'].title, TRANSLATIONS['en']['welcome'][0])
        self.assertEqual(self.source.embeds[0].to_dict(), original)
        self.source.edit.assert_not_awaited()
        i.edit_original_response.assert_not_awaited()

    async def test_switching_a_private_copy_changes_only_that_copy(self):
        i = self.interaction(private=True)
        await self.system.languages.show(i, 'welcome', 'fr')
        i.edit_original_response.assert_awaited_once()
        self.assertEqual(i.edit_original_response.await_args.kwargs['embed'].title, TRANSLATIONS['fr']['welcome'][0])
        i.followup.send.assert_not_awaited()
        self.source.edit.assert_not_awaited()

    async def test_private_staff_panels_cannot_be_translated_after_access_is_removed(self):
        i = self.interaction()
        i.channel_id = self.system.channel_id('staff')
        self.channel.permissions_for.return_value = NS(view_channel=False, read_message_history=True)
        with self.assertRaises(ValueError):
            await self.system.languages.show(i, 'staff', 'de')
        self.channel.fetch_message.assert_not_awaited()
        i.followup.send.assert_not_awaited()

    async def test_other_guilds_and_unregistered_or_foreign_messages_are_rejected(self):
        for change in ('guild','author','message','channel'):
            i = self.interaction()
            if change == 'guild': i.guild_id = 1244988345327550565
            elif change == 'author': i.message.author.id = 501
            elif change == 'message': i.message.id = 999
            else: i.channel_id = 999
            with self.subTest(change=change), self.assertRaises(ValueError):
                await self.system.languages.show(i, 'welcome', 'en')

    async def test_functional_callbacks_and_support_values_survive_localization(self):
        cases = [('welcome',EntryView),('support',SupportView),('direction',AdminView),('management',ManagementView)]
        for key, cls in cases:
            view = self.system.languages.attach(self.system.panel_view(key), key, 'en')
            self.assertIsInstance(view, cls)
            native = [item for item in view.children if not isinstance(item, LanguageButton)]
            self.assertTrue(native)
            self.assertTrue(all(item.view is view for item in native))
            if key == 'support':
                self.assertEqual([option.value for option in native[0].options], ['compras','soporte','error','colaboracion'])
                self.assertEqual(native[0].options[0].label, 'Purchases and orders')
            if key == 'welcome':
                self.assertEqual(native[0].label, 'Join the community')

    async def test_shop_link_and_banner_remain_available_in_translations(self):
        self.system.store.put('shop_url', 'https://studio.tebex.io/')
        embed = discord.Embed().set_image(url='attachment://esschino-banner.jpg')
        source = NS(embeds=[embed], attachments=[NS(filename='esschino-banner.jpg', url='https://cdn.discordapp.com/banner.jpg')])
        translated = self.system.languages.translated_embed('shop','pt-BR',source)
        self.assertEqual(translated.image.url, source.attachments[0].url)
        self.assertEqual(source.embeds[0].image.url, 'attachment://esschino-banner.jpg')
        view = self.system.languages.attach(self.system.panel_view('shop'),'shop','pt-BR')
        links = [item for item in view.children if isinstance(item,discord.ui.Button) and item.url]
        self.assertEqual(links[0].url, 'https://studio.tebex.io/')
        self.assertEqual(links[0].label, 'Visitar a loja oficial')

    async def test_language_dynamic_ids_can_be_restored_after_restart(self):
        import re
        pattern = r'ec:lang:(?P<panel>[a-z_]+):(?P<language>en|pt-BR|fr|de)'
        for language in LANGUAGES:
            item = LanguageButton('support', language['code'])
            restored = await LanguageButton.from_custom_id(None, item.item, re.fullmatch(pattern,item.custom_id))
            self.assertEqual(restored.panel, 'support')
            self.assertEqual(restored.language, language['code'])
            self.assertTrue(restored.is_persistent())

    async def test_migration_saves_before_state_and_updates_each_message_only_once(self):
        from studio_journal import ChangeLog
        self.bot.get_guild.return_value = self.guild
        self.bot.changes = ChangeLog(self.bot, self.system.store.path, GUILD_ID)
        self.bot.changes.journal.initialize()
        self.system.store.put('panel:direction', 3000)
        self.system.store.put('completion_message', 3001)
        messages = {}

        class ComponentRow:
            def __init__(self, raw):
                self.raw = raw
                self.children = [NS(custom_id=item.get('custom_id')) for item in raw['components']]
            def to_dict(self):
                return self.raw

        for mid in (3000,3001):
            message = NS(id=mid, author=NS(id=500), content='', attachments=[], components=[],
                embeds=[discord.Embed(title='Panel original',description='Información original en español')])
            async def edit(*, view, allowed_mentions, message=message):
                record = self.bot.changes.journal.rows()[0]
                self.assertEqual(record['status'], 'iniciado')
                import json
                self.assertEqual(json.loads(record['before_json'])['message_id'], message.id)
                message.components = [ComponentRow(row) for row in view.to_components()]
            message.edit = AsyncMock(side_effect=edit)
            messages[mid] = message
        self.channel.fetch_message.side_effect = lambda mid: messages[mid]
        await self.system.languages.ready(self.guild, [])
        await self.system.languages.ready(self.guild, [])
        self.assertEqual(len(self.bot.changes.journal.rows()), 2)
        self.assertTrue(all(row['status'] == 'completado' for row in self.bot.changes.journal.rows()))
        for message in messages.values():
            message.edit.assert_awaited_once()
            self.assertEqual(message.embeds[0].description, 'Información original en español')
