"""Advanced private tickets. Existing tickets and protected roles are never modified."""
import asyncio
from contextlib import suppress
import hashlib
import html
import io
import json
import logging
import os
from pathlib import Path
import re
import time

import discord
from discord import app_commands
from tickets_store import TicketStore,DEPARTMENTS,STATES,PROTECTED,NORMAL_STAFF,ALL_STAFF
from tickets_ui import TicketPanel,TicketAction,TicketControls,TextForm,ChoiceView,CasePicker,reply

log=logging.getLogger('LaVenganzaRP.tickets')
PANEL_CHANNEL=1513423707467415642
OLD_CATEGORY=1567093946419777546
CLOSED_NAME='│・ 🔒┊ 𝐓𝐢𝐜𝐤𝐞𝐭𝐬 𝐂𝐞𝐫𝐫𝐚𝐝𝐨𝐬'
ACTIVE_NAME='│・ 🎫┊ 𝐓𝐢𝐜𝐤𝐞𝐭𝐬 𝐀𝐜𝐭𝐢𝐯𝐨𝐬'
STATE_LABELS={'creando':'Preparando','nuevo':'Nuevo','en_atencion':'En atención','esperando_jugador':'Esperando al jugador',
 'resuelto':'Resuelto','cerrado':'Cerrado','fallido':'Creación fallida'}


def route_roles(store,department):
 if department=='staff':return set()
 raw=store.config('route:'+department)
 return NORMAL_STAFF|({int(v) for v in json.loads(raw)} if raw else set())


def can_staff(member,row,store):
 if row.get('excluded')==member.id and not member.guild_permissions.administrator:return False
 if member.guild_permissions.administrator:return True
 if row['department']=='staff':return False
 return bool({r.id for r in member.roles}&(ALL_STAFF|route_roles(store,row['department'])))


def channel_overwrites(guild,row,store,owner,people=(),staff=()):
 closed=row['status']=='cerrado'
 perms={guild.default_role:discord.PermissionOverwrite(view_channel=False,send_messages=False,
        create_public_threads=False,create_private_threads=False,send_messages_in_threads=False),
        guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True,
        attach_files=True,embed_links=True,manage_channels=True,manage_messages=True)}
 def access(member,write=True):
  if member.id==row.get('excluded') and not member.guild_permissions.administrator:return
  perms[member]=discord.PermissionOverwrite(view_channel=True,send_messages=write and not closed,
    read_message_history=True,attach_files=write and not closed,embed_links=write and not closed,
    use_application_commands=True,create_public_threads=False,create_private_threads=False,send_messages_in_threads=False)
 access(owner)
 for member in people:access(member)
 for member in staff:access(member)
 for role in guild.roles:
  # No overwrite is created or edited for Owner/Programador/Admin/Súper Admin.
  if role.id in PROTECTED:continue
  if role.id in route_roles(store,row['department']):
   perms[role]=discord.PermissionOverwrite(view_channel=True,send_messages=not closed,read_message_history=True,
      attach_files=not closed,embed_links=not closed,use_application_commands=True,
      create_public_threads=False,create_private_threads=False,send_messages_in_threads=False)
 if row.get('excluded') and row['excluded']!=row['owner']:
  target=discord.Object(id=row['excluded'],type=discord.Member)
  perms[target]=discord.PermissionOverwrite(view_channel=False,send_messages=False,read_message_history=False)
 return perms


def transcript_html(row,messages,files):
 entries=[]
 files_by_message={}
 for f in files:files_by_message.setdefault(f['message'],[]).append(f)
 for m in messages:
  body=html.escape(m['content'])
  if m['embeds']!='[]':body+='\n'+html.escape(m['embeds'])
  attachments=''.join('<li>'+html.escape(f['filename'])+' · '+html.escape(f['state'])+' · SHA-256 '+html.escape(f['sha256'] or 'pendiente')+'</li>' for f in files_by_message.get(m['message'],[]))
  entries.append(f"<article><h3>{html.escape(m['name'])} · {m['author']}</h3><small>{html.escape(m['created'])}"+
     (' · ELIMINADO' if m['deleted'] else '')+(' · EDITADO' if m['edited'] else '')+f"</small><pre>{body}</pre><ul>{attachments}</ul></article>")
 return '<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Ticket '+str(row['id'])+'</title><style>body{background:#171719;color:#eee;font:16px sans-serif;max-width:900px;margin:auto;padding:24px}article{border-left:3px solid #d60000;padding:12px;margin:16px 0;background:#252529}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#bbb}</style><h1>La Venganza RP · Ticket #'+str(row['id'])+'</h1><p>'+html.escape(row['subject'])+'</p><pre>'+html.escape(json.dumps(json.loads(row['form']),ensure_ascii=False,indent=2))+'</pre><p>Resolución: '+html.escape(row['resolution'] or 'Sin resolución registrada')+'</p>'+''.join(entries)+'</html>'

