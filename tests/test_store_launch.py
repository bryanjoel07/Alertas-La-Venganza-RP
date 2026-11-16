import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from esschino import EssChino, CHANNELS
from launch_content import COPY, PRODUCT, PRODUCT_VERSION, PENDING_STORE_URL, panel_copy
from panel_translations import TRANSLATIONS
from store_launch import BOT_ID, GUILD_ID, PROTECTED
from studio_journal import ChangeLog


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = EssChino(self.bot, Path(self.tmp.name) / 'store.db')
        await self.system.start()
        self.channels, self.messages = {}, {}
        self.guild = NS(id=GUILD_ID, get_channel=self.channels.get)
        self.bot.get_guild.side_effect = lambda gid: self.guild if gid == GUILD_ID else None
        self.bot.changes = ChangeLog(self.bot, self.system.store.path, GUILD_ID)
        self.bot.changes.journal.initialize()
        self.system.store.put('guild', GUILD_ID)
        for index, key in enumerate([row[0] for row in CHANNELS] + ['direction','setup'], 100):
            cid = PROTECTED if key in {'direction','setup'} else index
            mid = index + 1000
            self.system.store.put('channel:' + key, cid)
            self.system.store.put('completion_message' if key == 'setup' else 'panel:' + key, mid)
            if cid not in self.channels:
                channel = NS(id=cid, guild=self.guild, topic='Tema original', _overwrites=[], send=AsyncMock(), delete=AsyncMock())
                async def edit_channel(*,topic,reason,channel=channel):
                    channel.topic = topic
                channel.edit = AsyncMock(side_effect=edit_channel)
                channel.fetch_message = AsyncMock(side_effect=lambda mid:self.messages[mid])
                self.channels[cid] = channel
            message = NS(id=mid, author=NS(id=BOT_ID), content='', attachments=[], components=[],
                         embeds=[discord.Embed(title='Título original',description='Texto anterior').set_image(url='https://cdn.discordapp.com/original.jpg')])
            async def edit_message(*,embed,view,allowed_mentions,message=message):
                row = self.bot.changes.journal.rows()[0]
                self.assertEqual(row['status'], 'iniciado')
                self.assertEqual(json.loads(row['before_json'])['message_id'], message.id)
                self.assertTrue(json.loads(row['before_json'])['embeds'])
                message.embeds = [embed]
                message.components = [NS(children=[NS(**item) for item in row['components']], to_dict=lambda row=row:row)
                                      for row in view.to_components()]
            message.edit = AsyncMock(side_effect=edit_message)
            self.messages[mid] = message
        self.bot.fetch_channel = AsyncMock(side_effect=self.channels.get)

    async def test_launch_updates_existing_panels_once_with_before_states_and_keeps_artwork_and_controls(self):
        await self.system.launch.ready(self.guild)
        await self.system.launch.ready(self.guild)
        self.assertEqual(len(self.bot.changes.journal.rows(100)), 21)
        self.assertEqual(self.system.store.get('pending_shop_url'), PENDING_STORE_URL)
        self.assertFalse(self.system.store.get('shop_url'))
        for key in [row[0] for row in CHANNELS] + ['direction','setup']:
            mid = self.system.store.get('completion_message' if key == 'setup' else 'panel:' + key)
            message = self.messages[mid]
            message.edit.assert_awaited_once()
            self.assertIn(PRODUCT, message.embeds[0].description)
            self.assertEqual(message.embeds[0].image.url,'https://cdn.discordapp.com/original.jpg')
            ids = {getattr(item,'custom_id',None) for row in message.components for item in row.children}
            self.assertTrue({f'ec:lang:{key}:{lang}' for lang in ('en','pt-BR','fr','de')}.issubset(ids))
            self.assertNotIn(f'ec:lang:{key}:es',ids)
            if key == 'welcome': self.assertIn('ec:welcome:personal',ids)
            if key == 'support': self.assertIn('ec:open',ids)
        self.assertTrue(all(row['status']=='completado' for row in self.bot.changes.journal.rows(100)))
        for channel in self.channels.values():
            channel.send.assert_not_awaited()
            channel.delete.assert_not_awaited()
            for call in channel.edit.await_args_list:
                self.assertEqual(set(call.kwargs),{'topic','reason'})

    async def test_connecting_public_store_refreshes_purchase_links_and_preserves_later_manual_edits_on_restart(self):
        await self.system.launch.ready(self.guild)
        self.system.store.put('shop_url','https://studio.example.tebex.io/category/scripts')
        await self.system.launch.ready(self.guild)
        for key in ('shop','catalog','buying'):
            message = self.messages[self.system.store.get('panel:' + key)]
            self.assertIn('https://studio.example.tebex.io/category/scripts',message.embeds[0].description)
            self.assertEqual([item.url for row in message.components for item in row.children if hasattr(item,'url')],
                             ['https://studio.example.tebex.io/category/scripts'])
        message = self.messages[self.system.store.get('panel:catalog')]
        message.embeds[0].description = 'Edición posterior de administración'
        await self.system.launch.ready(self.guild)
        self.assertEqual(message.embeds[0].description,'Edición posterior de administración')
        self.assertEqual(message.edit.await_count,2)

    async def test_other_guild_bot_and_foreign_panel_are_rejected_before_edit(self):
        with self.assertRaises(ValueError):
            await self.system.launch.ready(NS(id=1244988345327550565))
        self.bot.user.id = 123
        with self.assertRaises(ValueError):
            await self.system.launch.ready(self.guild)
        self.bot.user.id = BOT_ID
        self.messages[self.system.store.get('panel:welcome')].author.id = 123
        with self.assertRaises(ValueError):
            await self.system.launch.ready(self.guild)
        for message in self.messages.values(): message.edit.assert_not_awaited()

    async def test_pending_domain_has_disabled_controls_in_all_languages_and_active_link_takes_precedence(self):
        for key in ('shop','catalog','buying'):
            for language in COPY:
                view = self.system.languages.attach(self.system.panel_view(key),key,language)
                pending = [item for item in view.children if getattr(item,'custom_id',None)=='ec:store:pending']
                self.assertEqual(len(pending),1)
                self.assertTrue(pending[0].disabled)
                self.assertFalse(any(getattr(item,'url',None) for item in view.children))
                if language != 'es': self.assertNotEqual(pending[0].label,'Tienda en activación')
        self.system.store.put('shop_url',PENDING_STORE_URL)
        for key in ('shop','catalog','buying'):
            view = self.system.panel_view(key)
            self.assertEqual([item.url for item in view.children],[PENDING_STORE_URL])
            self.assertTrue(all(not item.disabled for item in view.children))
            self.assertNotIn('Tienda en activación por Tebex',self.system.panel(key)[1])

    async def test_all_languages_and_panels_reflect_sale_without_editor_links_or_missing_placeholders(self):
        keys = [row[0] for row in CHANNELS] + ['direction','setup']
        source = NS(embeds=[discord.Embed()],attachments=[])
        for url in ('','https://studio.example.tebex.io/'):
            self.system.store.put('shop_url',url)
            for language in COPY:
                self.assertEqual(set(COPY[language]['panels']) | set(COPY[language]['prefix']),set(keys))
                for key in keys:
                    if language == 'es':
                        if key in {'direction','setup'}:
                            title,body = panel_copy(key,'es','Título','Texto',self.system.panel_values())
                        else:
                            title,body = self.system.panel(key)
                    else:
                        embed = self.system.languages.translated_embed(key,language,source)
                        title,body = embed.title,embed.description
                    self.assertIn(PRODUCT,body)
                    self.assertNotIn('{',body)
                    self.assertNotIn('<#None>',body)
                    self.assertNotIn('builder.tebex.io',body)
                    self.assertLessEqual(len(body),4096)
                    self.assertLessEqual(len(title),256)
                    if url and key in {'shop','catalog','buying','faq'}: self.assertIn(url,body)
        catalog = self.system.panel('catalog')[1]
        self.assertIn(PRODUCT_VERSION,catalog)
        for requirement in ('QBCore','Qbox','ESX','standalone','OneSync','oxmysql','MySQL/MariaDB'):
            self.assertIn(requirement,catalog)
