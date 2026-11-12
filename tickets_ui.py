"""Persistent ticket controls; every callback is authorized again by the service."""
import json
import logging
import discord
from tickets_store import DEPARTMENTS
from ticket_forms import FORMS,submission

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 try:return await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)
 except discord.HTTPException as error:
  if error.code!=10003:raise
  logging.getLogger('LaVenganzaRP.tickets').info('TICKETS response_channel_gone channel=%s',i.channel_id)

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
 'people':('Añadir miembro','👥'),'removepeople':('Remover miembro','➖'),
 'rate':('Valorar','⭐'),'proof':('Pruebas guardadas','🗃️'),'delete':('Eliminar ticket','🗑️')}
class TicketAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lv:ticket:case:(?P<ticket>[0-9]+):(?P<action>[a-z]+)'):
 def __init__(self,rid,action):
  label,emoji=ACTIONS[action]
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lv:ticket:case:{rid}:{action}',
   style=discord.ButtonStyle.danger if action in ('close','delete','removepeople') else discord.ButtonStyle.secondary))
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
 def __init__(self,rid,closed=False,deleted=False,*,assigned=False,staff=False,resolved=False,rated=False):
  super().__init__(timeout=None)
  if deleted:actions=[]
  elif closed:actions=['transcript','proof','reopen','delete'] if staff else ([] if rated else ['rate'])
  elif resolved and not staff:actions=[] if rated else ['rate']
  else:actions=['resolve','close','priority','people','removepeople'] if assigned else ['claim','resolve','close','priority','people','removepeople']
  for n,action in enumerate(actions):
   item=TicketAction(rid,action)
   item.item.row=1 if action in ('people','removepeople') else n//4
   self.add_item(item)
 @classmethod
 def from_row(cls,row,*,staff=False):
  return cls(row['id'],row['status']=='cerrado',bool(row.get('deleted_at')),assigned=bool(row.get('assignee')),
    staff=staff,resolved=row['status']=='resuelto',rated=row.get('rating') is not None)

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

class PriorityForm(discord.ui.Modal):
 def __init__(self,system,rid,current='normal'):
  super().__init__(title='Cambiar prioridad',timeout=600)
  self.system,self.rid=system,rid
  self.priority=discord.ui.Select(custom_id='priority',placeholder='Elige Normal, Alta o Urgente',options=[
    discord.SelectOption(label=label,value=value,emoji=emoji,default=value==current)
    for value,label,emoji in [('normal','Normal','⚪'),('alta','Alta','🟠'),('urgente','Urgente','🔴')]])
  self.reason=discord.ui.TextInput(custom_id='priority_reason',style=discord.TextStyle.paragraph,
    placeholder='Cuéntanos por qué quieres cambiarla.',required=True,max_length=1500)
  self.add_item(discord.ui.Label(text='Elige la prioridad',component=self.priority))
  self.add_item(discord.ui.Label(text='¿Por qué cambias la prioridad?',component=self.reason))
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   values=self.priority.values
   if len(values)!=1 or values[0] not in ('normal','alta','urgente'):
    raise ValueError('Elige Normal, Alta o Urgente en la lista.')
   reason=self.reason.value.strip()
   if not reason:raise ValueError('Cuéntanos brevemente por qué cambias la prioridad.')
   await self.system.change_priority(i,self.rid,values[0],reason)
  except ValueError as error:await reply(i,str(error))
  except discord.HTTPException:await reply(i,'Discord no completó la operación. El ticket y su historial siguen guardados.')
 async def on_error(self,i,error):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket priority form failed',exc_info=error)
  await reply(i,'No se completó el cambio. El ticket y sus datos siguen guardados.')

class RatingForm(discord.ui.Modal):
 def __init__(self,system,rid):
  super().__init__(title='¿Cómo te atendieron?',timeout=600)
  self.system,self.rid=system,rid
  self.stars=discord.ui.Select(custom_id='stars',placeholder='Elige de 1 a 5 estrellas',options=[
    discord.SelectOption(label='⭐'*score,value=str(score)) for score in range(1,6)])
  self.comment=discord.ui.TextInput(custom_id='comment',style=discord.TextStyle.paragraph,
    placeholder='Cuéntanos cómo te fue, si quieres.',required=False,max_length=1000)
  self.add_item(discord.ui.Label(text='¿Cuántas estrellas le das?',component=self.stars))
  self.add_item(discord.ui.Label(text='¿Quieres dejar un comentario?',component=self.comment))
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   value=self.stars.values[0] if self.stars.values else ''
   if value not in ('1','2','3','4','5'):raise ValueError('Elige de 1 a 5 estrellas, bro.')
   score=int(value)
   await self.system.submit_rating(i,self.rid,score,self.comment.value)
  except ValueError as error:await reply(i,str(error))
  except discord.HTTPException:await reply(i,'No pudimos guardar tu opinión. Inténtalo otra vez.')
 async def on_error(self,i,error):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket rating failed',exc_info=error)
  await reply(i,'No pudimos guardar tu opinión. Inténtalo otra vez.')

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
   await self.system.show_case(i,row,staff=self.staff)
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
  await i.response.edit_message(content='Guardando y verificando la copia del ticket. Cuando termine, este canal desaparecerá de tu lista.',view=None)
  self.stop()
  row=self.system.store.get(self.rid)
  source_is_ticket=bool(row and i.channel_id==row['channel'])
  try:
   changed=await self.system.delete_ticket(i.user,self.rid)
   if not source_is_ticket:
    await reply(i,'Canal eliminado y retirado de las listas. Se conserva una copia interna de respaldo.' if changed else 'El canal ya estaba eliminado; su archivo se conserva.')
  except (ValueError,discord.HTTPException) as error:
   await reply(i,str(error) if isinstance(error,ValueError) else 'Discord no confirmó la eliminación. El caso sigue registrado para revisión.')
 @discord.ui.button(label='Cancelar',style=discord.ButtonStyle.secondary)
 async def cancel(self,i,button):
  self.stop();await i.response.edit_message(content='Eliminación cancelada. El canal se conserva.',view=None)
