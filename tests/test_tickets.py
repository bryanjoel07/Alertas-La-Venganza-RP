import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from tickets_store import TicketStore,PROTECTED,NORMAL_STAFF
from tickets import TicketSystem,can_staff,channel_overwrites,transcript_html
from tickets_ui import TicketControls,TicketPanel,TicketAction

class FakeRole:
 def __init__(self,rid):self.id=rid
class FakeMember:
 def __init__(self,uid,roles=(),admin=False,guild=None):
  self.id=uid;self.roles=[FakeRole(r) for r in roles];self.guild_permissions=discord.Permissions(administrator=admin)
  self.guild=guild or SimpleNamespace(id=10);self.bot=False

class TicketStoreTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  self.store=TicketStore(Path(temp.name)/'db.sqlite3');self.store.initialize()
 def create(self,user=1,department='soporte',now=1000):return self.store.create(user,department,'Problema',{'detalles':'Necesito ayuda'},now=now)
 def active(self,user=1,department='soporte',now=1000):
  rid=self.create(user,department,now);self.store.update(rid,channel=rid+100,status='nuevo');return rid
 def test_duplicate_creation_is_atomic_across_connections(self):
  def opening(_):
   try:return self.create()
   except ValueError:return None
  with ThreadPoolExecutor(max_workers=5) as pool:result=list(pool.map(opening,range(5)))
  self.assertEqual(sum(r is not None for r in result),1)
  self.assertEqual(len(self.store.list()),1)
 def test_limits_cooldown_and_reopen_do_not_bypass_duplicates(self):
  a=self.active()
  with self.assertRaisesRegex(ValueError,'minuto'):self.create(department='tienda',now=1010)
  self.active(department='tienda',now=1061);self.active(department='apelacion',now=1122)
  with self.assertRaisesRegex(ValueError,'hasta'):self.create(department='donacion',now=1183)
  self.store.transition(a,'cerrado',5,'Caso resuelto')
  newer=self.active(department='soporte',now=1183)
  with self.assertRaises(ValueError):self.store.transition(a,'en_atencion',5,'Reapertura: vuelve a ocurrir')
  self.assertEqual(self.store.get(a)['status'],'cerrado')
  self.assertNotEqual(newer,a)
 def test_claim_race_has_one_responsible(self):
  rid=self.active()
  def claim(uid):
   try:self.store.claim(rid,uid);return uid
   except ValueError:return None
  with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(claim,(5,6)))
  self.assertEqual(sum(v is not None for v in result),1)
  self.assertIn(self.store.get(rid)['assignee'],(5,6))
 def test_waiting_reply_cancels_close_warning_and_first_response_is_stable(self):
  rid=self.active();self.store.transition(rid,'esperando_jugador',5,'Adjunta pruebas')
  self.store.update(rid,warning_at=2000)
  self.store.activity(rid,5,True,2100);self.store.activity(rid,5,True,2200)
  self.assertEqual(self.store.get(rid)['first_response'],2100)
  self.store.activity(rid,1,False,2300)
  row=self.store.get(rid)
  self.assertEqual(row['status'],'en_atencion');self.assertIsNone(row['warning_at'])
 def test_reserved_cases_cannot_be_declassified_and_rating_is_owner_only_once(self):
  rid=self.active(department='staff')
  with self.assertRaisesRegex(ValueError,'reservado'):self.store.transfer(rid,'soporte',5,'Transferir')
  self.store.transition(rid,'cerrado',5,'Resuelto')
  with self.assertRaises(ValueError):self.store.rate(rid,99,5,'Excelente')
  self.store.rate(rid,1,4,'Buena atención')
  with self.assertRaisesRegex(ValueError,'Ya valoraste'):self.store.rate(rid,1,1,'Otra')
 def test_proofs_survive_restart_and_limits_are_transactional(self):
  rid=self.active();self.store.file(rid,100,200,'prueba.txt','https://cdn.discordapp.com/test',5)
  self.store.save_blob(rid,200,b'proof')
  fresh=TicketStore(self.store.path);fresh.initialize()
  self.assertEqual(fresh.blob(rid,200),b'proof')
  self.assertEqual(fresh.files(rid)[0]['state'],'guardado')
  saved_hash=fresh.files(rid)[0]['sha256']
  fresh.file(rid,100,200,'prueba.txt','https://cdn.discordapp.com/test',5,state='pendiente')
  self.assertEqual(fresh.files(rid)[0]['state'],'guardado')
  self.assertEqual(fresh.files(rid)[0]['sha256'],saved_hash)
  fresh.config('max_file_mb',0)
  fresh.save_blob(rid,200,b'proof') # already saved: no duplicate growth
  fresh.file(rid,101,201,'otro.txt','https://cdn.discordapp.com/other',5)
  with self.assertRaises(ValueError):fresh.save_blob(rid,201,b'other')
  self.assertIsNone(fresh.blob(rid,201))
 def test_edit_and_delete_history_survives_and_html_is_escaped(self):
  rid=self.active()
  msg=SimpleNamespace(id=100,author=SimpleNamespace(id=1,display_name='<script>alert(1)</script>'),
     content='original',embeds=[],created_at=datetime.now(timezone.utc),edited_at=None)
  self.store.message(rid,msg);msg.content='<img src=x onerror=evil()>';msg.edited_at=datetime.now(timezone.utc)
  self.store.message(rid,msg);self.store.deleted(101,100)
  self.store.note(rid,5,'NOTA_INTERNA_SECRETA')
  messages=self.store.messages(rid)
  self.assertEqual(len(messages),2);self.assertTrue(all(m['deleted'] for m in messages))
  text=transcript_html(self.store.get(rid),messages,[])
  self.assertIn('original',text);self.assertNotIn('<script>',text);self.assertNotIn('<img',text)
  self.assertNotIn('NOTA_INTERNA_SECRETA',text)

