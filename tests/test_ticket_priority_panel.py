import asyncio
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

import discord

from ticket_priority_repair import repair_requested_priority,REQUEST_KEY
from tickets import TicketSystem
from tickets_store import TicketStore
from tickets_ui import TicketControls,PriorityForm
import test_ticket_members as fixtures


class PriorityPanelTests(unittest.IsolatedAsyncioTestCase):
 member=fixtures.TicketMemberTests.member
 update_raw=fixtures.TicketMemberTests.update_raw
 raw=fixtures.TicketMemberTests.raw
 async def asyncSetUp(self):
  await fixtures.TicketMemberTests.asyncSetUp(self)
  self.system.store.update(self.rid,priority='urgente',control_message=500,assignee=5)
  self.message=SimpleNamespace(id=500,author=self.bot.user,content='',
    embeds=[self.system.embed(self.system.store.get(self.rid))],
    components=[discord.components.ActionRow(c) for c in TicketControls.from_row(self.system.store.get(self.rid)).to_components()])
  self.writes=[]
  async def edit(**kwargs):
   self.message.embeds=[kwargs['embed']]
   self.message.components=[discord.components.ActionRow(c) for c in kwargs['view'].to_components()]
   self.writes.append(self.displayed());return self.message
  self.edit=edit;self.message.edit=AsyncMock(side_effect=edit)
  self.channel.fetch_message=AsyncMock(return_value=self.message)
  self.system.sync_control_messages=AsyncMock()
  self.system.notify_urgent=AsyncMock(return_value=False)
 def displayed(self):return next(field.value for field in self.message.embeds[0].fields if field.name=='Prioridad')
 def response(self):return self.i.followup.send.call_args or self.i.response.send_message.call_args
 async def test_real_modal_payload_updates_existing_public_panel_and_verifies_readback(self):
  before_acl=self.raw()
  modal=PriorityForm(self.system,self.rid,'urgente')
  modal._refresh(self.i,[
    {'type':18,'component':{'type':3,'custom_id':'priority','values':['alta']}},
    {'type':18,'component':{'type':4,'custom_id':'priority_reason','value':'Ya no es urgente, pero necesita atención.'}},
  ],{})
  self.assertEqual(modal.priority.values,['alta'])
  await modal.on_submit(self.i)
  self.assertEqual(self.system.store.get(self.rid)['priority'],'alta');self.assertEqual(self.displayed(),'alta')
  self.assertEqual(self.system.store.config(f'priority-panel:{self.rid}'),'')
  self.assertGreaterEqual(self.channel.fetch_message.await_count,2)
  self.assertIn('**Alta**',self.response().args[0]);self.assertIn('panel ya está actualizado',self.response().args[0])
  self.assertTrue(self.response().kwargs['ephemeral']);self.assertEqual(self.raw(),before_acl)
  actions=[c.custom_id for group in self.message.components for c in group.children]
  self.assertIn(f'lv:ticket:case:{self.rid}:people',actions);self.assertNotIn(f'lv:ticket:case:{self.rid}:claim',actions)
  record=self.bot.changes.journal.rows()[0]
  old=json.loads(record['before_json'])['embeds'][0]['fields']
  self.assertEqual(next(f['value'] for f in old if f['name']=='Prioridad'),'urgente')
  self.assertEqual(record['status'],'completado')
 async def test_failed_edit_keeps_priority_and_pending_retry_survives_restart(self):
  self.message.edit.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
  with self.assertLogs('LaVenganzaRP.tickets',level='WARNING'):
   await self.system.change_priority(self.i,self.rid,'alta','Revisar hoy')
  self.assertEqual(self.system.store.get(self.rid)['priority'],'alta');self.assertEqual(self.displayed(),'urgente')
  self.assertIn('automáticamente',self.response().args[0]);self.assertNotIn('panel ya está actualizado',self.response().args[0])
  restart=TicketSystem(self.bot,self.system.store.path,10);restart.store.initialize()
  self.assertEqual(restart.store.config(f'priority-panel:{self.rid}'),'alta')
  restart.channel=AsyncMock(return_value=self.channel)
  for name in ('notify_urgent','escalate','notify_player','maintain_ticket'):setattr(restart,name,AsyncMock())
  self.message.edit.side_effect=self.edit
  await restart.maintenance()
  self.assertEqual(self.displayed(),'alta');self.assertEqual(restart.store.config(f'priority-panel:{self.rid}'),'')
  self.assertEqual(len([e for e in restart.store.events(self.rid) if e['action']=='prioridad']),1)
 async def test_unconfirmed_discord_readback_is_not_reported_as_updated(self):
  self.message.edit.side_effect=None;self.message.edit.return_value=self.message
  with self.assertLogs('LaVenganzaRP.tickets',level='WARNING'):
   await self.system.change_priority(self.i,self.rid,'alta','Revisar')
  self.assertEqual(self.displayed(),'urgente');self.assertEqual(self.system.store.config(f'priority-panel:{self.rid}'),'alta')
  self.assertNotIn('panel ya está actualizado',self.response().args[0])
 async def test_older_inflight_refresh_never_overwrites_newer_priority_or_responsible(self):
  reached=asyncio.Event();release=asyncio.Event();first=True
  async def channel(row):
   nonlocal first
   if first:
    first=False;reached.set();await release.wait()
   return self.channel
  self.system.channel=AsyncMock(side_effect=channel)
  old=asyncio.create_task(self.system.refresh(self.system.store.get(self.rid)))
  await reached.wait()
  self.system.store.set_priority(self.rid,'alta',5,'Revisar')
  newer=asyncio.create_task(self.system.change_priority(self.i,self.rid,'alta','Revisar'))
  release.set();await asyncio.gather(old,newer)
  self.assertTrue(self.writes);self.assertEqual(set(self.writes),{'alta'})
  self.assertEqual(self.system.store.get(self.rid)['assignee'],5)
 async def test_same_priority_still_repairs_a_stale_panel_without_duplicate_event(self):
  self.system.store.set_priority(self.rid,'alta',5,'Revisar')
  before=self.system.store.events(self.rid)
  await self.system.change_priority(self.i,self.rid,'alta','Sigue alta')
  self.assertEqual(self.displayed(),'alta');self.assertEqual(self.system.store.events(self.rid),before)
  self.assertEqual(self.system.store.config(f'priority-panel:{self.rid}'),'')
 async def test_acknowledging_old_priority_cannot_discard_newer_retry(self):
  self.system.store.set_priority(self.rid,'alta',5,'Revisar')
  self.system.store.set_priority(self.rid,'urgente',5,'Empeoró')
  self.assertFalse(self.system.store.acknowledge_priority_panel(self.rid,'alta'))
  restart=TicketStore(self.system.store.path);restart.initialize()
  self.assertEqual(restart.config(f'priority-panel:{self.rid}'),'urgente')
 async def test_requested_correction_is_backed_up_verified_and_never_repeated(self):
  with patch.multiple('ticket_priority_repair',GUILD_ID=10,BOT_ID=99,TICKET_ID=self.rid,CHANNEL_ID=100,REQUEST_CUTOFF=int(time.time())+60):
   await repair_requested_priority(self.system)
   self.assertEqual(self.system.store.get(self.rid)['priority'],'alta');self.assertEqual(self.displayed(),'alta')
   self.assertEqual(self.system.store.config(REQUEST_KEY),'complete')
   repair=next(r for r in self.bot.changes.journal.rows() if 'Corregir la prioridad' in r['title'])
   self.assertEqual(json.loads(repair['before_json'])['ticket']['priority'],'urgente')
   self.assertEqual(json.loads(repair['after_json'])['ticket']['priority'],'alta')
   await self.system.change_priority(self.i,self.rid,'normal','Ya puede esperar')
   count=self.message.edit.await_count
   await repair_requested_priority(self.system)
   self.assertEqual(self.system.store.get(self.rid)['priority'],'normal')
   self.assertEqual(self.message.edit.await_count,count)
 async def test_requested_correction_preserves_staff_changes_after_the_request_cutoff(self):
  self.system.store.set_priority(self.rid,'normal',5,'Revisado hace un momento')
  with patch.multiple('ticket_priority_repair',GUILD_ID=10,BOT_ID=99,TICKET_ID=self.rid,CHANNEL_ID=100,REQUEST_CUTOFF=int(time.time())-60):
   await repair_requested_priority(self.system)
  self.assertEqual(self.system.store.get(self.rid)['priority'],'normal');self.assertEqual(self.displayed(),'normal')
  self.assertEqual(self.system.store.config(REQUEST_KEY),'complete')
