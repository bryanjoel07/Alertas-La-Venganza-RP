import asyncio
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch

import discord

from bug_ui import BugForm
from bug_store import BugStore
from bug_uploads import ClipUploads,validate_source
from bug_limits import MAX_CLIP_BYTES
import test_bugs as fixtures

DETAILS=fixtures.DETAILS

SOURCE=dict(id=900,url='https://cdn.discordapp.com/attachments/100/900/clip.mp4',proxy_url=None)
VALUES=dict(player_id='42',title='Inventario',details=DETAILS,clip='',discord_username='jugador')

class UploadStoreTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=BugStore(Path(temp.name)/'db');self.store.initialize();self.rid=self.store.begin(1)
    def prepare(self):return self.store.prepare_upload(self.rid,1,VALUES,0,SOURCE,'clip.mp4',4)
    def test_metadata_is_durable_but_publish_stays_blocked_until_video_is_stored(self):
        revision=self.prepare();fresh=BugStore(self.store.path)
        self.assertEqual(json.loads(fresh.get(self.rid)['data'])['description'],'No abre al pulsar F2')
        with self.assertRaisesRegex(ValueError,'preparando'):fresh.reserve(self.rid,1)
        self.assertTrue(fresh.complete_upload(self.rid,revision,b'clip'))
        fresh.reserve(self.rid,1)
        self.assertEqual(fresh.get(self.rid)['video'],b'clip')
        self.assertEqual(fresh.get(self.rid)['status'],'publicando')
    def test_old_worker_cannot_overwrite_a_new_form_submission(self):
        revision=self.prepare()
        self.store.save_full(self.rid,1,dict(VALUES,clip='https://example.com/new-clip'),revision)
        self.assertFalse(self.store.complete_upload(self.rid,revision,b'clip'))
        self.assertEqual(json.loads(self.store.get(self.rid)['data'])['clip'],'https://example.com/new-clip')
        self.assertIsNone(self.store.get(self.rid)['video'])
    def test_partial_download_is_rejected_and_cannot_enable_publish(self):
        revision=self.prepare()
        with self.assertRaises(ValueError):self.store.complete_upload(self.rid,revision,b'bad')
        with self.assertRaises(ValueError):self.store.reserve(self.rid,1)
    def test_only_discord_upload_sources_are_allowed(self):
        for url in ('http://cdn.discordapp.com/attachments/100/900/a.mp4','https://example.com/attachments/100/900/a.mp4','https://cdn.discordapp.com/attachments/100/901/a.mp4','https://user:secret@cdn.discordapp.com/attachments/100/900/a.mp4'):
            with self.assertRaises(ValueError):validate_source(dict(SOURCE,url=url))
    def test_more_than_120_mb_is_rejected_without_reserving_or_replacing_a_clip(self):
        with self.assertRaisesRegex(ValueError,'120 MB'):
            self.store.prepare_upload(self.rid,1,VALUES,0,SOURCE,'clip.mp4',MAX_CLIP_BYTES+1)
        self.assertIsNone(self.store.upload_job(self.rid))
        self.assertEqual(self.store.get(self.rid)['revision'],0)
    def test_queued_uploads_also_reserve_space_against_synchronous_saves(self):
        self.prepare();other=self.store.begin(2)
        with patch('bug_store.MAX_STORED_CLIP_BYTES',10):
            with self.assertRaisesRegex(ValueError,'espacio'):
                self.store.save_full(other,2,VALUES,0,'clip.mp4',b'1234567')

class ResponsiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await fixtures.ServiceTests.asyncSetUp(self)
        self.addAsyncCleanup(self.system.clips.close)
    def form(self,read):
        rid=self.system.store.begin(1);form=BugForm(self.system,self.system.store.get(rid))
        for key,value in VALUES.items():
            if key in form.inputs:form.inputs[key]._value=value
        form.clip._value=''
        form.file._values=[SimpleNamespace(**SOURCE,filename='clip.mp4',size=4,read=read)]
        self.i.response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True)
        self.i.followup=SimpleNamespace(send=AsyncMock());self.i.edit_original_response=AsyncMock()
        return rid,form
    async def test_slow_video_does_not_hold_form_response_or_allow_early_publish(self):
        gate=asyncio.Event();reading=asyncio.Event()
        async def slow_read():reading.set();await gate.wait();return b'clip'
        rid,form=self.form(AsyncMock(side_effect=slow_read))
        started=time.monotonic()
        await asyncio.wait_for(form.on_submit(self.i),1)
        receipt=time.monotonic()-started
        await asyncio.wait_for(reading.wait(),1)
        self.assertLess(receipt,1)
        self.assertIn('Datos guardados',self.i.edit_original_response.call_args.kwargs['content'])
        self.assertTrue(self.i.edit_original_response.call_args.kwargs['view'].children[0].item.disabled)
        with self.assertRaisesRegex(ValueError,'preparando'):self.system.store.reserve(rid,1)
        gate.set();await asyncio.gather(*list(self.system.clips.jobs.values()))
        self.assertEqual(self.i.edit_original_response.await_count,2)
        self.i.followup.send.assert_not_awaited()
        self.assertFalse(self.i.edit_original_response.call_args.kwargs['view'].children[0].item.disabled)
        self.assertEqual(self.system.store.get(rid)['video'],b'clip')
    async def test_invalid_details_are_rejected_before_downloading_video(self):
        read=AsyncMock(return_value=b'clip');rid,form=self.form(read)
        form.inputs['details']._value='Faltan los cuatro apartados'
        await form.on_submit(self.i)
        read.assert_not_awaited()
        self.assertFalse(self.system.clips.jobs)
        self.assertIsNone(self.system.store.upload_job(rid))
    async def test_restart_recovers_committed_upload_metadata_without_duplicate_jobs(self):
        rid=self.system.store.begin(1)
        revision=self.system.store.prepare_upload(rid,1,VALUES,0,SOURCE,'clip.mp4',4)
        self.system.bot.http=SimpleNamespace(get_from_cdn=AsyncMock(return_value=b'clip'))
        restarted=ClipUploads(self.system);self.addAsyncCleanup(restarted.close)
        await restarted.recover();await restarted.recover()
        await asyncio.gather(*list(restarted.jobs.values()))
        self.system.bot.http.get_from_cdn.assert_awaited_once_with(SOURCE['url'])
        self.assertEqual(self.system.store.get(rid)['step'],2)
        self.assertEqual(self.system.store.get(rid)['video'],b'clip')
    async def test_shutdown_cancels_download_but_keeps_pending_job_for_restart(self):
        gate=asyncio.Event();reading=asyncio.Event()
        async def read():reading.set();await gate.wait();return b'clip'
        rid,form=self.form(AsyncMock(side_effect=read));await form.on_submit(self.i)
        await asyncio.wait_for(reading.wait(),1)
        await self.system.clips.close()
        self.assertEqual(self.system.store.upload_job(rid)['state'],'pending')
        self.assertIsNone(self.system.clips.launch(rid,1))
    async def test_current_interaction_member_avoids_both_rest_reads_for_normal_form(self):
        actor=MagicMock(spec=discord.Member);actor.id=1;actor.bot=False;actor.guild=self.guild
        self.guild.get_channel=lambda cid:self.forum
        self.i.user=actor
        await self.system.member(self.i)
        self.guild.fetch_member.assert_not_awaited();self.bot.fetch_channel.assert_not_awaited()
        with self.assertRaises(ValueError):await self.system.member(self.i,admin=True)
        self.guild.fetch_member.assert_awaited_once_with(1)
    async def test_native_120_mb_user_upload_is_not_limited_by_the_bots_10_mb_guild_limit(self):
        self.guild.filesize_limit=10*1024*1024
        gate=asyncio.Event()
        async def read():await gate.wait();return b'clip'
        rid,form=self.form(AsyncMock(side_effect=read))
        form.file.values[0].size=MAX_CLIP_BYTES
        await asyncio.wait_for(form.on_submit(self.i),1)
        self.assertEqual(self.system.store.upload_job(rid)['size'],MAX_CLIP_BYTES)
        self.assertIn('Datos guardados',self.i.edit_original_response.call_args.kwargs['content'])
        self.assertTrue(all(len(label.description or '')<=100 for label in form.children))
    async def test_small_png_is_accepted_as_the_reports_evidence(self):
        read=AsyncMock(return_value=b'p'*2_800_000);rid,form=self.form(read)
        form.file.values[0].filename='foto.png'
        form.file.values[0].size=2_800_000
        await form.on_submit(self.i)
        await asyncio.gather(*list(self.system.clips.jobs.values()))
        read.assert_awaited_once()
        self.assertEqual(self.system.store.get(rid)['step'],2)
        self.assertEqual(len(self.system.store.get(rid)['video']),2_800_000)
        self.i.followup.send.assert_not_awaited()
    async def test_photo_weight_is_visible_before_download_and_stays_correct_when_ready(self):
        gate=asyncio.Event();reading=asyncio.Event()
        async def read():reading.set();await gate.wait();return b'p'*2_400_000
        rid,form=self.form(AsyncMock(side_effect=read))
        form.file.values[0].filename='foto.png';form.file.values[0].size=2_400_000
        await asyncio.wait_for(form.on_submit(self.i),1)
        await asyncio.wait_for(reading.wait(),1)
        first=self.i.edit_original_response.call_args_list[0].kwargs
        proof=next(f.value for f in first['embed'].fields if f.name=='📎 Pruebas')
        self.assertIn('2.4 MB / 120 MB',proof);self.assertIn('⏳',proof)
        self.assertTrue(first['view'].children[0].item.disabled)
        pending=BugStore(self.system.store.path).get(rid,include_video=False)
        self.assertEqual(pending['attachment_status'],[dict(filename='foto.png',size=2_400_000,state='pending')])
        gate.set();await asyncio.gather(*list(self.system.clips.jobs.values()))
        last=self.i.edit_original_response.call_args.kwargs
        proof=next(f.value for f in last['embed'].fields if f.name=='📎 Pruebas')
        self.assertIn('2.4 MB / 120 MB',proof);self.assertIn('✅',proof)
        self.assertFalse(last['view'].children[0].item.disabled)
        self.i.followup.send.assert_not_awaited()
        self.forum.create_thread.assert_not_called()
    async def test_video_above_120_mb_reports_its_actual_size_before_any_download(self):
        read=AsyncMock();rid,form=self.form(read)
        form.file.values[0].size=121_000_000
        await form.on_submit(self.i)
        message=self.i.followup.send.call_args.args[0]
        self.assertIn('pesa 121.0 MB',message)
        self.assertIn('límite es 120 MB',message)
        read.assert_not_awaited()
        self.assertIsNone(self.system.store.upload_job(rid))
    async def test_long_video_filename_keeps_its_extension_and_can_publish(self):
        rid,form=self.form(AsyncMock(return_value=b'clip'))
        form.file.values[0].filename='video-'+'a'*120+'.MP4'
        await form.on_submit(self.i)
        await asyncio.gather(*list(self.system.clips.jobs.values()))
        row=self.system.store.get(rid)
        self.assertEqual(row['step'],2)
        self.assertEqual(row['video'],b'clip')
        self.assertLessEqual(len(row['filename']),100)
        self.assertTrue(row['filename'].endswith('.mp4'))
