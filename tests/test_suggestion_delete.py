import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock,patch

import discord

import test_suggestions as fixtures
from suggestion_store import SuggestionStore
from suggestion_ui import DeleteIdea,idea_controls
from suggestions import SuggestionSystem,CHANNEL_ID


class DeleteTests(unittest.IsolatedAsyncioTestCase):
 update_raw=fixtures.ServiceTests.update_raw
 interaction=fixtures.ServiceTests.interaction
 fetch_message=fixtures.ServiceTests.fetch_message
 idea=fixtures.ServiceTests.idea
 bind_interaction=fixtures.ServiceTests.bind_interaction
 async def asyncSetUp(self):
  await fixtures.ServiceTests.asyncSetUp(self)
  self.admin=self.interaction(2);self.deleted_ids=[]
 def new_message(self,*args,**kwargs):
  message=fixtures.ServiceTests.new_message(self,*args,**kwargs);message.attachments=[]
  async def remove():
   self.deleted_ids.append(message.id);self.messages.pop(message.id,None)
   await self.system.deleted(10,message.channel_id,[message.id])
  message.delete=AsyncMock(side_effect=remove)
  return message
 async def confirmation(self,rid,actor=None):
  actor=actor or self.admin
  await self.system.handle(actor,'delete',rid)
  sent=actor.response.send_message.call_args or actor.followup.send.call_args
  self.assertTrue(sent.kwargs['ephemeral']);self.assertIsInstance(sent.kwargs['view'],DeleteIdea)
  return sent.kwargs['view']
 async def test_admin_confirmation_deletes_discord_and_all_three_active_tables(self):
  await self.system.ready();portal=int(self.system.store.config('portal_message'))
  rid=await self.idea();row=self.system.store.get(rid)
  self.system.store.vote(rid,3,1);self.system.store.decide(rid,'aceptada',2,'La vamos a trabajar.',0)
  await self.system.render(rid)
  self.users[3].id=3;other=self.interaction(3)
  await self.system.submit(other,'Otra propuesta','Una propuesta que debe conservarse.','')
  other_row=self.system.store.get(rid+1)
  view=await self.confirmation(rid)
  message=self.messages[row['message']];remove=message.delete.side_effect
  async def audited_remove():
   audit=next(r for r in self.bot.changes.journal.rows() if r['title']==f'Eliminar sugerencia #{rid}')
   saved=json.loads(audit['before_json'])
   self.assertEqual(saved['suggestion']['publication'],'published')
   self.assertEqual(saved['votes'][0]['user'],3);self.assertEqual(saved['decisions'][0]['status'],'aceptada')
   self.assertEqual(saved['message']['id'],row['message'])
   await remove()
   self.assertEqual(self.system.store.get(rid)['publication'],'deleting')
  message.delete.side_effect=audited_remove
  before=[vars(o).copy() for o in self.base._overwrites]
  await view.confirm.callback(self.admin)
  self.assertIsNone(self.system.store.get(rid));self.assertEqual(self.system.store.votes(rid),[])
  self.assertEqual(self.system.store.events(rid),[]);self.assertIsNone(self.system.store.deletion(rid))
  self.assertNotIn(row['message'],self.messages);self.assertIn(portal,self.messages)
  self.assertIn(other_row['message'],self.messages);self.assertIsNotNone(self.system.store.get(other_row['id']))
  self.assertEqual([vars(o) for o in self.base._overwrites],before)
  self.assertIn('ya se eliminaron',self.admin.edit_original_response.call_args.kwargs['content'])
  audit=next(r for r in self.bot.changes.journal.rows() if r['title']==f'Eliminar sugerencia #{rid}')
  self.assertEqual(audit['status'],'completado');self.assertIsNone(json.loads(audit['after_json'])['suggestion'])
 async def test_citizens_cannot_open_or_bypass_the_confirmation(self):
  rid=await self.idea();row=self.system.store.get(rid)
  with self.assertRaises(ValueError):await self.system.handle(self.i,'delete',rid)
  with self.assertRaises(ValueError):await self.system.delete_idea(self.i,row)
  self.assertEqual(self.system.store.get(rid)['publication'],'published')
  self.assertFalse(self.system.store.pending_deletions());self.assertEqual(self.deleted_ids,[])
  self.i.response.send_message.assert_awaited() # Only the original proposal confirmation.
 async def test_confirmation_is_bound_to_its_admin_and_cancel_has_no_side_effects(self):
  rid=await self.idea();view=await self.confirmation(rid)
  self.users[3].roles=[self.protected];other=self.interaction(3)
  self.assertFalse(await view.interaction_check(other))
  await view.confirm.callback(other);self.assertEqual(self.deleted_ids,[])
  await view.cancel.callback(self.admin)
  self.assertEqual(self.system.store.get(rid)['publication'],'published')
  self.assertFalse(self.system.store.pending_deletions());self.assertTrue(view.is_finished())
 async def test_lost_admin_role_is_checked_again_at_confirmation(self):
  rid=await self.idea();view=await self.confirmation(rid)
  self.users[2].roles=[]
  await view.confirm.callback(self.admin)
  self.assertIsNotNone(self.system.store.get(rid));self.assertEqual(self.deleted_ids,[])
  self.assertIsNone(self.system.store.deletion(rid))
 async def test_new_admin_decision_invalidates_old_confirmation_but_new_votes_do_not(self):
  rid=await self.idea();old=self.system.store.get(rid)
  self.system.store.decide(rid,'proceso',2,'Ya empezamos a trabajar.',0)
  with self.assertRaisesRegex(ValueError,'cambió'):await self.system.delete_idea(self.admin,old)
  fresh=self.system.store.get(rid);self.system.store.vote(rid,3,1)
  self.assertTrue(await self.system.delete_idea(self.admin,fresh));self.assertIsNone(self.system.store.get(rid))
 async def test_discord_denial_keeps_data_and_persistent_retry_finishes_after_restart(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']]
  self.system.store.vote(rid,3,1);remove=message.delete.side_effect
  message.delete.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing')
  with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):
   self.assertFalse(await self.system.delete_idea(self.admin,self.system.store.get(rid)))
  self.assertIn(row['message'],self.messages);self.assertEqual(self.system.store.get(rid)['up'],1)
  self.assertEqual(self.system.store.get(rid)['publication'],'deleting');self.assertEqual(self.system.store.list(),[])
  with self.assertRaises(ValueError):self.system.store.vote(rid,1,-1)
  with self.assertRaises(ValueError):self.system.store.decide(rid,'hecha',2,'Ya se hizo.',0)
  restart=SuggestionSystem(self.bot,self.path,10);restart.store.initialize();message.delete.side_effect=remove
  await restart.maintenance()
  self.assertIsNone(restart.store.get(rid));self.assertNotIn(row['message'],self.messages)
  self.assertFalse(restart.store.pending_deletions())
 async def test_timeout_after_discord_accepted_delete_does_not_leave_a_ghost_record(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']];remove=message.delete.side_effect
  async def ambiguous():await remove();raise TimeoutError('response was lost')
  message.delete.side_effect=ambiguous
  with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):
   self.assertFalse(await self.system.delete_idea(self.admin,row))
  self.assertNotIn(row['message'],self.messages);self.assertIsNotNone(self.system.store.get(rid))
  restart=SuggestionSystem(self.bot,self.path,10);restart.store.initialize();await restart.maintenance()
  self.assertIsNone(restart.store.get(rid));message.delete.assert_awaited_once()
 async def test_database_failure_after_discord_delete_is_completed_without_another_delete(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']]
  with patch.object(self.system.store,'purge',side_effect=sqlite3.OperationalError('temporary write failure')):
   with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):
    self.assertFalse(await self.system.delete_idea(self.admin,row))
  self.assertIsNotNone(self.system.store.get(rid));self.assertNotIn(row['message'],self.messages)
  await self.system.maintenance();self.assertIsNone(self.system.store.get(rid));message.delete.assert_awaited_once()
 async def test_data_is_not_purged_until_discord_absence_is_confirmed(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']];remove=message.delete.side_effect
  message.delete.side_effect=None
  with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):
   self.assertFalse(await self.system.delete_idea(self.admin,row))
  self.assertIsNotNone(self.system.store.get(rid));self.assertIn(row['message'],self.messages)
  message.delete.side_effect=remove;await self.system.maintenance();self.assertIsNone(self.system.store.get(rid))
 async def test_already_missing_publication_can_be_purged_and_ids_are_never_reused(self):
  rid=await self.idea();row=self.system.store.get(rid)
  self.messages.pop(row['message']);await self.system.deleted(10,row['channel'],[row['message']])
  self.assertTrue(await self.system.delete_idea(self.admin,self.system.store.get(rid)))
  restart=SuggestionStore(self.path);restart.initialize()
  new=restart.create('new-after-delete',1,'Una nueva idea','Esta idea no puede usar un número viejo.')
  self.assertGreater(new,rid)
  self.assertTrue(await self.system.delete_idea(self.admin,row));self.assertIsNotNone(restart.get(new))
 async def test_foreign_message_or_changed_identity_cannot_be_deleted(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']]
  message.author=SimpleNamespace(id=888)
  with self.assertRaises(ValueError):await self.system.delete_idea(self.admin,row)
  message.delete.assert_not_awaited();self.assertEqual(self.system.store.get(rid)['publication'],'published')
  message.author=self.bot.user
  wrong=dict(row,request='another-request')
  with self.assertRaises(ValueError):await self.system.delete_idea(self.admin,wrong)
  self.assertFalse(self.system.store.pending_deletions())
 async def test_pending_ambiguous_creation_is_not_republished_while_deleting(self):
  rid=self.system.store.create('pending',1,'Una idea pendiente','Esta petición se quedó a medias.')
  self.system.store.acquire(rid);row=self.system.store.get(rid)
  with patch('suggestion_delete.time.time',return_value=row['lease_until']-1):
   self.assertFalse(await self.system.delete_idea(self.admin,row))
  self.assertEqual(self.system.store.get(rid)['publication'],'deleting')
  self.assertNotIn(rid,self.system.store.pending())
  with patch('suggestion_delete.time.time',return_value=row['lease_until']+1):await self.system.maintenance()
  self.assertIsNone(self.system.store.get(rid));self.assertEqual(self.messages,{})
 async def test_upgrade_adds_delete_button_to_existing_card_without_changing_its_votes(self):
  rid=await self.idea();row=self.system.store.get(rid);message=self.messages[row['message']]
  self.system.store.vote(rid,3,1);await self.system.render(rid)
  view=idea_controls(self.system.store.get(rid))
  for item in list(view.children):
   if item.action=='delete':view.remove_item(item)
  message.components=[discord.components.ActionRow(c) for c in view.to_components()]
  await self.system.ready()
  ids=[c.custom_id for group in message.components for c in group.children]
  self.assertIn(f'lvsug:delete:{rid}',ids);self.assertEqual(self.system.store.get(rid)['up'],1)
  self.assertIsInstance(self.system.group.get_command('eliminar'),discord.app_commands.Command)
  self.assertEqual(self.deleted_ids,[])
 async def test_ambiguous_unbound_post_is_found_and_deleted_before_purging(self):
  rid=self.system.store.create('unknown-response',1,'Una idea pendiente','Discord recibió esta publicación.')
  self.system.store.acquire(rid);row=self.system.store.get(rid)
  ghost=self.new_message(CHANNEL_ID,self.system.embed(row),idea_controls(row))
  with patch('suggestion_delete.time.time',return_value=row['lease_until']+1):
   self.assertTrue(await self.system.delete_idea(self.admin,row))
  self.assertNotIn(ghost.id,self.messages);self.assertIsNone(self.system.store.get(rid))
  self.assertEqual(self.deleted_ids,[ghost.id])
 async def test_only_the_verified_bot_owned_forum_post_can_be_deleted(self):
  forum=MagicMock(spec=discord.ForumChannel);forum.id=CHANNEL_ID;forum.guild=self.guild
  forum.permissions_for=self.base.permissions_for;self.channels[CHANNEL_ID]=forum
  rid=self.system.store.create('forum-delete',1,'Una idea en un foro','Esta idea tiene su propia publicación.')
  row=self.system.store.get(rid);message=self.new_message(0,self.system.embed(row),idea_controls(row));message.channel_id=message.id
  thread=MagicMock(spec=discord.Thread);thread.id=message.id;thread.parent_id=CHANNEL_ID
  thread.guild=self.guild;thread.owner_id=99;thread.fetch_message=AsyncMock(side_effect=self.fetch_message)
  comment=SimpleNamespace(id=7000,author=SimpleNamespace(id=3),content='Comentario de la comunidad',embeds=[],attachments=[])
  async def history(**kwargs):
   yield message;yield comment
  thread.history=history;self.channels[thread.id]=thread
  self.system.store.bind(rid,thread.id,message.id);row=self.system.store.get(rid)
  thread.owner_id=777
  with self.assertRaises(ValueError):await self.system.delete_idea(self.admin,row)
  self.assertEqual(self.system.store.get(rid)['publication'],'published')
  thread.owner_id=99
  async def delete_thread(**kwargs):
   self.channels.pop(thread.id);self.messages.pop(message.id)
  thread.delete=AsyncMock(side_effect=delete_thread)
  self.assertTrue(await self.system.delete_idea(self.admin,row))
  thread.delete.assert_awaited_once();message.delete.assert_not_awaited()
  self.assertIsNone(self.system.store.get(rid));self.assertIn(CHANNEL_ID,self.channels)
  audit=next(r for r in self.bot.changes.journal.rows() if r['title']==f'Eliminar sugerencia #{rid}')
  saved=json.loads(audit['before_json'])
  self.assertEqual(saved['discussion'][1]['content'],'Comentario de la comunidad')

