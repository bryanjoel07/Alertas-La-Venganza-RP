import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from urllib.parse import urlsplit

import aiohttp
import discord

from bug_limits import MAX_CLIP_BYTES
from bug_store import BugStore
import test_bugs as fixtures
from test_bug_uploads import SOURCE,VALUES


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ServiceTests.asyncSetUp(self)
        self.system.media.base_url='https://clips.example.com'
        self.bot.is_ready=lambda:True
        with patch.dict('os.environ',PORT='0'):
            await self.system.media.start()
        self.addAsyncCleanup(self.system.media.close)
        port=self.system.media.runner.addresses[0][1]
        self.origin=f'http://127.0.0.1:{port}'
        self.session=aiohttp.ClientSession()
        self.addAsyncCleanup(self.session.close)
        async def tracked(rid,title,request,operation):return await operation()
        self.system.tracked=tracked
        self.forum.create_thread=AsyncMock(return_value=SimpleNamespace(thread=SimpleNamespace(id=700)))

    def video(self,data=b'0123456789abcdef'):
        rid=self.system.store.begin(1)
        rev=self.system.store.prepare_upload(rid,1,VALUES,0,SOURCE,'clip.mp4',len(data))
        self.assertTrue(self.system.store.complete_upload(rid,rev,data))
        return rid

    async def share(self,rid):
        self.system.store.reserve(rid,1)
        row=await self.system.media.share(rid)
        return urlsplit(self.system.media.url(row)).path

    async def test_120_mb_original_survives_restart_publishes_once_and_streams_intact(self):
        payload=b'x'*(MAX_CLIP_BYTES-4)+b'end!'
        digest=hashlib.sha256(payload).hexdigest()
        rid=self.video(payload);del payload
        self.system.store.reserve(rid,1)
        self.guild.filesize_limit=10*1024*1024
        await self.system.create(rid);await self.system.create(rid)
        self.forum.create_thread.assert_awaited_once()
        posted=self.forum.create_thread.call_args.kwargs
        self.assertNotIn('file',posted)
        self.assertEqual(posted['allowed_mentions'].to_dict()['parse'],[])
        row=BugStore(self.system.store.path).get(rid,include_video=False)
        self.assertEqual(row['video_size'],MAX_CLIP_BYTES)
        self.assertEqual(row['video'],1)  # Metadata avoids loading the file for a form/list.
        self.assertEqual(row['sha256'],digest)
        url=self.system.media.url(row);path=urlsplit(url).path
        self.assertIn(url,str(posted['embed'].to_dict()))
        self.assertEqual(self.system.store.media_token(rid),row['media_token'])
        response=await self.session.get(self.origin+path)
        self.assertEqual(response.status,200)
        self.assertEqual(int(response.headers['Content-Length']),MAX_CLIP_BYTES)
        received=hashlib.sha256()
        async for chunk in response.content.iter_chunked(256*1024):received.update(chunk)
        self.assertEqual(received.hexdigest(),digest)
        tail=await self.session.get(self.origin+path,headers={'Range':'bytes=-4'})
        self.assertEqual(tail.status,206);self.assertEqual(await tail.read(),b'end!')
        self.assertIn(url,str(self.system.embed(row).to_dict()))

    async def test_drafts_and_unknown_links_cannot_expose_even_a_cached_clip(self):
        rid=self.video()
        with self.assertRaisesRegex(ValueError,'confirmar'):self.system.store.media_token(rid)
        path=await self.share(rid)
        response=await self.session.get(self.origin+path)
        self.assertEqual(await response.read(),b'0123456789abcdef')
        with self.system.store.db() as db:db.execute("UPDATE lv_bugs SET status='borrador' WHERE id=?",(rid,))
        for url in (path,path.replace('clip.mp4','clip.html'),'/clips/'+'z'*43+'/clip.mp4','/data/lavenganza.sqlite3'):
            response=await self.session.get(self.origin+url)
            self.assertEqual(response.status,404)
            await response.read()

    async def test_video_range_head_and_health_work_without_holding_a_database_lock(self):
        rid=self.video();path=await self.share(rid)
        response=await self.session.get(self.origin+path,headers={'Range':'bytes=4-7'})
        self.assertEqual(response.status,206);self.assertEqual(await response.read(),b'4567')
        self.assertEqual(response.headers['Content-Type'],'video/mp4')
        self.assertEqual(response.headers['Content-Range'],'bytes 4-7/16')
        response=await self.session.head(self.origin+path)
        self.assertEqual(int(response.headers['Content-Length']),16)
        self.assertEqual(await response.read(),b'')
        response=await self.session.get(self.origin+path,headers={'Range':'bytes=16-'})
        self.assertEqual(response.status,416);await response.read()
        await asyncio.wait_for(self.system.call('begin',2),1)
        response=await self.session.get(self.origin+'/health')
        self.assertEqual((await response.json())['max_clip_mb'],120)

    async def test_discord_413_falls_back_to_saved_original_and_keeps_same_report(self):
        rid=self.video();self.system.store.reserve(rid,1)
        error=discord.HTTPException(SimpleNamespace(status=413,reason='Too large'),dict(code=40005,message='Too large'))
        self.forum.create_thread.side_effect=[error,SimpleNamespace(thread=SimpleNamespace(id=700))]
        await self.system.create(rid)
        self.assertEqual(self.forum.create_thread.await_count,2)
        self.assertIn('file',self.forum.create_thread.call_args_list[0].kwargs)
        self.assertNotIn('file',self.forum.create_thread.call_args_list[1].kwargs)
        row=self.system.store.get(rid,include_video=False)
        self.assertEqual(row['thread'],700)
        self.assertIn(self.system.media.url(row),str(self.forum.create_thread.call_args.kwargs['embed'].to_dict()))
