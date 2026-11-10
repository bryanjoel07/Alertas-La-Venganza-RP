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

from backup import snapshot
from change_log import ChangeLog
from suggestion_store import SuggestionStore,STATES
from suggestion_ui import SuggestionAction,IdeaForm,StateForm,idea_controls
from suggestions import SuggestionSystem,CHANNEL_ID,PORTAL_MARKER,marker
from tickets_store import PROTECTED


class StoreTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.path=Path(tmp.name)/'db.sqlite'
  with sqlite3.connect(self.path) as db:db.execute('CREATE TABLE keep_me(value TEXT)');db.execute("INSERT INTO keep_me VALUES ('original')")
  self.store=SuggestionStore(self.path);self.store.initialize()
 def idea(self,owner=1,request='a',now=1000):
  rid=self.store.create(request,owner,'Una buena idea','Una descripción suficientemente clara.',now=now)
  self.store.bind(rid,100,500+rid);return rid
 def test_atomic_duplicate_submission_and_additive_schema(self):
  with ThreadPoolExecutor(max_workers=5) as pool:
   ids=list(pool.map(lambda _:self.store.create('same',1,'Título de idea','Una idea para la comunidad.',now=1000),range(5)))
  self.assertEqual(len(set(ids)),1);self.assertEqual(len(self.store.list()),1)
  with sqlite3.connect(self.path) as db:self.assertEqual(db.execute('SELECT value FROM keep_me').fetchone()[0],'original')
  with self.assertRaises(ValueError):self.store.create('same',2,'Título de idea','Una idea para la comunidad.',now=1000)
 def test_content_duplicates_cooldown_and_validation(self):
  rid=self.idea()
  with self.assertRaisesRegex(ValueError,'Ya enviaste'):self.idea(request='duplicate',now=2000)
  with self.assertRaisesRegex(ValueError,'minuto'):self.store.create('new',1,'Otra idea','Otra explicación válida.',now=1001)
  for title,description,benefit in [('','Diez caracteres',''),('Un título','Corto',''),('Un título','Texto suficiente aquí','x'*701)]:
   with self.assertRaises(ValueError):self.store.create('bad',7,title,description,benefit,now=2000)
  self.assertEqual(self.store.get(rid)['title'],'Una buena idea')
 def test_concurrent_votes_have_one_ballot_per_person_and_can_change_or_remove(self):
  rid=self.idea()
  with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:self.store.vote(rid,1,1),range(30)))
  self.assertEqual((self.store.get(rid)['up'],self.store.get(rid)['down']),(1,0))
  self.assertFalse(self.store.vote(rid,1,1));self.assertTrue(self.store.vote(rid,1,-1))
  self.assertEqual((self.store.get(rid)['up'],self.store.get(rid)['down']),(0,1))
  self.assertTrue(self.store.vote(rid,1,0));self.assertFalse(self.store.vote(rid,1,0))
  with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda uid:self.store.vote(rid,uid,1 if uid%2 else -1),range(10,30)))
  self.assertEqual((self.store.get(rid)['up'],self.store.get(rid)['down']),(10,10))
 def test_decisions_keep_history_and_stale_admin_form_cannot_overwrite(self):
  rid=self.idea();self.store.vote(rid,2,1)
  self.store.decide(rid,'aceptada',7,'La vamos a trabajar.',0)
  with self.assertRaisesRegex(ValueError,'Otra persona'):self.store.decide(rid,'rechazada',8,'Cambió la decisión.',0)
  self.store.decide(rid,'proceso',8,'Ya empezamos a trabajar.',1)
  self.store.decide(rid,'hecha',8,'Ya está disponible.',2)
  with self.assertRaisesRegex(ValueError,'cerrados'):self.store.vote(rid,3,1)
  self.store.decide(rid,'pendiente',7,'Hay que revisarla de nuevo.',3);self.store.vote(rid,3,1)
  self.assertEqual(self.store.get(rid)['up'],2);self.assertEqual(len(self.store.events(rid)),4)
 def test_pending_publication_leases_and_render_ack_survive_restart(self):
  rid=self.store.create('a',1,'Una idea','Quiero mejorar el servidor.',now=1000)
  self.assertTrue(self.store.acquire(rid,1000));self.assertFalse(self.store.acquire(rid,1001))
  restart=SuggestionStore(self.path);restart.initialize()
  self.assertTrue(restart.acquire(rid,1180));restart.bind(rid,100,500)
  restart.vote(rid,2,1);self.assertFalse(restart.acknowledge(rid,0))
  self.assertIn(rid,restart.pending());self.assertTrue(restart.acknowledge(rid,1));self.assertNotIn(rid,restart.pending())
 def test_missing_publication_is_excluded_without_deleting_votes_or_history(self):
  a=self.idea();b=self.idea(owner=2,request='b')
  self.store.vote(a,3,1);self.store.decide(a,'rechazada',7,'No encaja por ahora.',0)
  self.store.missing(999,[500+a]);self.assertEqual(len(self.store.list()),2)
  self.store.missing(100,[500+a]);self.assertEqual([r['id'] for r in self.store.list()],[b])
  self.assertEqual(self.store.get(a)['up'],1);self.assertEqual(len(self.store.events(a)),1)
  with self.assertRaises(ValueError):self.store.vote(a,4,1)
 def test_existing_backup_covers_all_new_tables_and_restores_votes(self):
  rid=self.idea();self.store.vote(rid,2,1)
  result=snapshot(self.path,self.path.parent/'backup.sqlite')
  self.assertEqual(result['rows']['lv_suggestion_votes'],1)
  self.assertEqual(SuggestionStore(result['file']).get(rid)['up'],1)