class TicketSystem:
 def __init__(self,bot,path,guild_id):
  self.bot,self.guild_id=bot,guild_id;self.store=TicketStore(path)
  self.lock=asyncio.Lock();self.ready_lock=asyncio.Lock();self.file_lock=asyncio.Semaphore(2)
  self.task=None;self.prepared=False
  self.group=app_commands.Group(name='ticket',description='Atención, gestión y seguimiento de tickets')
  self.register()
 async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
 async def start(self):
  await self.call('initialize');self.bot.add_view(TicketPanel(self));self.bot.add_dynamic_items(TicketAction)
  self.task=asyncio.create_task(self.loop(),name='advanced-tickets')
 def enabled(self):return os.getenv('TICKETS_ENABLED')=='1'
 def authorize(self,member,row,staff=False):
  if member.guild.id!=self.guild_id:raise ValueError('Este sistema pertenece a La Venganza RP.')
  if row['department']=='staff' and member.id!=row['owner'] and not member.guild_permissions.administrator:
   raise ValueError('Este reporte está reservado para su autor y administradores de Discord.')
  permitted=can_staff(member,row,self.store)
  if staff and not permitted:raise ValueError('Solo el personal autorizado para este caso puede realizar esa acción.')
  if row.get('excluded')==member.id and not member.guild_permissions.administrator:raise ValueError('No tienes acceso a este caso.')
  if not staff and not permitted and member.id!=row['owner'] and member.id not in self.store.people(row['id']):
   raise ValueError('No tienes acceso a este caso.')
  return permitted
 def admin(self,member):
  if member.guild.id!=self.guild_id or not member.guild_permissions.administrator:raise ValueError('Esta configuración requiere Administrador de Discord.')
 async def channel(self,row):
  if not row['channel']:raise ValueError('El canal de este ticket todavía está en preparación. El staff puede usar /ticket recuperar.')
  channel=await self.bot.fetch_channel(row['channel'])
  if channel.guild.id!=self.guild_id or not isinstance(channel,discord.TextChannel) or channel.topic!=f"lv-ticket:{row['id']}":raise ValueError('Ese canal no está identificado como un ticket gestionado por este bot.')
  return channel
 async def member(self,guild,uid):
  try:return guild.get_member(uid) or await guild.fetch_member(uid)
  except discord.NotFound:return None
 def embed(self,row):
  emoji,label,_=DEPARTMENTS[row['department']]
  embed=discord.Embed(title=f"{emoji} Ticket #{row['id']} · {label}",color=0xD60000,description=discord.utils.escape_markdown(row['subject']))
  embed.add_field(name='Estado',value=STATE_LABELS.get(row['status'],row['status']))
  embed.add_field(name='Responsable',value=f"<@{row['assignee']}>" if row['assignee'] else 'Pendiente de asignación')
  embed.add_field(name='Prioridad',value=row['priority'])
  for key,value in json.loads(row['form']).items():
   if value:embed.add_field(name=key.capitalize(),value=discord.utils.escape_markdown(value)[:1024],inline=False)
  if row.get('purchase_id'):embed.add_field(name='Compra vinculada',value=f"`{row['purchase_id']}` · Staff puede consultar /ticket compra",inline=False)
  if row.get('resolution'):embed.add_field(name='Resolución',value=discord.utils.escape_markdown(row['resolution'])[:1024],inline=False)
  if row['department']=='staff':embed.add_field(name='Privacidad',value='Caso reservado. Los usuarios con Administrador en Discord conservan acceso técnico.',inline=False)
  embed.set_footer(text=f"Autor ID {row['owner']} · Usa los controles del ticket · No compartas contraseñas ni datos de tarjeta")
  return embed
 async def refresh(self,row):
  channel=await self.channel(row)
  message=None
  if row['control_message']:
   with suppress(discord.NotFound):message=await channel.fetch_message(row['control_message'])
  if message:await message.edit(embed=self.embed(row),view=TicketControls(row['id'],row['status']=='cerrado'))
  else:
   async for old in channel.history(limit=100,oldest_first=True):
    if old.author.id==self.bot.user.id and any(e.title and e.title.startswith(f"{DEPARTMENTS[row['department']][0]} Ticket #{row['id']} ·") for e in old.embeds):
     message=old;break
   if message:await message.edit(embed=self.embed(row),view=TicketControls(row['id'],row['status']=='cerrado'))
   else:message=await channel.send(embed=self.embed(row),view=TicketControls(row['id'],row['status']=='cerrado'),allowed_mentions=discord.AllowedMentions.none())
   await self.call('update',row['id'],control_message=message.id)
 async def ensure_category(self,guild,closed=False):
  key='closed_category' if closed else 'active_category'
  saved=self.store.config(key)
  channels=await guild.fetch_channels()
  category=next((c for c in channels if str(c.id)==saved and isinstance(c,discord.CategoryChannel)),None)
  if not closed and not category:
   # Reuse the existing Tickets category without altering any of its permissions.
   category=next((c for c in channels if c.id==OLD_CATEGORY and isinstance(c,discord.CategoryChannel)),None)
  name=CLOSED_NAME if closed else ACTIVE_NAME
  if not category:
   candidates=[c for c in channels if isinstance(c,discord.CategoryChannel) and c.name==name]
   if len(candidates)>1:raise ValueError('Hay categorías de tickets duplicadas; no se creará otra.')
   category=candidates[0] if candidates else None
  if category and sum(c.category_id==category.id for c in channels)<48:
   self.store.config(key,category.id);return category
  if category:
   overflow=[c for c in channels if isinstance(c,discord.CategoryChannel) and c.name.startswith(name+' ') and sum(child.category_id==c.id for child in channels)<48]
   if overflow:
    category=overflow[-1];self.store.config(key,category.id);return category
  suffix='' if not category else f" {len([c for c in channels if isinstance(c,discord.CategoryChannel) and c.name.startswith(name)])+1}"
  perms={guild.default_role:discord.PermissionOverwrite(view_channel=False),guild.me:discord.PermissionOverwrite(view_channel=True,manage_channels=True,manage_roles=True)}
  async def create_category():
   created=await guild.create_category(name+suffix,overwrites=perms,reason='Categoría de tickets solicitada por administración')
   anchor=next((c for c in channels if str(c.id)==self.store.config('active_category') and isinstance(c,discord.CategoryChannel)),None)
   if closed and anchor:
    await created.edit(position=anchor.position+1,reason='Colocar cerrados junto a los tickets activos')
    created=await self.bot.fetch_channel(created.id)
   return created
  category=await self.bot.changes.tracked('TICKET_CATEGORY','Crear categoría de tickets',create_category,request_id=f'{key}:{time.time_ns()}')
  self.store.config(key,category.id)
  log.info('TICKETS category_verified key=%s id=%s name=%s',key,category.id,category.name)
  return category
 async def snapshot(self,row):
  current=self.store.get(row['id'])
  value=dict(ticket=current)
  if current['channel']:
   with suppress(discord.NotFound):
    c=await self.channel(current)
    value['channel']=dict(id=str(c.id),parent=str(c.category_id),overwrites=[dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny)) for o in c._overwrites])
  return value
 async def tracked(self,row,title,operation):
  return await self.bot.changes.tracked('TICKET_OPERATION',title,operation,
      request_id=f"{row['id']}:{time.time_ns()}",snapshot=lambda:self.snapshot(row))
 async def move(self,row,category,reason):
  channel=await self.channel(row)
  async def change():return await channel.edit(category=category,sync_permissions=False,reason=reason)
  return await self.tracked(row,f"Mover ticket #{row['id']}",change)
 async def apply_permissions(self,row):
  channel=await self.channel(row);guild=channel.guild
  owner=await self.member(guild,row['owner'])
  if not owner:owner=discord.Object(id=row['owner'],type=discord.Member)
  people=[];staff=[]
  for uid in self.store.people(row['id']):
   member=await self.member(guild,uid)
   if member and (row['department']!='staff' or member.guild_permissions.administrator):people.append(member)
  if row['assignee']:
   member=await self.member(guild,row['assignee'])
   if member and can_staff(member,row,self.store):staff.append(member)
  # Preserve explicitly granted reviewers, provided they are still authorized.
  for target in channel.overwrites:
   if isinstance(target,discord.Member) and target.id not in (row['owner'],self.bot.user.id):
    if can_staff(target,row,self.store):staff.append(target)
  permissions=channel_overwrites(guild,row,self.store,owner,people,staff)
  permissions.update({target:overwrite for target,overwrite in channel.overwrites.items() if isinstance(target,discord.Role) and target.id in PROTECTED})
  async def change():
   return await channel.edit(overwrites=permissions,reason='Aplicar privacidad del ticket sin modificar roles protegidos')
  await self.tracked(row,f"Accesos del ticket #{row['id']}",change)
 async def access(self,member,row):
  row=self.store.get(row['id'])
  self.authorize(member,row,staff=True)
  if member.guild_permissions.administrator:return
  channel=await self.channel(row)
  overwrite=channel.overwrites_for(member)
  overwrite.view_channel=True;overwrite.read_message_history=True;overwrite.send_messages=row['status']!='cerrado'
  overwrite.attach_files=row['status']!='cerrado';overwrite.use_application_commands=True
  async def change():return await channel.set_permissions(member,overwrite=overwrite,reason='Acceso individual del responsable autorizado; roles intactos')
  await self.tracked(row,f"Acceso individual ticket #{row['id']}",change)
 async def call_purchase_list(self,user):
  return await asyncio.to_thread(self.bot.economy.store.rows,'SELECT id,name,status,price FROM eco_purchases WHERE buyer=? OR recipient=? ORDER BY created DESC LIMIT 24',(user,user))
 async def open(self,i,department,subject,form,excluded=None,purchase=None):
  if not self.enabled():raise ValueError('El nuevo sistema todavía no está habilitado.')
  if i.guild_id!=self.guild_id:raise ValueError('Abre el ticket en La Venganza RP.')
  if purchase:
   rows=await asyncio.to_thread(self.bot.economy.store.rows,'SELECT id FROM eco_purchases WHERE id=? AND (buyer=? OR recipient=?)',(purchase,i.user.id,i.user.id))
   if not rows:raise ValueError('Esa compra no te pertenece.')
  if excluded and not await self.member(i.guild,excluded):
   form=dict(form,reportado_id=str(excluded));excluded=None
  async with self.lock:
   rid=await self.call('create',i.user.id,department,subject,form,excluded,purchase)
   row=self.store.get(rid)
   try:
    category=await self.ensure_category(i.guild)
    async def create_channel():
     created=await i.guild.create_text_channel(f'🎫┊𝐭𝐢𝐜𝐤𝐞𝐭-{rid:04d}',category=category,topic=f'lv-ticket:{rid}',
       overwrites=channel_overwrites(i.guild,row,self.store,i.user),reason=f'Ticket #{rid} solicitado por el jugador')
     await self.call('update',rid,channel=created.id,status='nuevo')
     return created
    channel=await self.tracked(row,f'Crear ticket #{rid}',create_channel)
    await self.refresh(self.store.get(rid))
   except (discord.Forbidden,discord.NotFound) as error:
    await self.call('update',rid,status='creando' if self.store.get(rid)['channel'] else 'fallido');raise ValueError(f'No se pudo crear el ticket #{rid}; el staff debe revisar los permisos del bot.') from error
   except Exception:
    log.exception('TICKETS creation_pending id=%s',rid)
    raise ValueError(f'El ticket #{rid} quedó reservado. El staff puede revisar /ticket recuperar; no abras otro del mismo tema.') from None
  try:await self.notify_new(self.store.get(rid),channel)
  except discord.HTTPException:log.warning('TICKETS notification_pending id=%s',rid)
  await reply(i,f'✅ Tu ticket está listo: <#{channel.id}>. Envía allí capturas o archivos. No menciones a todo el servidor.')
  log.info('TICKETS opened id=%s department=%s channel=%s',rid,department,channel.id)
 async def notify_new(self,row,channel):
  if row['department']=='staff':
   ids={r.id for r in channel.guild.roles if r.id in PROTECTED and r.permissions.administrator}
  else:
   raw=self.store.config('route:'+row['department'])
   ids={int(v) for v in json.loads(raw)} if raw else NORMAL_STAFF
  roles=[r for r in channel.guild.roles if r.id in ids]
  mentions=' '.join(f'<@&{r.id}>' for r in roles)
  await channel.send(f"{mentions} Nuevo caso #{row['id']} pendiente de asignación.",allowed_mentions=discord.AllowedMentions(roles=roles,users=False,everyone=False))
 async def show_list(self,i,own=False,page=1):
  if not i.response.is_done():await i.response.defer(ephemeral=True)
  coordinator=any({r.id for r in i.user.roles}&route_roles(self.store,department) for department in DEPARTMENTS)
  if not own and not (i.user.guild_permissions.administrator or {r.id for r in i.user.roles}&ALL_STAFF or coordinator):raise ValueError('Panel reservado para el staff.')
  # Fetch beyond one department then filter BEFORE displaying anything, including statistics.
  all_rows=await self.call('list',owner=i.user.id if own else None,limit=10000)
  visible=[r for r in all_rows if (own or can_staff(i.user,r,self.store)) and not json.loads(r['form']).get('selftest')]
  visible=sorted(visible,key=lambda r:(r['status']=='cerrado',-r['id']))
  rows=visible[(page-1)*25:page*25]
  lines=[f"**#{r['id']}** · {DEPARTMENTS[r['department']][1]} · {STATE_LABELS.get(r['status'],r['status'])} · "+(f"<#{r['channel']}>" if r['channel'] else 'Preparando') for r in rows]
  embed=discord.Embed(title='📂 Mis tickets' if own else '🧰 Gestión de tickets',description='\n'.join(lines) or 'No hay casos en esta página.',color=0xD60000)
  if not own:
   active=[r for r in visible if r['status'] not in ('cerrado','fallido','creando')]
   responses=[r['first_response']-r['created'] for r in visible if r['first_response']]
   ratings=[r['rating'] for r in visible if r['rating'] is not None]
   embed.add_field(name='Seguimiento',value=f"Activos: {len(active)} · Sin responsable: {sum(not r['assignee'] for r in active)}\n"+
       (f"Primera respuesta media: {sum(responses)/len(responses)/60:.0f} min" if responses else 'Primera respuesta: sin datos')+
       (f" · Valoración: {sum(ratings)/len(ratings):.1f}/5" if ratings else ''),inline=False)
  embed.set_footer(text=f'Página {page} · /ticket gestion pagina:{page+1}' if not own else f'Página {page} · /ticket mis pagina:{page+1}')
  view=discord.ui.View(timeout=180)
  if rows:view.add_item(CasePicker(self,rows,not own))
  await reply(i,embed=embed,view=view)
 async def record(self,rid,actor,action,detail):
  def save():
   with self.store.db() as db:self.store.event(db,rid,actor,action,detail)
  await asyncio.to_thread(save)
 async def archive(self,row):
  channel=await self.channel(row)
  async for message in channel.history(limit=None,oldest_first=True):
   await self.capture(row,message,notify=False)
  files=await self.call('files',row['id'])
  text=transcript_html(row,await self.call('messages',row['id']),files)
  state='completo' if all(f['state']=='guardado' for f in files) else 'parcial'
  await self.call('update',row['id'],transcript=text,archive_state=state)
  return state
 async def capture(self,row,message,notify=True):
  await self.call('message',row['id'],message)
  previous={f['attachment']:f for f in await self.call('files',row['id'])}
  for attachment in message.attachments:
   if previous.get(attachment.id,{}).get('state')=='guardado':continue
   await self.call('file',row['id'],message.id,attachment.id,attachment.filename,attachment.url,attachment.size)
   try:
    if attachment.size>int(self.store.config('max_file_mb'))*1048576:raise ValueError(f"El archivo supera el máximo de {self.store.config('max_file_mb')} MB por prueba.")
    async with self.file_lock:
     try:data=await attachment.read()
     except discord.HTTPException:data=await attachment.read(use_cached=True)
    await self.call('save_blob',row['id'],attachment.id,data)
   except (discord.HTTPException,ValueError,asyncio.TimeoutError) as error:
    await self.call('file',row['id'],message.id,attachment.id,attachment.filename,attachment.url,attachment.size,state='no_respaldado')
    if notify:await message.channel.send(f"⚠️ La prueba `{discord.utils.escape_markdown(attachment.filename)[:100]}` no quedó respaldada. "+(str(error) if isinstance(error,ValueError) else 'Vuelve a adjuntarla para reintentar.'),allowed_mentions=discord.AllowedMentions.none())
    log.warning('TICKETS proof_incomplete ticket=%s attachment=%s error_type=%s status=%s reason=%s',row['id'],attachment.id,type(error).__name__,getattr(error,'status',None),str(error) if isinstance(error,ValueError) else 'CDN download failed')
 async def observe(self,message):
  if not self.enabled() or not message.guild or message.guild.id!=self.guild_id or message.author.bot:return
  row=await self.call('get',channel=message.channel.id)
  if not row:return
  async with self.lock:
   await self.call('activity',row['id'],message.author.id,can_staff(message.author,row,self.store))
  await self.capture(row,message)
  if row['status']=='cerrado':await self.call('update',row['id'],archive_state='pendiente_actualizacion')
 async def close(self,row,actor,reason):
  self.store.transition(row['id'],'cerrado',actor,reason)
  row=self.store.get(row['id'])
  channel=await self.channel(row)
  try:
   await self.apply_permissions(row)
   category=await self.ensure_category(channel.guild,True)
   await self.move(row,category,'Conservar ticket cerrado y su historial')
   await self.refresh(row)
   state=await self.archive(row)
  except Exception:
   self.store.update(row['id'],archive_state='pendiente')
   log.exception('TICKETS close_recovery_required id=%s',row['id']);raise
  await channel.send(f"🔒 Ticket cerrado. Resolución: {discord.utils.escape_markdown(reason)[:1200]}\nTranscripción y pruebas: **{state}**. El autor puede valorar o solicitar reapertura desde los controles.",
    view=TicketControls(row['id'],True),allowed_mentions=discord.AllowedMentions.none())
  owner=await self.member(channel.guild,row['owner'])
  if owner and not owner.bot:
   with suppress(discord.Forbidden):await owner.send(f"Tu ticket #{row['id']} de La Venganza RP fue cerrado.\nResolución: {discord.utils.escape_markdown(reason)[:1000]}\nPuedes valorarlo o reabrirlo en <#{channel.id}>.",allowed_mentions=discord.AllowedMentions.none())
 async def reopen(self,i,row,reason):
  self.authorize(i.user,row)
  if row['status']!='cerrado':raise ValueError('Ese ticket sigue abierto.')
  if not can_staff(i.user,row,self.store) and (i.user.id!=row['owner'] or time.time()-(row['closed'] or 0)>7*86400):raise ValueError('El autor puede reabrir durante siete días; después debe solicitarlo al staff.')
  self.store.transition(row['id'],'en_atencion',i.user.id,'Reapertura: '+reason)
  row=self.store.get(row['id']);channel=await self.channel(row)
  await self.apply_permissions(row)
  category=await self.ensure_category(channel.guild)
  await self.move(row,category,'Reabrir el mismo ticket conservando su historial')
  await self.refresh(row)
  await reply(i,f"Ticket #{row['id']} reabierto: <#{channel.id}>.")
 async def export(self,i,row,proof=None):
  row=self.store.get(row['id'])
  self.authorize(i.user,row)
  if proof is not None:
   files=await self.call('files',row['id'])
   target=next((f for f in files if f['attachment']==proof),None)
   if not target:raise ValueError('Archivo no encontrado en este caso.')
   data=await self.call('blob',row['id'],proof)
   if data is None:raise ValueError('Esta prueba no está respaldada. Revisa el mensaje original o vuelve a adjuntarla.')
   limit=min(i.guild.filesize_limit,8*1048576)-1024
   chunks=(len(data)+limit-1)//limit
   for index in range(chunks):
    suffix=f'.part{index+1:03d}' if chunks>1 else ''
    await reply(i,('Archivo dividido; une las partes en orden para recuperar el original.' if chunks>1 else None),file=discord.File(io.BytesIO(data[index*limit:(index+1)*limit]),filename=Path(target['filename']).name[:100]+suffix))
   return
  # Live tickets are exported from the saved messages, including already deleted messages.
  await self.archive(row)
  fresh=self.store.get(row['id'])
  data=fresh['transcript'].encode()
  await reply(i,f"Transcripción del ticket #{row['id']}. Respaldo de pruebas: {fresh['archive_state']}. Las notas internas están excluidas.",
    file=discord.File(io.BytesIO(data),filename=f'ticket-{row["id"]}.html'))
 async def action(self,i,rid,action):
  row=await self.call('get',rid)
  if not row:raise ValueError('Ese ticket no existe.')
  if i.guild_id!=self.guild_id:raise ValueError('Usa los controles en La Venganza RP.')
  self.authorize(i.user,row,staff=action in ('claim','wait','resolve','note','transfer','priority','people'))
  if action=='close' and not(can_staff(i.user,row,self.store) or i.user.id==row['owner']):raise ValueError('Solo el autor o el staff pueden cerrar.')
  if action in ('close','resolve','wait','note','reopen'):
   async def submit(click,value):
    async with self.lock:
     current=self.store.get(rid)
     self.authorize(click.user,current,staff=action in ('resolve','wait','note'))
     if action=='close':await self.close(current,click.user.id,value);return await reply(click,'Ticket cerrado y archivado; conserva su canal e historial.')
     if action=='reopen':return await self.reopen(click,current,value)
     if action=='note':
      await self.call('note',rid,click.user.id,value);return await reply(click,'Nota interna guardada. El jugador no la verá en su transcripción.')
     state='resuelto' if action=='resolve' else 'esperando_jugador'
     await self.call('transition',rid,state,click.user.id,value)
     channel=await self.channel(current)
     await channel.send(('✅ Resolución propuesta: ' if action=='resolve' else '📎 Información o pruebas solicitadas: ')+discord.utils.escape_markdown(value),allowed_mentions=discord.AllowedMentions.none())
     await self.refresh(self.store.get(rid));await reply(click,'Estado actualizado.')
   return await i.response.send_modal(TextForm({'close':'Cerrar ticket','resolve':'Resolver ticket','wait':'Solicitar información','note':'Nota interna privada','reopen':'Reabrir ticket'}[action],
      'Motivo o resolución' if action!='note' else 'Nota (solo personal autorizado)',submit))
  if action=='transfer':
   async def transfer_form(click,value):
    self.authorize(click.user,self.store.get(rid),staff=True)
    def chosen(inner,department):return self.transfer(inner,rid,department,value)
    options=[discord.SelectOption(label=label,emoji=emoji,value=key) for key,(emoji,label,_) in DEPARTMENTS.items() if row['department']!='staff' or key=='staff']
    await reply(click,'Elige el departamento de destino.',view=ChoiceView(options,chosen,'Departamento de destino'))
   return await i.response.send_modal(TextForm('Transferir caso','Motivo de la transferencia',transfer_form))
  if action=='people':return await reply(i,'Usa `/ticket participante` para añadir o retirar una persona. Cada cambio queda registrado. Los reportes contra staff solo permiten participantes que sean administradores.')
  if action=='priority':
   async def change_priority(click,value):
    parts=value.split(':',1)
    if len(parts)!=2 or parts[0].strip() not in ('normal','alta','urgente') or not parts[1].strip():raise ValueError('Escribe normal, alta o urgente, seguido de dos puntos y un motivo.')
    self.authorize(click.user,self.store.get(rid),staff=True)
    await self.call('update',rid,priority=parts[0].strip());await self.record(rid,click.user.id,'prioridad',value)
    await self.refresh(self.store.get(rid));await reply(click,'Prioridad registrada.')
   return await i.response.send_modal(TextForm('Cambiar prioridad','Ejemplo: alta: problema de acceso',change_priority))
  if action=='rate':
   if i.user.id!=row['owner'] or row['status']!='cerrado':raise ValueError('Solo el autor puede valorar un ticket cerrado.')
   async def rate_form(click,value):
    parts=value.split(':',1)
    try:score=int(parts[0].strip())
    except ValueError:raise ValueError('Escribe una puntuación de 1 a 5, seguida de dos puntos y tu comentario.')
    await self.call('rate',rid,click.user.id,score,parts[1].strip() if len(parts)>1 else '')
    await reply(click,'Gracias. Tu valoración quedó guardada de forma privada.')
   return await i.response.send_modal(TextForm('Valorar atención','Ejemplo: 5: resolvieron mi problema',rate_form,1000))
  await i.response.defer(ephemeral=True,thinking=True)
  if action=='claim':
   async with self.lock:
    self.store.claim(rid,i.user.id);await self.access(i.user,self.store.get(rid));await self.refresh(self.store.get(rid))
   return await reply(i,f"Ticket #{rid} asignado a ti: <#{row['channel']}>.")
  if action=='transcript':
   async with self.lock:return await self.export(i,row)
  if action=='proof':
   files=await self.call('files',rid)
   lines=[f"**{n+1}.** {discord.utils.escape_markdown(f['filename'])[:100]} · {f['state']} · ID `{f['attachment']}`" for n,f in enumerate(files)]
   return await reply(i,('\n'.join(lines)[:1700] or 'Todavía no hay archivos adjuntos.')+'\nDescarga una copia con `/ticket archivo` indicando el ID del archivo.')
 async def transfer(self,i,rid,department,reason,assignee=None):
  if not i.response.is_done():await i.response.defer(ephemeral=True)
  async with self.lock:
   row=self.store.get(rid);self.authorize(i.user,row,staff=True)
   if not reason.strip():raise ValueError('Indica el motivo de la transferencia.')
   if department=='staff':
    channel=await self.channel(row)
    if any(isinstance(target,discord.Role) and target.id in PROTECTED and not target.permissions.administrator and value.view_channel is True for target,value in channel.overwrites.items()):
     raise ValueError('Este canal tiene un acceso manual de un rol protegido. No se alterará ese permiso; abre un reporte reservado separado.')
   if assignee:
    candidate=dict(row,department=department)
    if not can_staff(assignee,candidate,self.store):raise ValueError('El nuevo responsable no tiene autorización para ese departamento.')
   self.store.transfer(rid,department,i.user.id,reason,assignee.id if assignee else None)
   await self.apply_permissions(self.store.get(rid));await self.refresh(self.store.get(rid))
   await reply(i,'Transferencia registrada y accesos actualizados.')
 async def install(self):
  guild=self.bot.get_guild(self.guild_id)
  panel=await self.bot.fetch_channel(PANEL_CHANNEL)
  if not isinstance(panel,discord.TextChannel) or panel.guild.id!=self.guild_id:raise ValueError('El canal de entrada de tickets no coincide con La Venganza RP.')
  await self.ensure_category(guild)
  closed=await self.ensure_category(guild,True)
  if closed.permissions_for(guild.default_role).view_channel:raise ValueError('La categoría de cerrados no es privada.')
  # Keep existing tickets and third-party controls operational. Record old panel IDs for migration.
  if not self.store.config('legacy_panels'):
   legacy=[]
   async for message in panel.history(limit=40):
    if message.author.bot and message.author.id!=self.bot.user.id and message.components:
     legacy.append(dict(message=str(message.id),author=str(message.author.id),components=[r.to_dict() for r in message.components]))
   self.store.config('legacy_panels',json.dumps(legacy))
   log.info('TICKETS legacy_panels_preserved count=%s',len(legacy))
  embed=discord.Embed(title='🎫 CENTRO DE ATENCIÓN | LA VENGANZA RP',color=0xD60000,
   description='**Nuevas solicitudes: usa este panel oficial del bot de La Venganza.**\nElige el motivo y completa su formulario. Se abrirá un canal privado para tu caso.\n\n'
    '🛠️ Soporte técnico · 🚨 Reportar jugador\n🛍️ Problemas con tienda · 💳 Donaciones\n⚖️ Apelar sanción · 🥷 Gangas y negocios\n🔒 Reportar al staff (solo administradores)\n\n'
    f"Puedes adjuntar pruebas (hasta {self.store.config('max_file_mb')} MB por archivo), consultar tu responsable, valorar la atención y reabrir tu caso. Los enlaces externos se guardan como referencia; adjunta el archivo para respaldarlo. Evita duplicados: continúa en tu ticket existente.\n"
    '**Los tickets anteriores conservan sus canales y controles originales.**')
  embed.set_footer(text='Privacidad por caso · Sin @everyone · No envíes contraseñas ni datos completos de pago')
  saved=self.store.config('panel_message');message=None
  if saved:
   with suppress(discord.NotFound):message=await panel.fetch_message(int(saved))
  if not message:
   async for item in panel.history(limit=100):
    if item.author.id==self.bot.user.id and any(e.title==embed.title for e in item.embeds):message=item;break
  if message:await message.edit(embed=embed,view=TicketPanel(self))
  else:message=await panel.send(embed=embed,view=TicketPanel(self),allowed_mentions=discord.AllowedMentions.none())
  self.store.config('panel_message',message.id)
  if not message.pinned:
   with suppress(discord.Forbidden):await message.pin(reason='Panel oficial del nuevo sistema de tickets')
  confirmed=await panel.fetch_message(message.id)
  ids=[getattr(c,'custom_id',None) for r in confirmed.components for c in r.children]
  labels=[option.label for row in confirmed.components for component in row.children for option in getattr(component,'options',[])]
  if 'lv:ticket:department' not in ids or DEPARTMENTS['faccion'][1] not in labels:raise ValueError('Discord no confirmó el panel de tickets actualizado.')
  for ticket in self.store.list(limit=10000):
   if ticket['department']=='faccion' and ticket['channel']:
    await self.refresh(ticket)
  log.info('TICKETS department_labels_verified labels=%s',labels)
  log.info('TICKETS panel_verified channel=%s message=%s closed_category=%s legacy_channels_untouched=True protected_roles_untouched=True',panel.id,message.id,closed.id)
 async def ready(self):
  if not self.enabled():return
  async with self.ready_lock:
   if not self.prepared:
    await self.bot.changes.tracked('TICKETS_INSTALL_REQUEST_ID','Instalar tickets avanzados',self.install)
    async with self.lock:await self.recover()
    await self.bot.changes.tracked('TICKETS_SELFTEST_REQUEST_ID','Verificar tickets avanzados',self.selftest)
    request=os.getenv('TICKETS_SELFTEST_REQUEST_ID','').strip()
    if request and self.bot.backups.enabled and not self.store.config('selftest-backup:'+request):
     result=await self.bot.backups.execute()
     if result.get('restore_state')!='verified':raise RuntimeError('No se verificó la restauración del respaldo con las pruebas')
     self.store.config('selftest-backup:'+request,'verified')
     log.info('TICKETS external_backup_verified proofs_in_sqlite=True restore_verified=True')
    self.prepared=True
    log.info('TICKETS ready panel=%s active_category=%s closed_category=%s persistent_controls=True',PANEL_CHANNEL,self.store.config('active_category'),self.store.config('closed_category'))
 async def recover(self,rid=None):
  guild=self.bot.get_guild(self.guild_id)
  channels=await guild.fetch_channels()
  rows=[self.store.get(rid)] if rid else self.store.list(limit=10000)
  for row in rows:
   if not row:continue
   if row['status']=='creando' or (row['status']=='fallido' and row['channel']):
    matches=[c for c in channels if isinstance(c,discord.TextChannel) and c.topic==f"lv-ticket:{row['id']}"]
    if len(matches)==1:
     self.store.update(row['id'],channel=matches[0].id,status='nuevo')
     await self.refresh(self.store.get(row['id']))
    elif len(matches)>1:log.error('TICKETS uncertain_duplicate id=%s',row['id'])
   row=self.store.get(row['id'])
   if row['status']=='cerrado' and row['archive_state'] in ('pendiente','pendiente_actualizacion'):
    try:
     await self.apply_permissions(row)
     channel=await self.channel(row);category=await self.ensure_category(guild,True)
     if channel.category_id!=category.id:await self.move(row,category,'Recuperar archivo interrumpido')
     await self.refresh(row);await self.archive(row)
    except discord.HTTPException:log.exception('TICKETS recovery_pending id=%s',row['id'])
 async def maintenance(self):
  now=int(time.time())
  for row in await self.call('list',limit=10000):
   if row['status'] in ('creando','fallido','cerrado'):continue
   if row['status']=='esperando_jugador':
    since=max(row['updated'],row['last_user'],row['last_staff'] or 0)
    if not row['warning_at'] and now-since>=int(self.store.config('inactive_hours'))*3600:
     channel=await self.channel(row)
     hours=int(self.store.config('close_warning_hours'))
     await channel.send(f"⏳ <@{row['owner']}> seguimos esperando tu respuesta. Si no respondes en {hours} horas, archivaremos este caso; podrás reabrirlo durante siete días.",allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=row['owner'])]))
     # Writing warning_at must not reset the waiting period; closing uses warning timestamp directly.
     await self.call('update',row['id'],warning_at=now)
    elif row['warning_at'] and now-row['warning_at']>=int(self.store.config('close_warning_hours'))*3600:
     async with self.lock:
      current=self.store.get(row['id'])
      if current['status']=='esperando_jugador' and current['warning_at']==row['warning_at']:
       await self.close(current,self.bot.user.id,'Archivado por falta de respuesta después del aviso previo. Puede reabrirse durante siete días.')
   elif row['status'] in ('nuevo','en_atencion') and now-max(row['created'],row['last_staff'] or 0,row['last_user'])>=int(self.store.config('remind_hours'))*3600 and now-(row['reminded_at'] or 0)>=int(self.store.config('remind_hours'))*3600:
    channel=await self.channel(row)
    target=f"<@{row['assignee']}> " if row['assignee'] else ''
    await channel.send('🔔 '+target+'este caso sigue pendiente de atención. Staff puede reclamarlo o actualizar su estado.',
        allowed_mentions=discord.AllowedMentions(users=[discord.Object(id=row['assignee'])] if row['assignee'] else []))
    await self.call('update',row['id'],reminded_at=now)
 async def loop(self):
  await self.bot.wait_until_ready()
  while not self.bot.is_closed():
   if self.enabled():
    try:
     await self.ready()
     await self.maintenance()
     async with self.lock:await self.recover()
    except Exception:log.exception('TICKETS background_error; existing cases preserved')
   await asyncio.sleep(60)
 def current(self,i,rid=None):
  row=self.store.get(rid,channel=i.channel_id) if rid is not None else self.store.get(channel=i.channel_id)
  if not row:raise ValueError('Usa este comando dentro de un ticket del nuevo bot o indica su número.')
  return row
 async def selftest(self):
  request=os.getenv('TICKETS_SELFTEST_REQUEST_ID','').strip()
  if not request or self.store.config('selftest-complete:'+request):return
  if not re.fullmatch('[A-Za-z0-9_-]{1,80}',request):raise ValueError('Identificador de prueba inválido')
  guild=self.bot.get_guild(self.guild_id)
  original_channels={c.id:(c.category_id,c.name,sorted((o.type,o.id,o.allow,o.deny) for o in c._overwrites)) for c in await guild.fetch_channels()}
  protected_before={r.id:(r.name,r.position,r.permissions.value,r.colour.value) for r in await guild.fetch_roles() if r.id in PROTECTED}
  async with self.lock:
   for index,department in enumerate(('soporte','staff')):
    key=f'selftest-{department}:'+request
    rid=self.store.config(key)
    if rid:rid=int(rid)
    else:
     rid=self.store.create(self.bot.user.id,department,'PRUEBA DEL SISTEMA · '+department,
        dict(selftest=request,detalles='Caso de verificación del bot; sin jugador real.'),now=int(time.time())-61*(1-index))
     self.store.config(key,rid)
    row=self.store.get(rid)
    if not row['channel']:
     existing=[c for c in await guild.fetch_channels() if getattr(c,'topic',None)==f'lv-ticket:{rid}']
     if len(existing)>1:raise RuntimeError('Prueba con creación incierta duplicada; requiere revisión')
     if existing:channel=existing[0]
     else:
      category=await self.ensure_category(guild)
      channel=await guild.create_text_channel(f'🧪┊𝐩𝐫𝐮𝐞𝐛𝐚-{rid:04d}',category=category,topic=f'lv-ticket:{rid}',
        overwrites=channel_overwrites(guild,row,self.store,guild.me),reason='Verificar el sistema de tickets sin jugadores ni roles protegidos')
     self.store.update(rid,channel=channel.id,status='nuevo');row=self.store.get(rid)
    channel=await self.channel(row)
    if row['status']=='cerrado':
     self.store.transition(rid,'en_atencion',self.bot.user.id,'Reapertura: continuar verificación interrumpida')
     row=self.store.get(rid);await self.apply_permissions(row)
    self.store.claim(rid,self.bot.user.id)
    secret=f'NOTA_INTERNA_PRUEBA_{rid}'
    if not self.store.events(rid,notes=True):self.store.note(rid,self.bot.user.id,secret)
    if not self.store.files(rid):
     await channel.send('Prueba de respaldo de archivo y conversación <script>no ejecutar</script>',
       file=discord.File(io.BytesIO(b'La Venganza RP - prueba de respaldo de tickets'),filename='prueba-ticket.txt'),allowed_mentions=discord.AllowedMentions.none())
    await self.refresh(self.store.get(rid))
    confirmed=await self.bot.fetch_channel(channel.id)
    if confirmed.permissions_for(guild.default_role).view_channel:raise RuntimeError('Prueba no privada')
    if any(o.type==0 and o.id in PROTECTED for o in confirmed._overwrites):raise RuntimeError('Se creó un overwrite para un rol protegido')
    for role in guild.roles:
     if role.id in NORMAL_STAFF:
      if confirmed.permissions_for(role).view_channel!=(department!='staff'):raise RuntimeError('Privacidad de departamento incorrecta')
    await self.close(self.store.get(rid),self.bot.user.id,'Prueba técnica completada. Este caso no corresponde a un jugador.')
    closed=self.store.get(rid)
    if closed['archive_state']!='completo' or secret in (closed['transcript'] or ''):raise RuntimeError('El archivo o las notas internas no pasaron la verificación')
    for attachment in self.store.files(rid):
     data=self.store.blob(rid,attachment['attachment'])
     if data is None or hashlib.sha256(data).hexdigest()!=attachment['sha256']:raise RuntimeError('La copia de una prueba no coincide')
    if department=='soporte':
     self.store.transition(rid,'en_atencion',self.bot.user.id,'Reapertura: verificar conservación del canal')
     row=self.store.get(rid);await self.apply_permissions(row);await self.move(row,await self.ensure_category(guild),'Prueba de reapertura')
     self.store.transfer(rid,'donacion',self.bot.user.id,'Verificar transferencia al staff habitual',self.bot.user.id)
     await self.apply_permissions(self.store.get(rid))
     await self.close(self.store.get(rid),self.bot.user.id,'Prueba de transferencia y reapertura completada.')
    if self.store.get(rid)['rating'] is None:self.store.rate(rid,self.bot.user.id,5,'Valoración de prueba; excluida del panel de gestión.')
    log.info('TICKETS selftest_case_verified id=%s department=%s channel=%s archived=True proofs_verified=True notes_private=True',rid,department,channel.id)
  protected_after={r.id:(r.name,r.position,r.permissions.value,r.colour.value) for r in await guild.fetch_roles() if r.id in PROTECTED}
  if protected_before!=protected_after:raise RuntimeError('Un rol protegido cambió durante la verificación')
  for channel in await guild.fetch_channels():
   if channel.id in original_channels and not (getattr(channel,'topic','') or '').startswith('lv-ticket:'):
    before=original_channels[channel.id]
    if (channel.category_id,channel.name,sorted((o.type,o.id,o.allow,o.deny) for o in channel._overwrites))!=before:
     log.error('TICKETS selftest_existing_channel_change id=%s parent_changed=%s name_changed=%s permissions_changed=%s',channel.id,channel.category_id!=before[0],channel.name!=before[1],sorted((o.type,o.id,o.allow,o.deny) for o in channel._overwrites)!=before[2])
     raise RuntimeError('Un canal anterior cambió durante la prueba')
  self.store.config('selftest-complete:'+request,'verified')
  log.info('TICKETS selftest_complete request=%s protected_roles_unchanged=True legacy_channels_unchanged=True',request)
 def register(self):
  @self.group.command(name='mis',description='Consultar tus tickets activos y cerrados')
  async def mine(i:discord.Interaction,pagina:app_commands.Range[int,1,1000000]=1):await self.show_list(i,True,pagina)
  @self.group.command(name='gestion',description='Panel privado de responsables, pendientes y atención')
  async def dashboard(i:discord.Interaction,pagina:app_commands.Range[int,1,1000000]=1):await self.show_list(i,False,pagina)
  @self.group.command(name='acceso',description='Abrir un ticket como revisor autorizado')
  async def access(i:discord.Interaction,numero:int):
   await i.response.defer(ephemeral=True)
   row=self.current(i,numero)
   async with self.lock:await self.access(i.user,row)
   await reply(i,f"Caso #{numero}: <#{row['channel']}>",embed=self.embed(row),view=TicketControls(numero,row['status']=='cerrado'))
  @self.group.command(name='nota',description='Guardar una nota interna que no verá el jugador')
  async def note(i:discord.Interaction,texto:app_commands.Range[str,1,1500],numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row,True)
   await self.call('note',row['id'],i.user.id,texto);await reply(i,'Nota privada guardada.')
  @self.group.command(name='notas',description='Consultar las notas internas de este caso')
  async def notes(i:discord.Interaction,numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row,True)
   await i.response.defer(ephemeral=True)
   records=await self.call('events',row['id'],notes=True)
   text='\n\n'.join(f"#{r['id']} · ID {r['actor']} · <t:{r['created']}:f>\n{r['text']}" for r in records) or 'Sin notas internas.'
   if len(text)<=1900:return await reply(i,text)
   await reply(i,file=discord.File(io.BytesIO(text.encode()),filename=f'notas-privadas-{row["id"]}.txt'))
  @self.group.command(name='estado',description='Cambiar el estado de atención con un motivo')
  @app_commands.choices(estado=[app_commands.Choice(name=label,value=key) for key,label in STATE_LABELS.items() if key in STATES])
  async def state(i:discord.Interaction,estado:str,motivo:app_commands.Range[str,1,1500],numero:int=None):
   await i.response.defer(ephemeral=True)
   async with self.lock:
    row=self.current(i,numero);self.authorize(i.user,row,True)
    if estado=='cerrado':await self.close(row,i.user.id,motivo)
    elif row['status']=='cerrado':return await self.reopen(i,row,motivo)
    else:await self.call('transition',row['id'],estado,i.user.id,motivo);await self.refresh(self.store.get(row['id']))
   await reply(i,'Estado y motivo guardados.')
  @self.group.command(name='transferir',description='Cambiar de departamento o responsable con motivo')
  @app_commands.choices(departamento=[app_commands.Choice(name=label,value=key) for key,(_,label,_) in DEPARTMENTS.items()])
  async def transfer(i:discord.Interaction,departamento:str,motivo:app_commands.Range[str,1,1000],responsable:discord.Member=None,numero:int=None):
   row=self.current(i,numero);await self.transfer(i,row['id'],departamento,motivo,responsable)
  @self.group.command(name='participante',description='Añadir o retirar una persona de un caso')
  async def participant(i:discord.Interaction,persona:discord.Member,añadir:bool,numero:int=None):
   await i.response.defer(ephemeral=True)
   async with self.lock:
    row=self.current(i,numero);self.authorize(i.user,row,True)
    if persona.bot or persona.id in (row['owner'],row.get('excluded')):raise ValueError('Esa persona no puede añadirse ni retirarse con esta acción.')
    if row['department']=='staff' and not persona.guild_permissions.administrator:raise ValueError('Los reportes contra staff solo admiten administradores como participantes adicionales.')
    await self.call('participant',row['id'],persona.id,i.user.id,añadir)
    await self.apply_permissions(self.store.get(row['id']))
   await reply(i,'Participantes actualizados y cambio registrado.')
  @self.group.command(name='transcripcion',description='Descargar la conversación sin notas internas')
  async def transcript(i:discord.Interaction,numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row)
   await i.response.defer(ephemeral=True,thinking=True)
   async with self.lock:await self.export(i,row)
  @self.group.command(name='archivo',description='Descargar una prueba respaldada por su ID')
  async def proof(i:discord.Interaction,archivo:str,numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row)
   if not archivo.isdigit():raise ValueError('Indica el ID numérico del archivo, disponible en Pruebas guardadas.')
   await i.response.defer(ephemeral=True,thinking=True);await self.export(i,row,int(archivo))
  @self.group.command(name='historial',description='Consultar quién hizo cada cambio de un caso')
  async def history(i:discord.Interaction,numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row,True)
   await i.response.defer(ephemeral=True)
   events=await self.call('events',row['id'])
   text='\n'.join(f"#{r['id']} · <t:{r['created']}:f> · ID {r['actor']} · {r['action']} · {r['detail']}" for r in events)
   await reply(i,file=discord.File(io.BytesIO(text.encode()),filename=f'historial-ticket-{row["id"]}.txt'))
  @self.group.command(name='compra',description='Consultar solo la compra vinculada a este ticket')
  async def purchase(i:discord.Interaction,numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row,True)
   if not row['purchase_id']:raise ValueError('Este caso no tiene una compra vinculada.')
   records=await asyncio.to_thread(self.bot.economy.store.rows,'SELECT id,name,status,price,buyer,recipient,created FROM eco_purchases WHERE id=?',(row['purchase_id'],))
   if not records:raise ValueError('Compra no encontrada.')
   p=records[0]
   await reply(i,f"**{discord.utils.escape_markdown(p['name'])}** · {p['price']} 🪙 · {p['status']}\nPagador ID {p['buyer']} · Destinatario ID {p['recipient']}\nCompra `{p['id']}` · <t:{p['created']}:f>")
  @self.group.command(name='devolver',description='Revisar una devolución autorizada de la compra vinculada')
  async def refund(i:discord.Interaction,motivo:app_commands.Range[str,1,500],numero:int=None):
   row=self.current(i,numero);self.authorize(i.user,row,True);self.bot.economy.authorized(i)
   if not row['purchase_id']:raise ValueError('No hay una compra vinculada.')
   from economy import Confirm
   async def confirmed(click):
    current=self.store.get(row['id']);self.authorize(click.user,current,True);self.bot.economy.authorized(click)
    async with self.bot.economy.delivery.lock:
     await asyncio.to_thread(self.bot.economy.store.refund,current['purchase_id'],click.user.id,motivo)
    await self.record(row['id'],click.user.id,'devolucion',motivo)
    return 'Devolución registrada por el sistema de economía. La retirada del cosmético se procesará con su entrega pendiente.'
   await reply(i,f"Revisar devolución de `{row['purchase_id']}`. Motivo: {discord.utils.escape_markdown(motivo)}\nSolo se ejecuta al confirmar.",view=Confirm(i.user.id,confirmed))
  @self.group.command(name='configuracion',description='Configurar límites y tiempos sin modificar roles')
  async def configuration(i:discord.Interaction,max_abiertos:app_commands.Range[int,1,10]=None,
       recordar_horas:app_commands.Range[int,1,168]=None,inactividad_horas:app_commands.Range[int,6,720]=None,
       aviso_horas:app_commands.Range[int,1,168]=None,archivo_mb:app_commands.Range[int,1,100]=None,
       caso_mb:app_commands.Range[int,25,500]=None,total_mb:app_commands.Range[int,100,2000]=None):
   self.admin(i.user);await i.response.defer(ephemeral=True)
   values=dict(max_open=max_abiertos,remind_hours=recordar_horas,inactive_hours=inactividad_horas,
      close_warning_hours=aviso_horas,max_file_mb=archivo_mb,max_case_mb=caso_mb,max_total_mb=total_mb)
   before={k:self.store.config(k) for k in values}
   proposed={k:(str(value) if value is not None else before[k]) for k,value in values.items()}
   if not int(proposed['max_file_mb'])<=int(proposed['max_case_mb'])<=int(proposed['max_total_mb']):raise ValueError('El límite por archivo no puede superar el del caso, ni el del caso superar el total.')
   if any(v is not None for v in values.values()):
    rid=await asyncio.to_thread(self.bot.changes.journal.begin,'ticket-config:'+str(i.id),'Configurar tickets',
      f'Configuración administrativa por ID {i.user.id}.','Restaurar únicamente las claves de configuración incluidas en before, sin modificar roles.',before)
    for key,value in values.items():
     if value is not None:self.store.config(key,value)
    await asyncio.to_thread(self.bot.changes.journal.finish,rid,'completado',{k:self.store.config(k) for k in values})
   await reply(i,'\n'.join(f"**{k}:** {self.store.config(k)}" for k in values))
  @self.group.command(name='departamento',description='Añadir un rol encargado a un departamento normal')
  @app_commands.choices(departamento=[app_commands.Choice(name=label,value=key) for key,(_,label,_) in DEPARTMENTS.items() if key!='staff'])
  async def route(i:discord.Interaction,departamento:str,rol:discord.Role,añadir:bool):
   self.admin(i.user)
   if departamento not in DEPARTMENTS or departamento=='staff':raise ValueError('El área reservada no admite roles de departamentos.')
   if rol.id in PROTECTED or rol.id in (self.guild_id,1245009164070158409) or rol.managed:raise ValueError('No se pueden configurar roles protegidos, Ciudadanos, @everyone ni roles administrados por otros bots.')
   await i.response.defer(ephemeral=True)
   async with self.lock:
    old=self.store.config('route:'+departamento);roles=set(json.loads(old)) if old else set()
    if añadir:roles.add(rol.id)
    else:roles.discard(rol.id)
    rid=await asyncio.to_thread(self.bot.changes.journal.begin,'ticket-route:'+str(i.id),'Encargados de tickets',
        f'Departamento {departamento}; actor ID {i.user.id}.','Restaurar la lista de encargados indicada en before y volver a aplicar accesos solo a tickets gestionados por este bot.',dict(department=departamento,roles=sorted(json.loads(old)) if old else []))
    self.store.config('route:'+departamento,json.dumps(sorted(roles)))
    for row in self.store.list(limit=10000):
     if row['department']==departamento and row['channel']:await self.apply_permissions(row)
    await asyncio.to_thread(self.bot.changes.journal.finish,rid,'completado',dict(department=departamento,roles=sorted(roles)))
   await reply(i,'Encargados actualizados para este departamento; roles protegidos intactos.')
  @self.group.command(name='recuperar',description='Reconciliar una creación o un archivo interrumpido')
  async def recover(i:discord.Interaction,numero:int,cancelar_reserva:bool=False):
   self.admin(i.user);await i.response.defer(ephemeral=True,thinking=True)
   async with self.lock:await self.recover(numero)
   row=self.current(i,numero)
   if row['status']=='creando' and not row['channel']:
    if cancelar_reserva:
     if time.time()-row['created']<120:raise ValueError('Espera dos minutos antes de cancelar una creación incierta.')
     if any(getattr(c,'topic',None)==f"lv-ticket:{numero}" for c in await i.guild.fetch_channels()):raise ValueError('Hay un canal para este caso. Vuelve a recuperar sin cancelar.')
     await self.call('update',numero,status='fallido');await self.record(numero,i.user.id,'cancelar_reserva','Revisión de canales completada; se habilita un nuevo intento del jugador.')
     return await reply(i,'Reserva cancelada sin borrar canales. El jugador puede abrir una nueva solicitud.')
    raise ValueError('La creación no tiene un canal confirmado. Revisa la auditoría; después de dos minutos puedes usar /ticket recuperar cancelar_reserva:true para habilitar otro intento sin borrar canales.')
   await reply(i,f"Ticket #{numero} revisado. Estado: {row['status']} · respaldo: {row['archive_state'] or 'sin archivo todavía'}.")
  @self.group.error
  async def error(i,exc):
   original=getattr(exc,'original',exc)
   if isinstance(original,ValueError):return await reply(i,str(original))
   if isinstance(original,discord.Forbidden):return await reply(i,'Discord negó esta operación. El caso se conserva; pide a un administrador revisar los accesos del bot.')
   log.error('TICKETS command_error',exc_info=original)
   await reply(i,'No se pudo completar la operación. El ticket y sus datos se conservan para revisión.')
