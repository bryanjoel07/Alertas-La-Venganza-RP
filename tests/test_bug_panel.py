import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock

import discord

from bug_panel import ReportPanel,FORUM,LEGACY,MARKER,safe_old_post
from bug_template import details_default,parse_details,panel_embed
from bug_store import BugStore
from bug_ui import buttons
from bugs import BugSystem,TAGS
from change_log import ChangeLog

DETAILS='Descripción del error:\nNo abre el inventario\n\nCómo ocurrió:\nPulsé F2 al entrar\n\nSistema afectado:\nInventario\n\nFrecuencia:\nA veces'


class TemplateTests(unittest.TestCase):
    def test_all_four_questions_are_separate_answers(self):
        data=parse_details(DETAILS)
        self.assertEqual(data,dict(description='No abre el inventario',steps='Pulsé F2 al entrar',system='Inventario',frequency='A veces'))
    def test_unfilled_scaffold_missing_section_or_duplicate_section_are_rejected(self):
        for text in (details_default({}),DETAILS.split('Frecuencia:')[0],DETAILS+'\nSistema afectado:\nOtro'):
            with self.assertRaises(ValueError):parse_details(text)
    def test_old_unstructured_draft_is_preserved_as_description(self):
        value=details_default(dict(details='Lo que escribió el jugador anteriormente.'))
        self.assertIn('Lo que escribió el jugador anteriormente.',value)
        self.assertIn('Cómo ocurrió:',value);self.assertIn('Frecuencia:',value)
    def test_new_instructions_include_old_template_requirements(self):
        embed=panel_embed();text=json.dumps(embed.to_dict(),ensure_ascii=False)
        for term in ('Discord','ID dentro del servidor','Descripción','Cómo ocurrió','Sistema afectado','Frecuencia','Sin clip'):
            self.assertIn(term,text)
        self.assertLess(len(embed),6000)