class Role:
 def __init__(self,rid,**bits):self.id=rid;self.permissions=discord.Permissions(**bits)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.path=Path(tmp.name)/'db.sqlite';self.messages={};self.channels={};self.next_id=5000
  self.citizen=Role(1245009164070158409,view_channel=True,read_message_history=True,use_application_commands=True)
  self.protected=Role(next(iter(PROTECTED)),view_channel=True,read_message_history=True,use_application_commands=True)
  self.guild=SimpleNamespace(id=10,get_role=lambda rid:self.citizen if rid==self.citizen.id else None,roles=[self.citizen,self.protected])
  self.users={uid:SimpleNamespace(id=uid,bot=False,guild=self.guild,roles=[self.protected] if uid==2 else [self.citizen],guild_permissions=discord.Permissions.none()) for uid in (1,2,3)}
  self.guild.fetch_member=AsyncMock(side_effect=lambda uid:self.users[uid])
  self.guild.get_channel_or_thread=lambda cid:self.channels.get(cid)
  self.guild.active_threads=AsyncMock(side_effect=lambda:[c for c in self.channels.values() if isinstance(c,discord.Thread)])
  self.base=MagicMock(spec=discord.TextChannel);self.base.id=CHANNEL_ID;self.base.guild=self.guild;self.base.name='💡┊Sugerencias';self.base.type=discord.ChannelType.text
  self.base._overwrites=[];self.overwrites={self.citizen:discord.PermissionOverwrite(send_messages=False),self.protected:discord.PermissionOverwrite(view_channel=True)}
  self.update_raw()
  self.base.overwrites_for=lambda role:discord.PermissionOverwrite.from_pair(*self.overwrites.get(role,discord.PermissionOverwrite()).pair())
  def permissions(role):
   if hasattr(role,'roles'):role=role.roles[0] if role.roles else Role(0)
   overwrite=self.overwrites.get(role,discord.PermissionOverwrite())
   return discord.Permissions(**{key:getattr(overwrite,key) if getattr(overwrite,key) is not None else getattr(role.permissions,key) for key in ('view_channel','read_message_history','use_application_commands','send_messages')})
  self.base.permissions_for=permissions
  async def grant(role,overwrite,**kwargs):self.overwrites[role]=overwrite;self.update_raw()
  self.base.set_permissions=AsyncMock(side_effect=grant)
  self.channels[CHANNEL_ID]=self.base
  async def fetch_channel(cid):
   if cid not in self.channels:raise discord.NotFound(SimpleNamespace(status=404,reason='Missing'),'missing')
   return self.channels[cid]
  self.bot=SimpleNamespace(user=SimpleNamespace(id=99),get_guild=lambda gid:self.guild,fetch_channel=AsyncMock(side_effect=fetch_channel))
  self.system=SuggestionSystem(self.bot,self.path,10);self.system.store.initialize()
  self.bot.changes=ChangeLog(self.bot,self.path,10);self.bot.changes.journal.initialize()
  self.bot.suggestions=self.system
  self.base.fetch_message=AsyncMock(side_effect=self.fetch_message)
  self.base.send=AsyncMock(side_effect=lambda **kwargs:self.new_message(CHANNEL_ID,**kwargs))
  async def history(**kwargs):
   for message in list(self.messages.values()):
    if message.channel_id==CHANNEL_ID:yield message
  self.base.history=history
  self.i=self.interaction(1)
 def update_raw(self):
  self.base._overwrites=[]
  for role,overwrite in self.overwrites.items():
   allow,deny=overwrite.pair();self.base._overwrites.append(SimpleNamespace(id=role.id,type=0,allow=allow.value,deny=deny.value))
 def interaction(self,uid):
  i=SimpleNamespace(id=uid*100000+1,user=self.users[uid],guild_id=10,channel_id=CHANNEL_ID,client=self.bot,message=None)
  i.response=SimpleNamespace(is_done=lambda:False,defer=AsyncMock(),send_message=AsyncMock(),send_modal=AsyncMock(),edit_message=AsyncMock())
  i.followup=SimpleNamespace(send=AsyncMock());i.edit_original_response=AsyncMock()
  return i
 def new_message(self,channel,embed,view,allowed_mentions=None):
  self.next_id+=1
  message=SimpleNamespace(id=self.next_id,channel_id=channel,author=self.bot.user,pinned=False,content='',embeds=[embed],
    components=[discord.components.ActionRow(c) for c in view.to_components()])
  async def edit(**kwargs):
   message.embeds=[kwargs['embed']];message.components=[discord.components.ActionRow(c) for c in kwargs['view'].to_components()];return message
  async def pin(**kwargs):message.pinned=True
  message.edit=AsyncMock(side_effect=edit);message.pin=AsyncMock(side_effect=pin)
  self.messages[message.id]=message;return message
 def fetch_message(self,mid):
  if mid not in self.messages:raise discord.NotFound(SimpleNamespace(status=404,reason='Missing'),'missing')
  return self.messages[mid]
 async def idea(self):
  await self.system.submit(self.i,'Carreras de la comunidad','Podemos organizar carreras con los jugadores.','Para compartir más entre todos.')
  return self.system.store.list()[0]['id']
 def bind_interaction(self,i,rid):
  row=self.system.store.get(rid);i.channel_id=row['channel'];i.message=self.messages[row['message']]
 async def test_portal_is_installed_once_and_preserves_other_messages_and_permissions(self):
  old=self.new_message(CHANNEL_ID,discord.Embed(title='Mensaje anterior'),discord.ui.View());old.author=SimpleNamespace(id=77);old.pinned=True
  before=[vars(o).copy() for o in self.base._overwrites]
  await self.system.ready();portal=self.system.store.config('portal_message')
  self.system.prepared=False;await self.system.ready()
  self.assertEqual(self.system.store.config('portal_message'),portal);self.assertEqual(len(self.messages),2)
  old.edit.assert_not_awaited();self.assertTrue(old.pinned);self.assertEqual([vars(o) for o in self.base._overwrites],before)
  self.assertTrue(self.messages[int(portal)].pinned)
  self.assertEqual(marker(self.messages[int(portal)]),PORTAL_MARKER)
  self.base.set_permissions.assert_not_awaited()
 async def test_citizen_access_changes_only_three_bits_and_keeps_writing_and_protected_roles(self):
  self.overwrites[self.citizen].view_channel=False;self.overwrites[self.citizen].read_message_history=False
  self.update_raw();protected=self.overwrites[self.protected].pair();original_bits=self.citizen.permissions.value
  await self.system.ready()
  actual=self.overwrites[self.citizen]
  self.assertTrue(actual.view_channel);self.assertTrue(actual.read_message_history);self.assertTrue(actual.use_application_commands)
  self.assertFalse(actual.send_messages);self.assertEqual(self.overwrites[self.protected].pair(),protected)
  self.assertEqual(self.citizen.permissions.value,original_bits)
  record=next(r for r in self.bot.changes.journal.rows() if r['title'].startswith('Dar a Ciudadanos'))
  self.assertEqual(record['status'],'completado');self.assertTrue(json.loads(record['before_json'])['overwrites'])
 async def test_real_form_publishes_one_credited_card_with_working_votes(self):
  await self.system.handle(self.i,'new',0)
  form=self.i.response.send_modal.call_args.args[0]
  form.title_input._value='Carreras para todos';form.description._value='Organizar carreras para que participen los jugadores.';form.benefit._value='Compartir en comunidad.'
  await form.on_submit(self.i)
  row=self.system.store.get(1);message=self.messages[row['message']]
  self.assertIn('<@1>',message.embeds[0].description);self.assertEqual(row['rendered'],row['revision'])
  self.assertEqual([c.custom_id for group in message.components for c in group.children],['lvsug:up:1','lvsug:down:1','lvsug:clear:1','lvsug:state:1','lvsug:delete:1'])
  self.bind_interaction(self.i,1)
  for action,up,down in [('up',1,0),('up',1,0),('down',0,1),('clear',0,0)]:
   await self.system.handle(self.i,action,1);row=self.system.store.get(1)
   self.assertEqual((row['up'],row['down']),(up,down))
  self.assertEqual(len(self.messages),1)
 async def test_state_modal_checks_fresh_admin_access_and_publishes_reason_and_closed_votes(self):
  rid=await self.idea();admin=self.interaction(2)
  with self.assertRaises(ValueError):await self.system.handle(self.i,'state',rid)
  await self.system.handle(admin,'state',rid);form=admin.response.send_modal.call_args.args[0]
  form._refresh(admin,[{'type':18,'component':{'type':3,'custom_id':'suggestion_state','values':['hecha']}},
    {'type':18,'component':{'type':4,'custom_id':'suggestion_reason','value':'Ya están disponibles las carreras.'}}],{})
  self.users[2].roles=[]
  await form.on_submit(admin);self.assertEqual(self.system.store.get(rid)['status'],'pendiente')
  self.users[2].roles=[self.protected];await form.on_submit(admin)
  row=self.system.store.get(rid);message=self.messages[row['message']]
  self.assertEqual(row['status'],'hecha');self.assertEqual(row['reason'],'Ya están disponibles las carreras.')
  self.assertTrue(all(c.disabled for c in message.components[0].children[:3]));self.assertFalse(message.components[0].children[3].disabled)
  event=self.system.store.events(rid)[0];self.assertEqual(event['actor'],2)
  journal=next(r for r in self.bot.changes.journal.rows() if r['title'].startswith('Cambiar el estado'))
  self.assertEqual(json.loads(journal['before_json'])['suggestion']['status'],'pendiente')
  self.assertEqual(json.loads(journal['after_json'])['suggestion']['status'],'hecha')
 async def test_failed_vote_render_is_durable_and_recovers_after_restart(self):
  rid=await self.idea();self.bind_interaction(self.i,rid);message=self.i.message;edit=message.edit.side_effect
  message.edit.side_effect=discord.HTTPException(SimpleNamespace(status=503,reason='Unavailable'),'later')
  with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):await self.system.handle(self.i,'up',rid)
  self.assertEqual(self.system.store.get(rid)['up'],1);self.assertIn(rid,self.system.store.pending())
  restart=SuggestionSystem(self.bot,self.path,10);restart.store.initialize();message.edit.side_effect=edit
  await restart.maintenance()
  self.assertNotIn(rid,restart.store.pending());self.assertIn('1',message.components[0].children[0].label)
 async def test_ambiguous_publish_is_found_by_marker_instead_of_posting_twice(self):
  async def ambiguous(**kwargs):
   self.new_message(CHANNEL_ID,**kwargs);raise TimeoutError('request accepted but response lost')
  self.base.send.side_effect=ambiguous
  with self.assertLogs('LaVenganzaRP.suggestions',level='ERROR'):await self.idea()
  row=self.system.store.get(1);self.assertEqual(row['publication'],'publishing');self.assertEqual(len(self.messages),1)
  self.base.send.side_effect=lambda **kwargs:self.new_message(CHANNEL_ID,**kwargs)
  with self.system.store.db() as db:db.execute('UPDATE lv_suggestions SET lease_until=0 WHERE id=1')
  restart=SuggestionSystem(self.bot,self.path,10);restart.store.initialize();await restart.maintenance()
  self.assertEqual(len(self.messages),1);self.assertEqual(restart.store.get(1)['publication'],'published')
  self.assertNotIn(1,restart.store.pending())
 async def test_foreign_guild_hidden_channel_bots_and_wrong_card_cannot_vote(self):
  rid=await self.idea();self.bind_interaction(self.i,rid)
  self.i.guild_id=20
  with self.assertRaises(ValueError):await self.system.handle(self.i,'up',rid)
  self.i.guild_id=10;self.users[1].bot=True
  with self.assertRaises(ValueError):await self.system.handle(self.i,'up',rid)
  self.users[1].bot=False;self.overwrites[self.citizen].view_channel=False
  with self.assertRaises(ValueError):await self.system.handle(self.i,'up',rid)
  self.overwrites[self.citizen].view_channel=True;self.i.message=SimpleNamespace(id=999)
  with self.assertRaises(ValueError):await self.system.handle(self.i,'up',rid)
  self.assertEqual(self.system.store.get(rid)['up'],0)
 async def test_deleted_card_is_not_reposted_and_is_absent_from_my_ideas(self):
  rid=await self.idea();row=self.system.store.get(rid)
  await self.system.deleted(10,row['channel'],[row['message']]);await self.system.maintenance()
  self.assertEqual(self.system.store.get(rid)['publication'],'missing');self.assertEqual(self.system.store.list(1),[])
  self.assertEqual(len(self.messages),1)
 async def test_persistent_buttons_survive_restart_and_mine_is_private(self):
  rid=await self.idea()
  for item in idea_controls(self.system.store.get(rid)).children:
   match=SuggestionAction.__discord_ui_compiled_template__.fullmatch(item.custom_id)
   restored=await SuggestionAction.from_custom_id(self.i,item,match);self.assertEqual(restored.rid,rid)
  await self.system.handle(self.i,'mine',0)
  result=self.i.response.send_message.call_args
  self.assertTrue(result.kwargs['ephemeral']);view=result.kwargs['view']
  self.assertFalse(await view.interaction_check(self.interaction(3)))
  self.assertEqual(result.kwargs['allowed_mentions'].to_dict()['parse'],[])
 async def test_forum_target_creates_separate_posts_and_reuses_existing_portal(self):
  forum=MagicMock(spec=discord.ForumChannel);forum.id=CHANNEL_ID;forum.guild=self.guild;forum.name='Sugerencias';forum.type=discord.ChannelType.forum
  forum._overwrites=self.base._overwrites;forum.permissions_for=self.base.permissions_for;forum.flags=discord.ChannelFlags();forum.available_tags=[]
  async def archived(**kwargs):
   if False:yield None
  forum.archived_threads=archived
  async def create(**kwargs):
   message=self.new_message(0,kwargs['embed'],kwargs['view']);message.channel_id=message.id
   thread=MagicMock(spec=discord.Thread);thread.id=message.id;thread.parent_id=CHANNEL_ID;thread.guild=self.guild
   thread.owner_id=99;thread.name=kwargs['name'];thread.fetch_message=AsyncMock(side_effect=self.fetch_message)
   self.channels[thread.id]=thread
   return SimpleNamespace(thread=thread,message=message)
  forum.create_thread=AsyncMock(side_effect=create);self.channels[CHANNEL_ID]=forum
  await self.system.ready();rid=await self.idea();self.system.prepared=False;await self.system.ready()
  self.assertEqual(forum.create_thread.await_count,2)
  row=self.system.store.get(rid);self.assertNotEqual(row['channel'],CHANNEL_ID);self.assertEqual(row['message'],row['channel'])
  self.assertEqual(len(self.messages),2)
