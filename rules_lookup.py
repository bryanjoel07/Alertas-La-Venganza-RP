"""Private /regla search over the owner's rules channel; Discord is read-only."""
from settings_catalog import value as setting
import asyncio
import logging
import time

import discord
from discord import app_commands

from rules_search import sections,search,pages,fingerprint,normalize,ALIASES
from rule_topics import TOPICS,topic_for

CHANNEL_ID=1528925322362228787
RED=0xD60000
NONE=discord.AllowedMentions.none()
log=logging.getLogger('LaVenganzaRP.rules')


async def reply(i,content=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(content,ephemeral=True,allowed_mentions=NONE,**kwargs)


class RuleResults(discord.ui.View):
 def __init__(self,system,owner,query,page=0):
  super().__init__(timeout=300)
  self.system,self.owner,self.query,self.page=system,owner,query,page
 async def interaction_check(self,i):
  if i.user.id==self.owner and i.guild_id==self.system.guild_id:return True
  await reply(i,'Usa /regla para abrir tu propia búsqueda, bro.');return False
 async def on_error(self,i,error,item):await self.system.failed(i,error)
 def build(self,total,url):
  self.clear_items()
  navigation=[('Anterior',-1,self.page==0),('Siguiente',1,self.page>=total-1)] if total>1 else []
  for label,step,disabled in navigation:
   button=discord.ui.Button(label=label,disabled=disabled)
   async def turn(i,step=step):
    await i.response.defer()
    self.page+=step
    await self.system.show(i,self,edit=True)
   button.callback=turn;self.add_item(button)
  self.add_item(discord.ui.Button(label='Ver mensaje oficial',emoji='📚',url=url))


class RulesLookup:
 def __init__(self,bot,guild_id):
  self.bot,self.guild_id=bot,guild_id
  self.source_id=CHANNEL_ID;self.cache_seconds=300
  self.index=();self.loaded_at=0;self.generation=0;self.invalid=True
  self.lock=asyncio.Lock();self.ready_lock=asyncio.Lock();self.prepared=False;self.task=None
  @app_commands.command(name='regla',description='Buscar una norma de La Venganza y abrir su mensaje oficial')
  @app_commands.describe(tema='Qué buscas: CK, PK, PKT, secuestros, vehículos, zonas seguras…')
  @app_commands.guild_only()
  async def command(i,tema:app_commands.Range[str,1,100]):
   await i.response.defer(ephemeral=True,thinking=True)
   try:
    await self.show(i,RuleResults(self,i.user.id,tema))
   except Exception as error:await self.failed(i,error)
  @command.autocomplete('tema')
  async def complete(i,current):return await self.autocomplete(i,current)
  self.command=command
 async def start(self):
  panel=getattr(self.bot,'settings_panel',None)
  if panel is not None:
   self.source_id=await asyncio.to_thread(setting,panel.store.path,'rules','source_channel')
   self.cache_seconds=60*await asyncio.to_thread(setting,panel.store.path,'rules','cache_minutes')
  if self.task is None or self.task.done():self.task=asyncio.create_task(self.loop(),name='official-rules-search')
 async def channel(self):
  source=await self.bot.fetch_channel(self.source_id)
  if not isinstance(source,discord.TextChannel) or source.guild.id!=self.guild_id:
   raise ValueError('No encuentro el canal oficial de normas esperado.')
  return source
 def invalidate(self,guild,channel):
  if guild==self.guild_id and channel==self.source_id:
   self.invalid=True;self.generation+=1
 async def member(self,i):
  if i.guild_id!=self.guild_id:raise ValueError('Consulta las normas dentro de La Venganza RP.')
  guild=self.bot.get_guild(self.guild_id)
  if guild is None:raise ValueError('El bot se está conectando. Inténtalo en un momento.')
  member=i.user if isinstance(i.user,discord.Member) and i.user.guild.id==self.guild_id else await guild.fetch_member(i.user.id)
  if member.bot:raise ValueError('Este buscador es para los jugadores.')
  source=await self.channel()
  effective=source.permissions_for(member)
  if not effective.view_channel or not effective.read_message_history:
   raise ValueError('Necesitas poder ver el canal de normas y leer su historial para consultarlo.')
  return source
 async def refresh(self,force=False):
  async with self.lock:
   if not force and not self.invalid and self.loaded_at and time.monotonic()-self.loaded_at<self.cache_seconds:return
   for attempt in range(2):
    generation=self.generation;source=await self.channel()
    messages=[m async for m in source.history(limit=None,oldest_first=True)]
    updated=tuple(section for message in messages for section in sections(message))
    if generation!=self.generation:continue
    self.index=updated;self.loaded_at=time.monotonic();self.invalid=False
    log.info('RULES index_verified channel=%s messages=%s sections=%s source_ids=%s discord_mutations=0',
      source.id,len(messages),len(updated),sorted({s.message for s in updated}))
    return
   raise ValueError('El staff está actualizando las normas ahora mismo. Inténtalo otra vez en un momento.')
 def matching_pages(self,query):
  return [(section,part,n+1,len(parts)) for section in search(self.index,query)
    for parts in [pages(section.body)] for n,part in enumerate(parts)]
 async def show(self,i,view,edit=False):
  source=await self.member(i)
  await self.refresh()
  if source.id!=self.source_id:raise ValueError('El canal de normas cambió durante la consulta. Abre la búsqueda otra vez.')
  explanation=topic_for(view.query)
  if explanation:return await self.show_explanation(i,source,explanation,edit=edit)
  selected=None
  for attempt in range(3):
   matches=self.matching_pages(view.query)
   if not matches:
    if attempt==0:await self.refresh(force=True);continue
    break
   view.page=max(0,min(view.page,len(matches)-1));section,part,number,total=matches[view.page]
   try:message=await source.fetch_message(section.message)
   except discord.NotFound:
    self.invalidate(self.guild_id,self.source_id);await self.refresh(force=True);continue
   if fingerprint(message)!=section.fingerprint:
    self.invalidate(self.guild_id,self.source_id);await self.refresh(force=True);continue
   selected=section,part,number,total,len(matches);break
  if selected is None:
   if matches:raise ValueError('El staff está actualizando esa norma. Vuelve a consultar en un momento.')
   query=discord.utils.escape_mentions(discord.utils.escape_markdown(view.query))
   content=f'No encontré una norma que coincida con **{query}**, bro. Prueba otra palabra o revisa el canal de normas.'
   fallback=discord.ui.View(timeout=None)
   fallback.add_item(discord.ui.Button(label='Abrir normas',url=f'https://discord.com/channels/{self.guild_id}/{self.source_id}'))
   if edit:await i.edit_original_response(content=content,embed=None,view=fallback,allowed_mentions=NONE)
   else:await reply(i,content,view=fallback)
   return
  section,part,number,total,count=selected
  if source.id!=self.source_id:raise ValueError('El canal de normas cambió durante la consulta. Abre la búsqueda otra vez.')
  url=f'https://discord.com/channels/{self.guild_id}/{self.source_id}/{section.message}'
  embed=discord.Embed(title=f'📚 {section.heading}'[:256],color=RED,
    description=discord.utils.escape_mentions(part))
  embed.add_field(name='Fuente oficial',value=f'[Abrir el mensaje original]({url})',inline=False)
  embed.set_footer(text=f'La Venganza RP · Resultado {view.page+1}/{count}'+(f' · Parte {number}/{total}' if total>1 else ''))
  view.build(count,url)
  if edit:await i.edit_original_response(content=None,embed=embed,view=view,allowed_mentions=NONE)
  else:await reply(i,embed=embed,view=view)
  log.info('RULES result_verified query=%s source=%s section=%s page=%s/%s private=True',normalize(view.query),section.message,section.key,view.page+1,count)
 async def show_explanation(self,i,source,topic,edit=False):
  # This link is context for the approved explanation, rather than a quotation source.
  url=f'https://discord.com/channels/{self.guild_id}/{self.source_id}'
  reference=next((row for row in search(self.index,'pk') if 'muerte' in normalize(row.heading)),None)
  if reference:
   try:message=await source.fetch_message(reference.message)
   except discord.NotFound:
    self.invalidate(self.guild_id,self.source_id)
    await self.refresh(force=True)
   else:
    url+=f'/{message.id}'
    if fingerprint(message)!=reference.fingerprint:self.invalidate(self.guild_id,self.source_id)
  embed=discord.Embed(title=f'📚 {topic.heading}',description=topic.body,color=RED)
  if source.id!=self.source_id:raise ValueError('El canal de normas cambió durante la consulta. Abre la búsqueda otra vez.')
  embed.add_field(name='Reglamento del servidor',value=f'[Consultar las normas publicadas]({url})',inline=False)
  embed.set_footer(text='La Venganza RP · Explicación de administración')
  controls=discord.ui.View(timeout=None)
  controls.add_item(discord.ui.Button(label='Ver normas',emoji='📚',url=url))
  if edit:await i.edit_original_response(content=None,embed=embed,view=controls,allowed_mentions=NONE)
  else:await reply(i,embed=embed,view=controls)
  log.info('RULES explanation_served topic=%s owner_requested=True private=True',topic.key)
 async def autocomplete(self,i,current):
  if i.guild_id!=self.guild_id or self.invalid:return []
  guild=self.bot.get_guild(self.guild_id)
  source=guild.get_channel(self.source_id) if guild else None
  if source is None or not isinstance(i.user,discord.Member):return []
  permission=source.permissions_for(i.user)
  if not permission.view_channel or not permission.read_message_history:return []
  choices=[];seen=set();query=normalize(current)
  topics=[key.upper() if len(key)<=3 else key for key in ALIASES if key in TOPICS or search(self.index,key)]
  topics.extend(section.heading for section in self.index)
  for topic in topics:
   if topic in seen or query and query not in normalize(topic):continue
   seen.add(topic);choices.append(app_commands.Choice(name=topic[:100],value=topic[:100]))
   if len(choices)==25:break
  return choices
 async def failed(self,i,error):
  if isinstance(error,ValueError):return await reply(i,str(error))
  log.error('RULES lookup_failed',exc_info=error)
  await reply(i,'No pude comprobar las normas ahora mismo, bro. Inténtalo otra vez en un momento.')
 async def ready(self):
  async with self.ready_lock:
   if self.prepared:return
   await self.refresh(force=True)
   source=await self.channel()
   for query in ('ck','pk'):
    hits=search(self.index,query)
    if not hits:
     log.info('RULES query_not_present topic=%s source=%s',query,self.source_id);continue
    first=hits[0];message=await source.fetch_message(first.message)
    if fingerprint(message)!=first.fingerprint:raise RuntimeError('Las normas cambiaron durante la verificación inicial.')
    log.info('RULES query_verified topic=%s results=%s first_message=%s first_heading=%s original_text=True',query,len(hits),first.message,first.heading)
   registered=await self.bot.tree.fetch_commands(guild=discord.Object(id=self.guild_id))
   command=next((c.to_dict() for c in registered if c.name=='regla'),{})
   if not any(p['name']=='tema' and p['type']==3 and p.get('autocomplete') for p in command.get('options',[])):
    raise RuntimeError('Discord no confirmó /regla con su buscador de temas.')
   for key,topic in TOPICS.items():
    if topic_for(key) is not topic or len(topic.body)>4096:raise RuntimeError('No se confirmó la explicación solicitada para '+key)
    log.info('RULES explanation_verified topic=%s title=%s separate_topic=True owner_requested=True channel_messages_unchanged=True',key,topic.heading)
   self.prepared=True
   log.info('RULES ready channel=%s sections=%s command=/regla autocomplete=True private=True live_source_verified=True roles_unchanged=True messages_unchanged=True',self.source_id,len(self.index))
 async def loop(self):
  await self.bot.wait_until_ready()
  while not self.bot.is_closed():
   try:
    if not self.prepared:await self.ready()
    else:await self.refresh()
   except Exception:log.exception('RULES refresh_pending; source messages preserved')
   await asyncio.sleep(60)
