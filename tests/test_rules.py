from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,MagicMock

import discord

from rules_lookup import RulesLookup,RuleResults,CHANNEL_ID
from rules_search import sections,search,pages,normalize
from rule_topics import TOPICS,topic_for,TICKETS_CHANNEL

FIRST=1567278823324782854
SECOND=1567278835332812821
# Passages from the channel supplied by the owner, including its own VDM wording.
TEXT_ONE='''**1. Normativas generales de rol**
*1.* Valorar la vida (VDM): Tu personaje debe valorar su vida en todo momento. No puedes actuar como si fueras inmortal.
*2. *MetaGaming (MG): Está prohibido utilizar información obtenida fuera del juego para beneficio dentro del rol.
*3.* PowerGaming (PG): Prohibido realizar acciones irreales o imposibles dentro del rol.
*4. *DeathMatch (DM): Está prohibido agredir o asesinar a otros jugadores sin motivos de rol.
*5.* Vehicle DeathMatch (VDM): Prohibido utilizar vehículos como armas para atropellar intencionalmente a otros jugadores.

**2. Normativas de comportamiento**
*1. *Está prohibido insultar o faltar al respeto fuera del personaje (OOC).

**3. Normativas de enfrentamientos**
*1. *Toda agresión debe tener un motivo de rol válido.
*3.* Está prohibido regresar a un enfrentamiento después de morir.
*4.* No se puede recordar información de los últimos acontecimientos si se ha sufrido pérdida de memoria por muerte, según la normativa de PK.

**4. Normativas de secuestros**
*1.* Todo secuestro debe tener una justificación de rol.

**5. Normativas de vehículos**
*1.* Está prohibido conducir de manera irrealista.

**6. Normativas de zonas seguras**
*1.* Está prohibido iniciar enfrentamientos dentro de zonas seguras.'''
TEXT_TWO='''**7. Normativas de rol policial y EMS**
*1. *Se debe respetar la autoridad de los cuerpos policiales.

**8. Normativas de muerte y heridas**
*1.* Todo jugador debe interpretar las heridas de su personaje.
*2.* Está prohibido levantarse inmediatamente después de recibir disparos o sufrir accidentes graves.
*3. *Se debe respetar el estado de inconsciencia.
*4. *El jugador deberá respetar las condiciones de PK y CK establecidas por el servidor.
*5.* Está prohibido regresar a una situación de rol de la que se ha sido eliminado mediante PK.'''


def message(mid,content):return SimpleNamespace(id=mid,content=content,embeds=[],edit=AsyncMock(),delete=AsyncMock())


