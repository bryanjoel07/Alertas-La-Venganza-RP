"""Community ideas in the requested channel, with durable votes and admin decisions."""
import asyncio
from datetime import datetime,timezone
import logging
import time

import discord
from discord import app_commands

from suggestion_store import SuggestionStore,STATES,CLOSED
from suggestion_ui import SuggestionAction,IdeaForm,StateForm,MyIdeas,DeleteIdea,panel_controls,idea_controls,reply,failed,NONE
import suggestion_delete
from tickets_store import PROTECTED

CHANNEL_ID=1539013973947588759
PORTAL_MARKER='La Venganza RP · Sugerencias'
RED=0xD60000
log=logging.getLogger('LaVenganzaRP.suggestions')


def text(value):return discord.utils.escape_mentions(discord.utils.escape_markdown(value))

def marker(message):
 return str(message.embeds[0].footer.text or '') if message.embeds else ''

def idea_marker(rid):return f'La Venganza RP · Idea #{rid} · '

def message_state(message):
 return dict(id=message.id,author=message.author.id,content=message.content,pinned=message.pinned,
   embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components])


class SuggestionSystem:
 def __init__(self,bot,path,guild_id):
  self.bot,self.guild_id=bot,guild_id;self.store=SuggestionStore(path)
  self.locks={};self.install_lock=asyncio.Lock();self.prepared=False;self.task=None
  self.group=app_commands.Group(name='sugerencias',description='Proponer ideas, votar y seguir lo que decide administración',guild_only=True)
  self.register()
 async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
 def lock(self,rid):return self.locks.setdefault(rid,asyncio.Lock())
 async def start(self):
  if self.task is not None and not self.task.done():return
  await self.call('initialize');self.bot.add_dynamic_items(SuggestionAction)
  self.task=asyncio.create_task(self.loop(),name='community-suggestions')
 async def target(self):
  channel=await self.bot.fetch_channel(CHANNEL_ID)
  if not isinstance(channel,(discord.TextChannel,discord.ForumChannel,discord.Thread)) or channel.guild.id!=self.guild_id:
   raise ValueError('No encuentro el canal de Sugerencias esperado. No se cambiará ningún otro canal.')
  return channel
 async def member(self,i,admin=False):
  if i.guild_id!=self.guild_id:raise ValueError('Usa las sugerencias dentro de La Venganza RP.')
  guild=self.bot.get_guild(self.guild_id)
  if not guild:raise ValueError('El bot se está conectando. Inténtalo en un momento.')
  member=i.user if not admin and isinstance(i.user,discord.Member) and i.user.guild.id==self.guild_id else await guild.fetch_member(i.user.id)
  if member.bot:raise ValueError('Las sugerencias son para los jugadores.')
  base=guild.get_channel_or_thread(CHANNEL_ID)
  if base is None:base=await self.target()
  if not base.permissions_for(member).view_channel or not base.permissions_for(member).read_message_history:
   raise ValueError('Necesitas acceso al canal de Sugerencias para usar este sistema.')
  if admin and not (member.guild_permissions.administrator or {r.id for r in member.roles}&PROTECTED):
   raise ValueError('Solo Owner, Programador y administradores pueden gestionar las ideas.')
  return member
 def embed(self,row):
  emoji,label=STATES[row['status']]
  embed=discord.Embed(title=f"💡 Idea #{row['id']} · {text(row['title'])}"[:256],color=RED,
    description=f"Propuesta por <@{row['owner']}>\n\n{text(row['description'])}")
  if row['benefit']:embed.add_field(name='¿En qué ayudaría?',value=text(row['benefit'])[:1024],inline=False)
  embed.add_field(name='Estado',value=f'{emoji} {label}')
  embed.add_field(name='Votos',value=f"👍 {row['up']} a favor · 👎 {row['down']} en contra")
  if row['reason']:
   embed.add_field(name='Respuesta de administración',value=text(row['reason'])[:1024],inline=False)
   embed.add_field(name='Actualizada por',value=f"<@{row['decided_by']}>")
  embed.set_footer(text=idea_marker(row['id'])+('Votación cerrada' if row['status'] in CLOSED else 'Un voto por persona'))
  return embed
 def portal_embed(self):
  return discord.Embed(title='💡 TUS IDEAS PARA LA VENGANZA',color=RED,description=
    '¿Qué te gustaría mejorar o añadir? Pulsa **Proponer una idea** y cuéntanos.\n\n'
    '**Así funciona**\n'
    '• Cada idea se publica con tu nombre y sus botones de votos.\n'
    '• Puedes votar a favor o en contra, cambiar tu voto o quitarlo.\n'
    '• Administración revisa las ideas y deja una respuesta para que todos sepan cómo van.\n'
    '• Solo administración puede eliminar una idea; siempre se pide confirmación.\n\n'
    '**Estados**\n🕓 Pendiente · ✅ Aceptada · 🛠️ En proceso · 🎉 Hecha · ❌ Rechazada\n\n'
    'Los votos ayudan a decidir. Al quedar hecha o rechazada, se cierra su votación. '
    'Envía una idea por formulario y revisa las que ya están para evitar repetirlas.').set_footer(text=PORTAL_MARKER)
 async def location(self,channel_id):
  channel=await self.bot.fetch_channel(channel_id)
  valid=channel.id==CHANNEL_ID or isinstance(channel,discord.Thread) and channel.parent_id==CHANNEL_ID
  if channel.guild.id!=self.guild_id or not valid or not isinstance(channel,(discord.TextChannel,discord.Thread)):
   raise ValueError('La publicación no pertenece al canal de Sugerencias.')
  return channel
 async def card(self,row,*,allow_deleting=False):
  if not row or row['publication'] not in (('published','missing','deleting') if allow_deleting else ('published',)) or not row['message']:
   raise ValueError('La idea todavía se está publicando o ya no está disponible.')
  channel=await self.location(row['channel']);message=await channel.fetch_message(row['message'])
  if message.author.id!=self.bot.user.id or not marker(message).startswith(idea_marker(row['id'])):
   raise ValueError('Esta publicación no pertenece al sistema de sugerencias del bot.')
  return channel,message
 async def find_idea(self,row):
  base=await self.target()
  return await self.find(base,idea_marker(row['id']),row['created'],row['id'])
 async def snapshot(self,rid=None):
  value=dict(channel=CHANNEL_ID,portal_channel=self.store.config('portal_channel'),portal_message=self.store.config('portal_message'))
  if rid:
   row=self.store.get(rid);value.update(suggestion=row,decisions=self.store.events(rid))
   if row and row['publication']=='published':
    try:
     _,message=await self.card(row);value['message']=message_state(message)
    except discord.NotFound:value['message_missing']=True
  else:
   base=await self.target()
   citizen=base.guild.get_role(1245009164070158409)
   value.update(name=base.name,type=str(base.type),citizen_permissions=str(citizen.permissions.value) if citizen else None,
     overwrites=[dict(id=o.id,type=o.type,allow=str(o.allow),deny=str(o.deny)) for o in getattr(base,'_overwrites',())])
   if value['portal_message']:
    try:
     location=await self.location(int(value['portal_channel']))
     value['message']=message_state(await location.fetch_message(int(value['portal_message'])))
    except discord.NotFound:value['message_missing']=True
  return value
 async def tracked(self,rid,title,operation):
  return await self.bot.changes.tracked('COMMUNITY_SUGGESTIONS',title,operation,
    request_id=f'{rid or "portal"}:{time.time_ns()}',snapshot=lambda:self.snapshot(rid))
 async def find(self,base,expected,created=0,rid=None):
  if isinstance(base,discord.ForumChannel):
   active=[t for t in await base.guild.active_threads() if t.parent_id==base.id]
   archived=[t async for t in base.archived_threads(limit=None)]
   for thread in {t.id:t for t in [*active,*archived]}.values():
    if thread.owner_id!=self.bot.user.id:continue
    if expected==PORTAL_MARKER and not thread.name.startswith('💡 Cómo proponer'):continue
    if rid is not None and not thread.name.startswith(f"💡 #{rid} ·"):continue
    try:message=await thread.fetch_message(thread.id)
    except discord.NotFound:continue
    if message.author.id==self.bot.user.id and marker(message).startswith(expected):return thread,message
  else:
   after=datetime.fromtimestamp(max(0,created-120),timezone.utc) if created else None
   async for message in base.history(limit=None,after=after):
    if message.author.id==self.bot.user.id and marker(message).startswith(expected):return base,message
  return None
 async def send(self,base,name,embed,view):
  if isinstance(base,discord.ForumChannel):
   tags=[]
   if base.flags.require_tag:
    tags=[next((tag for tag in base.available_tags if 'pendiente' in tag.name.casefold() or 'idea' in tag.name.casefold()),base.available_tags[0] if base.available_tags else None)]
    if tags==[None]:raise ValueError('El foro exige una etiqueta, pero no tiene ninguna disponible.')
   result=await base.create_thread(name=name[:100],embed=embed,view=view,applied_tags=tags,allowed_mentions=NONE,
     reason='Nueva publicación del sistema de sugerencias solicitado por el dueño')
   return result.thread,result.message
  return base,await base.send(embed=embed,view=view,allowed_mentions=NONE)
 async def ready(self):
  async with self.install_lock:
   if self.prepared:return
   base=await self.target()
   citizen=base.guild.get_role(1245009164070158409)
   if citizen and isinstance(base,(discord.TextChannel,discord.ForumChannel)):
    fields=('view_channel','read_message_history','use_application_commands')
    if not all(getattr(base.permissions_for(citizen),key) for key in fields):
     async def grant_access():
      current=await self.target();overwrite=current.overwrites_for(citizen)
      before=[(o.id,o.type,o.allow,o.deny) for o in current._overwrites if (o.id,o.type)!=(citizen.id,0)]
      original=overwrite.pair();role_bits=citizen.permissions.value
      for key in fields:setattr(overwrite,key,True)
      await current.set_permissions(citizen,overwrite=overwrite,reason='Permitir a Ciudadanos usar el panel de Sugerencias solicitado por el dueño')
      verified=await self.target();actual=verified.overwrites_for(citizen);mask=discord.Permissions(**dict.fromkeys(fields,True)).value
      after=[(o.id,o.type,o.allow,o.deny) for o in verified._overwrites if (o.id,o.type)!=(citizen.id,0)]
      if (not all(getattr(verified.permissions_for(citizen),key) for key in fields) or before!=after
        or citizen.permissions.value!=role_bits or any(a.value&~mask!=b.value&~mask for a,b in zip(original,actual.pair()))):
       raise RuntimeError('No se confirmó el acceso de Ciudadanos conservando los otros permisos.')
     await self.tracked(None,'Dar a Ciudadanos acceso al panel de Sugerencias',grant_access)
     base=await self.target()
   saved=self.store.config('portal_message');found=None
   if saved:
    try:
     location=await self.location(int(self.store.config('portal_channel')))
     message=await location.fetch_message(int(saved))
     if message.author.id!=self.bot.user.id or marker(message)!=PORTAL_MARKER:
      raise ValueError('El mensaje guardado no es el panel de Sugerencias de este bot.')
     found=location,message
    except discord.NotFound:pass
   if found is None:found=await self.find(base,PORTAL_MARKER)
   async def install():
    nonlocal found
    if found is None:found=await self.send(base,'💡 Cómo proponer una idea',self.portal_embed(),panel_controls())
    else:await found[1].edit(embed=self.portal_embed(),view=panel_controls(),allowed_mentions=NONE)
    location,message=found
    self.store.config('portal_channel',location.id);self.store.config('portal_message',message.id)
    if isinstance(base,discord.TextChannel) and not message.pinned:
     await message.pin(reason='Mantener a mano el panel de Sugerencias')
   await self.tracked(None,'Instalar el panel de sugerencias con votos',install)
   location,message=found;verified=await location.fetch_message(message.id)
   ids=[c.custom_id for group in verified.components for c in group.children]
   if verified.author.id!=self.bot.user.id or marker(verified)!=PORTAL_MARKER or ids!=['lvsug:new:0','lvsug:mine:0']:
    raise RuntimeError('Discord no confirmó el panel de Sugerencias y sus botones.')
   form=IdeaForm(self);state=StateForm(self,dict(id=0,status='pendiente',reason='',status_version=0))
   if len(form.to_dict()['components'])!=3 or len(state.to_dict()['components'])!=2:raise RuntimeError('No se confirmaron los formularios de Sugerencias.')
   await self.upgrade_delete_controls()
   self.prepared=True
   citizens=base.guild.get_role(1245009164070158409)
   log.info('SUGGESTIONS ready channel=%s type=%s panel_channel=%s panel_message=%s controls=%s forms=idea:3,state:2 states=%s citizen_view=%s citizen_history=%s admin_roles=%s protected_roles_unchanged=True citizen_write_unchanged=True legacy_messages_preserved=True',
     base.id,str(base.type),location.id,message.id,ids,list(STATES),base.permissions_for(citizens).view_channel if citizens else None,
     base.permissions_for(citizens).read_message_history if citizens else None,sorted(PROTECTED))
   log.info('SUGGESTIONS deletion_ready admin_only=True confirmation=True hard_delete_tables=3 source_ids_never_reused=True persistent_retry=True command=/sugerencias eliminar')
 async def upgrade_delete_controls(self):
  if self.store.config('delete_controls_version')=='1':return
  for rid in await self.call('published'):
   async with self.lock(rid):
    row=self.store.get(rid)
    if not row or row['publication']!='published':continue
    async def update():return await self.render(rid)
    try:
     await self.tracked(rid,f'Añadir Eliminar idea a la sugerencia #{rid}',update)
     log.info('SUGGESTIONS delete_controls_verified id=%s admin_only=True',rid)
    except discord.NotFound:await self.call('missing',row['channel'],[row['message']])
  self.store.config('delete_controls_version','1')
 async def publish(self,rid):
  row=self.store.get(rid)
  if not row:return None
  if row['publication']=='published':return await self.render(rid)
  if row['publication'] in ('missing','deleting') or not await self.call('acquire',rid):return None
  base=await self.target()
  found=await self.find(base,idea_marker(rid),row['created'],rid)
  async def publish():
   nonlocal found
   if found is None:
    latest=self.store.get(rid)
    found=await self.send(base,f"💡 #{rid} · {latest['title']}",self.embed(latest),idea_controls(latest))
   await self.call('bind',rid,found[0].id,found[1].id)
   return await self.render(rid)
  return await self.tracked(rid,f'Publicar sugerencia #{rid}',publish)
 async def render(self,rid):
  row=self.store.get(rid);location,message=await self.card(row)
  row=self.store.get(rid);expected=self.embed(row);view=idea_controls(row)
  await message.edit(embed=expected,view=view,allowed_mentions=NONE)
  verified=await location.fetch_message(message.id)
  actual=verified.embeds[0] if verified.embeds else None
  fields=lambda embed:[(f.name,f.value,f.inline) for f in embed.fields]
  buttons=lambda msg:[(c.custom_id,c.label,c.disabled) for group in msg.components for c in group.children]
  desired=[(c.custom_id,c.item.label,c.item.disabled) for c in view.children]
  if (verified.author.id!=self.bot.user.id or not actual or marker(verified)!=expected.footer.text
    or actual.title!=expected.title or actual.description!=expected.description or fields(actual)!=fields(expected) or buttons(verified)!=desired):
   raise RuntimeError('Discord todavía no confirmó los votos y el estado de la idea.')
  if not await self.call('acknowledge',rid,row['revision']):raise RuntimeError('La idea cambió durante la actualización; se volverá a sincronizar.')
  log.info('SUGGESTIONS card_verified id=%s status=%s up=%s down=%s revision=%s message=%s',rid,row['status'],row['up'],row['down'],row['revision'],message.id)
  return verified
 def link(self,row):
  return f"https://discord.com/channels/{self.guild_id}/{row['channel']}/{row['message']}" if row['channel'] and row['message'] else ''
 async def submit(self,i,title,description,benefit):
  member=await self.member(i)
  rid=await self.call('create',str(i.id),member.id,title,description,benefit)
  async with self.lock(rid):
   try:await self.publish(rid)
   except Exception:log.exception('SUGGESTIONS publication_pending id=%s; preserving request for recovery',rid)
  row=self.store.get(rid)
  await reply(i,f"Tu idea **#{rid}** ya está publicada, bro.\n{self.link(row)}" if row['publication']=='published' else f'Tu idea **#{rid}** quedó guardada, bro. Discord está tardando; el bot terminará de publicarla. Puedes verla en **Mis ideas**.')
 async def vote(self,i,rid,value):
  await self.member(i)
  async with self.lock(rid):
   row=self.store.get(rid)
   if not row or i.channel_id!=row['channel'] or not i.message or i.message.id!=row['message']:
    raise ValueError('Usa los votos de la publicación original de esa idea.')
   changed=await self.call('vote',rid,i.user.id,value)
   synchronized=True
   try:await self.render(rid)
   except discord.NotFound:
    await self.call('missing',row['channel'],[row['message']]);raise ValueError('La publicación de esa idea ya no está disponible.') from None
   except Exception:
    synchronized=False;log.exception('SUGGESTIONS vote_render_pending id=%s',rid)
  message=('Quitaste tu voto.' if value==0 else 'Tu voto quedó a favor.' if value==1 else 'Tu voto quedó en contra.') if changed else ('No tenías un voto que quitar.' if value==0 else 'Ya tenías ese voto, bro.')
  if not synchronized:message+=' Está guardado; los botones se actualizarán en un momento.'
  await reply(i,message)
 async def decide(self,i,rid,status,reason,expected):
  admin=await self.member(i,admin=True)
  async with self.lock(rid):
   if not self.store.get(rid):raise ValueError('Esa idea no existe.')
   async def decide():
    await self.call('decide',rid,status,admin.id,reason,expected)
    try:await self.render(rid)
    except (discord.HTTPException,RuntimeError):log.exception('SUGGESTIONS decision_render_pending id=%s',rid)
   await self.tracked(rid,f'Cambiar el estado de la sugerencia #{rid}',decide)
   row=self.store.get(rid)
  pending=row['revision']!=row['rendered']
  await reply(i,f"La idea **#{rid}** quedó como **{STATES[row['status']][1]}**."+(' Está guardado; la publicación se actualizará en un momento.' if pending else ' Ya se ve tu explicación en la publicación.'))
 async def mine(self,i,page=0,edit=False):
  await self.member(i)
  rows=await self.call('list',i.user.id,11,max(0,page)*10)
  if not rows and page>0:return await self.mine(i,page-1,edit)
  view=MyIdeas(self,i.user.id,max(0,page));view.next.disabled=len(rows)<=10
  embed=discord.Embed(title='📋 Mis ideas',color=RED)
  lines=[]
  for row in rows[:10]:
   label=f"#{row['id']} · {text(row['title'])}"
   link=self.link(row)
   lines.append((f'**[{label}]({link})**' if link else f'**{label}**')+f"\n{STATES[row['status']][0]} {STATES[row['status']][1]}"+(' · Preparando publicación' if row['publication']!='published' else ''))
  embed.description='\n\n'.join(lines) or 'Todavía no has enviado una idea. Pulsa **Proponer una idea** para empezar.'
  embed.set_footer(text=f'Página {max(0,page)+1}')
  if edit:await i.edit_original_response(embed=embed,view=view,allowed_mentions=NONE)
  else:await reply(i,embed=embed,view=view)
 async def handle(self,i,action,rid):
  if action=='new':
   await self.member(i);return await i.response.send_modal(IdeaForm(self))
  if action=='state':
   await self.member(i,admin=True);row=self.store.get(rid)
   if not row or row['publication']!='published':raise ValueError('Esa idea ya no está disponible.')
   return await i.response.send_modal(StateForm(self,row))
  await i.response.defer(ephemeral=True,thinking=True)
  if action=='delete':return await self.prepare_delete(i,rid)
  if action=='mine':return await self.mine(i)
  await self.vote(i,rid,{'up':1,'down':-1,'clear':0}[action])
 async def prepare_delete(self,i,rid):
  await self.member(i,admin=True)
  row=self.store.get(rid)
  if not row:raise ValueError('Esa idea ya fue eliminada o no existe.')
  message=(f"¿Eliminar la idea **#{rid} · {text(row['title'])}**?\n"
    'Se borrará su publicación de Discord y la idea con sus votos y respuestas de administración del sistema. '
    'No se puede deshacer desde este panel. Se conservará una copia interna de respaldo.')
  if row['channel'] and row['channel']==row['message']:message+=' También se borrarán los comentarios de esa publicación.'
  await reply(i,message,embed=self.embed(row),view=DeleteIdea(self,i.user.id,row))
 async def delete_idea(self,i,expected):return await suggestion_delete.delete(self,i,expected)
 async def deleted(self,guild,channel,messages=None):
  if guild!=self.guild_id:return
  await self.call('missing',channel,messages)
  if (messages is None and str(channel)==self.store.config('portal_channel')) or (messages and str(channel)==self.store.config('portal_channel') and int(self.store.config('portal_message') or 0) in messages):
   self.prepared=False
 async def maintenance(self):
  await suggestion_delete.recover(self)
  for rid in await self.call('pending'):
   try:
    async with self.lock(rid):await self.publish(rid)
   except discord.NotFound:
    row=self.store.get(rid)
    if row and row['publication']=='published':await self.call('missing',row['channel'],[row['message']])
    log.warning('SUGGESTIONS missing_publication id=%s; record preserved',rid)
   except Exception:log.exception('SUGGESTIONS retry_pending id=%s; continuing other ideas',rid)
 async def loop(self):
  await self.bot.wait_until_ready()
  while not self.bot.is_closed():
   try:await self.ready();await self.maintenance()
   except Exception:log.exception('SUGGESTIONS background_error; existing messages preserved')
   await asyncio.sleep(60)
 def register(self):
  @self.group.command(name='proponer',description='Cuéntanos una idea para La Venganza')
  async def propose(i):await self.handle(i,'new',0)
  @self.group.command(name='mis',description='Ver las ideas que has enviado y su estado')
  async def mine(i):await self.handle(i,'mine',0)
  @self.group.command(name='ver',description='Consultar una idea por su número')
  async def show(i,numero:app_commands.Range[int,1]):
   await i.response.defer(ephemeral=True,thinking=True);await self.member(i)
   row=self.store.get(numero)
   if not row or row['publication'] in ('missing','deleting'):raise ValueError('Esa idea no está disponible.')
   await reply(i,self.link(row) or 'La idea está guardada y preparando su publicación.',embed=self.embed(row))
  @self.group.command(name='eliminar',description='Solo administración: eliminar una idea del sistema y de Discord')
  async def remove(i,numero:app_commands.Range[int,1]):await self.handle(i,'delete',numero)
  @self.group.error
  async def error(i,exc):await failed(i,getattr(exc,'original',exc))
