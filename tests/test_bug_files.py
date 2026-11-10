import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

from bug_limits import MAX_CLIP_BYTES
from bug_store import BugStore
from bug_ui import BugForm,size_summary
from bug_uploads import ClipUploads
from bugs import FORUM
import test_bug_media as mediafixtures
from test_bug_uploads import VALUES


def selection(count=2,images_only=False,size=6):
    return [dict(source=dict(id=900+n,url=f'https://cdn.discordapp.com/attachments/100/{900+n}/proof',proxy_url=None),
        filename='foto.png' if images_only or n%2==0 else 'video.mp4',size=size) for n in range(count)]


class MultiStoreTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=BugStore(Path(temp.name)/'db');self.store.initialize();self.rid=self.store.begin(1)
    def prepare(self):return self.store.prepare_files(self.rid,1,VALUES,0,selection())
    def complete(self,revision):
        for job in self.store.file_jobs(self.rid,revision):
            self.assertTrue(self.store.complete_file(self.rid,revision,job['id'],f"file-{job['position']}".encode()))
    def test_all_originals_must_finish_before_publish_and_survive_restart(self):
        revision=self.prepare();jobs=self.store.file_jobs(self.rid,revision)
        self.assertTrue(self.store.complete_file(self.rid,revision,jobs[0]['id'],b'file-0'))
        with self.assertRaisesRegex(ValueError,'preparando'):self.store.reserve(self.rid,1)
        self.assertTrue(self.store.complete_file(self.rid,revision,jobs[1]['id'],b'file-1'))
        fresh=BugStore(self.store.path);row=fresh.get(self.rid,include_video=False)
        self.assertEqual(row['file_count'],2);self.assertFalse(row['video'])
        self.assertEqual([f['sha256'] for f in row['files']],[hashlib.sha256(f'file-{n}'.encode()).hexdigest() for n in range(2)])
        fresh.reserve(self.rid,1)
        self.assertEqual(fresh.get(self.rid)['status'],'publicando')
    def test_stale_worker_cannot_overwrite_an_edited_form_or_new_source(self):
        revision=self.prepare();job=self.store.file_jobs(self.rid,revision)[0]
        self.store.save_full(self.rid,1,dict(VALUES,clip='https://example.com/proof'),revision)
        self.assertFalse(self.store.complete_file(self.rid,revision,job['id'],b'file-0'))
        self.assertEqual(json.loads(self.store.get(self.rid)['data'])['clip'],'https://example.com/proof')
        self.assertFalse(self.store.pending_file_groups())
    def test_editing_text_preserves_the_group_and_tokens_are_private_until_confirmed(self):
        revision=self.prepare();self.complete(revision)
        self.store.save_full(self.rid,1,dict(VALUES,title='Otro título'),revision)
        row=self.store.get(self.rid,include_video=False)
        self.assertEqual(row['file_count'],2)
        self.assertTrue(all(f['token'] is None for f in row['files']))
        with self.assertRaisesRegex(ValueError,'confirmar'):self.store.file_tokens(self.rid)
        self.store.reserve(self.rid,1);self.store.file_tokens(self.rid)
        tokens=[f['token'] for f in self.store.get(self.rid)['files']]
        self.assertEqual(len(set(tokens)),2)
        self.store.file_tokens(self.rid)
        self.assertEqual(tokens,[f['token'] for f in self.store.get(self.rid)['files']])
    def test_replacing_a_legacy_file_preserves_it_until_the_new_group_is_complete(self):
        self.store.save_full(self.rid,1,VALUES,0,'old.mp4',b'old')
        revision=self.store.prepare_files(self.rid,1,VALUES,1,selection())
        self.assertEqual(self.store.get(self.rid)['video'],b'old')
        self.complete(revision)
        self.assertIsNone(self.store.get(self.rid)['video'])
        self.assertEqual(self.store.get(self.rid)['file_count'],2)
    def test_replacing_a_group_with_one_photo_clears_only_the_old_draft_group(self):
        revision=self.prepare();self.complete(revision)
        item=selection()[0]
        revision=self.store.prepare_upload(self.rid,1,VALUES,revision,item['source'],'new.png',3)
        self.assertEqual(self.store.get(self.rid)['file_count'],2)
        self.assertEqual(self.store.get(self.rid)['attachment_status'],[dict(filename='new.png',size=3,state='pending')])
        self.assertTrue(self.store.complete_upload(self.rid,revision,b'png'))
        row=self.store.get(self.rid)
        self.assertEqual(row['video'],b'png');self.assertEqual(row['file_count'],0)
        self.store.reserve(self.rid,1)
    def test_ten_120_mb_files_reserve_total_space_and_eleven_or_oversize_are_refused(self):
        with self.assertRaisesRegex(ValueError,'10 archivos'):
            self.store.prepare_files(self.rid,1,VALUES,0,selection(11))
        with self.assertRaisesRegex(ValueError,'120 MB'):
            self.store.prepare_files(self.rid,1,VALUES,0,selection(size=MAX_CLIP_BYTES+1))
        self.store.prepare_files(self.rid,1,VALUES,0,selection(10,size=MAX_CLIP_BYTES))
        other=self.store.begin(2)
        with self.assertRaisesRegex(ValueError,'espacio'):
            self.store.prepare_files(other,2,VALUES,0,selection(8,size=MAX_CLIP_BYTES))
    def test_missing_or_partial_original_cannot_complete_or_publish(self):
        revision=self.prepare();jobs=self.store.file_jobs(self.rid,revision)
        with self.assertRaisesRegex(ValueError,'completo'):self.store.complete_file(self.rid,revision,jobs[0]['id'],b'bad')
        self.store.fail_files(self.rid,revision,'download')
        self.assertFalse(self.store.pending_file_groups())
        with self.assertRaises(ValueError):self.store.reserve(self.rid,1)
    def test_counter_totals_and_each_file_status_are_preserved_as_group_prepares(self):
        selected=selection();selected[0]['size']=2_400_000;selected[1]['size']=3_600_000
        revision=self.store.prepare_files(self.rid,1,VALUES,0,selected)
        jobs=self.store.file_jobs(self.rid,revision)
        first=size_summary(self.store.get(self.rid,include_video=False)['attachment_status'])
        for text in ('2/10 archivos','6.0 MB','2.4 MB / 120 MB','3.6 MB / 120 MB'):self.assertIn(text,first)
        self.assertEqual(first.count('⏳'),2)
        self.store.complete_file(self.rid,revision,jobs[0]['id'],b'p'*2_400_000)
        partial=size_summary(self.store.get(self.rid,include_video=False)['attachment_status'])
        self.assertEqual(partial.count('✅'),1);self.assertEqual(partial.count('⏳'),1)
        with self.assertRaises(ValueError):self.store.reserve(self.rid,1)
        self.store.complete_file(self.rid,revision,jobs[1]['id'],b'v'*3_600_000)
        final=size_summary(BugStore(self.store.path).get(self.rid,include_video=False)['attachment_status'])
        self.assertEqual(final.count('✅'),2);self.assertIn('6.0 MB',final)
    def test_ten_maximum_files_have_clear_individual_limits_and_fit_one_discord_field(self):
        files=[dict(filename='*'*100+'.png',size=MAX_CLIP_BYTES,state='complete') for _ in range(10)]
        value=size_summary(files)
        self.assertLessEqual(len(value),1024)
        self.assertIn('Total: **1200.0 MB**',value)
        self.assertEqual(value.count('120.0 MB / 120 MB'),10)


class MultiServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await mediafixtures.MediaTests.asyncSetUp(self)
        self.addAsyncCleanup(self.system.clips.close)
    def prepare(self,count=2,images_only=False):
        rid=self.system.store.begin(1)
        revision=self.system.store.prepare_files(rid,1,VALUES,0,selection(count,images_only))
        for job in self.system.store.file_jobs(rid,revision):self.system.store.complete_file(rid,revision,job['id'],f"file-{job['position']}".encode())
        return rid
    async def test_mixed_files_publish_once_and_each_photo_and_video_opens_the_correct_original(self):
        rid=self.prepare();self.system.store.reserve(rid,1)
        await self.system.create(rid);await self.system.create(rid)
        self.forum.create_thread.assert_awaited_once()
        posted=self.forum.create_thread.call_args.kwargs
        self.assertEqual(len(posted['embeds']),1)
        self.assertIn('<@1>',posted['embeds'][0].description)
        self.assertEqual(posted['allowed_mentions'].to_dict()['parse'],[])
        row=self.system.store.get(rid,include_video=False)
        urls=[self.system.media.file_url(f) for f in row['files']]
        self.assertEqual(posted['embeds'][0].image.url,urls[0])
        for n,(item,url) in enumerate(zip(row['files'],urls)):
            self.assertIn(url,posted['content'])
            response=await self.session.get(self.origin+urlsplit(url).path)
            self.assertEqual(response.status,200);self.assertEqual(await response.read(),f'file-{n}'.encode())
            self.assertEqual(response.headers['Content-Type'],'image/png' if n==0 else 'video/mp4')
        with self.system.store.db() as db:db.execute("UPDATE lv_bugs SET status='borrador' WHERE id=?",(rid,))
        response=await self.session.get(self.origin+urlsplit(urls[0]).path)
        self.assertEqual(response.status,404);await response.read()
    async def test_ten_photos_keep_all_images_and_links_on_refresh_without_extra_posts(self):
        rid=self.prepare(10,images_only=True);self.system.store.reserve(rid,1)
        await self.system.create(rid)
        posted=self.forum.create_thread.call_args.kwargs
        self.assertEqual(len(posted['embeds']),10)
        self.assertLessEqual(sum(len(e) for e in posted['embeds']),6000)
        self.assertLessEqual(len(posted['content']),2000)
        self.assertEqual(len(set(e.image.url for e in posted['embeds'])),10)
        message=SimpleNamespace(author=self.bot.user,edit=AsyncMock())
        thread=SimpleNamespace(parent_id=FORUM,fetch_message=AsyncMock(return_value=message))
        self.bot.fetch_channel=AsyncMock(return_value=thread)
        await self.system.refresh(rid)
        self.assertEqual([e.image.url for e in message.edit.call_args.kwargs['embeds']],[e.image.url for e in posted['embeds']])
        self.forum.create_thread.assert_awaited_once()
    async def test_single_photo_can_use_the_existing_attachment_path_and_large_file_link(self):
        rid=self.system.store.begin(1);item=selection()[0]
        rev=self.system.store.prepare_upload(rid,1,VALUES,0,item['source'],'foto.png',6)
        self.system.store.complete_upload(rid,rev,b'file-0');self.system.store.reserve(rid,1)
        self.guild.filesize_limit=1
        await self.system.create(rid)
        row=self.system.store.get(rid,include_video=False);url=self.system.media.url(row)
        self.assertEqual(self.forum.create_thread.call_args.kwargs['embed'].image.url,url)
        response=await self.session.get(self.origin+urlsplit(url).path)
        self.assertEqual(response.headers['Content-Type'],'image/png');self.assertEqual(await response.read(),b'file-0')
    async def test_slow_mixed_upload_is_acknowledged_first_and_blocks_publish_until_all_files_finish(self):
        rid=self.system.store.begin(1);form=BugForm(self.system,self.system.store.get(rid))
        for key,item in form.inputs.items():item._value=VALUES[key]
        form.clip._value=''
        gate=asyncio.Event();reading=asyncio.Event();files=[]
        async def slow():reading.set();await gate.wait();return b'file-1'
        for n,item in enumerate(selection()):
            files.append(SimpleNamespace(**item['source'],filename=item['filename'],size=item['size'],read=AsyncMock(return_value=b'file-0') if n==0 else AsyncMock(side_effect=slow)))
        form.file._values=files
        self.i.response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True)
        self.i.followup=SimpleNamespace(send=AsyncMock());self.i.edit_original_response=AsyncMock()
        await asyncio.wait_for(form.on_submit(self.i),1)
        await asyncio.wait_for(reading.wait(),1)
        self.assertIn('Datos guardados',self.i.edit_original_response.call_args.kwargs['content'])
        self.assertTrue(self.i.edit_original_response.call_args.kwargs['view'].children[0].item.disabled)
        with self.assertRaisesRegex(ValueError,'preparando'):self.system.store.reserve(rid,1)
        gate.set();await asyncio.gather(*list(self.system.clips.jobs.values()))
        self.assertEqual(self.system.store.get(rid)['file_count'],2)
        self.assertFalse(self.i.edit_original_response.call_args.kwargs['view'].children[0].item.disabled)
        self.forum.create_thread.assert_not_awaited();self.i.followup.send.assert_not_awaited()
    async def test_restart_resumes_only_unfinished_files_without_duplicate_download_jobs(self):
        rid=self.system.store.begin(1);rev=self.system.store.prepare_files(rid,1,VALUES,0,selection())
        jobs=self.system.store.file_jobs(rid,rev)
        self.system.store.complete_file(rid,rev,jobs[0]['id'],b'file-0')
        self.bot.http=SimpleNamespace(get_from_cdn=AsyncMock(return_value=b'file-1'))
        restarted=ClipUploads(self.system);self.addAsyncCleanup(restarted.close)
        await restarted.recover();await restarted.recover()
        await asyncio.gather(*list(restarted.jobs.values()))
        self.bot.http.get_from_cdn.assert_awaited_once_with(selection()[1]['source']['url'])
        self.assertEqual(self.system.store.get(rid)['file_count'],2)