class ParserTests(unittest.TestCase):
 def setUp(self):self.rows=sections(message(FIRST,TEXT_ONE))+sections(message(SECOND,TEXT_TWO))
 def test_actual_markdown_yields_eight_whole_official_sections(self):
  self.assertEqual(len(self.rows),8)
  for row in self.rows:
   self.assertIn(row.body,TEXT_ONE if row.message==FIRST else TEXT_TWO)
  self.assertEqual(sections(message(3,'@everyone @here')),[])
 def test_ck_and_pk_quote_official_passages_instead_of_inventing_definitions(self):
  ck=search(self.rows,'ck');pk=search(self.rows,'pk')
  self.assertEqual(len(ck),1);self.assertEqual(ck[0].message,SECOND)
  self.assertEqual(ck[0].heading,'8. Normativas de muerte y heridas')
  self.assertNotIn('Character Kill',ck[0].body)
  self.assertEqual(len(pk),2);self.assertEqual(pk[0].message,SECOND)
  self.assertEqual(pk[1].heading,'3. Normativas de enfrentamientos')
 def test_short_abbreviations_do_not_match_other_words_or_other_rule_types(self):
  rows=sections(message(1,'**Reglas**\nEl parking está cerrado. Nunca mezcles las condiciones de PKT con otras normas.'))
  self.assertEqual(search(rows,'pk'),[])
  self.assertTrue(search(rows,'pkt'));self.assertEqual(search(self.rows,'PK TOTAL'),[])
  self.assertEqual(search(self.rows,'una regla inexistente'),[])
 def test_accents_fonts_punctuation_and_aliases_work(self):
  for query,heading in [('𝐂𝐊','8.'),('C.K.','8.'),('character kill','8.'),('vehiculo','5.'),('policía','7.'),('secuestro','4.'),('meta gaming','1.')]:
   self.assertTrue(search(self.rows,query)[0].heading.startswith(heading),query)
  self.assertEqual(normalize('𝐕𝐞𝐡í𝐜𝐮𝐥𝐨𝐬'),'vehiculos')
 def test_original_conflicting_terms_are_preserved_verbatim(self):
  result=search(self.rows,'VDM')[0]
  self.assertIn('Valorar la vida (VDM)',result.body);self.assertIn('Vehicle DeathMatch (VDM)',result.body)
 def test_embeds_are_searchable_and_long_sections_keep_their_final_conditions(self):
  embed=discord.Embed(title='Normas').add_field(name='CK',value='Texto oficial. Solo se permite con autorización del staff.')
  rows=sections(SimpleNamespace(id=7,content='',embeds=[embed]))
  self.assertEqual(search(rows,'ck')[0].body,'Texto oficial. Solo se permite con autorización del staff.')
  original=('Una condición de la norma.\n'*400)+'No se permite sin autorización del staff.'
  chunks=pages(original)
  self.assertGreater(len(chunks),1);self.assertTrue(all(len(c)<=3300 for c in chunks))
  self.assertTrue(chunks[-1].endswith('No se permite sin autorización del staff.'))
  self.assertEqual(' '.join(' '.join(chunks).split()),' '.join(original.split()))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.messages={FIRST:message(FIRST,TEXT_ONE),SECOND:message(SECOND,TEXT_TWO),3:message(3,'@everyone @here')}
  self.source=MagicMock(spec=discord.TextChannel);self.source.id=CHANNEL_ID;self.source.name='Info-Servidor'
  self.guild=SimpleNamespace(id=10,get_channel=lambda cid:self.source if cid==CHANNEL_ID else None)
  self.user=MagicMock(spec=discord.Member);self.user.id=1;self.user.guild=self.guild;self.user.bot=False;self.user.can_read=True;self.user.can_history=True
  self.guild.fetch_member=AsyncMock(return_value=self.user);self.source.guild=self.guild
  self.source.permissions_for=lambda member:discord.Permissions(view_channel=member.can_read,read_message_history=member.can_history)
  async def history(**kwargs):
   for item in list(self.messages.values()):yield item
  self.source.history=history
  def fetch(mid):
   if mid not in self.messages:raise discord.NotFound(SimpleNamespace(status=404,reason='Missing'),'missing')
   return self.messages[mid]
  self.source.fetch_message=AsyncMock(side_effect=fetch)
  registered=SimpleNamespace(name='regla',to_dict=lambda:dict(name='regla',options=[dict(name='tema',type=3,autocomplete=True)]))
  self.bot=SimpleNamespace(fetch_channel=AsyncMock(return_value=self.source),get_guild=lambda gid:self.guild,
    tree=SimpleNamespace(fetch_commands=AsyncMock(return_value=[registered])))
  self.system=RulesLookup(self.bot,10)
  self.i=SimpleNamespace(guild_id=10,user=self.user,response=SimpleNamespace(is_done=lambda:False,defer=AsyncMock(),send_message=AsyncMock()),
    followup=SimpleNamespace(send=AsyncMock()),edit_original_response=AsyncMock())
 def response(self):return self.i.response.send_message.call_args or self.i.followup.send.call_args
 async def test_command_returns_an_exact_passage_and_the_correct_original_link_privately(self):
  await self.system.command.callback(self.i,'zonas seguras')
  self.i.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
  response=self.response();embed=response.kwargs['embed'];view=response.kwargs['view']
  self.assertEqual(embed.description,search(self.system.index,'zonas seguras')[0].body)
  self.assertIn(str(FIRST),view.children[-1].url);self.assertEqual(len(view.children),1)
  self.assertTrue(response.kwargs['ephemeral']);self.assertEqual(response.kwargs['allowed_mentions'].to_dict()['parse'],[])
  for source in self.messages.values():source.edit.assert_not_awaited();source.delete.assert_not_awaited()
  self.source.set_permissions.assert_not_called();self.source.send.assert_not_called()
 async def test_pk_results_have_navigation_and_each_result_has_its_own_citation(self):
  await self.system.command.callback(self.i,'pk');view=self.response().kwargs['view']
  self.assertIsInstance(view,RuleResults);self.assertEqual(len(view.children),3)
  self.assertIn(str(SECOND),view.children[-1].url)
  await view.children[1].callback(self.i)
  result=self.i.edit_original_response.call_args.kwargs
  self.assertIn('enfrentamientos',result['embed'].title);self.assertIn(str(FIRST),view.children[-1].url)
 async def test_permission_checks_apply_to_lookup_pagination_and_autocomplete(self):
  await self.system.refresh();self.user.can_read=False
  with self.assertRaises(ValueError):await self.system.member(self.i)
  self.assertEqual(await self.system.autocomplete(self.i,'ck'),[])
  self.user.can_read=True;self.user.can_history=False
  with self.assertRaises(ValueError):await self.system.show(self.i,RuleResults(self.system,1,'ck'))
  self.user.can_history=True;self.i.guild_id=99
  with self.assertRaises(ValueError):await self.system.member(self.i)
 async def test_edits_are_checked_live_even_if_the_gateway_invalidation_event_was_missed(self):
  await self.system.refresh();self.assertTrue(search(self.system.index,'ems'))
  self.messages[SECOND].content='**8. Normativas de muerte y heridas**\nSe deben interpretar las heridas.'
  await self.system.command.callback(self.i,'ems')
  response=self.response();self.assertNotIn('embed',response.kwargs)
  self.assertIn('No encontré',response.args[0]);self.assertEqual(search(self.system.index,'ems'),[])
 async def test_deleted_source_and_bulk_edits_never_return_stale_rule_text(self):
  await self.system.refresh();self.messages.pop(SECOND)
  self.system.invalidate(10,CHANNEL_ID)
  self.assertEqual(await self.system.autocomplete(self.i,'EMS'),[])
  await self.system.command.callback(self.i,'ems')
  self.assertIn('No encontré',self.response().args[0]);self.assertNotIn('embed',self.response().kwargs)
 async def test_autocomplete_includes_official_and_owner_requested_topics(self):
  await self.system.refresh()
  choices=await self.system.autocomplete(self.i,'pk')
  self.assertIn('PK',[c.value for c in choices]);self.assertIn('PKT',[c.value for c in choices])
  self.assertEqual(search(self.system.index,'pkt'),[])
  self.assertEqual(await self.system.autocomplete(self.i,'nra'),[])
 async def test_failed_live_verification_never_falls_back_to_cached_text(self):
  await self.system.refresh()
  self.source.fetch_message.side_effect=discord.Forbidden(SimpleNamespace(status=403,reason='Forbidden'),'missing access')
  with self.assertLogs('LaVenganzaRP.rules',level='ERROR'):await self.system.command.callback(self.i,'ck')
  response=self.response();self.assertNotIn('embed',response.kwargs);self.assertIn('No pude comprobar',response.args[0])
 async def test_result_controls_are_bound_to_the_person_who_searched(self):
  view=RuleResults(self.system,99,'pk')
  self.assertFalse(await view.interaction_check(self.i))
  view.owner=1;self.assertTrue(await view.interaction_check(self.i))
 async def test_ready_reads_back_the_registered_command_and_real_ck_pk_sources(self):
  with self.assertLogs('LaVenganzaRP.rules',level='INFO') as logs:await self.system.ready()
  self.assertEqual(len(self.system.index),8);self.assertTrue(self.system.prepared)
  self.assertTrue(any('query_verified topic=ck' in line for line in logs.output))
  self.assertTrue(any('query_verified topic=pk' in line for line in logs.output))
  self.bot.tree.fetch_commands.assert_awaited_once()
  await self.system.ready();self.bot.tree.fetch_commands.assert_awaited_once()
 async def test_ck_and_pkt_have_their_own_explanations_without_rewriting_source_messages(self):
  originals={mid:source.content for mid,source in self.messages.items()}
  for query,key in [('CK','ck'),('PKT','pkt'),('qué significa un PKT','pkt'),('Character Kill','ck'),('PK TOTAL','pkt')]:
   self.i.response.send_message.reset_mock()
   await self.system.command.callback(self.i,query)
   response=self.response();embed=response.kwargs['embed']
   self.assertEqual(embed.title,'📚 '+TOPICS[key].heading)
   self.assertEqual(embed.description,TOPICS[key].body)
   self.assertIn('Explicación de administración',embed.footer.text)
   self.assertNotIn('Fuente oficial',[field.name for field in embed.fields])
   self.assertIn(str(TICKETS_CHANNEL),embed.description)
   self.assertTrue(response.kwargs['ephemeral'])
  self.assertEqual({mid:source.content for mid,source in self.messages.items()},originals)
  for source in self.messages.values():source.edit.assert_not_awaited();source.delete.assert_not_awaited()
 async def test_pk_keeps_its_original_search_and_is_not_treated_as_pkt(self):
  self.assertIsNone(topic_for('PK'));self.assertIsNone(topic_for('player kill'))
  self.assertIsNone(topic_for('CL'))
  self.assertEqual(topic_for('C.K.').key,'ck');self.assertEqual(topic_for('P.K.T.').key,'pkt')
  await self.system.command.callback(self.i,'PK')
  self.assertIn('muerte y heridas',self.response().kwargs['embed'].title)
  self.assertNotIn('Player Kill Total',self.response().kwargs['embed'].description)
 async def test_custom_topics_preserve_access_checks_and_can_use_a_channel_link_after_source_deletion(self):
  self.user.can_read=False
  for key in ('CK','PKT'):
   with self.assertRaises(ValueError):await self.system.show(self.i,RuleResults(self.system,1,key))
  self.user.can_read=True;await self.system.refresh();self.messages.pop(SECOND)
  await self.system.command.callback(self.i,'PKT')
  response=self.response()
  self.assertIn('PKT',response.kwargs['embed'].title)
  self.assertTrue(response.kwargs['view'].children[0].url.endswith(str(CHANNEL_ID)))
 async def test_ready_verifies_both_approved_explanations(self):
  with self.assertLogs('LaVenganzaRP.rules',level='INFO') as logs:await self.system.ready()
  self.assertTrue(any('explanation_verified topic=ck' in line for line in logs.output))
  self.assertTrue(any('explanation_verified topic=pkt' in line for line in logs.output))
