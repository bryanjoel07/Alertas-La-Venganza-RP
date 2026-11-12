import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock

from community_features import CommunityFeatures,GuideView
from economy_store import EconomyStore
from economy import Economy


class CommunityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        path=Path(tmp.name)/'db.sqlite3'
        with sqlite3.connect(path) as db:
            db.executescript('''CREATE TABLE events(id INTEGER PRIMARY KEY,status TEXT,winner1 TEXT,winner2 TEXT,winner3 TEXT,title TEXT,starts_at TEXT);
                CREATE TABLE registrations(event_id INTEGER,user_id INTEGER);''')
        store=EconomyStore(path);store.initialize()
        self.economy=object.__new__(Economy)
        self.economy.store=store;self.economy.ready=True
        self.economy.guild=SimpleNamespace(id=1244988345327550565)
        store.runtime_config("profiles_channel","1569151200673140897")
        store.runtime_config("shop_channel","1569084821983076512")
        self.economy.bot=MagicMock()
        self.economy.preview=AsyncMock()
        self.economy.bot.event_features.call=AsyncMock(return_value=dict(
            stats=dict(participations=0,first=0,second=0,third=0),rank=None,ranked_players=0,
            total_events=0,page=1,pages=1,events=[]))
        self.features=CommunityFeatures(self.economy)
        self.i=MagicMock()
        self.i.user=SimpleNamespace(id=7,name='jugador',display_name='Jugador',display_avatar=SimpleNamespace(url='https://cdn.example/avatar.png'))
        self.i.response.is_done.return_value=False
        self.i.response.defer=AsyncMock()
        self.i.response.send_message=AsyncMock()
        self.i.followup.send=AsyncMock()

    async def test_banner_fitting_uploads_local_image_and_does_not_buy_or_equip(self):
        before=self.economy.store.account(7)['balance']
        await self.features.try_product(self.i,'banner-garaje')
        kwargs=self.i.response.send_message.call_args.kwargs
        self.assertTrue(kwargs['ephemeral'])
        self.assertEqual(kwargs['embed'].image.url,'attachment://garaje.jpg')
        self.assertTrue(kwargs['file'].fp.read())
        kwargs['file'].close()
        self.assertEqual(self.economy.store.account(7)['balance'],before)
        self.assertFalse(self.economy.store.inventory(7))
        self.assertFalse(self.economy.store.equipped(7))
        self.assertFalse(self.economy.store.rows('SELECT * FROM eco_quotes'))
        self.economy.preview.assert_not_awaited()

    async def test_custom_plate_can_be_previewed_without_purchasing(self):
        await self.features.try_product(self.i,'matricula-rp','chino-7')
        embed=self.i.response.send_message.call_args.kwargs['embed']
        self.assertIn('CHINO-7',str(embed.to_dict()))
        self.assertFalse(self.economy.store.inventory(7))

    async def test_guide_is_persistent_and_links_the_current_bot_features(self):
        view=GuideView(self.features)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children),14)
        expected = {
            'Mi perfil': '1569151200673140897',
            'Mi saldo': '1569151200673140897',
            'Tienda': '1569084821983076512',
            'Probador': '1569084821983076512',
            'Retos y monedas': '1569084821983076512',
            'Ser streamer': '1568403146219454586',
            'Fotos':'1513422142014754976',
            'Minijuegos':'1513422089162330184',
            'Tickets':'1513423707467415642',
            'Feedback':'1539014594348064939',
            'Sugerencias':'1539013973947588759',
            'Errores':'1556488595131466000',
            'Postulaciones':'1567399097500041237',
            'Normas':'1528925322362228787',
        }
        import discord
        for button in view.children:
            self.assertEqual(button.style,discord.ButtonStyle.link)
            self.assertIsNone(button.custom_id)
            self.assertEqual(button.url,f'https://discord.com/channels/1244988345327550565/{expected[button.label]}')
        embed=self.features.guide_embed()
        self.assertLess(len(embed),6000)
        for text in ('/perfil','/probar','/retos','/streamer registrar','6:30'):
            self.assertIn(text,str(embed.to_dict()))


    async def test_catalog_details_with_no_balance_never_create_quote_or_purchase(self):
        self.economy.product_details=Economy.product_details.__get__(self.economy,Economy)
        self.assertEqual(self.economy.store.account(7)['balance'],0)
        await self.economy.product_details(self.i,'banner-garaje')
        response=self.i.response.send_message.call_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertIn('900',response['embed'].description)
        self.assertIn('Ilustración',response['embed'].description)
        self.assertFalse(self.economy.store.rows('SELECT * FROM eco_quotes'))
        self.assertFalse(self.economy.store.inventory(7))
        self.assertEqual(self.economy.store.account(7)['balance'],0)
        self.economy.preview.assert_not_awaited()

    async def test_all_catalog_pages_reachable_and_within_discord_limits(self):
        import discord
        from economy import CatalogView,catalog_embed
        products=self.features.available(7)
        products=[dict(products[0],sku=f'product-{n}',name=f'Producto {n}') for n in range(37)]
        seen=[]
        for page in range(7):
            view=CatalogView(self.economy,7,products,page)
            picker=next(c for c in view.children if isinstance(c,discord.ui.Select))
            seen.extend(o.value for o in picker.options)
            self.assertLessEqual(len(picker.options),25)
            self.assertLess(len(catalog_embed(products,page)),6000)
            self.assertEqual(view.previous.disabled,page==0)
            self.assertEqual(view.next_page.disabled,page==6)
        self.assertEqual(seen,[p['sku'] for p in products])
