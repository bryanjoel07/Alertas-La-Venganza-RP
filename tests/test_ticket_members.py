import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock

import discord

from change_log import ChangeLog
from photo_members import DirectoryUnavailable
from ticket_members import TicketMemberPicker,TicketMemberSearch
from tickets import TicketSystem,channel_overwrites
from tickets_store import NORMAL_STAFF,PROTECTED,TicketStore
from tickets_ui import TicketControls
from test_tickets import FakeMember,FakeRole


class TicketMemberTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.bot=MagicMock();self.bot.user.id=99
  self.system=TicketSystem(self.bot,Path(tmp.name)/'db.sqlite3',10);self.system.store.initialize()
  self.guild=SimpleNamespace(id=10,default_role=FakeRole(10),me=FakeMember(99,admin=True),
    roles=[FakeRole(r) for r in PROTECTED|NORMAL_STAFF])
  self.bot.get_guild.return_value=self.guild
  self.staff=self.member(5,roles=NORMAL_STAFF);self.guest=self.member(7)
  self.members={5:self.staff,7:self.guest}
  async def fetch(uid):
   if uid not in self.members:raise discord.NotFound(SimpleNamespace(status=404,reason='Missing'),'missing')
   return self.members[uid]
  self.guild.fetch_member=AsyncMock(side_effect=fetch)
  self.i=MagicMock(user=self.staff,guild_id=10,guild=self.guild)
  self.i.response.is_done.return_value=False
  self.i.response.send_message=AsyncMock();self.i.response.edit_message=AsyncMock()
  self.i.response.defer=AsyncMock();self.i.followup.send=AsyncMock();self.i.edit_original_response=AsyncMock()
  self.rid=self.system.store.create(1,'soporte','Ayuda',{},now=1000)
  self.system.store.update(self.rid,status='nuevo',channel=100)
  self.unrelated=self.member(88)
  self.overwrites={self.guild.default_role:discord.PermissionOverwrite(view_channel=False),
    self.unrelated:discord.PermissionOverwrite(view_channel=True,manage_messages=False),
    self.guest:discord.PermissionOverwrite(manage_messages=False,add_reactions=True)}
  for role in self.guild.roles:self.overwrites[role]=discord.PermissionOverwrite(read_message_history=True)
  self.channel=SimpleNamespace(id=100,category_id=50,overwrites=self.overwrites)
  def get_overwrite(member):return discord.PermissionOverwrite.from_pair(*self.overwrites.get(member,discord.PermissionOverwrite()).pair())
  self.channel.overwrites_for=get_overwrite
  def effective(member):
   if member.guild_permissions.administrator:return discord.Permissions.all()
   return get_overwrite(member).pair()[0]
  self.channel.permissions_for=effective
  async def grant(member,overwrite,reason):
   # The durable journal must contain the exact before-state before the first Discord write.
   record=self.bot.changes.journal.rows()[0]
   self.assertEqual(json.loads(record['before_json'])['participants'],self.system.store.people(self.rid))
   self.overwrites[member]=overwrite;self.update_raw()
  self.channel.set_permissions=AsyncMock(side_effect=grant)
  self.system.channel=AsyncMock(return_value=self.channel)
  self.bot.changes=ChangeLog(self.bot,self.system.store.path,10);self.bot.changes.journal.initialize()
  self.update_raw()
 def member(self,uid,roles=(),admin=False):
  member=FakeMember(uid,roles=roles,admin=admin,guild=self.guild)
  member.name=f'jugador{uid}';member.display_name=f'Jugador {uid}';member.global_name=None
  return member
 def update_raw(self):
  self.channel._overwrites=[]
  for member,overwrite in self.overwrites.items():
   allow,deny=overwrite.pair()
   self.channel._overwrites.append(SimpleNamespace(id=member.id,type=1 if isinstance(member,FakeMember) else 0,allow=allow.value,deny=deny.value))
 def raw(self):return [(o.id,o.type,o.allow,o.deny) for o in self.channel._overwrites]
 async def test_add_only_target_access_with_durable_before_after_and_restart(self):
  original={m.id:p.pair() for m,p in self.overwrites.items()};before=self.raw()
  self.assertTrue(await self.system.add_ticket_member(self.i,self.rid,7))
  self.channel.set_permissions.assert_awaited_once()
  self.assertEqual(self.system.store.people(self.rid),[7])
  for member,permission in self.overwrites.items():
   if member.id!=7:self.assertEqual(permission.pair(),original[member.id])
  grant=self.overwrites[self.guest]
  for key in ('view_channel','send_messages','read_message_history','attach_files','embed_links','use_application_commands'):
   self.assertTrue(getattr(grant,key))
  self.assertFalse(grant.manage_messages);self.assertTrue(grant.add_reactions)
  self.system.authorize(self.guest,self.system.store.get(self.rid))
  record=self.bot.changes.journal.rows()[0]
  self.assertEqual(record['status'],'completado')
  stored=json.loads(record['before_json'])
  self.assertEqual([(int(o['id']),o['type'],int(o['allow']),int(o['deny'])) for o in stored['channel']['overwrites']],before)
  self.assertEqual(json.loads(record['after_json'])['participants'],[7])
  restart=TicketStore(self.system.store.path);restart.initialize();self.assertEqual(restart.people(self.rid),[7])
  events=self.system.store.events(self.rid)
  self.assertFalse(await self.system.add_ticket_member(self.i,self.rid,7))
  self.assertEqual(self.system.store.events(self.rid),events);self.channel.set_permissions.assert_awaited_once()
 async def test_previously_recorded_participant_with_missing_grant_is_repaired(self):
  self.system.store.participant(self.rid,7,5,True)
  events=self.system.store.events(self.rid)
  self.assertTrue(await self.system.add_ticket_member(self.i,self.rid,7))
  self.channel.set_permissions.assert_awaited_once()
  self.assertTrue(self.channel.permissions_for(self.guest).send_messages)
  self.assertEqual(self.system.store.events(self.rid),events)
  fields=self.system.embed(self.system.store.get(self.rid)).fields
  self.assertEqual([f.value for f in fields if f.name=='Participantes añadidos'],['<@7>'])
 async def test_ordinary_ticket_lists_an_admin_as_an_explicit_participant(self):
  self.guest.guild_permissions.administrator=True
  self.assertTrue(await self.system.add_ticket_member(self.i,self.rid,7))
  self.assertTrue(self.overwrites[self.guest].view_channel)
  self.assertEqual(self.system.store.people(self.rid),[7])
 async def test_blocked_effective_access_does_not_report_success(self):
  self.channel.permissions_for=lambda member:discord.Permissions(view_channel=True,read_message_history=True,send_messages=False)
  with self.assertRaisesRegex(ValueError,'no confirmó'):
   await self.system.add_ticket_member(self.i,self.rid,7)
  self.assertEqual(self.system.store.people(self.rid),[])
 async def test_stale_permissions_and_invalid_targets_cannot_grant_access(self):
  original=self.raw()
  self.members[5]=self.member(5)
  with self.assertRaises(ValueError):await self.system.add_ticket_member(self.i,self.rid,7)
  self.members[5]=self.staff
  for invalid in (self.member(1),self.member(12),self.member(13)):
   self.members[invalid.id]=invalid
  self.members[12].bot=True
  with self.system.store.db() as db:db.execute('UPDATE lv_tickets SET excluded=? WHERE id=?',(13,self.rid))
  for uid in (1,12,13,404):
   with self.assertRaises(ValueError):await self.system.add_ticket_member(self.i,self.rid,uid)
  self.assertEqual(self.raw(),original);self.channel.set_permissions.assert_not_awaited()
  self.assertEqual(self.system.store.people(self.rid),[])
 async def test_closed_or_closing_case_and_other_guild_are_rejected(self):
  for values in ({'status':'cerrado'},{'status':'fallido'},{'status':'creando'},
    {'status':'nuevo','deletion_requested':123},{'status':'nuevo','deletion_requested':None,'deleted_at':123}):
   with self.system.store.db() as db:
    db.execute('UPDATE lv_tickets SET '+','.join(key+'=?' for key in values)+' WHERE id=?',(*values.values(),self.rid))
   with self.assertRaises(ValueError):await self.system.add_ticket_member(self.i,self.rid,7)
  with self.system.store.db() as db:
   db.execute("UPDATE lv_tickets SET status='nuevo',deleted_at=NULL,deletion_requested=NULL WHERE id=?",(self.rid,))
  self.i.guild_id=20
  with self.assertRaises(ValueError):await self.system.add_ticket_member(self.i,self.rid,7)
  self.channel.set_permissions.assert_not_awaited()
 async def test_discord_denial_does_not_record_a_participant_or_change_other_access(self):
  original=self.raw()
  self.channel.set_permissions.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing')
  with self.assertRaises(discord.Forbidden):await self.system.add_ticket_member(self.i,self.rid,7)
  self.assertEqual(self.raw(),original);self.assertEqual(self.system.store.people(self.rid),[])
  self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'fallido')
 async def test_unconfirmed_access_does_not_create_stored_participant(self):
  self.channel.set_permissions.side_effect=None
  with self.assertRaisesRegex(ValueError,'no confirmó'):await self.system.add_ticket_member(self.i,self.rid,7)
  self.assertEqual(self.system.store.people(self.rid),[])
 async def test_reserved_report_requires_current_admins_without_lasting_guest_grant(self):
  self.system.store.update(self.rid,department='staff')
  with self.assertRaises(ValueError):await self.system.add_ticket_member(self.i,self.rid,7)
  self.staff.guild_permissions.administrator=True
  with self.assertRaisesRegex(ValueError,'administradores'):await self.system.add_ticket_member(self.i,self.rid,7)
  self.guest.guild_permissions.administrator=True
  self.assertTrue(await self.system.add_ticket_member(self.i,self.rid,7))
  self.channel.set_permissions.assert_not_awaited()
  row=self.system.store.get(self.rid)
  permissions=channel_overwrites(self.guild,row,self.system.store,self.member(1),people=[self.guest])
  self.assertNotIn(self.guest,permissions)
  self.guest.guild_permissions.administrator=False
  with self.assertRaises(ValueError):self.system.authorize(self.guest,row)
 async def test_invitation_waiting_for_close_rechecks_the_current_state(self):
  lock=self.system.case_lock(self.rid)
  async with lock:
   adding=asyncio.create_task(self.system.add_ticket_member(self.i,self.rid,7))
   await asyncio.sleep(0)
   self.system.store.transition(self.rid,'cerrado',5,'Listo')
  with self.assertRaises(ValueError):await adding
  self.channel.set_permissions.assert_not_awaited()
 async def test_open_action_loads_the_full_directory_and_closed_button_does_not_appear(self):
  self.system.member_directory.load=AsyncMock(return_value=[self.guest])
  await self.system.action(self.i,self.rid,'people')
  self.system.member_directory.load.assert_awaited_once_with(self.guild,force=True)
  self.i.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
  sent=self.i.response.send_message.call_args or self.i.followup.send.call_args
  self.assertIsInstance(sent.kwargs['view'],TicketMemberPicker);self.assertTrue(sent.kwargs['ephemeral'])
  self.assertIn('Añadir miembro',[c.item.label for c in TicketControls(self.rid,assigned=True).children])
  self.assertNotIn('Añadir miembro',[c.item.label for c in TicketControls(self.rid,True).children])
 async def test_directory_failure_is_private_and_never_grants_partial_access(self):
  self.system.member_directory.load=AsyncMock(side_effect=DirectoryUnavailable())
  await self.system.action(self.i,self.rid,'people')
  sent=self.i.response.send_message.call_args or self.i.followup.send.call_args
  self.assertTrue(sent.kwargs['ephemeral'])
  picker=sent.kwargs['view']
  self.assertEqual(len(picker.children),1)
  self.assertIsInstance(picker.children[0],discord.ui.UserSelect)
  self.assertIn('no está disponible',picker.content())
  self.channel.set_permissions.assert_not_awaited()
 async def test_picker_pages_and_search_include_offline_members_and_unicode_names(self):
  members=[self.member(n) for n in range(100,160)]
  members[-1].display_name='𝕽𝖆𝖒𝖔𝖓';members[-1].status=discord.Status.offline
  picker=TicketMemberPicker(self.system,5,self.rid,members)
  self.assertEqual(len(picker.children[1].options),25)
  self.assertNotIn('159',[o.value for o in picker.children[1].options])
  picker.page=2;picker.build();self.assertEqual(len(picker.children[1].options),10)
  form=TicketMemberSearch(picker);form.query._value='ramon'
  await form.on_submit(self.i)
  self.assertEqual(picker.page,0)
  self.assertEqual([o.value for o in picker.children[1].options],['159'])
  picker.query='159';picker.build();self.assertEqual([o.value for o in picker.children[1].options],['159'])
  picker.query='Nobody';picker.build();self.assertTrue(picker.children[1].disabled)
 async def test_picker_is_bound_to_actor_and_rechecks_access_and_ticket_state(self):
  picker=TicketMemberPicker(self.system,5,self.rid,[self.guest])
  self.i.user=self.guest;self.assertFalse(await picker.interaction_check(self.i))
  self.i.user=self.staff;self.assertTrue(await picker.interaction_check(self.i))
  self.system.store.transition(self.rid,'cerrado',5,'Listo')
  self.assertFalse(await picker.interaction_check(self.i))
 async def test_selection_adds_one_person_then_clears_the_private_picker(self):
  picker=TicketMemberPicker(self.system,5,self.rid,[self.guest])
  select=picker.children[1];select._values=['7']
  await select.callback(self.i)
  self.assertEqual(self.system.store.people(self.rid),[7])
  self.assertIsNone(self.i.edit_original_response.call_args.kwargs['view'])
  self.assertEqual(self.i.edit_original_response.call_args.kwargs['allowed_mentions'].to_dict(),discord.AllowedMentions.none().to_dict())
  self.assertTrue(picker.is_finished())
 async def test_native_search_adds_member_outside_the_displayed_page(self):
  picker=TicketMemberPicker(self.system,5,self.rid,[self.member(n) for n in range(100,130)]+[self.guest])
  search=picker.children[0]
  self.assertIsInstance(search,discord.ui.UserSelect)
  self.assertNotIn('7',[option.value for option in picker.children[1].options])
  search._values=[self.guest]
  await search.callback(self.i)
  self.assertEqual(self.system.store.people(self.rid),[7])
  self.assertIsNone(self.i.edit_original_response.call_args.kwargs['view'])
 async def test_native_search_revalidates_ineligible_member_with_no_directory(self):
  self.guest.bot=True
  picker=TicketMemberPicker(self.system,5,self.rid,None)
  search=picker.children[0];search._values=[self.guest]
  with self.assertRaisesRegex(ValueError,'No puedes añadir'):await search.callback(self.i)
  self.channel.set_permissions.assert_not_awaited()
  self.assertFalse(picker.is_finished())
 async def test_existing_open_controls_are_backed_up_before_adding_the_button(self):
  row=self.system.store.get(self.rid)
  view=TicketControls.from_row(row)
  for item in list(view.children):
   if item.item.label=='Añadir miembro':view.remove_item(item)
  message=SimpleNamespace(id=500,author=self.bot.user,content='',embeds=[self.system.embed(row)],
    components=[discord.components.ActionRow(c) for c in view.to_components()])
  async def edit(**kwargs):
   saved=self.bot.changes.journal.rows()[0]
   before=[c['custom_id'] for group in json.loads(saved['before_json'])['components'] for c in group['components']]
   self.assertNotIn(f'lv:ticket:case:{self.rid}:people',before)
   message.components=[discord.components.ActionRow(c) for c in kwargs['view'].to_components()]
  message.edit=AsyncMock(side_effect=edit)
  self.channel.fetch_message=AsyncMock(return_value=message)
  await self.system.edit_control(row,self.channel,message)
  record=self.bot.changes.journal.rows()[0]
  after=[c['custom_id'] for group in json.loads(record['after_json'])['components'] for c in group['components']]
  self.assertIn(f'lv:ticket:case:{self.rid}:people',after)
  self.assertEqual(record['status'],'completado')
