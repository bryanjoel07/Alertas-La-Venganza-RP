"""Private, searchable participant invitations and removals for an existing ticket."""
import logging
from types import SimpleNamespace

import discord

from photo_members import PAGE_SIZE,matches
from tickets_ui import SafeView,reply


class TicketMemberSearch(discord.ui.Modal):
 def __init__(self,picker):
  super().__init__(title='Buscar miembro',timeout=300)
  self.picker=picker
  self.query=discord.ui.TextInput(label='Nombre, usuario o ID',required=False,max_length=100,
    placeholder='Déjalo vacío para ver a todos.',default=picker.query or None)
  self.add_item(self.query)
 async def on_submit(self,i):
  if not await self.picker.interaction_check(i):return
  self.picker.query=self.query.value.strip();self.picker.page=0;self.picker.build()
  await i.response.edit_message(content=self.picker.content(),view=self.picker,allowed_mentions=discord.AllowedMentions.none())
 async def on_error(self,i,error):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket member search failed',exc_info=error)
  await reply(i,'No pude buscar ahora. Vuelve a abrir el selector de miembros.')


class TicketMemberPicker(SafeView):
 def __init__(self,system,actor,rid,members):
  super().__init__(timeout=300)
  self.system,self.actor,self.rid=system,actor,rid
  self.directory_available=members is not None
  self.members={m.id:m for m in members or ()}
  self.query='';self.page=0;self.build()
 def filtered(self):
  row=self.system.store.get(self.rid)
  if not row:return []
  excluded={row['owner'],row.get('excluded'),*self.system.store.people(self.rid)}
  return [m for m in self.members.values() if not m.bot and m.id not in excluded
    and (row['department']!='staff' or m.guild_permissions.administrator) and matches(m,self.query)]
 def content(self):
  header=(f'**Añadir miembro al ticket #{self.rid}**\n'
    'La persona que elijas podrá leer el historial y escribir en este ticket.\n'
    'Abre **Buscar miembro** y escribe su nombre o usuario.')
  if not self.directory_available:
   return header+'\nLa lista por páginas no está disponible ahora.'
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  return (header+'\nTambién puedes recorrer la lista o usar **Filtrar lista** por apodo, usuario o ID.'
    f'\n\n{len(rows)} personas · Página {self.page+1}/{pages}')
 async def invite(self,i,uid):
  await i.response.defer()
  changed=await self.system.add_ticket_member(i,self.rid,uid)
  channel_id=self.system.store.get(self.rid)['channel']
  text=(f'<@{uid}> añadido como participante de <#{channel_id}>.' if changed
    else f'<@{uid}> ya figura como participante de <#{channel_id}>.')
  try:await self.system.sync_member_panel(self.rid)
  except (discord.HTTPException,ValueError):
   logging.getLogger('LaVenganzaRP.tickets').exception('Ticket member panel update failed ticket=%s',self.rid)
   text+=' El panel de participantes está pendiente de actualización.'
  await i.edit_original_response(content=text+' Acceso de lectura y escritura verificado.',view=None,
    allowed_mentions=discord.AllowedMentions.none())
  self.stop()
 def build(self):
  self.clear_items()
  search_member=discord.ui.UserSelect(placeholder='Buscar miembro por nombre o usuario…',row=0)
  async def choose_member(i):
   if search_member.values:await self.invite(i,search_member.values[0].id)
  search_member.callback=choose_member
  self.add_item(search_member)
  if not self.directory_available:return
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  self.page=max(0,min(self.page,pages-1))
  visible=rows[self.page*PAGE_SIZE:(self.page+1)*PAGE_SIZE]
  select=discord.ui.Select(row=1,placeholder='Elegir de esta página' if visible else 'No hay personas disponibles',
    disabled=not visible,options=[discord.SelectOption(label=m.display_name[:100],value=str(m.id),
      description=f'@{m.name} · {m.id}'[:100]) for m in visible] or [discord.SelectOption(label='Sin resultados',value='none')])
  async def choose(i):
   if not select.values or select.values[0] not in {str(m.id) for m in visible}:
    return await reply(i,'Elige a alguien de la lista.')
   await self.invite(i,int(select.values[0]))
  select.callback=choose;self.add_item(select)
  for label,step,disabled in [('Anterior',-1,self.page==0),('Siguiente',1,self.page>=pages-1)]:
   button=discord.ui.Button(label=label,disabled=disabled,row=2)
   async def move(i,step=step):
    self.page+=step;self.build()
    await i.response.edit_message(content=self.content(),view=self,allowed_mentions=discord.AllowedMentions.none())
   button.callback=move;self.add_item(button)
  search=discord.ui.Button(label='Filtrar lista',emoji='🔎',row=2)
  async def find(i):await i.response.send_modal(TicketMemberSearch(self))
  search.callback=find;self.add_item(search)
 async def interaction_check(self,i):
  try:
   if i.user.id!=self.actor:raise ValueError('Abre tu propio botón Añadir miembro para usar esta lista.')
   self.system.member_ticket(i,self.rid)
  except ValueError as error:
   await reply(i,str(error));return False
  return True


