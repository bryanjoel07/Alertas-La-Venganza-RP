"""Persistent ticket controls; every callback is authorized again by the service."""
import re
import logging
import discord
from discord import app_commands
from tickets_store import DEPARTMENTS

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)

class SafeView(discord.ui.View):
 async def on_error(self,i,error,item):
  logging.getLogger('LaVenganzaRP.tickets').error('Ticket control error',exc_info=error)
  await reply(i,str(error) if isinstance(error,ValueError) else 'No se pudo completar esa acción. El caso sigue guardado.')

class OpenForm(discord.ui.Modal):
 def __init__(self,system,department,purchase=''):
  super().__init__(title=DEPARTMENTS[department][1],timeout=600)
  self.system,self.department,self.purchase=system,department,purchase
  self.subject=discord.ui.TextInput(label='Asunto',max_length=100)
  self.details=discord.ui.TextInput(label=DEPARTMENTS[department][2][:45],style=discord.TextStyle.paragraph,max_length=2000)
  self.reference=discord.ui.TextInput(label='Fecha, organización o referencia',required=False,max_length=200)
  self.proofs=discord.ui.TextInput(label='Enlaces a pruebas (archivos después de abrir)',style=discord.TextStyle.paragraph,required=False,max_length=1000)
  for item in (self.subject,self.details,self.reference,self.proofs):self.add_item(item)
  self.target=None
  if department in ('staff','jugador'):
   self.target=discord.ui.TextInput(label='ID Discord del reportado, si lo sabes',required=False,max_length=20)
   self.add_item(self.target)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   excluded=None
   if self.target and self.target.value:
    if not re.fullmatch(r'\d{17,20}',self.target.value):raise ValueError('El ID de Discord debe tener entre 17 y 20 números. Deja ese campo vacío si solo conoces el ID del juego.')
    excluded=int(self.target.value)
    if excluded==i.user.id:raise ValueError('No puedes indicar tu propio ID como reportado.')
   await self.system.open(i,self.department,self.subject.value,dict(detalles=self.details.value,
       referencia=self.reference.value,pruebas=self.proofs.value),excluded,self.purchase or None)
  except (ValueError,discord.HTTPException) as error:await reply(i,str(error) if isinstance(error,ValueError) else 'Discord no permitió completar la apertura. El intento quedó registrado para revisión.')

class PurchasePicker(discord.ui.Select):
 def __init__(self,system,purchases):
  options=[discord.SelectOption(label=f"{p['name']} · {p['status']}"[:100],value=p['id'],description=f"{p['price']} 🪙 · Compra {p['id']}"[:100]) for p in purchases[:24]]
  options.append(discord.SelectOption(label='Otro problema de tienda / sin compra',value='none'))
  super().__init__(placeholder='Selecciona tu compra afectada',options=options)
  self.system=system
 async def callback(self,i):await i.response.send_modal(OpenForm(self.system,'tienda','' if self.values[0]=='none' else self.values[0]))

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

ACTIONS={'claim':('Reclamar','🙋'),'wait':('Solicitar pruebas','📎'),'resolve':('Resolver','✅'),
 'close':('Cerrar','🔒'),'reopen':('Reabrir','🔓'),'transcript':('Transcripción','📄'),
 'note':('Nota interna','📝'),'transfer':('Transferir','🔀'),'priority':('Prioridad','🚩'),
 'people':('Participantes','👥'),'rate':('Valorar','⭐'),'proof':('Pruebas guardadas','🗃️')}
class TicketAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lv:ticket:case:(?P<ticket>[0-9]+):(?P<action>[a-z]+)'):
 def __init__(self,rid,action):
  label,emoji=ACTIONS[action]
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lv:ticket:case:{rid}:{action}',
   style=discord.ButtonStyle.danger if action=='close' else discord.ButtonStyle.secondary))
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
 def __init__(self,rid,closed=False):
  super().__init__(timeout=None)
  for n,action in enumerate(ACTIONS):
   item=TicketAction(rid,action)
   item.item.row=n//4
   item.item.disabled=(closed and action in ('claim','wait','resolve','close','transfer','priority','people')) or (not closed and action in ('reopen','rate'))
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
 def __init__(self,system,rows,staff):
  super().__init__(placeholder='Abrir un caso',options=[discord.SelectOption(label=f"#{r['id']} · {r['subject']}"[:100],value=str(r['id']),description=f"{DEPARTMENTS[r['department']][1]} · {r['status']}"[:100]) for r in rows])
  self.system,self.staff=system,staff
 async def callback(self,i):
  await i.response.defer(ephemeral=True)
  try:
   row=self.system.store.get(int(self.values[0]))
   if self.staff:
    async with self.system.lock:await self.system.access(i.user,row)
   else:self.system.authorize(i.user,row)
   row=self.system.store.get(row['id'])
   await reply(i,f"Ticket #{row['id']} · <#{row['channel']}>",embed=self.system.embed(row),view=TicketControls(row['id'],row['status']=='cerrado'))
  except (ValueError,discord.HTTPException) as error:await reply(i,str(error) if isinstance(error,ValueError) else 'No se pudo abrir el caso.')

class ChoiceView(SafeView):
 def __init__(self,options,callback,placeholder):
  super().__init__(timeout=180)
  select=discord.ui.Select(placeholder=placeholder,options=options)
  async def choose(i):await callback(i,select.values[0])
  select.callback=choose;self.add_item(select)
