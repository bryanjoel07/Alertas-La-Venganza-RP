"""Private, searchable member invitations for an existing ticket."""
import logging

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
  await reply(i,'No pude buscar ahora. Vuelve a abrir Añadir miembro.')


class TicketMemberPicker(SafeView):
 def __init__(self,system,actor,rid,members):
  super().__init__(timeout=300)
  self.system,self.actor,self.rid=system,actor,rid
  self.members={m.id:m for m in members}
  self.query='';self.page=0;self.build()
 def filtered(self):
  row=self.system.store.get(self.rid)
  if not row:return []
  excluded={row['owner'],row.get('excluded'),*self.system.store.people(self.rid)}
  return [m for m in self.members.values() if not m.bot and m.id not in excluded
    and (row['department']!='staff' or m.guild_permissions.administrator) and matches(m,self.query)]
 def content(self):
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  return (f'**Añadir miembro al ticket #{self.rid}**\n'
    'La persona que elijas podrá leer el historial y escribir en este ticket.\n'
    'Usa **Buscar** para encontrarla por nombre, usuario o ID, aunque esté desconectada.\n\n'
    f'{len(rows)} personas · Página {self.page+1}/{pages}')
 def build(self):
  self.clear_items()
  rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
  self.page=max(0,min(self.page,pages-1))
  visible=rows[self.page*PAGE_SIZE:(self.page+1)*PAGE_SIZE]
  select=discord.ui.Select(placeholder='Elige a quién añadir' if visible else 'No hay personas disponibles',
    disabled=not visible,options=[discord.SelectOption(label=m.display_name[:100],value=str(m.id),
      description=f'@{m.name} · {m.id}'[:100]) for m in visible] or [discord.SelectOption(label='Sin resultados',value='none')])
  async def choose(i):
   if not select.values or select.values[0] not in {str(m.id) for m in visible}:
    return await reply(i,'Elige a alguien de la lista.')
   await i.response.defer()
   uid=int(select.values[0])
   changed=await self.system.add_ticket_member(i,self.rid,uid)
   await i.edit_original_response(content=(f'<@{uid}> ya tiene acceso al ticket #{self.rid}.' if changed
     else f'<@{uid}> ya estaba añadido a este ticket.'),view=None,allowed_mentions=discord.AllowedMentions.none())
   self.stop()
  select.callback=choose;self.add_item(select)
  for label,step,disabled in [('Anterior',-1,self.page==0),('Siguiente',1,self.page>=pages-1)]:
   button=discord.ui.Button(label=label,disabled=disabled,row=1)
   async def move(i,step=step):
    self.page+=step;self.build()
    await i.response.edit_message(content=self.content(),view=self,allowed_mentions=discord.AllowedMentions.none())
   button.callback=move;self.add_item(button)
  search=discord.ui.Button(label='Buscar',emoji='🔎',row=1)
  async def find(i):await i.response.send_modal(TicketMemberSearch(self))
  search.callback=find;self.add_item(search)
 async def interaction_check(self,i):
  try:
   if i.user.id!=self.actor:raise ValueError('Abre tu propio botón Añadir miembro para usar esta lista.')
   self.system.member_ticket(i,self.rid)
  except ValueError as error:
   await reply(i,str(error));return False
  return True
