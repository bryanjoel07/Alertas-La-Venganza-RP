"""Persistent suggestion buttons and simple player/admin forms."""
import logging
import discord
from suggestion_store import STATES,CLOSED

NONE=discord.AllowedMentions.none()
log=logging.getLogger('LaVenganzaRP.suggestions')

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(text,ephemeral=True,allowed_mentions=NONE,**kwargs)

async def failed(i,error):
 if isinstance(error,ValueError):return await reply(i,str(error))
 log.error('SUGGESTIONS interaction_failed',exc_info=error)
 await reply(i,'Discord no completó la acción, bro. Revisa Mis ideas antes de enviarla otra vez.')

class SuggestionAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lvsug:(?P<action>new|mine|up|down|clear|state):(?P<rid>[0-9]+)'):
 def __init__(self,action,rid=0,*,count=0,closed=False):
  label,emoji={'new':('Proponer una idea','💡'),'mine':('Mis ideas','📋'),'up':(f'A favor · {count}','👍'),
    'down':(f'En contra · {count}','👎'),'clear':('Quitar voto','↩️'),'state':('Estado','🛠️')}[action]
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lvsug:{action}:{rid}',
    disabled=closed and action in ('up','down','clear'),
    style=discord.ButtonStyle.primary if action=='new' else discord.ButtonStyle.secondary))
  self.action,self.rid=action,rid
 @classmethod
 async def from_custom_id(cls,i,item,match):return cls(match['action'],int(match['rid']))
 async def callback(self,i):
  try:await i.client.suggestions.handle(i,self.action,self.rid)
  except Exception as error:await failed(i,error)

def panel_controls():
 view=discord.ui.View(timeout=None)
 for action in ('new','mine'):view.add_item(SuggestionAction(action))
 return view

def idea_controls(row):
 view=discord.ui.View(timeout=None)
 for action in ('up','down','clear','state'):
  view.add_item(SuggestionAction(action,row['id'],count=row['up'] if action=='up' else row['down'] if action=='down' else 0,closed=row['status'] in CLOSED))
 return view

class IdeaForm(discord.ui.Modal):
 def __init__(self,system):
  super().__init__(title='Cuéntanos tu idea',timeout=600)
  self.system=system
  self.title_input=discord.ui.TextInput(label='Ponle un título',min_length=3,max_length=100,placeholder='¿Qué te gustaría mejorar o añadir?')
  self.description=discord.ui.TextInput(label='¿Cuál es tu idea?',style=discord.TextStyle.paragraph,min_length=10,max_length=2000,
    placeholder='Cuéntanos cómo te gustaría que funcionara.')
  self.benefit=discord.ui.TextInput(label='¿En qué ayudaría?',style=discord.TextStyle.paragraph,required=False,max_length=700,
    placeholder='¿Qué mejoraría para la comunidad?')
  for field in (self.title_input,self.description,self.benefit):self.add_item(field)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:await self.system.submit(i,self.title_input.value,self.description.value,self.benefit.value)
  except Exception as error:await failed(i,error)
 async def on_error(self,i,error):await failed(i,error)

class StateForm(discord.ui.Modal):
 def __init__(self,system,row):
  super().__init__(title=f"Estado de la idea #{row['id']}",timeout=600)
  self.system,self.rid,self.expected=system,row['id'],row['status_version']
  self.state=discord.ui.Select(custom_id='suggestion_state',options=[
    discord.SelectOption(label=label,value=key,emoji=emoji,default=key==row['status']) for key,(emoji,label) in STATES.items()])
  self.reason=discord.ui.TextInput(custom_id='suggestion_reason',style=discord.TextStyle.paragraph,min_length=3,max_length=1000,
    placeholder='Cuéntale a la comunidad qué decidieron o cómo va la idea.',default=row['reason'] or None)
  self.add_item(discord.ui.Label(text='¿Cómo va esta idea?',component=self.state))
  self.add_item(discord.ui.Label(text='Deja una explicación',component=self.reason))
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   if len(self.state.values)!=1 or self.state.values[0] not in STATES:raise ValueError('Elige el estado de la idea, bro.')
   await self.system.decide(i,self.rid,self.state.values[0],self.reason.value,self.expected)
  except Exception as error:await failed(i,error)
 async def on_error(self,i,error):await failed(i,error)

class MyIdeas(discord.ui.View):
 def __init__(self,system,owner,page=0):
  super().__init__(timeout=300)
  self.system,self.owner,self.page=system,owner,page
  self.previous.disabled=page==0
 async def interaction_check(self,i):
  if i.user.id==self.owner and i.guild_id==self.system.guild_id:return True
  await reply(i,'Abre Mis ideas para consultar las tuyas, bro.');return False
 async def on_error(self,i,error,item):await failed(i,error)
 @discord.ui.button(label='Anterior')
 async def previous(self,i,button):
  await i.response.defer();await self.system.mine(i,self.page-1,edit=True)
 @discord.ui.button(label='Siguiente')
 async def next(self,i,button):
  await i.response.defer();await self.system.mine(i,self.page+1,edit=True)
