import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

import discord

from change_log import ChangeLog
from server_up_media import BANNER,DIGEST,ROUTE,CHANNEL,MESSAGE,BOT,GUILD,ServerUpBanner
from sqlite_runtime import transaction


class ServerUpRepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'bot.db'
        with transaction(self.path) as db:db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.url='https://bot.example.com'+ROUTE
        embed=discord.Embed(title='🟢 SERVER UP | LA VENGANZA RP 🔥',description='Texto del jugador',color=0xE53935)
        embed.set_footer(text='6:30 p. m. Puerto Rico')
        data=embed.to_dict();data['image']=dict(url='https://cdn.discordapp.com/attachments/old.gif',proxy_url='https://media.discordapp.net/attachments/old.gif')
        self.message=SimpleNamespace(id=MESSAGE,author=SimpleNamespace(id=BOT),content='@everyone',embeds=[discord.Embed.from_dict(data)],components=[],
            attachments=[SimpleNamespace(id=999,filename='server-up.gif',size=BANNER.stat().st_size,url='https://cdn.discordapp.com/attachments/old.gif')])
        async def edit(**kwargs):
            self.message.embeds=kwargs['embeds'];self.message.attachments=kwargs['attachments']
            rendered=self.message.embeds[0].to_dict();rendered['image'].update(proxy_url='https://images-ext-1.discordapp.net/external/new.gif',width=400,height=225)
            self.message.embeds[0]=discord.Embed.from_dict(rendered)
        self.message.edit=AsyncMock(side_effect=edit)
        self.channel=SimpleNamespace(id=CHANNEL,guild=SimpleNamespace(id=GUILD),fetch_message=AsyncMock(return_value=self.message),send=AsyncMock())
        self.bot=SimpleNamespace(user=SimpleNamespace(id=BOT),fetch_channel=AsyncMock(return_value=self.channel),
            bugs=SimpleNamespace(media=SimpleNamespace(base_url='https://bot.example.com',runner=object())),get_guild=lambda gid:SimpleNamespace(id=gid))
        self.bot.changes=ChangeLog(self.bot,self.path,GUILD);self.bot.changes.journal.initialize()
        self.system=ServerUpBanner(self.bot,self.path)
        self.asset=dict(status=200,content_type='image/gif',sha256=DIGEST,bytes=BANNER.stat().st_size)

    async def test_repairs_the_same_message_once_with_backup_and_no_extra_ping_or_duplicate_image(self):
        before=self.message.embeds[0].to_dict()
        with patch('server_up_media.probe',AsyncMock(side_effect=[self.asset,dict(status=404),self.asset])) as probe:
            await self.system.repair();await ServerUpBanner(self.bot,self.path).repair()
        self.message.edit.assert_awaited_once();self.channel.send.assert_not_awaited()
        kwargs=self.message.edit.call_args.kwargs
        self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'],[])
        self.assertEqual(kwargs['attachments'],[]);self.assertNotIn('content',kwargs)
        self.assertEqual(self.message.embeds[0].image.url,self.url)
        after=self.message.embeds[0].to_dict()
        self.assertEqual({k:v for k,v in before.items() if k!='image'},{k:v for k,v in after.items() if k!='image'})
        self.assertEqual(self.message.content,'@everyone');self.assertEqual(probe.await_count,3)
        row=self.bot.changes.journal.rows()[0]
        self.assertEqual(row['status'],'completado')
        import json
        old=json.loads(row['before_json']);new=json.loads(row['after_json'])
        self.assertEqual(old['attachments'][0]['id'],999)
        self.assertEqual(old['original_asset']['sha256'],DIGEST)
        self.assertEqual(new['attachments'],[])

    async def test_bad_public_asset_never_replaces_the_existing_banner_and_can_retry(self):
        with patch('server_up_media.probe',AsyncMock(return_value=dict(self.asset,sha256='wrong'))):
            with self.assertRaises(RuntimeError):await self.system.repair()
        self.message.edit.assert_not_awaited();self.assertEqual(self.system.receipt(),'')
        with patch('server_up_media.probe',AsyncMock(side_effect=[self.asset,dict(status=404),self.asset])):
            await self.system.repair()
        self.message.edit.assert_awaited_once()

    async def test_discord_image_processing_retries_without_posting_or_editing_twice(self):
        with patch('server_up_media.probe',AsyncMock(side_effect=[self.asset,dict(status=404),dict(status=503),self.asset])),patch('server_up_media.asyncio.sleep',AsyncMock()) as wait:
            await self.system.repair()
        self.message.edit.assert_awaited_once();self.channel.send.assert_not_awaited()
        wait.assert_awaited_once_with(3)

    async def test_foreign_message_or_unrelated_attachments_are_preserved(self):
        self.message.author.id=1
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)):
            with self.assertRaises(ValueError):await self.system.repair()
            self.message.author.id=BOT;self.message.attachments[0].filename='another.gif'
            with self.assertRaises(ValueError):await self.system.repair()
        self.message.edit.assert_not_awaited();self.channel.send.assert_not_awaited()

    async def test_original_gif_is_preserved_byte_for_byte(self):
        data=BANNER.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),DIGEST)
        self.assertEqual(data[:6],b'GIF89a')
        self.assertEqual(int.from_bytes(data[6:8],'little'),400)
        self.assertEqual(int.from_bytes(data[8:10],'little'),225)
        self.assertTrue(data.endswith(b';'))
