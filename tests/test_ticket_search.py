from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,MagicMock

import discord
from tickets import TicketSystem
from tickets_store import NORMAL_STAFF


class PlayerSearchTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.bot=MagicMock();self.bot.user.id=99
  self.system=TicketSystem(self.bot,Path(tmp.name)/'db.sqlite3',10)
  self.store=self.system.store;self.store.initialize()
  self.channels=[];self.stamp=1000
  self.guild=SimpleNamespace(id=10,fetch_channels=AsyncMock(side_effect=lambda:self.channels))
  self.bot.get_guild.return_value=self.guild
  self.staff=SimpleNamespace(id=5,guild=self.guild,roles=[SimpleNamespace(id=rid) for rid in NORMAL_STAFF],guild_permissions=discord.Permissions())
  self.player=SimpleNamespace(id=1)
  self.i=MagicMock(user=self.staff,guild_id=10)
  self.i.response.is_done.return_value=False;self.i.response.defer=AsyncMock();self.i.response.send_message=AsyncMock();self.i.followup.send=AsyncMock()

 def case(self,owner=1,department='soporte',closed=True,excluded=None,form=None,assigned=None):
  self.stamp+=61
  rid=self.store.create(owner,department,f'Caso {self.stamp}',form or {},excluded=excluded,now=self.stamp)
  self.store.update(rid,status='nuevo',channel=100+rid,control_message=500+rid,assignee=assigned)
  if closed:self.store.transition(rid,'cerrado',6,f'SOLUCION_{rid}')
  self.channels.append(MagicMock(spec=discord.TextChannel,id=100+rid,topic=f'lv-ticket:{rid}'))
  return rid

 def response(self):return self.i.response.send_message.call_args.kwargs

 async def test_history_shows_responsible_and_solution_privately_without_granting_access(self):
  rid=self.case(assigned=7)
  self.store.note(rid,6,'NOTA_INTERNA_QUE_NO_DEBE_SALIR')
  self.system.access=AsyncMock()
  command=self.system.group.get_command('buscar')
  await command.callback(self.i,self.player)
  response=self.response();embed=response['embed']
  self.assertTrue(response['ephemeral']);self.assertFalse(response['allowed_mentions'].everyone)
  self.assertIn('<@1>',embed.description);self.assertIn(f'#{rid}',embed.fields[0].name)
  self.assertIn('<@7>',embed.fields[0].value);self.assertIn(f'SOLUCION\\_{rid}',embed.fields[0].value)
  self.assertIn('<@6>',embed.fields[0].value)
  self.assertNotIn('NOTA_INTERNA',str(embed.to_dict()))
  self.system.access.assert_not_awaited()
  self.assertEqual([o.value for o in response['view'].children[0].options],[str(rid)])

 async def test_reserved_excluded_other_players_deleted_missing_and_tests_are_filtered_before_counts(self):
  visible=self.case()
  reserved=self.case(department='staff')
  self.case(owner=2)
  self.case(excluded=5)
  deleted=self.case();self.store.mark_deleted(deleted,6)
  missing=self.case();self.channels=[c for c in self.channels if c.id!=100+missing]
  foreign=self.case();next(c for c in self.channels if c.id==100+foreign).topic='otro canal'
  self.case(form={'selftest':'hidden'})
  await self.system.show_list(self.i,player=self.player)
  response=self.response()
  self.assertIn('**1**',response['embed'].description)
  self.assertEqual([o.value for o in response['view'].children[0].options],[str(visible)])
  self.assertNotIn(f'#{reserved}',str(response['embed'].to_dict()))
  self.i.user=SimpleNamespace(id=8,guild=self.guild,roles=[],guild_permissions=discord.Permissions(administrator=True))
  await self.system.show_list(self.i,player=self.player)
  values=[o.value for o in self.response()['view'].children[0].options]
  self.assertIn(str(reserved),values);self.assertNotIn(str(deleted),values)

 async def test_department_reviewer_only_sees_their_cases_and_no_hidden_totals(self):
  self.case(department='soporte')
  shop=self.case(department='tienda')
  self.case(department='staff')
  self.store.config('route:tienda','[123]')
  self.i.user=SimpleNamespace(id=8,guild=self.guild,roles=[SimpleNamespace(id=123)],guild_permissions=discord.Permissions())
  await self.system.show_list(self.i,player=self.player)
  self.assertIn('**1**',self.response()['embed'].description)
  self.assertEqual([o.value for o in self.response()['view'].children[0].options],[str(shop)])

 async def test_citizens_and_other_guilds_cannot_search_even_their_own_history(self):
  self.case()
  self.i.user=SimpleNamespace(id=1,guild=self.guild,roles=[],guild_permissions=discord.Permissions())
  with self.assertRaisesRegex(ValueError,'staff'):await self.system.show_list(self.i,player=self.player)
  self.guild.fetch_channels.assert_not_awaited();self.i.response.send_message.assert_not_awaited()
  self.i.user=self.staff;self.i.guild_id=11
  with self.assertRaisesRegex(ValueError,'La Venganza'):await self.system.show_list(self.i,player=self.player)
  self.guild.fetch_channels.assert_not_awaited()

 async def test_pagination_is_after_access_filtering_and_long_solutions_fit_discord(self):
  expected=[]
  for n in range(6):
   expected.append(self.case())
   self.case(department='staff')
  for rid in expected:self.store.update(rid,resolution='*Texto muy largo* '*300)
  await self.system.show_list(self.i,player=self.player)
  response=self.response();embed=response['embed']
  self.assertIn('**6**',embed.description);self.assertEqual(len(embed.fields),5)
  self.assertLessEqual(len(embed),6000);self.assertTrue(all(len(f.value)<=1024 for f in embed.fields))
  first_values=[o.value for o in response['view'].children[0].options]
  await self.system.show_list(self.i,player=self.player,page=2)
  last_values=[o.value for o in self.response()['view'].children[0].options]
  self.assertEqual(set(first_values+last_values),set(map(str,expected)))
  self.assertFalse(set(first_values)&set(last_values))
  self.assertIn('pagina:3',self.response()['embed'].footer.text)

 async def test_transfer_during_fetch_is_filtered_and_stale_selection_cannot_bypass_access(self):
  rid=self.case(closed=False)
  async def fetch():
   self.store.transfer(rid,'staff',8,'Solo administradores')
   return self.channels
  self.guild.fetch_channels.side_effect=fetch
  await self.system.show_list(self.i,player=self.player)
  self.assertIn('**0**',self.response()['embed'].description)
  self.assertFalse(self.response()['view'].children)
  # A previously returned menu also rechecks the current department when clicked.
  from tickets_ui import CasePicker
  picker=CasePicker(self.system,[self.store.get(rid)],True);picker._values=[str(rid)]
  self.system.access=AsyncMock();self.system.channel=AsyncMock()
  await picker.callback(self.i)
  self.system.access.assert_not_awaited();self.system.channel.assert_not_awaited()

 async def test_staff_response_without_claim_is_identified_and_owner_or_bot_is_not_guessed(self):
  rid=self.case(closed=False)
  msg=SimpleNamespace(id=900,author=SimpleNamespace(id=8,display_name='Staff'),content='Ya lo reviso',embeds=[],created_at=datetime.now(timezone.utc),edited_at=None)
  self.store.message(rid,msg);self.store.activity(rid,8,True,message_id=900)
  await self.system.show_list(self.i,player=self.player)
  self.assertIn('**Atendió:** <@8>',self.response()['embed'].fields[0].value)
  self.assertEqual(self.store.attended_by(rid,99),8)
  msg.id=901;msg.author.id=99;self.store.message(rid,msg);self.store.activity(rid,99,True,message_id=901)
  self.assertIsNone(self.store.attended_by(rid,99))

