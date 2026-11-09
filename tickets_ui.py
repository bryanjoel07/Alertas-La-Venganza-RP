"""Persistent ticket controls; every callback is authorized again by the service."""
import json
from contextlib import suppress
import logging
import discord
from discord import app_commands
from tickets_store import DEPARTMENTS
from ticket_forms import FORMS,submission

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)

class SafeView(discord.ui.View):
 async def on_error(self,i,error,item):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket control error',exc_info=error)
  await reply(i,str(error) if isinstance(error,ValueError) else 'No se pudo completar esa acción. El caso sigue guardado.')

class OpenForm(discord.ui.Modal):
 def __init__(self,system,department,purchase='',purchase_name=''):
  super().__init__(title=DEPARTMENTS[department][1],timeout=600)
  self.system,self.department,self.purchase=system,department,purchase
  self.inputs={}
  for question in FORMS[department]:
   value=discord.ui.TextInput(label=question.label,placeholder=question.hint or None,
      max_length=question.limit,required=question.required,
      style=discord.TextStyle.paragraph if question.paragraph else discord.TextStyle.short,
      default=purchase_name[:question.limit] if question.key=='item' and purchase_name else None)
   self.inputs[question.key]=value;self.add_item(value)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   subject,form,excluded=submission(self.department,{key:value.value for key,value in self.inputs.items()},i.user.id)
   await self.system.open(i,self.department,subject,form,excluded,self.purchase or None)
  except (ValueError,discord.HTTPException) as error:
   await reply(i,str(error) if isinstance(error,ValueError) else 'No pudimos abrir el ticket. Inténtalo otra vez o avisa al staff.')
 async def on_error(self,i,error):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket opening form failed',exc_info=error)
  await reply(i,'No pudimos abrir el ticket. Inténtalo otra vez o avisa al staff.')

class PurchasePicker(discord.ui.Select):
 def __init__(self,system,purchases):
  options=[discord.SelectOption(label=f"{p['name']} · {p['status']}"[:100],value=p['id'],description=f"{p['price']} 🪙 · Compra {p['id']}"[:100]) for p in purchases[:24]]
  options.append(discord.SelectOption(label='Otro problema de tienda / sin compra',value='none'))
  super().__init__(placeholder='Selecciona tu compra afectada',options=options)
  self.system=system;self.purchases={p['id']:p for p in purchases}
 async def callback(self,i):
  chosen=self.values[0]
  await i.response.send_modal(OpenForm(self.system,'tienda','' if chosen=='none' else chosen,self.purchases.get(chosen,{}).get('name','')))

class DepartmentPicker(discord.ui.Select):
 def __init__(self,system):
  super().__init__(placeholder='¿En qué podemos ayudarte?',custom_id='lv:ticket:department',options=[
   discord.SelectOption(label=label,value=key,emoji=emoji,description=desc[:100]) for key,(emoji,label,desc) in DEPARTMENTS.items()])
  self.system=system
 async def callback(self,i):
  if self.values[0]=='tienda':
   await i.response.defer(ephemeral=True)
   purchases=await self.system.call_purchase_list(i.user.id)
   view=discord.ui.View(timeout=180);view.add_item(PurchasePicker(self.system,purchases))
   return await reply(i,'Selecciona una compra propia. El staff verá su estado; no se cobra ni devuelve nada al abrir el ticket.',view=view)
  await i.response.send_modal(OpenForm(self.system,self.values[0]))

class TicketPanel(SafeView):
 def __init__(self,system):
  super().__init__(timeout=None);self.system=system;self.add_item(DepartmentPicker(system))
 @discord.ui.button(label='Mis tickets',emoji='📂',custom_id='lv:ticket:mine',row=1)
 async def mine(self,i,button):await self.system.show_list(i,own=True)
 @discord.ui.button(label='Gestión Staff',emoji='🧰',custom_id='lv:ticket:dashboard',row=1)
 async def dashboard(self,i,button):await self.system.show_list(i,own=False)

class ClosedArchivePanel(SafeView):
 def __init__(self,system):
  super().__init__(timeout=None);self.system=system
 @discord.ui.button(label='Consultar tickets cerrados',emoji='📂',custom_id='lv:ticket:closed')
 async def closed(self,i,button):await self.system.show_closed(i)

ACTIONS={'claim':('Reclamar','🙋'),'wait':('Solicitar pruebas','📎'),'resolve':('Resolver','✅'),
 'close':('Cerrar','🔒'),'reopen':('Reabrir','🔓'),'transcript':('Transcripción','📄'),
 'note':('Nota interna','📝'),'transfer':('Transferir','🔀'),'priority':('Prioridad','🚩'),
 'people':('Participantes','👥'),'rate':('Valorar','⭐'),'proof':('Pruebas guardadas','🗃️'),'delete':('Eliminar ticket','🗑️')}
class TicketAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lv:ticket:case:(?P<ticket>[0-9]+):(?P<action>[a-z]+)'):
 def __init__(self,rid,action):
  label,emoji=ACTIONS[action]
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lv:ticket:case:{rid}:{action}',
   style=discord.ButtonStyle.danger if action in ('close','delete') else discord.ButtonStyle.secondary))
  self.rid,self.action=rid,action
 @classmethod
 async def from_custom_id(cls,i,item,match):return cls(int(match['ticket']),match['action'])
 async def callback(self,i):
  try:await i.client.tickets.action(i,self.rid,self.action)
  except ValueError as error:await reply(i,str(error))
  except discord.HTTPException:
   await reply(i,'Discord no completó la operación. El caso se conserva; vuelve a intentarlo.')
  except Exception as error:
   logging.getLogger('LaVenganzaRP.tickets').error('Ticket action failed',exc_info=error)
   await reply(i,'El caso se conserva, pero esa acción necesita revisión. Inténtalo de nuevo o avisa a administración.')

class TicketControls(discord.ui.View):
 def __init__(self,rid,closed=False,deleted=False):
  super().__init__(timeout=None)
  actions=[] if deleted else ['rate','delete'] if closed else ['claim','resolve','close','priority']
  for n,action in enumerate(actions):
   item=TicketAction(rid,action)
   item.item.row=n//4
   self.add_item(item)

class TextForm(discord.ui.Modal):
 async def on_error(self,i,error):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket form failed',exc_info=error)
  await reply(i,'No se completó la operación. El caso y sus datos se conservan para revisión.')
 def __init__(self,title,label,callback,limit=1500):
  super().__init__(title=title,timeout=600);self.callback=callback
  self.value=discord.ui.TextInput(label=label[:45],style=discord.TextStyle.paragraph,max_length=limit)
  self.add_item(self.value)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:await self.callback(i,self.value.value)
  except ValueError as error:await reply(i,str(error))
  except discord.HTTPException:await reply(i,'Discord no completó la operación. El ticket y su historial siguen guardados.')

class CasePicker(discord.ui.Select):
 def __init__(self,system,rows,staff,closed_only=False):
  super().__init__(placeholder='Abrir un caso',options=[discord.SelectOption(label=f"#{r['id']} · {r['subject']}"[:100],value=str(r['id']),description=f"{DEPARTMENTS[r['department']][1]} · {r['status']}"[:100]) for r in rows])
  self.system,self.staff,self.closed_only=system,staff,closed_only
 async def callback(self,i):
  await i.response.defer(ephemeral=True)
  try:
   async with self.system.lock:
    row=self.system.store.get(int(self.values[0]))
    if row is None:raise ValueError('Ese ticket ya no está disponible. Actualiza la lista.')
    self.system.authorize(i.user,row,staff=self.staff)
    if row.get('deleted_at') or json.loads(row['form']).get('selftest'):
     raise ValueError('Ese ticket ya no está disponible. Actualiza la lista.')
    if self.closed_only and row['status']!='cerrado':raise ValueError('Ese ticket ya no está cerrado. Actualiza la lista.')
    await self.system.channel(row)
    if self.staff:await self.system.access(i.user,row)
    row=self.system.store.get(row['id'])
   location='Canal eliminado · archivo disponible' if row.get('deleted_at') else f"<#{row['channel']}>"
   await reply(i,f"Ticket #{row['id']} · {location}",embed=self.system.embed(row),view=TicketControls(row['id'],row['status']=='cerrado',bool(row.get('deleted_at'))))
  except discord.NotFound:await reply(i,'El canal de ese ticket ya no existe. Abre de nuevo la lista.')
  except (ValueError,discord.HTTPException) as error:await reply(i,str(error) if isinstance(error,ValueError) else 'No se pudo abrir el caso.')

class ChoiceView(SafeView):
 def __init__(self,options,callback,placeholder):
  super().__init__(timeout=180)
  select=discord.ui.Select(placeholder=placeholder,options=options)
  async def choose(i):await callback(i,select.values[0])
  select.callback=choose;self.add_item(select)


class DeleteConfirm(SafeView):
 def __init__(self,system,user,rid):
  super().__init__(timeout=90);self.system,self.user,self.rid=system,user,rid
 async def interaction_check(self,i):
  if i.user.id==self.user:return True
  await reply(i,'Solo quien solicitó la eliminación puede confirmarla.');return False
 @discord.ui.button(label='Confirmar eliminación',emoji='🗑️',style=discord.ButtonStyle.danger)
 async def confirm(self,i,button):
  await i.response.edit_message(content='Verificando la transcripción, las pruebas y el respaldo antes de eliminar…',view=None)
  self.stop()
  try:
   changed=await self.system.delete_ticket(i.user,self.rid)
   with suppress(discord.NotFound):
    await reply(i,'Canal eliminado y retirado de las listas. Se conserva una copia interna de respaldo.' if changed else 'El canal ya estaba eliminado; su archivo se conserva.')
  except (ValueError,discord.HTTPException) as error:
   await reply(i,str(error) if isinstance(error,ValueError) else 'Discord no confirmó la eliminación. El caso sigue registrado para revisión.')
 @discord.ui.button(label='Cancelar',style=discord.ButtonStyle.secondary)
 async def cancel(self,i,button):
  self.stop();await i.response.edit_message(content='Eliminación cancelada. El canal se conserva.',view=None)
