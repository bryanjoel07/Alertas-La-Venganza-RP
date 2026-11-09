import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,Mock,patch

import discord
from recruitment_store import RecruitmentStore,QUESTIONS,ACTIVE
from recruitment_ui import ApplicationForm,InterviewForm,TextForm,RecruitPanel,controls,detail_pages,Confirm
from recruitment import RecruitmentSystem,can_review,parse_date,pair,overwrite_from,CHANNELS,LEGACY_PANEL,LEGACY_AUTHOR
from recruitment_survey import RecruitmentSource
from tickets_store import ALL_STAFF,PROTECTED

class StoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db.sqlite';self.store=RecruitmentStore(self.path);self.store.initialize()
 def tearDown(self):self.tmp.cleanup()
 def draft(self,user=99):return self.store.begin(user)
 def complete(self,user=99):
  row=self.draft(user)
  for step,questions in enumerate((QUESTIONS[:5],QUESTIONS[5:])):
   self.store.save_step(row['id'],user,step,{q[0]:'Mi respuesta' for q in questions},row['revision']);row=self.store.get(row['id'])
  return row
 def submitted(self,user=99):
  row=self.complete(user);self.store.submit(row['id'],user,row['revision']);return self.store.get(row['id'])
 def test_one_draft_survives_reinitialization(self):
  row=self.draft();other=RecruitmentStore(self.path);other.initialize();self.assertEqual(row,other.begin(99))
 def test_application_requires_two_completed_steps(self):
  row=self.draft()
  with self.assertRaises(ValueError):self.store.submit(row['id'],99,row['revision'])
 def test_steps_reject_missing_oversize_and_wrong_owner(self):
  row=self.draft();values={q[0]:'Sí' for q in QUESTIONS[:5]}
  with self.assertRaises(ValueError):self.store.save_step(row['id'],1,0,values,0)
  with self.assertRaises(ValueError):self.store.save_step(row['id'],99,0,{},0)
  values['nombre']='X'*101
  with self.assertRaises(ValueError):self.store.save_step(row['id'],99,0,values,0)
 def test_double_submission_has_single_notice_and_event(self):
  row=self.complete();self.store.submit(row['id'],99,row['revision'])
  with self.assertRaises(ValueError):self.store.submit(row['id'],99,row['revision'])
  self.assertEqual(len(self.store.pending()),1);self.assertEqual(len(self.store.events(row['id'])),1)
 def test_own_review_forbidden(self):
  row=self.submitted()
  for action,args in [(self.store.claim,(99,row['revision'])),(self.store.decide,(99,False,'No',row['revision']))]:
   with self.assertRaises(ValueError):action(row['id'],*args)
 def test_concurrent_review_uses_revision(self):
  row=self.submitted();self.store.claim(row['id'],1,row['revision'])
  with self.assertRaises(ValueError):self.store.claim(row['id'],2,row['revision'])
  fresh=self.store.get(row['id'])
  with self.assertRaises(ValueError):self.store.claim(row['id'],2,fresh['revision'])
 def test_asking_and_answering_preserves_private_notes(self):
  row=self.submitted();rid=row['id']
  self.store.staff_text(rid,1,'nota','Nota privada',row['revision']);row=self.store.get(rid)
  self.store.staff_text(rid,1,'pregunta','¿Cuándo puedes?',row['revision']);row=self.store.get(rid)
  self.assertEqual(row['status'],'esperando')
  self.store.answer(rid,99,'Mañana',row['revision']);self.assertEqual(self.store.get(rid)['status'],'revision')
  self.assertFalse(any(e['text']=='Nota privada' for e in self.store.events(rid)))
  self.assertTrue(any(e['text']=='Nota privada' for e in self.store.events(rid,True)))
 def test_accept_requires_interview_then_is_final_and_manual(self):
  row=self.submitted();rid=row['id']
  with self.assertRaises(ValueError):self.store.decide(rid,1,True,'Bienvenido',row['revision'])
  self.store.schedule(rid,1,int(time.time())+3600,1,'Nos vemos',row['revision']);row=self.store.get(rid)
  self.store.interviewed(rid,1,'Buena entrevista',row['revision']);row=self.store.get(rid)
  self.store.decide(rid,1,True,'Bienvenido',row['revision']);final=self.store.get(rid)
  self.assertEqual(final['status'],'aceptada');self.assertEqual(final['decided_by'],1)
  with self.assertRaises(ValueError):self.store.decide(rid,2,False,'No',final['revision'])
  self.assertNotIn('role',final)
 def test_closed_application_rejects_candidate_reply(self):
  row=self.submitted();self.store.decide(row['id'],1,False,'Necesitas más práctica.',row['revision']);row=self.store.get(row['id'])
  with self.assertRaises(ValueError):self.store.answer(row['id'],99,'hola',row['revision'])
 def test_notification_receipts_do_not_requeue(self):
  row=self.submitted();n=self.store.pending()[0];self.store.notice_done(n['id'],'blocked')
  self.assertFalse(self.store.pending());self.store.initialize();self.assertFalse(self.store.pending())
 def test_intake_pause_preserves_old_application_but_stops_new(self):
  row=self.submitted();self.store.config('open',0)
  self.assertEqual(self.store.begin(99)['id'],row['id'])
  with self.assertRaises(ValueError):self.store.begin(100)
 def test_draft_restart_keeps_values_and_withdrawal_is_not_staff_history(self):
  row=self.complete();self.store.restart(row['id'],99,row['revision']);row=self.store.get(row['id'])
  self.assertEqual(row['step'],0);self.assertTrue(json.loads(row['answers']))
  self.store.withdraw(row['id'],99,row['revision']);self.assertFalse(self.store.rows(submitted=True))
 def test_reminder_idempotent_and_reprogramming_gets_new_reminder(self):
  row=self.submitted();at=int(time.time())+1800;rid=row['id']
  self.store.schedule(rid,1,at,1,'Prepárate',row['revision']);self.store.remind();self.store.remind()
  reminders=[n for n in self.store.pending() if n['kind'].startswith('recordatorio:')];self.assertEqual(len(reminders),1)
  row=self.store.get(rid);self.store.schedule(rid,1,at+600,1,'Cambiamos la hora',row['revision']);self.store.remind()
  self.assertEqual(len([n for n in self.store.pending() if n['kind'].startswith('recordatorio:')]),2)
 def test_history_pagination_does_not_skip_unsubmitted_drafts(self):
  self.submitted(99);self.draft(100)
  self.assertEqual(len(self.store.rows(submitted=True,limit=1)),1)
  self.assertEqual(self.store.rows(submitted=True,limit=1)[0]['owner'],99)
 def test_old_revision_cannot_overwrite_new_answer(self):
  row=self.submitted();self.store.staff_text(row['id'],1,'mensaje','Hola',row['revision'])
  with self.assertRaises(ValueError):self.store.answer(row['id'],99,'Test',row['revision'])
 def test_dates_are_puerto_rico(self):
  self.assertEqual(parse_date('2026-11-12','19:30'),1794526200)
  with self.assertRaises(ValueError):parse_date('12/11','7pm')

