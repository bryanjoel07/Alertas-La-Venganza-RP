import asyncio
import json
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,MagicMock,patch

import discord
from tickets import TicketSystem,HEAD_STAFF,ESCALATE_SECONDS,overnight,NIGHT_NOTICE
from tickets_store import TicketStore
from tickets_ui import RatingForm


def role(rid,name,admin=False,managed=False):
 return SimpleNamespace(id=rid,name=name,managed=managed,permissions=discord.Permissions(administrator=admin))


class FollowupTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.bot=MagicMock();self.bot.user.id=99
  self.system=TicketSystem(self.bot,Path(tmp.name)/'db.sqlite3',10);self.store=self.system.store;self.store.initialize()
  self.head=role(HEAD_STAFF,'Jefe de Staff');self.admin=role(1300627506801541230,'Programador',True)
  self.support=role(1300627732954349619,'Soporte');self.bot_role=role(999,'Bot',True,True)
  self.guild=SimpleNamespace(id=10,default_role=role(10,'@everyone'),roles=[self.head,self.admin,self.support,self.bot_role])
  self.owner=SimpleNamespace(id=1,bot=False,guild=self.guild,roles=[],guild_permissions=discord.Permissions(),send=AsyncMock(return_value=SimpleNamespace(id=600)))
  self.guild.get_member=lambda uid:self.owner if uid==1 else None
  self.guild.fetch_member=AsyncMock(return_value=None)
  self.rid=self.store.create(1,'soporte','Ayuda',{},now=1000)
  self.store.update(self.rid,status='nuevo',channel=100,control_message=500)
  self.channel=MagicMock(spec=discord.TextChannel);self.channel.id=100;self.channel.guild=self.guild;self.channel.topic=f'lv-ticket:{self.rid}'
  self.channel.permissions_for=lambda target:discord.Permissions(view_channel=target.id!=10)
  self.channel.send=AsyncMock(return_value=SimpleNamespace(id=700))
  self.bot.fetch_channel=AsyncMock(return_value=self.channel);self.bot.get_guild.return_value=self.guild
  self.i=MagicMock(user=self.owner,guild_id=10)
  self.i.response.is_done.return_value=False;self.i.response.defer=AsyncMock();self.i.response.send_message=AsyncMock()
  self.i.followup.send=AsyncMock();self.i.response.send_modal=AsyncMock()

 async def test_exactly_24_hours_claiming_and_bumping_do_not_delay_escalation(self):
  self.store.claim(self.rid,5)
  self.store.activity(self.rid,1,False,now=80000,message_id=1001)
  self.assertFalse(await self.system.escalate(self.rid,1000+ESCALATE_SECONDS-1))
  self.assertTrue(await self.system.escalate(self.rid,1000+ESCALATE_SECONDS))
  self.assertFalse(await self.system.escalate(self.rid,1000+2*ESCALATE_SECONDS))
  self.assertEqual(self.channel.send.await_count,1)
  args=self.channel.send.call_args
  self.assertIn(f'<@&{HEAD_STAFF}>',args.args[0]);self.assertNotIn('@everyone',args.args[0])
  mentions=args.kwargs['allowed_mentions']
  self.assertEqual([r.id for r in mentions.roles],[HEAD_STAFF]);self.assertFalse(mentions.users);self.assertFalse(mentions.everyone)
  restarted=TicketSystem(self.bot,self.store.path,10);restarted.store.initialize()
  self.assertFalse(await restarted.escalate(self.rid,1000+3*ESCALATE_SECONDS))

 async def test_another_unanswered_turn_can_escalate_after_staff_has_replied(self):
  await self.system.escalate(self.rid,87400)
  self.store.activity(self.rid,5,True,now=88000,message_id=1002)
  self.assertIsNone(self.store.get(self.rid)['staff_wait_since'])
  self.assertFalse(await self.system.escalate(self.rid,200000))
  self.store.activity(self.rid,1,False,now=200001,message_id=1003)
  self.store.activity(self.rid,1,False,now=200100,message_id=1004)
  self.assertEqual(self.store.get(self.rid)['staff_wait_since'],200001)
  self.assertTrue(await self.system.escalate(self.rid,200001+ESCALATE_SECONDS))
  self.assertEqual(self.channel.send.await_count,2)

 async def test_reserved_reports_only_notify_real_administrators(self):
  self.store.transfer(self.rid,'staff',self.admin.id,'Solo administradores')
  self.store.config('route:staff',json.dumps([HEAD_STAFF,self.support.id]))
  self.assertTrue(await self.system.escalate(self.rid,87400))
  args=self.channel.send.call_args
  self.assertEqual([r.id for r in args.kwargs['allowed_mentions'].roles],[self.admin.id])
  self.assertNotIn(str(HEAD_STAFF),args.args[0]);self.assertNotIn(str(self.support.id),args.args[0])
  self.assertNotIn(str(self.bot_role.id),args.args[0])

 async def test_waiting_resolved_closed_deleted_and_test_cases_are_not_escalated(self):
  for state in ('esperando_jugador','resuelto','cerrado'):
   self.store.transition(self.rid,state,5,'Ya se atendió')
   self.assertFalse(await self.system.escalate(self.rid,1000000))
  self.store.mark_deleted(self.rid,5)
  self.assertFalse(await self.system.escalate(self.rid,1000000))
  rid=self.store.create(2,'staff','Prueba',{'selftest':'hidden'},now=1000)
  self.store.update(rid,status='nuevo',channel=101)
  self.assertFalse(await self.system.escalate(rid,1000000))
  self.channel.send.assert_not_awaited()

 async def test_private_channel_and_staff_access_are_checked_before_alerting(self):
  self.channel.permissions_for=lambda target:discord.Permissions(view_channel=target.id not in (10,HEAD_STAFF))
  self.assertTrue(await self.system.escalate(self.rid,87400))
  self.assertEqual([r.id for r in self.channel.send.call_args.kwargs['allowed_mentions'].roles],[self.admin.id])
  with self.store.db() as db:db.execute('DELETE FROM lv_ticket_notices')
  self.channel.permissions_for=lambda target:discord.Permissions(view_channel=True)
  with self.assertRaisesRegex(ValueError,'privado'):await self.system.escalate(self.rid,87400)
  self.assertEqual(self.channel.send.await_count,1)

 async def test_failed_alert_is_retried_after_15_minutes_and_never_stops_other_tickets(self):
  self.channel.send.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'try later')
  with self.assertRaises(discord.HTTPException):await self.system.escalate(self.rid,87400)
  self.assertFalse(await self.system.escalate(self.rid,87401))
  self.channel.send.side_effect=None
  self.assertTrue(await self.system.escalate(self.rid,88300))
  other=self.store.create(2,'soporte','Otra ayuda',{},now=1000);self.store.update(other,status='nuevo',channel=101)
  self.system.escalate=AsyncMock(side_effect=[discord.NotFound(SimpleNamespace(status=404,reason='Missing'),'missing'),True])
  self.system.notify_player=AsyncMock();self.system.maintain_ticket=AsyncMock()
  with self.assertLogs('LaVenganzaRP.tickets',level='WARNING'):await self.system.maintenance()
  self.assertEqual(self.system.escalate.await_count,2);self.system.maintain_ticket.assert_awaited_once()

 async def test_claim_dm_is_once_and_reply_notices_are_coalesced_across_restarts(self):
  self.store.claim(self.rid,5)
  with patch('tickets.time.time',return_value=2000):
   self.assertTrue(await self.system.notify_player(self.rid,'claim'))
   self.assertFalse(await self.system.notify_player(self.rid,'claim'))
  self.assertIn('Ya están atendiendo',self.owner.send.call_args.args[0])
  self.assertIn('https://discord.com/channels/10/100/500',self.owner.send.call_args.args[0])
  self.store.activity(self.rid,5,True,now=2010,message_id=1001)
  with patch('tickets.time.time',return_value=2010):self.assertFalse(await self.system.notify_player(self.rid,'reply'))
  self.system=TicketSystem(self.bot,self.store.path,10);self.system.store.initialize()
  with patch('tickets.time.time',return_value=2900):self.assertTrue(await self.system.notify_player(self.rid,'reply'))
  self.assertIn('Te dejaron una respuesta',self.owner.send.call_args.args[0]);self.assertIn('/100/1001',self.owner.send.call_args.args[0])
  self.store.activity(self.rid,5,True,now=3000,message_id=1002)
  with patch('tickets.time.time',return_value=4000):self.assertFalse(await self.system.notify_player(self.rid,'reply'))
  self.store.activity(self.rid,1,False,now=4000,message_id=1003)
  self.store.activity(self.rid,5,True,now=4100,message_id=1004)
  with patch('tickets.time.time',return_value=4100):self.assertTrue(await self.system.notify_player(self.rid,'reply'))
  self.assertEqual(self.owner.send.await_count,3)

 async def test_reply_during_cooldown_is_delivered_later_unless_owner_already_replied(self):
  self.store.activity(self.rid,5,True,now=2000,message_id=1001)
  with patch('tickets.time.time',return_value=2000):await self.system.notify_player(self.rid,'reply')
  self.store.activity(self.rid,1,False,now=2100,message_id=1002)
  self.store.activity(self.rid,5,True,now=2200,message_id=1003)
  self.system.escalate=AsyncMock();self.system.maintain_ticket=AsyncMock()
  with patch('tickets.time.time',return_value=2300):await self.system.maintenance()
  self.assertEqual(self.owner.send.await_count,1)
  with patch('tickets.time.time',return_value=2900):await self.system.maintenance()
  self.assertEqual(self.owner.send.await_count,2)
  self.store.activity(self.rid,1,False,now=3000,message_id=1004)
  with patch('tickets.time.time',return_value=4000):await self.system.maintenance()
  self.assertEqual(self.owner.send.await_count,2)

 async def test_blocked_dms_and_transient_failures_do_not_break_ticket_actions(self):
  self.store.claim(self.rid,5)
  self.owner.send.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'DMs off')
  with patch('tickets.time.time',return_value=2000):self.assertFalse(await self.system.notify_player(self.rid,'claim'))
  with patch('tickets.time.time',return_value=4000):self.assertFalse(await self.system.notify_player(self.rid,'claim'))
  self.assertEqual(self.owner.send.await_count,1);self.assertEqual(self.store.get(self.rid)['assignee'],5)
  self.store.activity(self.rid,5,True,now=4000,message_id=1001)
  self.owner.send.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
  with patch('tickets.time.time',return_value=4000):self.assertFalse(await self.system.notify_player(self.rid,'reply'))
  with patch('tickets.time.time',return_value=4001):self.assertFalse(await self.system.notify_player(self.rid,'reply'))
  self.owner.send.side_effect=None
  with patch('tickets.time.time',return_value=4900):self.assertTrue(await self.system.notify_player(self.rid,'reply'))

 async def test_edits_are_archived_without_resetting_wait_or_sending_reply_alerts(self):
  author=SimpleNamespace(id=5,bot=False,roles=[self.support],guild_permissions=discord.Permissions())
  message=SimpleNamespace(id=1001,author=author,guild=self.guild,channel=self.channel,edited_at=datetime.now(timezone.utc))
  self.system.capture=AsyncMock();self.system.notify_player=AsyncMock()
  with patch.dict('os.environ',TICKETS_ENABLED='1'):await self.system.observe(message)
  self.assertEqual(self.store.get(self.rid)['staff_wait_since'],1000)
  self.system.notify_player.assert_not_awaited();self.system.capture.assert_awaited_once()

 async def test_live_staff_reply_clears_wait_and_notifies_but_owner_with_staff_role_is_player(self):
  self.system.capture=AsyncMock()
  author=SimpleNamespace(id=5,bot=False,roles=[self.support],guild_permissions=discord.Permissions())
  message=SimpleNamespace(id=1001,author=author,guild=self.guild,channel=self.channel,edited_at=None)
  with patch.dict('os.environ',TICKETS_ENABLED='1'),patch('tickets.time.time',return_value=2000):
   await self.system.observe(message)
  self.assertIsNone(self.store.get(self.rid)['staff_wait_since']);self.owner.send.assert_awaited_once()
  self.owner.roles=[self.support];message.author=self.owner;message.id=1002
  with patch.dict('os.environ',TICKETS_ENABLED='1'),patch('tickets.time.time',return_value=2100):
   await self.system.observe(message)
  self.assertEqual(self.store.get(self.rid)['staff_wait_since'],2100)
  self.assertEqual(self.store.get(self.rid)['last_owner_message'],1002);self.owner.send.assert_awaited_once()

 async def test_staff_solution_sent_from_button_also_notifies_the_player(self):
  self.i.user=SimpleNamespace(id=5,guild=self.guild,bot=False,roles=[self.support],guild_permissions=discord.Permissions())
  self.system.refresh=AsyncMock()
  await self.system.action(self.i,self.rid,'resolve')
  modal=self.i.response.send_modal.call_args.args[0];modal.value._value='Ya puedes entrar'
  with patch('tickets.time.time',return_value=2000):await modal.on_submit(self.i)
  self.assertEqual(self.store.get(self.rid)['status'],'resuelto')
  self.assertEqual(self.store.get(self.rid)['last_staff_message'],700)
  self.owner.send.assert_awaited_once();self.assertIn('/100/700',self.owner.send.call_args.args[0])

 async def test_rating_select_has_five_choices_optional_comment_and_accepts_no_comment(self):
  self.store.transition(self.rid,'cerrado',5,'Listo')
  await self.system.action(self.i,self.rid,'rate')
  modal=self.i.response.send_modal.call_args.args[0]
  payload=modal.to_dict()['components']
  self.assertEqual([o['value'] for o in payload[0]['component']['options']],['1','2','3','4','5'])
  self.assertFalse(payload[1]['component']['required'])
  modal.stars._values=['4'];modal.comment._value=''
  await modal.on_submit(self.i)
  self.assertEqual(self.store.get(self.rid)['rating'],4);self.assertEqual(self.store.get(self.rid)['rating_comment'],'')
  with self.assertRaisesRegex(ValueError,'Ya dejaste'):await self.system.action(self.i,self.rid,'rate')

 async def test_rating_submission_rechecks_owner_closed_state_deletion_and_score(self):
  self.store.transition(self.rid,'cerrado',5,'Listo')
  modal=RatingForm(self.system,self.rid);modal.stars._values=['5'];modal.comment._value='Bien'
  intruder=SimpleNamespace(id=5,guild=self.guild,roles=[self.support],guild_permissions=discord.Permissions())
  self.i.user=intruder;await modal.on_submit(self.i)
  self.assertIsNone(self.store.get(self.rid)['rating'])
  self.i.user=self.owner
  self.store.transition(self.rid,'en_atencion',5,'Reapertura: falta algo')
  await modal.on_submit(self.i);self.assertIsNone(self.store.get(self.rid)['rating'])
  self.store.transition(self.rid,'cerrado',5,'Arreglado');modal.stars._values=['6']
  await modal.on_submit(self.i);self.assertIsNone(self.store.get(self.rid)['rating'])
  modal.stars._values=['5'];self.store.mark_deleted(self.rid,5)
  await modal.on_submit(self.i);self.assertIsNone(self.store.get(self.rid)['rating'])

 async def test_upgrade_preserves_tickets_and_reconstructs_only_existing_pending_waits(self):
  self.store.activity(self.rid,5,True,now=2000,message_id=1001)
  pending=self.store.create(2,'soporte','Pendiente',{},now=1000);self.store.update(pending,status='nuevo',channel=101)
  waiting=self.store.create(3,'soporte','Esperando jugador',{},now=1000);self.store.update(waiting,status='nuevo',channel=102)
  self.store.transition(waiting,'esperando_jugador',5,'Adjunta pruebas')
  with self.store.db() as db:
   for col in ('staff_wait_since','last_owner_message','last_staff_message'):db.execute(f'ALTER TABLE lv_tickets DROP COLUMN {col}')
  self.store.initialize()
  self.assertIsNone(self.store.get(self.rid)['staff_wait_since'])
  self.assertEqual(self.store.get(pending)['staff_wait_since'],1000)
  self.assertIsNone(self.store.get(waiting)['staff_wait_since'])
  self.assertIsNone(self.store.get(self.rid)['last_staff_message'])
  self.assertEqual(len(self.store.list()),3)

 def use_staff(self,admin=False):
  self.i.user=SimpleNamespace(id=5,guild=self.guild,bot=False,roles=[self.admin if admin else self.support],guild_permissions=discord.Permissions(administrator=admin))
  self.system.refresh=AsyncMock()

 async def test_priority_button_alerts_immediately_and_not_again_for_the_same_urgent_period(self):
  self.use_staff()
  await self.system.action(self.i,self.rid,'priority')
  modal=self.i.response.send_modal.call_args.args[0];modal.value._value='urgente: Nadie puede entrar'
  with patch('tickets.time.time',return_value=2000):await modal.on_submit(self.i)
  self.assertEqual(self.store.get(self.rid)['priority'],'urgente')
  self.channel.send.assert_awaited_once()
  args=self.channel.send.call_args
  self.assertIn('urgente',args.args[0]);self.assertIn('Nadie puede entrar',args.args[0]);self.assertNotIn('@everyone',args.args[0])
  self.assertEqual([r.id for r in args.kwargs['allowed_mentions'].roles],[HEAD_STAFF])
  with patch('tickets.time.time',return_value=2100):await modal.on_submit(self.i)
  self.channel.send.assert_awaited_once()
  self.assertEqual(len([e for e in self.store.events(self.rid) if e['action']=='prioridad']),1)
  restarted=TicketSystem(self.bot,self.store.path,10);restarted.store.initialize()
  self.assertFalse(await restarted.notify_urgent(self.rid,3000))
  with patch('tickets.time.time',return_value=4000):
   await self.system.change_priority(self.i,self.rid,'alta','Se puede entrar de nuevo')
   await self.system.change_priority(self.i,self.rid,'urgente','Volvió el problema')
  self.assertEqual(self.channel.send.await_count,2)

 async def test_reserved_urgent_alert_only_mentions_actual_administrators(self):
  self.store.transfer(self.rid,'staff',self.admin.id,'Solo administradores')
  self.store.config('route:staff',json.dumps([HEAD_STAFF,self.support.id]))
  self.use_staff(admin=True)
  with patch('tickets.time.time',return_value=2000):await self.system.change_priority(self.i,self.rid,'urgente','Revisar hoy')
  args=self.channel.send.call_args
  self.assertEqual([r.id for r in args.kwargs['allowed_mentions'].roles],[self.admin.id])
  self.assertNotIn(str(HEAD_STAFF),args.args[0]);self.assertFalse(args.kwargs['allowed_mentions'].everyone)

 async def test_priority_submission_rechecks_permissions_and_closed_state(self):
  self.use_staff();await self.system.action(self.i,self.rid,'priority')
  modal=self.i.response.send_modal.call_args.args[0];modal.value._value='urgente: Revisar'
  self.i.user=self.owner
  await modal.on_submit(self.i)
  self.assertEqual(self.store.get(self.rid)['priority'],'normal');self.channel.send.assert_not_awaited()
  self.use_staff();self.store.transition(self.rid,'cerrado',5,'Ya está')
  await modal.on_submit(self.i)
  self.assertEqual(self.store.get(self.rid)['priority'],'normal');self.channel.send.assert_not_awaited()
  self.system.refresh.assert_not_awaited()

 async def test_urgent_failure_keeps_priority_and_maintenance_retries_without_waiting_24_hours(self):
  self.use_staff()
  self.channel.send.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
  with patch('tickets.time.time',return_value=2000),self.assertLogs('LaVenganzaRP.tickets',level='WARNING'):
   await self.system.change_priority(self.i,self.rid,'urgente','No carga')
  self.assertEqual(self.store.get(self.rid)['priority'],'urgente')
  self.assertEqual(self.store.notice(self.rid,'urgent')['state'],'failed')
  self.assertIn('volveré a intentarlo',self.i.response.send_message.call_args.args[0])
  self.channel.send.side_effect=None
  self.system.maintain_ticket=AsyncMock()
  with patch('tickets.time.time',return_value=2001):await self.system.maintenance()
  self.assertEqual(self.channel.send.await_count,1)
  with patch('tickets.time.time',return_value=2900):await self.system.maintenance()
  self.assertEqual(self.channel.send.await_count,2);self.assertEqual(self.store.notice(self.rid,'urgent')['state'],'sent')

 async def test_parallel_urgent_changes_send_one_alert_with_priority_durably_saved_first(self):
  self.use_staff()
  async def send(*args,**kwargs):
   self.assertEqual(self.store.get(self.rid)['priority'],'urgente')
   self.assertEqual(self.store.priority_event(self.rid)['actor'],5)
   return SimpleNamespace(id=700)
  self.channel.send.side_effect=send
  with patch('tickets.time.time',return_value=2000):
   await asyncio.gather(self.system.change_priority(self.i,self.rid,'urgente','Revisar'),self.system.change_priority(self.i,self.rid,'urgente','Revisar'))
  self.channel.send.assert_awaited_once()

 async def test_urgent_notice_avoids_simultaneous_24_hour_ping_but_keeps_later_reminder(self):
  self.use_staff();self.system.maintain_ticket=AsyncMock()
  with patch('tickets.time.time',return_value=87400):
   await self.system.change_priority(self.i,self.rid,'urgente','Pendiente')
   await self.system.maintenance()
  self.assertEqual(self.channel.send.await_count,1)
  with patch('tickets.time.time',return_value=88300):await self.system.maintenance()
  self.assertEqual(self.channel.send.await_count,2)
  self.assertIn('24 horas',self.channel.send.call_args.args[0])

 async def test_waiting_player_can_be_marked_urgent_but_closed_deleted_tests_cannot_notify(self):
  self.use_staff();self.store.transition(self.rid,'esperando_jugador',5,'Pruebas')
  with patch('tickets.time.time',return_value=2000):await self.system.change_priority(self.i,self.rid,'urgente','Revisar antes')
  self.channel.send.assert_awaited_once()
  self.store.transition(self.rid,'cerrado',5,'Solucionado');self.store.mark_deleted(self.rid,5)
  self.assertFalse(await self.system.notify_urgent(self.rid,3000))
  rid=self.store.create(2,'staff','Prueba',{'selftest':'hidden'},now=1000)
  self.store.update(rid,status='nuevo',channel=101)
  self.store.set_priority(rid,'urgente',5,'Prueba')
  self.assertFalse(await self.system.notify_urgent(rid,3000));self.channel.send.assert_awaited_once()


class OvernightTests(unittest.TestCase):
 def test_puerto_rico_boundaries_even_when_utc_date_differs(self):
  def stamp(value):return datetime.fromisoformat(value).timestamp()
  self.assertFalse(overnight(stamp('2026-11-09T03:59:59+00:00')))
  self.assertTrue(overnight(stamp('2026-11-09T04:00:00+00:00')))
  self.assertTrue(overnight(stamp('2026-11-09T11:59:59+00:00')))
  self.assertFalse(overnight(stamp('2026-11-09T12:00:00+00:00')))
  self.assertIn('Recibimos tu ticket, bro',NIGHT_NOTICE)

