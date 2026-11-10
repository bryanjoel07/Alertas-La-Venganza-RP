import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

import discord

from change_log import ChangeLog
from server_up_media import (BANNER,DIGEST,RENDER_BANNER,RENDER_DIGEST,RENDER_ROUTE,FILENAME,
    ATTACHMENT,CHANNEL,MESSAGE,BOT,GUILD,ServerUpBanner)
from sqlite_runtime import transaction


class ServerUpRepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'bot.db'
        with transaction(self.path) as db:db.execute('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        self.url='https://bot.example.com'+RENDER_ROUTE
        self.native_dimensions=self.hosted_dimensions=(400,225)
        embed=discord.Embed(title='🟢 SERVER UP | LA VENGANZA RP 🔥',description='Texto del jugador',color=0xE53935)
        embed.set_footer(text='6:30 p. m. Puerto Rico')
        data=embed.to_dict();data['image']=dict(url='https://cdn.discordapp.com/attachments/old.gif',proxy_url='https://media.discordapp.net/attachments/old.gif',width=0,height=0)
        self.message=SimpleNamespace(id=MESSAGE,author=SimpleNamespace(id=BOT),content='@everyone',embeds=[discord.Embed.from_dict(data)],components=[],
            attachments=[SimpleNamespace(id=999,filename='server-up.gif',size=BANNER.stat().st_size,url='https://cdn.discordapp.com/attachments/old.gif')])
        async def edit(**kwargs):
            self.message.embeds=kwargs['embeds'];self.message.attachments=[]
            for file in kwargs['attachments']:
                raw=file.fp.read()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),RENDER_DIGEST)
                self.message.attachments.append(SimpleNamespace(id=1000,filename=file.filename,size=len(raw),url='https://cdn.discordapp.com/attachments/'+file.filename))
            rendered=self.message.embeds[0].to_dict()
            native=rendered['image']['url']==ATTACHMENT
            if native:rendered['image']['url']='https://cdn.discordapp.com/attachments/'+FILENAME
            width,height=self.native_dimensions if native else self.hosted_dimensions
            rendered['image'].update(proxy_url='https://images-ext-1.discordapp.net/external/new.gif',width=width,height=height)
            self.message.embeds[0]=discord.Embed.from_dict(rendered)
        self.message.edit=AsyncMock(side_effect=edit)
        self.channel=SimpleNamespace(id=CHANNEL,guild=SimpleNamespace(id=GUILD),fetch_message=AsyncMock(return_value=self.message),send=AsyncMock())
        self.bot=SimpleNamespace(user=SimpleNamespace(id=BOT),fetch_channel=AsyncMock(return_value=self.channel),
            bugs=SimpleNamespace(media=SimpleNamespace(base_url='https://bot.example.com',runner=object())),get_guild=lambda gid:SimpleNamespace(id=gid))
        self.bot.changes=ChangeLog(self.bot,self.path,GUILD);self.bot.changes.journal.initialize()
        self.system=ServerUpBanner(self.bot,self.path)
        self.asset=dict(status=200,content_type='image/gif',sha256=RENDER_DIGEST,bytes=RENDER_BANNER.stat().st_size)

    async def test_repairs_the_same_message_once_with_backup_and_no_extra_ping(self):
        before=self.message.embeds[0].to_dict()
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)) as probe:
            await self.system.repair();await ServerUpBanner(self.bot,self.path).repair()
        self.message.edit.assert_awaited_once();self.channel.send.assert_not_awaited()
        kwargs=self.message.edit.call_args.kwargs
        self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'],[])
        self.assertNotIn('content',kwargs)
        self.assertEqual(len(self.message.attachments),1)
        self.assertEqual(self.message.attachments[0].filename,FILENAME)
        after=self.message.embeds[0].to_dict()
        self.assertEqual({k:v for k,v in before.items() if k!='image'},{k:v for k,v in after.items() if k!='image'})
        self.assertEqual(self.message.content,'@everyone');probe.assert_awaited_once()
        row=self.bot.changes.journal.rows()[0]
        self.assertEqual(row['status'],'completado')
        import json
        old=json.loads(row['before_json']);new=json.loads(row['after_json'])
        self.assertEqual(old['attachments'][0]['id'],999)
        self.assertEqual(old['original_asset']['sha256'],DIGEST)
        self.assertEqual(new['rendering']['width'],400);self.assertEqual(new['rendering']['height'],225)

    async def test_http_200_with_zero_dimensions_is_never_marked_complete_and_can_retry(self):
        self.native_dimensions=self.hosted_dimensions=(0,0)
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)),patch('server_up_media.asyncio.sleep',AsyncMock()):
            with self.assertRaisesRegex(RuntimeError,'sin dimensiones'):await self.system.repair()
        self.assertEqual(self.system.receipt(),'')
        self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'fallido')
        self.channel.send.assert_not_awaited()
        self.native_dimensions=(400,225)
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)):await self.system.repair()
        self.assertEqual(self.system.receipt(),RENDER_DIGEST)
        self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'completado')

    async def test_foreign_message_or_unrelated_attachments_are_preserved(self):
        self.message.author.id=1
        with self.assertRaises(ValueError):await self.system.repair()
        self.message.author.id=BOT;self.message.attachments[0].filename='another.gif'
        with self.assertRaises(ValueError):await self.system.repair()
        self.message.edit.assert_not_awaited();self.channel.send.assert_not_awaited()

    async def test_original_is_preserved_and_compatible_gif_is_smaller_with_same_canvas(self):
        for file,digest in ((BANNER,DIGEST),(RENDER_BANNER,RENDER_DIGEST)):
            data=file.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),digest)
            self.assertEqual(data[:6],b'GIF89a')
            self.assertEqual(int.from_bytes(data[6:8],'little'),400)
            self.assertEqual(int.from_bytes(data[8:10],'little'),225)
            self.assertTrue(data.endswith(b';'))
        self.assertLess(RENDER_BANNER.stat().st_size,5_000_000)

    async def test_hosted_fallback_also_requires_dimensions_and_never_posts_a_second_message(self):
        self.native_dimensions=(0,0)
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)),patch('server_up_media.asyncio.sleep',AsyncMock()):
            await self.system.repair()
        self.assertEqual(self.message.edit.await_count,2)
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.message.embeds[0].image.url,self.url)
        self.assertEqual(self.message.attachments,[])

    async def test_discord_processing_is_rechecked_after_fetching_proxy(self):
        self.native_dimensions=(0,0)
        async def delayed(_):
            self.message.embeds[0]._image.update(width=400,height=225)
            return self.asset
        with patch('server_up_media.probe',AsyncMock(side_effect=delayed)):
            await self.system.repair()
        self.message.edit.assert_awaited_once()
        self.assertEqual(self.system.receipt(),RENDER_DIGEST)

    async def test_future_announcement_can_fallback_without_sending_or_mentioning_twice(self):
        async def sent(**kwargs):
            self.assertEqual(hashlib.sha256(kwargs['file'].fp.read()).hexdigest(),RENDER_DIGEST)
            data=kwargs['embed'].to_dict()
            data['image']=dict(url='https://cdn.discordapp.com/attachments/'+FILENAME,
                proxy_url='https://media.discordapp.net/attachments/'+FILENAME,width=0,height=0)
            self.message.embeds=[discord.Embed.from_dict(data)]
            self.message.attachments=[SimpleNamespace(id=1000,filename=FILENAME,size=RENDER_BANNER.stat().st_size,url=data['image']['url'])]
            return self.message
        self.channel.send.side_effect=sent
        with patch('server_up_media.probe',AsyncMock(return_value=self.asset)),patch('server_up_media.asyncio.sleep',AsyncMock()):
            await self.system.send(self.channel,discord.Embed(title='SERVER UP',description='Texto conservado'))
        self.channel.send.assert_awaited_once();self.message.edit.assert_awaited_once()
        self.assertEqual(self.channel.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'],['everyone'])
        self.assertEqual(self.message.edit.call_args.kwargs['allowed_mentions'].to_dict()['parse'],[])
        self.assertEqual(self.message.embeds[0].description,'Texto conservado')