class UiTests(unittest.IsolatedAsyncioTestCase):
 async def test_forms_fit_discord_limits(self):
  row={'id':1,'owner':99,'revision':0,'step':0,'answers':'{}'}
  for step in (0,1):
   row['step']=step;modal=ApplicationForm(None,row)
   self.assertLessEqual(len(modal.children),5)
   for child in modal.children:
    self.assertLessEqual(len(child.label),45);self.assertLessEqual(len(child.placeholder),100)
  self.assertEqual(len(InterviewForm(None,row).children),3)
  for kind in ('reply','question','message','note','attended','accept','reject'):
   modal=TextForm(None,row,kind);self.assertLessEqual(len(modal.children[0].label),45)
 async def test_persistent_controls_after_restart(self):
  view=controls(54,['detail','claim','interview','decision']);self.assertTrue(view.is_persistent());self.assertEqual(len(view.children),4)
  self.assertTrue(RecruitPanel(None).is_persistent())
 async def test_confirmation_edits_ephemeral_prompt_through_interaction(self):
  callback=AsyncMock();view=Confirm(99,callback)
  interaction=NS(response=NS(edit_message=AsyncMock()),message=NS(edit=AsyncMock(side_effect=AssertionError('Ephemeral messages cannot use the channel endpoint'))))
  await view.confirm.callback(interaction)
  interaction.response.edit_message.assert_awaited_once_with(view=view)
  interaction.message.edit.assert_not_awaited();callback.assert_awaited_once_with(interaction)
  self.assertTrue(all(child.disabled for child in view.children))
 async def test_private_notes_not_in_candidate_pages_even_if_passed(self):
  row={'id':1,'owner':99,'status':'enviada','answers':json.dumps({q[0]:'X'*q[2] for q in QUESTIONS})}
  events=[{'private':1,'action':'nota','text':'SECRETO','created':1}]
  pages=detail_pages(row,events,False);self.assertNotIn('SECRETO',''.join(pages));self.assertTrue(all(len(p)<4096 for p in pages))
  self.assertIn('SECRETO',''.join(detail_pages(row,events,True)))

class ServiceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.bot=NS()
  self.system=RecruitmentSystem(self.bot,self.path,55);await self.system.call('initialize')
 async def asyncTearDown(self):self.tmp.cleanup()
 def member(self,uid=1,roles=(),admin=False):return NS(id=uid,roles=[NS(id=r) for r in roles],guild_permissions=discord.Permissions(administrator=admin))
 async def submitted(self):
  row=await self.system.call('begin',99)
  for step,qs in enumerate((QUESTIONS[:5],QUESTIONS[5:])):
   await self.system.call('save_step',row['id'],99,step,{q[0]:'Hola' for q in qs},row['revision']);row=await self.system.call('get',row['id'])
  await self.system.call('submit',row['id'],99,row['revision']);return await self.system.call('get',row['id'])
 async def test_exact_seven_roles_and_admin_authorized(self):
  for role in ALL_STAFF:self.assertTrue(can_review(self.member(roles=[role])))
  self.assertTrue(can_review(self.member(admin=True)));self.assertFalse(can_review(self.member(roles=[333])))
 async def test_forged_other_candidate_and_demoted_staff_denied(self):
  row=await self.submitted();self.system.member=AsyncMock(return_value=self.member(uid=5))
  with self.assertRaises(ValueError):await self.system.authorized(NS(),row['id'])
  with self.assertRaises(ValueError):await self.system.authorized(NS(),row['id'],staff=True)
  self.system.member.return_value=self.member(uid=99,roles=[next(iter(ALL_STAFF))])
  with self.assertRaises(ValueError):await self.system.authorized(NS(),row['id'],staff=True)
 async def test_staff_cannot_read_unsubmitted_draft(self):
  row=await self.system.call('begin',99);self.system.member=AsyncMock(return_value=self.member(roles=[next(iter(ALL_STAFF))]))
  with self.assertRaises(ValueError):await self.system.authorized(NS(),row['id'],staff=True)
 async def test_acceptance_never_assigns_or_edits_roles(self):
  row=await self.submitted();rid=row['id']
  await self.system.call('schedule',rid,1,int(time.time())+600,1,'Ven a la sala',row['revision']);row=await self.system.call('get',rid)
  await self.system.call('interviewed',rid,1,'Hablamos y fue bien',row['revision']);row=await self.system.call('get',rid)
  member=self.member(roles=[next(iter(ALL_STAFF))]);member.add_roles=AsyncMock();member.remove_roles=AsyncMock()
  self.system.authorized=AsyncMock(return_value=(member,row));self.system.sync=AsyncMock()
  async def tracked(title,request,operation,*args,**kwargs):return await operation()
  self.system.tracked=tracked
  with patch('recruitment.reply',new=AsyncMock()) as send:
   await self.system.prepare_decision(NS(user=NS(id=1)),rid,True,'Bienvenido',row['revision']);view=send.call_args.kwargs['view']
   await view.callback(NS(user=NS(id=1),id=123))
  self.assertEqual((await self.system.call('get',rid))['status'],'aceptada')
  member.add_roles.assert_not_awaited();member.remove_roles.assert_not_awaited()
 async def test_legacy_panel_not_deleted_without_durable_backup(self):
  source=RecruitmentSource(self.path);source.initialize();channel=NS(fetch_message=AsyncMock())
  self.system.channel=AsyncMock(return_value=channel)
  with self.assertRaises(ValueError):await self.system.retire_legacy()
  channel.fetch_message.assert_not_awaited()
 async def test_legacy_panel_only_specific_backed_message_deleted(self):
  source=RecruitmentSource(self.path);source.initialize()
  payload={'channel':str(CHANNELS['apply']),'id':str(LEGACY_PANEL),'author':str(LEGACY_AUTHOR),'attachments':[],
   'content':'Panel anterior','embeds':[],'components':[{'type':1}]}
  source.message(payload)
  message=NS(author=NS(id=LEGACY_AUTHOR),content='Panel anterior',embeds=[],attachments=[],components=[NS(to_dict=lambda:{'type':1})],delete=AsyncMock())
  class Empty:
   async def __aiter__(self):
    if False:yield
  channel=NS(fetch_message=AsyncMock(return_value=message),history=Mock(return_value=Empty()))
  self.system.channel=AsyncMock(return_value=channel)
  await self.system.retire_legacy();message.delete.assert_awaited_once_with()
 async def test_manual_overwrite_roundtrip(self):
  saved={'present':True,'allow':'1024','deny':'2048'};value=overwrite_from(saved)
  self.assertTrue(value.view_channel);self.assertFalse(value.send_messages);self.assertIsNone(overwrite_from({'present':False,'allow':'0','deny':'0'}))
 async def test_decision_confirmation_rechecks_current_roles(self):
  row=await self.submitted();self.system.authorized=AsyncMock(return_value=(self.member(roles=[next(iter(ALL_STAFF))]),row))
  with patch('recruitment.reply',new=AsyncMock()) as send:
   await self.system.prepare_decision(NS(user=NS(id=1)),row['id'],False,'Aún no',row['revision']);view=send.call_args.kwargs['view']
  self.system.authorized.side_effect=ValueError('Ya no tienes acceso')
  with self.assertRaises(ValueError):await view.callback(NS(user=NS(id=1)))
  self.assertEqual((await self.system.call('get',row['id']))['status'],'enviada')

class AccessTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.system=RecruitmentSystem(NS(),Path(self.tmp.name)/'db',55);await self.system.call('initialize')
 async def asyncTearDown(self):self.tmp.cleanup()
 def channel(self):
  from tickets_store import NORMAL_STAFF
  roles={rid:NS(id=rid) for rid in ALL_STAFF};member=NS(id=99)
  class Fake:
   def __init__(self):
    self.values={rid:discord.PermissionOverwrite(view_channel=True) for rid in PROTECTED}
    self.values[55]=discord.PermissionOverwrite(view_channel=False);self.changed=[]
    self.guild=NS(get_role=roles.get,fetch_member=AsyncMock(return_value=member));self.sync()
   def sync(self):
    self._overwrites=[NS(id=rid,type=0 if rid!=99 else 1,allow=ov.pair()[0].value,deny=ov.pair()[1].value) for rid,ov in self.values.items()]
   def overwrites_for(self,target):return discord.PermissionOverwrite.from_pair(*self.values.get(target.id,discord.PermissionOverwrite()).pair())
   def permissions_for(self,target):return NS(view_channel=self.values.get(target.id,discord.PermissionOverwrite()).view_channel)
   async def set_permissions(self,target,overwrite,reason):
    self.changed.append(target.id)
    if overwrite is None:self.values.pop(target.id,None)
    else:self.values[target.id]=overwrite
    self.sync()
  return Fake(),member
 async def test_only_requested_nonprotected_roles_updated(self):
  from tickets_store import NORMAL_STAFF
  channel,member=self.channel();before={rid:pair(channel,NS(id=rid)) for rid in PROTECTED|{55}}
  self.system.channel=AsyncMock(return_value=channel);await self.system.access()
  self.assertEqual(set(channel.changed),NORMAL_STAFF)
  self.assertEqual(before,{rid:pair(channel,NS(id=rid)) for rid in PROTECTED|{55}})
 async def test_voice_grant_recover_and_restore_without_touching_roles(self):
  channel,member=self.channel();self.system.channel=AsyncMock(return_value=channel)
  async def tracked(title,request,operation,*args,**kwargs):return await operation()
  self.system.tracked=tracked
  row={'id':1,'owner':99,'status':'entrevista','interview_done':0,'interview_at':int(time.time())+600}
  before=pair(channel,member);await self.system.voice_access(row)
  self.assertTrue(channel.overwrites_for(member).view_channel)
  self.assertEqual((await self.system.call('voice',1))[0]['state'],'active')
  await self.system.voice_access(row);self.assertEqual(channel.changed.count(99),1)
  row['status']='aceptada';await self.system.voice_access(row)
  self.assertEqual(pair(channel,member),before);self.assertEqual((await self.system.call('voice',1))[0]['state'],'restored')
  self.assertEqual(set(channel.changed),{99})
 async def test_voice_manual_changes_preserved(self):
  channel,member=self.channel();self.system.channel=AsyncMock(return_value=channel)
  async def tracked(title,request,operation,*args,**kwargs):return await operation()
  self.system.tracked=tracked
  row={'id':1,'owner':99,'status':'entrevista','interview_done':0,'interview_at':int(time.time())+600}
  await self.system.voice_access(row)
  channel.values[99].speak=False;channel.sync();manual=pair(channel,member)
  row['status']='rechazada';await self.system.voice_access(row)
  self.assertEqual(pair(channel,member),manual);self.assertEqual((await self.system.call('voice',1))[0]['state'],'conflict')
 async def test_rescheduled_interview_grants_access_again_after_previous_restore(self):
  channel,member=self.channel();self.system.channel=AsyncMock(return_value=channel)
  async def tracked(title,request,operation,*args,**kwargs):return await operation()
  self.system.tracked=tracked
  row={'id':1,'owner':99,'status':'entrevista','interview_done':0,'interview_at':int(time.time())+600}
  await self.system.voice_access(row);row['interview_done']=1;await self.system.voice_access(row)
  row['interview_done']=0;row['interview_at']+=60;await self.system.voice_access(row)
  self.assertTrue(channel.overwrites_for(member).view_channel)
