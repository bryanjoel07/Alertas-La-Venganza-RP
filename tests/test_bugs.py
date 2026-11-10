import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from bug_store import BugStore,clip_url
from bug_ui import BugForm
from bugs import BugSystem,FORUM,TAGS,GUIDE,OLD_PORTAL,PORTAL
from tickets_store import PROTECTED

DETAILS='Descripción del error:\nNo abre al pulsar F2\n\nCómo ocurrió:\nEntré al servidor y pulsé F2\n\nSistema afectado:\nInventario\n\nFrecuencia:\nSiempre'

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=BugStore(Path(self.temp.name)/'db');self.store.initialize()
    def draft(self):
        rid=self.store.begin(1)
        self.store.save(rid,1,1,dict(player_id='42',title='Inventario',description='No abre',steps='Pulsar F2',system='Inventario'),0)
        return rid
    def test_draft_resumes_and_stale_form_cannot_overwrite(self):
        rid=self.draft();self.assertEqual(self.store.begin(1),rid)
        with self.assertRaises(ValueError):self.store.save(rid,1,1,{},0)
        self.assertEqual(json.loads(self.store.get(rid)['data'])['player_id'],'42')
    def test_video_is_an_alternative_to_url_and_survives_restart(self):
        rid=self.draft();video=b'video-test'
        self.store.save(rid,1,2,dict(frequency='Siempre',clip=''),1,'clip.mp4',video)
        fresh=BugStore(self.store.path);row=fresh.get(rid)
        self.assertEqual(row['video'],video);self.assertEqual(row['sha256'],hashlib.sha256(video).hexdigest())
        fresh.reserve(rid,1)
        with self.assertRaises(ValueError):fresh.reserve(rid,1)
        self.assertEqual(fresh.rows(recovery=True)[0]['id'],rid)
    def test_missing_clip_cannot_publish_and_another_user_cannot_submit(self):
        rid=self.draft()
        with self.assertRaises(ValueError):self.store.save(rid,1,2,dict(frequency='Siempre',clip=''),1)
        with self.assertRaises(ValueError):self.store.reserve(rid,1)
        with self.assertRaises(ValueError):self.store.save(rid,2,2,dict(frequency='Siempre',clip='https://example.com/clip'),1)
        self.assertEqual(self.store.get(rid)['status'],'borrador')
    def test_state_intent_is_recoverable_and_history_is_once_only(self):
        rid=self.draft();self.store.save(rid,1,2,dict(frequency='A veces',clip='https://example.com/video'),1)
        self.store.reserve(rid,1);self.store.published(rid,100,100)
        self.store.intent(rid,8,'revision','Revisando inventario')
        self.assertTrue(self.store.rows(recovery=True))
        self.store.finish(rid);self.store.finish(rid)
        self.assertEqual(self.store.get(rid)['status'],'revision');self.assertEqual(len(self.store.events(rid)),1)
    def test_manual_report_requires_clip_before_progress_but_can_be_closed(self):
        rid=self.store.adopt(100,1,'Error','Descripción')
        with self.assertRaises(ValueError):self.store.intent(rid,8,'revision','Revisar')
        self.store.manual_clip(rid,1,'https://example.com/clip');self.store.intent(rid,8,'revision','Ya tiene clip')
        self.assertEqual(self.store.by_thread(100)['id'],rid)
        self.assertEqual(self.store.adopt(100,1,'Otro','Texto'),rid)
    def test_clip_url_rejects_credentials_and_non_https(self):
        for value in ('http://example.com/a','https://user:secret@example.com/a','no es enlace'):
            with self.assertRaises(ValueError):clip_url(value)
    def test_full_form_cannot_be_saved_or_published_without_any_clip(self):
        rid=self.store.begin(1)
        values=dict(player_id='42',title='Error',details='Dónde pasa y cómo repetirlo',clip='')
        with self.assertRaisesRegex(ValueError,'clip es obligatorio'):self.store.save_full(rid,1,values,0)
        self.assertEqual(self.store.get(rid)['step'],0)
        with self.assertRaises(ValueError):self.store.reserve(rid,1)
    def test_full_form_accepts_link_or_file_and_preserves_both_across_restart(self):
        rid=self.store.begin(1)
        values=dict(player_id='42',title='Error',details=DETAILS,clip='https://example.com/clip')
        self.store.save_full(rid,1,values,0)
        self.assertEqual(self.store.get(rid)['step'],2)
        values['clip']=''
        self.store.save_full(rid,1,values,1,'video.mp4',b'video')
        fresh=BugStore(self.store.path)
        self.assertEqual(fresh.get(rid)['video'],b'video')
        fresh.reserve(rid,1)
        self.assertEqual(fresh.get(rid)['status'],'publicando')

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.guild=SimpleNamespace(id=10,fetch_member=AsyncMock())
        self.member=SimpleNamespace(id=1,name='usuario1',bot=False,roles=[],guild_permissions=discord.Permissions.none())
        self.guild.fetch_member.return_value=self.member
        self.forum=MagicMock(spec=discord.ForumChannel);self.forum.guild=self.guild;self.forum.id=FORUM
        self.forum.available_tags=[SimpleNamespace(id=i) for i in TAGS.values()]
        self.forum.permissions_for.return_value.view_channel=True
        self.bot=SimpleNamespace(user=SimpleNamespace(id=500),get_guild=lambda gid:self.guild,fetch_channel=AsyncMock(return_value=self.forum))
        self.system=BugSystem(self.bot,Path(temp.name)/'db',10);self.system.store.initialize()
        self.i=SimpleNamespace(guild_id=10,user=SimpleNamespace(id=1))
    async def test_only_requested_admin_roles_can_manage_and_fresh_permissions_are_checked(self):
        with self.assertRaises(ValueError):await self.system.member(self.i,admin=True)
        self.member.roles=[SimpleNamespace(id=next(iter(PROTECTED)))]
        await self.system.member(self.i,admin=True)
        self.member.roles=[]
        with self.assertRaises(ValueError):await self.system.member(self.i,admin=True)
        self.forum.permissions_for.return_value.view_channel=False
        with self.assertRaises(ValueError):await self.system.member(self.i)
    async def test_one_modal_has_details_and_native_file_upload_even_for_old_drafts(self):
        rid=self.system.store.begin(1);row=self.system.store.get(rid)
        first=BugForm(self.system,row);self.assertEqual(len(first.children),5)
        self.system.store.save(rid,1,1,dict(player_id='1',title='Error',description='Problema',steps='Pasos',system='Inventario'),0)
        second=BugForm(self.system,self.system.store.get(rid));payload=second.to_dict()
        self.assertEqual(second.title,'Reportar un error');self.assertEqual(len(payload['components']),5)
        self.assertEqual(payload['components'][3]['component']['type'],19)
        self.assertFalse(second.file.required)
        self.assertIn('Descripción del error:\nProblema',second.inputs['details'].default)
        self.assertIn('Cómo ocurrió:\nPasos',second.inputs['details'].default)
    async def test_report_embed_never_mentions_everyone_or_loses_credit(self):
        rid=self.system.store.begin(1);self.system.store.save(rid,1,1,dict(player_id='42',title='Error',description='Problema',steps='Pasos',system='Inventario'),0)
        embed=self.system.embed(self.system.store.get(rid))
        self.assertIn('<@1>',embed.description)
        self.assertNotIn('@everyone',json.dumps(embed.to_dict()))
    async def test_all_fields_and_file_are_submitted_in_one_modal(self):
        rid=self.system.store.begin(1);form=BugForm(self.system,self.system.store.get(rid))
        for key,value in dict(player_id='42',title='Inventario',details=DETAILS).items():form.inputs[key]._value=value
        form.clip._value=''
        form.file._values=[SimpleNamespace(id=900,filename='clip.mp4',size=10,url='https://cdn.discordapp.com/attachments/100/900/clip.mp4',proxy_url=None,read=AsyncMock(return_value=b'clip-video'))]
        self.i.response=SimpleNamespace(defer=AsyncMock(),is_done=lambda:True)
        self.i.edit_original_response=AsyncMock()
        self.i.followup=SimpleNamespace(send=AsyncMock())
        await form.on_submit(self.i)
        import asyncio
        await asyncio.gather(*list(self.system.clips.jobs.values()))
        saved=self.system.store.get(rid)
        self.assertEqual(saved['step'],2);self.assertEqual(saved['video'],b'clip-video')
        data=json.loads(saved['data'])
        self.assertEqual(data['details'],DETAILS)
        self.assertEqual(data['description'],'No abre al pulsar F2')
        self.assertEqual(data['system'],'Inventario');self.assertEqual(data['frequency'],'Siempre')
        self.assertEqual(data['discord_username'],'usuario1')
        self.forum.create_thread.assert_not_called()
        self.assertIn('Datos guardados',self.i.edit_original_response.call_args_list[0].kwargs['content'])
        self.assertIn('Revisa tu reporte',self.i.edit_original_response.call_args.kwargs['content'])
    async def test_publication_itself_refuses_a_forged_completed_draft_without_clip(self):
        rid=self.system.store.begin(1)
        with self.system.store.db() as db:db.execute("UPDATE lv_bugs SET status='publicando',step=2 WHERE id=?",(rid,))
        with self.assertRaisesRegex(ValueError,'clip es obligatorio'):await self.system.create(rid)
        self.forum.create_thread.assert_not_called()
    async def test_video_is_stored_before_discord_and_double_publish_does_not_create_two_threads(self):
        rid=self.system.store.begin(1)
        self.system.store.save(rid,1,1,dict(player_id='42',title='Error',description='Problema',steps='Pasos',system='Inventario'),0)
        self.system.store.save(rid,1,2,dict(frequency='Siempre',clip=''),1,'video.mp4',b'clip-data')
        self.system.store.reserve(rid,1)
        async def tracked(rid,title,request,operation):return await operation()
        self.system.tracked=tracked
        async def create(**kwargs):
            self.assertEqual(self.system.store.get(rid)['video'],b'clip-data')
            self.assertEqual(kwargs['file'].fp.read(),b'clip-data')
            self.assertEqual(kwargs['allowed_mentions'].to_dict()['parse'],[])
            return SimpleNamespace(thread=SimpleNamespace(id=700))
        self.forum.create_thread=AsyncMock(side_effect=create)
        await self.system.create(rid);await self.system.create(rid)
        self.forum.create_thread.assert_awaited_once()
        self.assertEqual(self.system.store.get(rid)['thread'],700)
    async def test_failed_tag_update_preserves_intent_and_retry_keeps_unrelated_tags(self):
        rid=self.system.store.adopt(700,1,'Error','Descripción','https://example.com/clip')
        self.system.store.controls(rid,701);self.system.store.intent(rid,2,'revision','Revisar')
        message=SimpleNamespace(author=SimpleNamespace(id=500),edit=AsyncMock())
        thread=SimpleNamespace(parent_id=FORUM,applied_tags=[SimpleNamespace(id=TAGS['pendiente']),SimpleNamespace(id=999)],
            edit=AsyncMock(side_effect=TimeoutError()),fetch_message=AsyncMock(return_value=message))
        self.bot.fetch_channel=AsyncMock(side_effect=lambda cid:self.forum if cid==FORUM else thread)
        self.forum.get_tag.side_effect=lambda rid:SimpleNamespace(id=rid)
        with self.assertRaises(TimeoutError):await self.system.apply_state(rid)
        self.assertIsNotNone(self.system.store.get(rid)['pending'])
        thread.edit.side_effect=None
        await self.system.apply_state(rid)
        self.assertEqual([t.id for t in thread.edit.call_args.kwargs['applied_tags']],[999,TAGS['revision']])
        self.assertEqual(self.system.store.get(rid)['status'],'revision')
    async def test_original_pinned_guide_keeps_its_text_and_gets_buttons_only_once(self):
        original=SimpleNamespace(id=GUIDE,author=SimpleNamespace(id=99),components=[],content='PLANTILLA ORIGINAL',edit=AsyncMock())
        messages=[original]
        async def history(**kwargs):
            for message in messages:yield message
        async def send(content,**kwargs):
            message=SimpleNamespace(id=888,author=self.bot.user,components=[SimpleNamespace(children=[SimpleNamespace(custom_id='lvbug:new:0'),SimpleNamespace(custom_id='lvbug:mine:0')])])
            messages.append(message);return message
        guide=SimpleNamespace(parent_id=FORUM,history=history,send=AsyncMock(side_effect=send))
        self.bot.fetch_channel=AsyncMock(return_value=guide)
        await self.system.guide_buttons();await self.system.guide_buttons()
        guide.send.assert_awaited_once();original.edit.assert_not_awaited()
        self.assertEqual(original.content,'PLANTILLA ORIGINAL')
    async def test_extra_portal_is_archived_without_deleting_thread_or_user_history(self):
        root=SimpleNamespace(id=OLD_PORTAL,author=self.bot.user,attachments=[],content='Panel anterior',
            embeds=[discord.Embed(title='🐛 ¿Encontraste un error?')],components=[],edit=AsyncMock())
        thread=SimpleNamespace(id=OLD_PORTAL,parent_id=FORUM,owner_id=500,name=PORTAL,archived=False,locked=False,
            fetch_message=AsyncMock(return_value=root),edit=AsyncMock(),delete=AsyncMock())
        async def edit_root(**kwargs):
            root.content=kwargs['content'];root.embeds=[];root.components=[]
        async def edit_thread(**kwargs):thread.archived=True;thread.locked=True
        root.edit.side_effect=edit_root;thread.edit.side_effect=edit_thread
        self.bot.fetch_channel=AsyncMock(return_value=thread)
        snapshots=[]
        async def tracked(env,title,operation,*,request_id,snapshot):
            snapshots.append(await snapshot());await operation();snapshots.append(await snapshot())
        self.bot.changes=SimpleNamespace(tracked=tracked)
        self.system.store.config('guide_buttons',888)
        await self.system.retire_duplicate_portal();await self.system.retire_duplicate_portal()
        thread.delete.assert_not_awaited();root.edit.assert_awaited_once()
        self.assertFalse(snapshots[0]['archived']);self.assertTrue(snapshots[1]['archived'])
        self.assertIn(str(GUIDE),root.content)
    async def test_canonical_ready_never_creates_another_forum_post_even_when_called_twice(self):
        entry=SimpleNamespace(author=self.bot.user,id=888,components=[SimpleNamespace(children=[SimpleNamespace(custom_id='lvbug:new:0'),SimpleNamespace(custom_id='lvbug:mine:0')])])
        guide=SimpleNamespace(id=888,fetch_message=AsyncMock(return_value=entry))
        self.bot.fetch_channel=AsyncMock(return_value=guide)
        self.system.forum=AsyncMock(return_value=self.forum)
        self.system.guide_buttons=AsyncMock()
        self.system.retire_duplicate_portal=AsyncMock()
        async def tracked(rid,title,request,operation):return await operation()
        self.system.tracked=tracked;self.system.store.config('guide_buttons',888)
        with patch('bug_panel.ReportPanel.ready',AsyncMock(return_value=guide)):
            await self.system.ready();await self.system.ready()
        self.forum.create_thread.assert_not_called()
    async def test_cleanup_refuses_a_real_report_even_if_it_has_the_old_portal_id(self):
        self.system.store.adopt(OLD_PORTAL,1,'Reporte real','Datos','https://example.com/video')
        thread=SimpleNamespace(parent_id=FORUM,owner_id=500,delete=AsyncMock(),edit=AsyncMock())
        self.bot.fetch_channel=AsyncMock(return_value=thread)
        with self.assertRaises(ValueError):await self.system.retire_duplicate_portal()
        thread.delete.assert_not_awaited();thread.edit.assert_not_awaited()
