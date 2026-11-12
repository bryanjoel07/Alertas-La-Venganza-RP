import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from photo_members import DirectoryUnavailable
from ticket_members import TicketMemberRemovePicker,TicketMemberSearch
from tickets import TICKET_MEMBER_GRANTS
from tickets_store import NORMAL_STAFF,TicketStore
from tickets_ui import TicketControls
import test_ticket_members as fixtures


class TicketMemberRemovalTests(unittest.IsolatedAsyncioTestCase):
 member=fixtures.TicketMemberTests.member
 update_raw=fixtures.TicketMemberTests.update_raw
 raw=fixtures.TicketMemberTests.raw
 async def asyncSetUp(self):
  await fixtures.TicketMemberTests.asyncSetUp(self)
  def existing(target):return next((member for member in self.overwrites if member.id==target.id),target)
  def get_overwrite(target):
   return discord.PermissionOverwrite.from_pair(*self.overwrites.get(existing(target),discord.PermissionOverwrite()).pair())
  self.channel.overwrites_for=get_overwrite
  async def set_permissions(target,overwrite,reason):
   record=self.bot.changes.journal.rows()[0]
   self.assertEqual(json.loads(record['before_json'])['participants'],self.system.store.people(self.rid))
   if overwrite is None:self.overwrites.pop(existing(target),None)
   else:self.overwrites[existing(target)]=overwrite
   self.update_raw()
  self.channel.set_permissions=AsyncMock(side_effect=set_permissions)
  self.system.sync_member_panel=AsyncMock()
 async def invited(self):
  await self.system.add_ticket_member(self.i,self.rid,7)
  self.channel.set_permissions.reset_mock()
 async def test_remove_only_invitation_grants_after_durable_snapshot_and_verified_readback(self):
  await self.invited();before={m.id:p.pair() for m,p in self.overwrites.items()}
  result=await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertEqual(result,dict(removed=True,retains_access=False))
  self.assertEqual(self.system.store.people(self.rid),[])
  remaining=self.overwrites[self.guest]
  for key in TICKET_MEMBER_GRANTS:self.assertIsNone(getattr(remaining,key))
  self.assertFalse(remaining.manage_messages);self.assertTrue(remaining.add_reactions)
  for target,overwrite in self.overwrites.items():
   if target.id!=7:self.assertEqual(overwrite.pair(),before[target.id])
  record=self.bot.changes.journal.rows()[0]
  self.assertEqual(record['status'],'completado')
  self.assertEqual(json.loads(record['before_json'])['participants'],[7])
  self.assertEqual(json.loads(record['after_json'])['participants'],[])
  restarted=TicketStore(self.system.store.path);restarted.initialize()
  self.assertEqual(restarted.people(self.rid),[])
  self.assertEqual(self.system.store.events(self.rid)[-1]['action'],'retirar')
  events=self.system.store.events(self.rid)
  self.assertFalse((await self.system.remove_ticket_member(self.i,self.rid,7))['removed'])
  self.assertEqual(self.system.store.events(self.rid),events)
  self.channel.set_permissions.assert_awaited_once()
 async def test_empty_individual_overwrite_is_deleted_and_existing_denials_are_preserved(self):
  await self.invited()
  self.overwrites[self.guest]=discord.PermissionOverwrite(**{key:True for key in TICKET_MEMBER_GRANTS})
  self.update_raw()
  await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertIsNone(self.channel.set_permissions.call_args.kwargs['overwrite'])
  self.assertNotIn(self.guest,self.overwrites)
  await self.invited()
  self.overwrites[self.guest].attach_files=False
  await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertFalse(self.overwrites[self.guest].attach_files)
 async def test_discord_denial_preserves_participant_and_other_access(self):
  await self.invited();before=self.raw()
  self.channel.set_permissions.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'denied')
  with self.assertRaises(discord.Forbidden):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertEqual(self.system.store.people(self.rid),[7]);self.assertEqual(self.raw(),before)
  self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'fallido')
 async def test_unconfirmed_removal_preserves_the_record_for_retry(self):
  await self.invited();self.channel.set_permissions.side_effect=None
  with self.assertRaisesRegex(ValueError,'no confirmó'):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertEqual(self.system.store.people(self.rid),[7])
  self.assertEqual(self.bot.changes.journal.rows()[0]['status'],'fallido')
 async def test_current_actor_permissions_are_checked_again(self):
  await self.invited();self.members[5]=self.member(5)
  with self.assertRaises(ValueError):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.channel.set_permissions.assert_not_awaited();self.assertEqual(self.system.store.people(self.rid),[7])
 async def test_author_responsible_excluded_and_bot_cannot_be_removed(self):
  await self.invited()
  for uid in (1,99):
   with self.assertRaises(ValueError):await self.system.remove_ticket_member(self.i,self.rid,uid)
  self.system.store.update(self.rid,assignee=7)
  with self.assertRaises(ValueError):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.system.store.update(self.rid,assignee=None)
  with self.system.store.db() as db:db.execute('UPDATE lv_tickets SET excluded=7 WHERE id=?',(self.rid,))
  with self.assertRaises(ValueError):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.channel.set_permissions.assert_not_awaited();self.assertEqual(self.system.store.people(self.rid),[7])
 async def test_ordinary_participant_cannot_open_the_removal_selector(self):
  await self.invited();self.i.user=self.guest
  with self.assertRaises(ValueError):await self.system.action(self.i,self.rid,'removepeople')
  self.channel.set_permissions.assert_not_awaited()
 async def test_staff_and_administrators_lose_only_the_invitation_record(self):
  for admin,roles in ((True,()),(False,NORMAL_STAFF)):
   with self.subTest(admin=admin):
    self.guest.guild_permissions.administrator=admin
    self.guest.roles=self.member(7,roles=roles).roles
    await self.invited();before=self.raw()
    result=await self.system.remove_ticket_member(self.i,self.rid,7)
    self.assertTrue(result['retains_access']);self.assertEqual(self.raw(),before)
    self.channel.set_permissions.assert_not_awaited();self.assertEqual(self.system.store.people(self.rid),[])
 async def test_other_role_access_is_reported_without_editing_that_role(self):
  await self.invited();self.channel.permissions_for=lambda member:discord.Permissions(view_channel=True)
  result=await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertTrue(result['retains_access']);self.assertEqual(self.system.store.people(self.rid),[])
  for key in TICKET_MEMBER_GRANTS:self.assertIsNone(getattr(self.overwrites[self.guest],key))
 async def test_departed_member_can_be_removed_by_saved_id(self):
  await self.invited();del self.members[7]
  result=await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertTrue(result['removed']);self.assertFalse(result['retains_access'])
  target=self.channel.set_permissions.call_args.args[0]
  self.assertIsInstance(target,discord.User);self.assertEqual(target.id,7)
  self.assertEqual(self.system.store.people(self.rid),[])
  for key in TICKET_MEMBER_GRANTS:self.assertIsNone(getattr(self.overwrites[self.guest],key))
 async def test_reserved_case_requires_current_admin_but_can_remove_a_former_admin(self):
  await self.invited();self.system.store.update(self.rid,department='staff')
  with self.assertRaises(ValueError):await self.system.remove_ticket_member(self.i,self.rid,7)
  self.staff.guild_permissions.administrator=True
  result=await self.system.remove_ticket_member(self.i,self.rid,7)
  self.assertTrue(result['removed']);self.assertEqual(self.system.store.people(self.rid),[])
 async def test_close_while_waiting_on_case_lock_cancels_removal(self):
  await self.invited()
  async with self.system.case_lock(self.rid):
   removing=asyncio.create_task(self.system.remove_ticket_member(self.i,self.rid,7))
   await asyncio.sleep(0)
   self.system.store.transition(self.rid,'cerrado',5,'Listo')
  with self.assertRaises(ValueError):await removing
  self.channel.set_permissions.assert_not_awaited();self.assertEqual(self.system.store.people(self.rid),[7])
 async def test_buttons_are_adjacent_persistent_and_absent_from_closed_cases(self):
  for assigned in (False,True):
   view=TicketControls(self.rid,assigned=assigned)
   self.assertTrue(view.is_persistent())
   buttons={child.item.label:child.item for child in view.children}
   self.assertEqual(buttons['Añadir miembro'].row,buttons['Remover miembro'].row)
   self.assertTrue(buttons['Remover miembro'].custom_id.endswith(':removepeople'))
   self.assertLessEqual(len(view.to_components()[1]['components']),5)
  self.assertNotIn('Remover miembro',[child.item.label for child in TicketControls(self.rid,True).children])
 async def test_action_is_private_and_directory_failure_still_lists_saved_participants(self):
  await self.invited();self.system.member_directory.load=AsyncMock(side_effect=DirectoryUnavailable())
  await self.system.action(self.i,self.rid,'removepeople')
  response=self.i.response.send_message.call_args or self.i.followup.send.call_args
  self.assertTrue(response.kwargs['ephemeral'])
  self.i.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
  picker=response.kwargs['view'];self.assertIsInstance(picker,TicketMemberRemovePicker)
  self.assertEqual([option.value for option in picker.children[0].options],['7'])
  self.assertFalse(any(isinstance(child,discord.ui.UserSelect) for child in picker.children))
 async def test_picker_lists_only_added_people_paginates_and_searches_offline_names(self):
  members=[self.member(uid) for uid in range(100,131)]
  members[-1].display_name='𝕽𝖆𝖒𝖔𝖓';members[-1].status=discord.Status.offline
  for member in members:self.system.store.participant(self.rid,member.id,5,True)
  self.system.store.participant(self.rid,1,5,True);self.system.store.participant(self.rid,5,5,True)
  self.system.store.update(self.rid,assignee=5)
  picker=TicketMemberRemovePicker(self.system,5,self.rid,members+[self.member(88)])
  self.assertEqual(len(picker.children[0].options),25)
  self.assertNotIn('88',[option.value for option in picker.children[0].options])
  picker.page=1;picker.build();self.assertEqual(len(picker.children[0].options),6)
  search=TicketMemberSearch(picker);search.query._value='ramon';await search.on_submit(self.i)
  self.assertEqual(picker.page,0);self.assertEqual([option.value for option in picker.children[0].options],['130'])
 async def test_picker_is_actor_bound_and_rechecks_case_state(self):
  await self.invited();picker=TicketMemberRemovePicker(self.system,5,self.rid,[self.guest])
  self.i.user=self.guest;self.assertFalse(await picker.interaction_check(self.i))
  self.i.user=self.staff;self.assertTrue(await picker.interaction_check(self.i))
  self.system.store.transition(self.rid,'cerrado',5,'Listo')
  self.assertFalse(await picker.interaction_check(self.i))
 async def test_selection_removes_one_participant_updates_roster_and_clears_private_controls(self):
  await self.invited();picker=TicketMemberRemovePicker(self.system,5,self.rid,[self.guest])
  picker.children[0]._values=['7'];await picker.children[0].callback(self.i)
  self.assertEqual(self.system.store.people(self.rid),[])
  self.system.sync_member_panel.assert_awaited_once_with(self.rid)
  result=self.i.edit_original_response.call_args
  self.assertIsNone(result.kwargs['view']);self.assertIn('removido',result.kwargs['content'])
  self.assertEqual(result.kwargs['allowed_mentions'].to_dict(),discord.AllowedMentions.none().to_dict())
  self.assertTrue(picker.is_finished())
 async def test_active_slash_removal_uses_the_same_targeted_operation(self):
  await self.invited()
  command=self.system.group.get_command('participante')
  await command.callback(self.i,self.guest,False,self.rid)
  self.assertEqual(self.system.store.people(self.rid),[])
  self.channel.set_permissions.assert_awaited_once()
  self.system.sync_member_panel.assert_awaited_once_with(self.rid)
 async def test_existing_ticket_control_upgrade_is_backed_up_before_new_button(self):
  row=self.system.store.get(self.rid);view=TicketControls.from_row(row)
  for child in list(view.children):
   if child.item.label=='Remover miembro':view.remove_item(child)
  message=SimpleNamespace(id=500,author=self.bot.user,content='',embeds=[self.system.embed(row)],
    components=[discord.components.ActionRow(data) for data in view.to_components()])
  async def edit(**kwargs):
   record=self.bot.changes.journal.rows()[0]
   old=[child['custom_id'] for group in json.loads(record['before_json'])['components'] for child in group['components']]
   self.assertNotIn(f'lv:ticket:case:{self.rid}:removepeople',old)
   message.components=[discord.components.ActionRow(data) for data in kwargs['view'].to_components()]
  message.edit=AsyncMock(side_effect=edit);self.channel.fetch_message=AsyncMock(return_value=message)
  await self.system.edit_control(row,self.channel,message)
  record=self.bot.changes.journal.rows()[0]
  after=[child['custom_id'] for group in json.loads(record['after_json'])['components'] for child in group['components']]
  self.assertIn(f'lv:ticket:case:{self.rid}:removepeople',after);self.assertEqual(record['status'],'completado')