class TicketMemberRemovePicker(SafeView):
 def __init__(self,system,actor,rid,members):
  super().__init__(timeout=300)
  self.system,self.actor,self.rid=system,actor,rid
  self.members={member.id:member for member in members or ()}
  self.query='';self.page=0;self.build()
 def filtered(self):
  row=self.system.store.get(self.rid)
  if not row:return []
  excluded={row['owner'],row.get('assignee'),row.get('excluded'),self.system.bot.user.id}
  people=[]
  for uid in self.system.store.people(self.rid):
   if uid in excluded:continue
   member=self.members.get(uid) or SimpleNamespace(id=uid,name=str(uid),display_name=f'Usuario {uid}',global_name=None,bot=False)
   if not member.bot and matches(member,self.query):people.append(member)
  return people
 def content(self):
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  return (f'**Remover miembro del ticket #{self.rid}**\n'
    'Elige a un participante añadido para retirar su invitación y sus permisos individuales.\n'
    'El autor y el responsable se conservan. El staff y los administradores mantienen el acceso que les corresponde.\n'
    f'\n{len(rows)} participantes · Página {self.page+1}/{pages}')
 def build(self):
  self.clear_items()
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  self.page=max(0,min(self.page,pages-1))
  visible=rows[self.page*PAGE_SIZE:(self.page+1)*PAGE_SIZE]
  select=discord.ui.Select(row=0,placeholder='Elige a quién remover' if visible else 'No hay participantes para remover',
    disabled=not visible,options=[discord.SelectOption(label=member.display_name[:100],value=str(member.id),
      description=f'@{member.name} · {member.id}'[:100]) for member in visible]
      or [discord.SelectOption(label='Sin resultados',value='none')])
  async def choose(i):
   if not select.values or select.values[0] not in {str(member.id) for member in visible}:
    return await reply(i,'Elige a un participante de la lista.')
   uid=int(select.values[0]);await i.response.defer()
   result=await self.system.remove_ticket_member(i,self.rid,uid)
   text=(f'<@{uid}> removido como participante del ticket #{self.rid}.' if result['removed']
     else f'<@{uid}> ya no figuraba como participante del ticket #{self.rid}.')
   if result['retains_access']:text+=' Conserva acceso por su función de staff, Administrador u otros permisos del canal.'
   try:await self.system.sync_member_panel(self.rid)
   except (discord.HTTPException,ValueError):
    logging.getLogger('LaVenganzaRP.tickets').exception('Ticket member panel update failed ticket=%s',self.rid)
    text+=' El panel de participantes está pendiente de actualización.'
   await i.edit_original_response(content=text,view=None,allowed_mentions=discord.AllowedMentions.none())
   self.stop()
  select.callback=choose;self.add_item(select)
  for label,step,disabled in [('Anterior',-1,self.page==0),('Siguiente',1,self.page>=pages-1)]:
   button=discord.ui.Button(label=label,disabled=disabled,row=1)
   async def move(i,step=step):
    self.page+=step;self.build()
    await i.response.edit_message(content=self.content(),view=self,allowed_mentions=discord.AllowedMentions.none())
   button.callback=move;self.add_item(button)
  search=discord.ui.Button(label='Filtrar participantes',emoji='🔎',row=1)
  async def find(i):await i.response.send_modal(TicketMemberSearch(self))
  search.callback=find;self.add_item(search)
 async def interaction_check(self,i):
  try:
   if i.user.id!=self.actor:raise ValueError('Abre tu propio botón Remover miembro para usar esta lista.')
   self.system.member_ticket(i,self.rid)
  except ValueError as error:
   await reply(i,str(error));return False
  return True