class Message:
    def __init__(self,mid,author,content='',embed=None,view=None):
        self.id,self.author,self.content=mid,author,content
        self.embeds=[embed] if embed else []
        self.components=[discord.components.ActionRow(row) for row in view.to_components()] if view else []
        self.attachments=[];self.stickers=[]
    async def edit(self,**kwargs):
        if 'content' in kwargs:self.content=kwargs['content'] or ''
        if 'embed' in kwargs:self.embeds=[kwargs['embed']] if kwargs['embed'] else []
        if 'view' in kwargs:self.components=[discord.components.ActionRow(row) for row in kwargs['view'].to_components()] if kwargs['view'] else []
        return self


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'db.sqlite'
        self.bot_user=SimpleNamespace(id=500)
        self.source_user=SimpleNamespace(id=99)
        self.threads={};self.fail_pin=False
        self.guild=SimpleNamespace(id=10,active_threads=AsyncMock(side_effect=lambda:list(self.threads.values())))
        self.forum=MagicMock(spec=discord.ForumChannel);self.forum.id=FORUM;self.forum.guild=self.guild
        self.forum.available_tags=[SimpleNamespace(id=rid) for rid in TAGS.values()]
        self.forum.get_tag.side_effect=lambda rid:SimpleNamespace(id=rid)
        async def archived(**kwargs):
            if False:yield None
        self.forum.archived_threads=archived
        self.old=self.thread(LEGACY,99,'🐛 PLANTILLA OFICIAL',pinned=True)
        self.old.messages[LEGACY]=Message(LEGACY,self.source_user,'🐛 PLANTILLA OFICIAL | REPORTE DE ERRORES\nInstrucciones anteriores')
        self.old.messages[LEGACY+1]=Message(LEGACY+1,self.bot_user,'Botones anteriores',view=buttons('new','mine'))
        async def fetch(tid):
            if tid==FORUM:return self.forum
            if tid not in self.threads:raise discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),dict(code=10003,message='Unknown Channel'))
            return self.threads[tid]
        self.bot=SimpleNamespace(user=self.bot_user,get_guild=lambda gid:self.guild,fetch_channel=AsyncMock(side_effect=fetch))
        self.bot.changes=ChangeLog(self.bot,self.path,10);self.bot.changes.journal.initialize()
        self.system=BugSystem(self.bot,self.path,10);self.system.store.initialize()
        self.panel=ReportPanel(self.system)
        async def create(**kwargs):
            tid=9000+len(self.threads)
            thread=self.thread(tid,500,kwargs['name'])
            thread.messages[tid]=Message(tid,self.bot_user,embed=kwargs['embed'],view=kwargs['view'])
            return SimpleNamespace(thread=thread)
        self.forum.create_thread=AsyncMock(side_effect=create)

    def thread(self,tid,owner,name,pinned=False):
        thread=SimpleNamespace(id=tid,owner_id=owner,parent_id=FORUM,name=name,
            archived=False,locked=False,flags=SimpleNamespace(pinned=pinned),applied_tags=[SimpleNamespace(id=TAGS['info'])],messages={})
        async def fetch(mid):
            if mid not in thread.messages:raise discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),dict(code=10008,message='Unknown Message'))
            return thread.messages[mid]
        async def history(**kwargs):
            for message in list(thread.messages.values()):yield message
        async def edit(**kwargs):
            if kwargs.get('pinned'):
                if self.fail_pin and tid!=LEGACY:raise discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),dict(code=50013,message='Missing Permissions'))
                if any(t.id!=tid and t.flags.pinned for t in self.threads.values()):raise discord.HTTPException(SimpleNamespace(status=400,reason='Bad Request'),dict(code=30047,message='Maximum pinned threads'))
            if 'pinned' in kwargs:thread.flags.pinned=kwargs['pinned']
            for field in ('archived','locked','name'):
                if field in kwargs:setattr(thread,field,kwargs[field])
            return thread
        async def delete(**kwargs):
            self.assertEqual(tid,LEGACY)
            self.assertIsNotNone(self.system.store.panel_backup(LEGACY))
            others=[t for t in self.threads.values() if t.id!=LEGACY and t.flags.pinned]
            self.assertEqual(len(others),1)
            root=others[0].messages[others[0].id]
            self.assertEqual(root.author.id,500);self.assertEqual(root.embeds[0].footer.text,MARKER)
            del self.threads[tid]
        thread.fetch_message=AsyncMock(side_effect=fetch);thread.history=history
        thread.edit=AsyncMock(side_effect=edit);thread.delete=AsyncMock(side_effect=delete)
        self.threads[tid]=thread
        return thread

    async def test_new_panel_is_verified_and_pinned_before_exact_old_template_is_removed(self):
        new=await self.panel.ready()
        self.assertNotIn(LEGACY,self.threads)
        self.assertTrue(new.flags.pinned)
        self.assertEqual(new.owner_id,500)
        self.assertEqual(self.system.entry_controls(new.messages[new.id]),['lvbug:new:0','lvbug:mine:0'])
        self.assertEqual(self.system.store.config('legacy_guide_removed'),'1')
        saved=self.system.store.panel_backup(LEGACY)
        self.assertIn('Instrucciones anteriores',saved['messages'][0]['content'])
        self.assertTrue(all(r['status']=='completado' for r in self.bot.changes.journal.rows()))

    async def test_restarting_does_not_recreate_old_post_or_duplicate_new_one(self):
        new=await self.panel.ready();await ReportPanel(self.system).ready()
        self.forum.create_thread.assert_awaited_once()
        self.assertEqual(len(self.threads),1);self.assertIn(new.id,self.threads)

    async def test_failed_pin_restores_original_pin_and_never_deletes_old_template(self):
        self.fail_pin=True
        with self.assertRaises(discord.Forbidden):await self.panel.ready()
        self.assertIn(LEGACY,self.threads);self.assertTrue(self.old.flags.pinned)
        self.old.delete.assert_not_awaited()

    async def test_human_replies_are_preserved_and_prevent_deleting_old_post(self):
        self.old.messages[1234]=Message(1234,SimpleNamespace(id=7),'Una conversación que se conserva')
        new=await self.panel.ready()
        self.assertIn(LEGACY,self.threads);self.assertTrue(self.old.archived)
        self.assertTrue(new.flags.pinned);self.old.delete.assert_not_awaited()
        self.assertEqual(self.old.messages[1234].content,'Una conversación que se conserva')

    async def test_source_attachment_or_real_report_is_never_eligible_for_removal(self):
        self.old.messages[LEGACY].attachments=[SimpleNamespace(id=1,filename='clip.mp4',url='https://example.com/clip')]
        self.assertFalse(safe_old_post(self.old,list(self.old.messages.values()),500))
        self.system.store.adopt(LEGACY,1,'Reporte real','Datos','https://example.com/video')
        with self.assertRaises(ValueError):await self.panel.ready()
        self.old.delete.assert_not_awaited();self.forum.create_thread.assert_not_awaited()

    async def test_private_backup_digest_failure_blocks_deletion(self):
        await self.panel.capture_old()
        with self.system.store.db() as db:db.execute("UPDATE lv_bug_panel_backups SET payload='corrupt'")
        with self.assertRaisesRegex(ValueError,'verificación'):await self.panel.ready()
        self.old.delete.assert_not_awaited();self.forum.create_thread.assert_not_awaited()

    async def test_lost_creation_response_recovers_same_post_without_duplicates(self):
        original=self.forum.create_thread.side_effect
        async def uncertain(**kwargs):
            await original(**kwargs)
            raise TimeoutError('response lost')
        self.forum.create_thread.side_effect=uncertain
        with self.assertRaises(TimeoutError):await self.panel.ready()
        self.old.delete.assert_not_awaited();self.assertTrue(self.old.flags.pinned)
        self.forum.create_thread.side_effect=original
        new=await self.panel.ready()
        self.forum.create_thread.assert_awaited_once()
        self.assertEqual(list(self.threads),[new.id])

    async def test_new_reply_after_backup_prevents_deletion(self):
        original=self.old.edit.side_effect
        async def reply_during_migration(**kwargs):
            result=await original(**kwargs)
            if kwargs.get('archived'):
                self.old.messages[1234]=Message(1234,SimpleNamespace(id=7),'Respuesta que llegó después de la copia')
            return result
        self.old.edit.side_effect=reply_during_migration
        with self.assertRaisesRegex(ValueError,'recibió cambios'):await self.panel.ready()
        self.old.delete.assert_not_awaited()
        self.assertIn(LEGACY,self.threads)
        self.assertIn(1234,self.old.messages)