class PrivacyTests(unittest.TestCase):
 setUp=TicketStoreTests.setUp
 create=TicketStoreTests.create
 active=TicketStoreTests.active
 def test_permissions_and_api_checks_reserve_staff_reports(self):
  system=TicketSystem(MagicMock(),self.store.path,10);system.store=self.store
  rid=self.active(department='staff');row=self.store.get(rid)
  owner=FakeMember(1,roles=NORMAL_STAFF)
  support=FakeMember(2,roles=NORMAL_STAFF)
  admin=FakeMember(3,admin=True)
  self.assertFalse(can_staff(support,row,self.store));self.assertTrue(can_staff(admin,row,self.store))
  self.store.participant(rid,2,3)
  with self.assertRaisesRegex(ValueError,'reservado'):system.authorize(support,row)
  system.authorize(owner,row);system.authorize(admin,row,True)
  with self.assertRaises(ValueError):system.authorize(owner,row,True)
 def test_channel_overwrites_never_edit_protected_roles_or_grant_citizens(self):
  rid=self.active();row=self.store.get(rid)
  guild=SimpleNamespace(default_role=FakeRole(10),me=FakeMember(99,admin=True),roles=[FakeRole(r) for r in PROTECTED|NORMAL_STAFF])
  perms=channel_overwrites(guild,row,self.store,FakeMember(1))
  self.assertFalse(perms[guild.default_role].view_channel)
  self.assertFalse(PROTECTED&{target.id for target in perms if isinstance(target,FakeRole)})
  self.assertTrue(all(not p.create_public_threads for p in perms.values()))
  row['status']='cerrado';perms=channel_overwrites(guild,row,self.store,FakeMember(1))
  self.assertTrue(all(not value.send_messages for target,value in perms.items() if target.id!=99))
 def test_reported_staff_cannot_claim_or_read_case(self):
  rid=self.store.create(1,'jugador','Reporte',{},excluded=2,now=1000)
  row=self.store.get(rid);member=FakeMember(2,roles=NORMAL_STAFF)
  self.assertFalse(can_staff(member,row,self.store))
  system=TicketSystem(MagicMock(),self.store.path,10);system.store=self.store
  with self.assertRaises(ValueError):system.authorize(member,row)

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.bot=MagicMock();self.system=TicketSystem(self.bot,Path(tmp.name)/'db.sqlite3',10)
  self.system.store.initialize()
  self.guild=SimpleNamespace(id=10)
  self.owner=FakeMember(1,guild=self.guild);self.staff=FakeMember(5,roles=NORMAL_STAFF,guild=self.guild)
  self.i=MagicMock(user=self.owner,guild_id=10)
  self.i.response.is_done.return_value=False;self.i.response.defer=AsyncMock();self.i.response.send_message=AsyncMock();self.i.followup.send=AsyncMock()
  self.rid=self.system.store.create(1,'soporte','Ayuda',{},now=1000)
  self.system.store.update(self.rid,status='nuevo',channel=100)
 async def test_buttons_are_persistent_and_all_routes_have_unique_ids(self):
  view=TicketControls(self.rid)
  self.assertTrue(view.is_persistent());self.assertEqual(len(view.children),12)
  ids=[c.custom_id for c in view.children];self.assertEqual(len(set(ids)),12)
  self.assertTrue(TicketPanel(self.system).is_persistent())
  for custom in ids:
   match=TicketAction.__discord_ui_compiled_template__.fullmatch(custom)
   rebuilt=await TicketAction.from_custom_id(self.i,None,match)
   self.assertEqual(rebuilt.rid,self.rid)
 async def test_unauthorized_note_or_export_has_no_side_effects(self):
  row=self.system.store.get(self.rid)
  with self.assertRaises(ValueError):await self.system.action(self.i,self.rid,'note')
  self.assertFalse(self.system.store.events(self.rid,notes=True))
  self.i.user=FakeMember(77,guild=self.guild)
  self.system.archive=AsyncMock()
  with self.assertRaises(ValueError):await self.system.export(self.i,row)
  self.system.archive.assert_not_awaited()
 async def test_waiting_inactivity_warns_before_closing_and_human_reply_prevents_it(self):
  self.system.store.transition(self.rid,'esperando_jugador',5,'Pruebas')
  with self.system.store.db() as db:db.execute('UPDATE lv_tickets SET updated=1,last_user=1,last_staff=1 WHERE id=?',(self.rid,))
  channel=MagicMock();channel.send=AsyncMock()
  self.system.channel=AsyncMock(return_value=channel);self.system.close=AsyncMock()
  with patch('tickets.time.time',return_value=500000):await self.system.maintenance()
  self.system.close.assert_not_awaited();self.assertEqual(self.system.store.get(self.rid)['warning_at'],500000)
  self.system.store.activity(self.rid,1,False,500100)
  with patch('tickets.time.time',return_value=600000):await self.system.maintenance()
  self.system.close.assert_not_awaited()
 async def test_purchase_link_rejects_other_users_receipt_before_creating_ticket(self):
  self.bot.economy.store.rows.return_value=[]
  self.i.user=FakeMember(7,guild=self.guild)
  with patch.dict('os.environ',TICKETS_ENABLED='1'):
   with self.assertRaisesRegex(ValueError,'pertenece'):await self.system.open(self.i,'tienda','Otra compra',{},purchase='someone-else')
  self.assertFalse(self.system.store.list(owner=7))
 async def test_authorized_claim_does_not_edit_any_role(self):
  self.i.user=self.staff
  self.system.access=AsyncMock();self.system.refresh=AsyncMock()
  await self.system.action(self.i,self.rid,'claim')
  self.assertEqual(self.system.store.get(self.rid)['assignee'],5)
  self.system.access.assert_awaited_once()
  self.bot.get_guild.return_value.edit_role_positions.assert_not_called()

 async def test_reserved_transfer_removes_former_participant_api_access(self):
  self.system.store.participant(self.rid,7,5)
  former=FakeMember(7,guild=self.guild)
  self.system.authorize(former,self.system.store.get(self.rid))
  self.system.store.transfer(self.rid,'staff',5,'Escalar a administradores')
  with self.assertRaisesRegex(ValueError,'reservado'):self.system.authorize(former,self.system.store.get(self.rid))
  with self.assertRaisesRegex(ValueError,'reservado'):self.system.authorize(self.staff,self.system.store.get(self.rid))

 async def test_scoped_journal_durably_precedes_permission_mutation(self):
  from change_log import ChangeLog
  service=ChangeLog(self.bot,self.system.store.path,10);service.journal.initialize()
  self.bot.changes=service
  self.system.snapshot=AsyncMock(side_effect=[{'permissions':'before'},{'permissions':'after'}])
  async def operation():
   rows=service.journal.rows()
   self.assertEqual(rows[0]['status'],'iniciado')
   self.assertEqual(json.loads(rows[0]['before_json']),{'permissions':'before'})
  await self.system.tracked(self.system.store.get(self.rid),'Cambiar accesos',operation)
  self.assertEqual(service.journal.rows()[0]['status'],'completado')

 async def test_archive_preserves_deleted_messages_and_excludes_notes(self):
  row=self.system.store.get(self.rid)
  msg=SimpleNamespace(id=101,author=SimpleNamespace(id=1,display_name='Jugador'),content='PRUEBA_ORIGINAL',embeds=[],attachments=[],created_at=datetime.now(timezone.utc),edited_at=None)
  self.system.store.message(self.rid,msg);self.system.store.deleted(100,101)
  self.system.store.note(self.rid,5,'NOTA_QUE_NO_PUEDE_SALIR')
  channel=MagicMock()
  async def history(**kwargs):
   if False:yield None
  channel.history=history;self.system.channel=AsyncMock(return_value=channel)
  self.assertEqual(await self.system.archive(row),'completo')
  archived=self.system.store.get(self.rid)['transcript']
  self.assertIn('PRUEBA_ORIGINAL',archived);self.assertIn('ELIMINADO',archived)
  self.assertNotIn('NOTA_QUE_NO_PUEDE_SALIR',archived)

 async def test_category_position_only_edit_can_return_none_without_losing_created_id(self):
  active=MagicMock(spec=discord.CategoryChannel);active.id=50;active.name='Tickets';active.position=5;active.category_id=None
  created=MagicMock(spec=discord.CategoryChannel);created.id=51;created.name='Cerrados';created.position=99
  created.edit=AsyncMock(return_value=None)
  guild=MagicMock();guild.fetch_channels=AsyncMock(return_value=[active]);guild.create_category=AsyncMock(return_value=created)
  self.system.store.config('active_category',50)
  self.bot.fetch_channel=AsyncMock(return_value=created)
  async def tracked(env,title,operation,**kwargs):return await operation()
  self.bot.changes.tracked=tracked
  result=await self.system.ensure_category(guild,True)
  self.assertEqual(result.id,51)
  self.assertEqual(self.system.store.config('closed_category'),'51')
  created.edit.assert_awaited_once()

 async def test_attachment_uses_original_url_and_falls_back_to_cache(self):
  missing=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),'missing')
  attachment=SimpleNamespace(id=900,filename='proof.txt',url='https://cdn.discordapp.com/proof',size=5,
      read=AsyncMock(side_effect=[missing,b'proof']))
  message=SimpleNamespace(id=902,author=SimpleNamespace(id=1,display_name='Jugador'),content='Prueba',embeds=[],
      attachments=[attachment],created_at=datetime.now(timezone.utc),edited_at=None)
  await self.system.capture(self.system.store.get(self.rid),message,notify=False)
  self.assertEqual(self.system.store.blob(self.rid,900),b'proof')
  self.assertEqual(attachment.read.await_args_list[0].kwargs,{})
  self.assertEqual(attachment.read.await_args_list[1].kwargs,{'use_cached':True})

 async def test_closed_shortcut_filters_other_players_and_reserved_cases(self):
  self.system.store.transition(self.rid,'cerrado',5,'Resuelto')
  other=self.system.store.create(8,'soporte','Otro caso',{},now=1000)
  self.system.store.update(other,status='nuevo',channel=101)
  self.system.store.transition(other,'cerrado',5,'Privado')
  reserved=self.system.store.create(9,'staff','Reservado',{},now=1000)
  self.system.store.update(reserved,status='nuevo',channel=102)
  self.system.store.transition(reserved,'cerrado',3,'Reservado')
  await self.system.show_closed(self.i)
  body=self.i.response.send_message.call_args.kwargs['embed'].description
  self.assertIn(f'**#{self.rid}**',body);self.assertNotIn(f'**#{other}**',body);self.assertNotIn(f'**#{reserved}**',body)
  self.i.user=self.staff
  await self.system.show_closed(self.i)
  body=self.i.response.send_message.call_args.kwargs['embed'].description
  self.assertIn(f'**#{other}**',body);self.assertNotIn(f'**#{reserved}**',body)
  panel=TicketPanel(self.system)
  self.assertIn('lv:ticket:closed',[item.custom_id for item in panel.children])

 async def prepare_deletion(self):
  self.system.store.transition(self.rid,'cerrado',5,'Resuelto')
  self.system.store.update(self.rid,transcript='<html>CONVERSACION_GUARDADA</html>',archive_state='completo')
  self.system.archive=AsyncMock(return_value='completo')
  channel=MagicMock();channel.delete=AsyncMock()
  self.system.channel=AsyncMock(return_value=channel)
  self.bot.backups.enabled=True;self.bot.backups.execute=AsyncMock(return_value={'restore_state':'verified'})
  async def tracked(row,title,operation):return await operation()
  self.system.tracked=tracked
  return channel

 async def test_delete_only_after_close_staff_confirmation_and_verified_backup(self):
  channel=await self.prepare_deletion()
  self.system.store.file(self.rid,1,2,'proof.txt','https://cdn.discordapp.com/test',5)
  self.system.store.save_blob(self.rid,2,b'proof')
  order=[]
  async def backup():order.append('backup');return {'restore_state':'verified'}
  async def delete(**kwargs):order.append('delete')
  self.bot.backups.execute.side_effect=backup;channel.delete.side_effect=delete
  self.assertTrue(await self.system.delete_ticket(self.staff,self.rid))
  self.assertEqual(order,['backup','delete'])
  archived=self.system.store.get(self.rid)
  self.assertTrue(archived['deleted_at']);self.assertEqual(archived['deletion_actor'],5)
  self.assertIn('CONVERSACION_GUARDADA',archived['transcript'])
  self.assertEqual(self.system.store.blob(self.rid,2),b'proof')
  self.assertFalse(await self.system.delete_ticket(self.staff,self.rid))
  channel.delete.assert_awaited_once()
  self.i.user=self.owner
  await self.system.export(self.i,archived)
  self.assertIn('CONVERSACION_GUARDADA',self.i.response.send_message.call_args.kwargs['file'].fp.read().decode())
  self.assertEqual(self.system.archive.await_count,2) # Export after deletion never fetches the vanished channel.
  with self.assertRaisesRegex(ValueError,'eliminado'):self.system.store.transition(self.rid,'en_atencion',5,'Reabrir')

 async def test_delete_blocks_open_unauthorized_and_incomplete_backup(self):
  channel=await self.prepare_deletion()
  with self.assertRaises(ValueError):await self.system.delete_ticket(self.owner,self.rid)
  self.system.store.transition(self.rid,'en_atencion',5,'Reapertura: revisar')
  with self.assertRaisesRegex(ValueError,'cerrados'):await self.system.delete_ticket(self.staff,self.rid)
  self.system.store.transition(self.rid,'cerrado',5,'Resuelto de nuevo')
  self.system.archive.return_value='parcial'
  with self.assertRaisesRegex(ValueError,'No se elimina'):await self.system.delete_ticket(self.staff,self.rid)
  self.system.archive.return_value='completo'
  self.bot.backups.execute.return_value={'restore_state':'failed'}
  with self.assertRaisesRegex(ValueError,'respaldo externo'):await self.system.delete_ticket(self.staff,self.rid)
  channel.delete.assert_not_awaited();self.assertIsNone(self.system.store.get(self.rid)['deleted_at'])

 async def test_delete_refuses_corrupted_or_missing_proof(self):
  channel=await self.prepare_deletion()
  self.system.store.file(self.rid,1,2,'proof.txt','https://cdn.discordapp.com/test',5,state='guardado',sha='invalid')
  with self.assertRaisesRegex(ValueError,'íntegra'):await self.system.delete_ticket(self.staff,self.rid)
  channel.delete.assert_not_awaited();self.bot.backups.execute.assert_not_awaited()

 async def test_delete_button_only_on_closed_and_opening_confirmation_does_not_delete(self):
  self.assertNotIn('lv:ticket:case:1:delete',[c.custom_id for c in TicketControls(1).children])
  self.assertIn('lv:ticket:case:1:delete',[c.custom_id for c in TicketControls(1,True).children])
  self.assertNotIn('lv:ticket:case:1:delete',[c.custom_id for c in TicketControls(1,True,True).children])
  await self.prepare_deletion();self.i.user=self.staff
  self.system.delete_ticket=AsyncMock()
  await self.system.action(self.i,self.rid,'delete')
  confirmation=self.i.response.send_message.call_args.kwargs['view']
  self.system.delete_ticket.assert_not_awaited()
  self.i.response.edit_message=AsyncMock()
  await confirmation.cancel.callback(self.i)
  self.system.delete_ticket.assert_not_awaited()

 async def test_delete_confirmation_rechecks_reopened_case(self):
  channel=await self.prepare_deletion();self.i.user=self.staff
  await self.system.action(self.i,self.rid,'delete')
  confirm=self.i.response.send_message.call_args.kwargs['view']
  self.system.store.transition(self.rid,'en_atencion',5,'Reapertura: todavía pendiente')
  self.i.response.edit_message=AsyncMock()
  await confirm.confirm.callback(self.i)
  channel.delete.assert_not_awaited()

 async def test_recovery_reconciles_confirmed_delete_without_repeating_delete_request(self):
  await self.prepare_deletion()
  self.system.store.update(self.rid,deletion_requested=123,deletion_actor=5)
  guild=self.bot.get_guild.return_value;guild.fetch_channels=AsyncMock(return_value=[])
  self.system.channel=AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),'missing'))
  await self.system.recover(self.rid)
  self.assertTrue(self.system.store.get(self.rid)['deleted_at'])
  self.assertIn('CONVERSACION_GUARDADA',self.system.store.get(self.rid)['transcript'])

 async def test_deletion_columns_upgrade_existing_tickets_without_losing_history(self):
  self.system.store.note(self.rid,5,'Nota conservada')
  with self.system.store.db() as db:
   for column in ('deleted_at','deletion_requested','deletion_actor'):
    db.execute(f'ALTER TABLE lv_tickets DROP COLUMN {column}')
  self.system.store.initialize()
  row=self.system.store.get(self.rid)
  self.assertEqual(row['owner'],1);self.assertIsNone(row['deleted_at'])
  self.assertEqual(self.system.store.events(self.rid,notes=True)[0]['text'],'Nota conservada')


 async def test_new_messages_during_backup_prevent_deletion_until_confirmed_again(self):
  channel=await self.prepare_deletion()
  async def archive(row):
   if self.system.archive.await_count==2:
    self.system.store.update(self.rid,transcript='<html>MENSAJE_NUEVO</html>')
   return 'completo'
  self.system.archive.side_effect=archive
  with self.assertRaisesRegex(ValueError,'cambió durante'):await self.system.delete_ticket(self.staff,self.rid)
  channel.delete.assert_not_awaited()
  self.assertIsNone(self.system.store.get(self.rid)['deleted_at'])

 async def test_closed_visibility_includes_requested_ranks_but_not_reserved_reports(self):
  from tickets import closed_staff_roles
  roles=[FakeRole(rid) for rid in PROTECTED|NORMAL_STAFF]
  head=FakeRole(123);head.name='🔱┊𝐉𝐞𝐟𝐞 𝐃𝐞 𝐀𝐝𝐦𝐢𝐧';roles.append(head)
  guild=SimpleNamespace(default_role=FakeRole(10),me=FakeMember(99,admin=True),roles=roles)
  row=self.system.store.get(self.rid);row['status']='cerrado'
  permissions=channel_overwrites(guild,row,self.system.store,self.owner)
  for role in closed_staff_roles(guild):
   self.assertTrue(permissions[role].view_channel);self.assertTrue(permissions[role].read_message_history)
  row['department']='staff'
  reserved=channel_overwrites(guild,row,self.system.store,self.owner)
  self.assertTrue(all(role not in reserved for role in closed_staff_roles(guild)))
