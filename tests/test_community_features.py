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

    async def test_guide_is_persistent_and_links_all_five_flows(self):
        view=GuideView(self.features)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len(view.children),6)
        self.assertEqual(len({b.custom_id for b in view.children}),6)
        embed=self.features.guide_embed()
        self.assertLess(len(embed),6000)
        for text in ('/perfil','/probar','/retos','/streamer registrar','6:30'):
            self.assertIn(text,str(embed.to_dict()))
