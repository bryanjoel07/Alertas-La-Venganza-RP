"""Private questions launched from a persistent panel in General."""
import logging
import discord

log=logging.getLogger('LaVenganzaRP.minigames')
RED=0xC52232

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)

class SafeView(discord.ui.View):
 async def on_error(self,i,error,item):
  log.error('Minigame control failed',exc_info=error)
  await reply(i,str(error) if isinstance(error,ValueError) else 'No pude completar eso. Abre el juego otra vez; tu progreso sigue guardado.')

class GamePanel(SafeView):
 def __init__(self,system):super().__init__(timeout=None);self.system=system
 @discord.ui.button(label='Adivinar lugar',emoji='📸',style=discord.ButtonStyle.primary,custom_id='lv:game:start:foto')
 async def photo(self,i,button):await self.system.play(i,'foto')
 @discord.ui.button(label='Roleplay',emoji='🎭',custom_id='lv:game:start:roleplay')
 async def rp(self,i,button):await self.system.play(i,'roleplay')
 @discord.ui.button(label='Acertijos',emoji='🧩',custom_id='lv:game:start:acertijo')
 async def riddle(self,i,button):await self.system.play(i,'acertijo')
 @discord.ui.button(label='Mi progreso',emoji='📊',custom_id='lv:game:progress',row=1)
 async def progress(self,i,button):await self.system.progress(i)
 @discord.ui.button(label='Ranking',emoji='🏆',custom_id='lv:game:ranking',row=1)
 async def ranking(self,i,button):await self.system.ranking(i)

LABELS={'answer':('Responder','✍️'),'skip':('Otra pregunta','🔄'),'next':('Siguiente','➡️'),'hint':('Dame una pista','💡')}
class GameAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lv:game:session:(?P<token>[a-f0-9]{24}):(?P<action>answer|skip|next|hint)'):
 def __init__(self,token,action):
  label,emoji=LABELS[action]
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lv:game:session:{token}:{action}',
   style=discord.ButtonStyle.primary if action in {'answer','next'} else discord.ButtonStyle.secondary))
  self.token,self.action=token,action
 @classmethod
 async def from_custom_id(cls,i,item,match):return cls(match['token'],match['action'])
 async def callback(self,i):
  try:await i.client.minigames.action(i,self.token,self.action)
  except ValueError as error:await reply(i,str(error))
  except Exception as error:
   log.error('Minigame action failed',exc_info=error)
   await reply(i,'No pude completar eso. Abre el juego otra vez para ver cómo quedó. Tus premios siguen guardados.')

def controls(token,actions):
 view=SafeView(timeout=None)
 for action in actions:view.add_item(GameAction(token,action))
 return view

class AnswerForm(discord.ui.Modal):
 def __init__(self,system,token):
  super().__init__(title='¿Cuál es tu respuesta?',timeout=600);self.system,self.token=system,token
  self.answer=discord.ui.TextInput(label='Escribe tu respuesta',max_length=150,placeholder='Puedes escribir sin tildes ni mayúsculas.')
  self.add_item(self.answer)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  try:await self.system.answer(i,self.token,self.answer.value)
  except ValueError as error:await reply(i,str(error),view=controls(self.token,['answer']))
 async def on_error(self,i,error):
  log.error('Minigame answer failed',exc_info=error)
  await reply(i,'No pude comprobar la respuesta. Tu progreso se conserva; vuelve a abrir la pregunta.')
