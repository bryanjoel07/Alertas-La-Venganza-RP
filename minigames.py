"""La Venganza RP minigames. No role, permission or channel mutations."""
import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands

from minigame_catalog import load_bank,ASSETS,KINDS
from minigame_store import MinigameStore,REWARD,normalize
from minigame_ui import GamePanel,GameAction,AnswerForm,controls,reply,RED

log=logging.getLogger('LaVenganzaRP.minigames')
GENERAL=1513422089162330184
MARKER='La Venganza RP · minigames-panel'

class MinigameSystem:
 def __init__(self,bot,path,guild_id):
  self.bot,self.guild_id=bot,guild_id;self.store=MinigameStore(path)
  self.lock=asyncio.Lock();self.prepared=False;self.bank=[]
  self.group=app_commands.Group(name='minijuegos',description='Tu progreso, ranking y juegos de La Venganza RP')
  self.play_command=app_commands.Command(name='jugar',description='Adivina un lugar, responde sobre rol o resuelve un acertijo',callback=self.command_play)
  self.register()
 async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
 async def start(self):
  self.bank=await asyncio.to_thread(load_bank,True)
  await self.call('initialize',self.bank)
  self.bot.add_view(GamePanel(self));self.bot.add_dynamic_items(GameAction)
 async def member(self,i):
  if i.guild_id!=self.guild_id:raise ValueError('Estos juegos son de La Venganza RP.')
  if i.channel_id!=GENERAL:raise ValueError(f'Abre los minijuegos en <#{GENERAL}>. Allí está el panel para jugar.')
  if i.user.bot:raise ValueError('Los minijuegos son para los jugadores.')
  guild=self.bot.get_guild(self.guild_id)
  if guild is None:raise ValueError('El bot se está conectando. Inténtalo en un momento.')
  try:return await guild.fetch_member(i.user.id)
  except discord.NotFound:raise ValueError('Tienes que estar en La Venganza RP para jugar.') from None
 async def command_play(self,i:discord.Interaction,modo:Literal['foto','roleplay','acertijo']='foto'):
  try:await self.play(i,modo)
  except ValueError as error:await reply(i,str(error))
  except Exception as error:
   log.error('Could not open minigame',exc_info=error)
   await reply(i,'No pude abrir el juego. Inténtalo otra vez; tu progreso sigue guardado.')
 async def play(self,i,kind,previous=None,skip=False):
  if not i.response.is_done():await i.response.defer(ephemeral=True,thinking=True)
  await self.member(i)
  row=await self.call('open',i.user.id,kind,previous=previous,skip=skip)
  if row is None:
   await reply(i,'¡Ya acertaste todas las preguntas de este modo! 🏆\nPuedes probar los otros modos desde estos botones.',view=GamePanel(self));return
  await self.show_question(i,row)
 async def show_question(self,i,row):
  q=json.loads(row['payload'])
  embed=discord.Embed(title={'foto':'📸 ¿Conoces Los Santos?','roleplay':'🎭 ¿Qué tanto sabes de rol?','acertijo':'🧩 A ver si te sale…'}[q['kind']],
   description=q['prompt']+'\n\nPulsa **Responder** y escribe tu respuesta.\n🪙 **25 monedas si aciertas.**',color=RED)
  embed.set_footer(text=('Recreación de un lugar de GTA V · ' if q['kind']=='foto' else '')+'Un premio por pregunta y jugador · Tu progreso se guarda')
  kwargs={}
  if q.get('image'):
   image=(ASSETS/q['image']).resolve()
   if image.parent!=ASSETS.resolve() or not image.is_file():raise ValueError('No encuentro la imagen. Puedes elegir otro modo mientras se revisa.')
   kwargs['file']=discord.File(image,filename='reto.png');embed.set_image(url='attachment://reto.png')
  await reply(i,embed=embed,view=controls(row['id'],['answer','hint','skip']),**kwargs)
 async def action(self,i,token,action):
  if action!='answer':await i.response.defer(ephemeral=True,thinking=True)
  await self.member(i);row=await self.call('get',token,i.user.id);q=json.loads(row['payload'])
  if action=='answer':
   if row['status']!='active':
    await i.response.defer(ephemeral=True)
    return await reply(i,'Esta pregunta ya terminó. Pulsa «Siguiente» para seguir jugando.',view=controls(token,['next']))
   await i.response.send_modal(AnswerForm(self,token))
  elif action=='hint':
   if row['status']!='active':return await reply(i,'Esta pregunta ya terminó.',view=controls(token,['next']))
   hint=q.get('hint') or f'La respuesta empieza por **{normalize(q["answer"])[0].upper()}**.'
   await reply(i,'💡 '+hint,view=controls(token,['answer']))
  elif action in {'next','skip'}:
   await self.play(i,q['kind'],previous=token,skip=action=='skip')
  else:raise ValueError('Ese botón ya no se usa.')
 async def answer(self,i,token,text):
  await self.member(i)
  row=await self.call('get',token,i.user.id)
  result=await self.call('answer',i.user.id,token,text,str(i.id),self.bot.user.id)
  q=json.loads(row['payload'])
  if result['state']=='wrong':
   return await reply(i,'Por ahí no, bro. Prueba otra vez o pide una pista.',view=controls(token,['answer','hint','skip']))
  if result['state']=='skipped':return await reply(i,'Esa pregunta ya la cambiaste. Abre el juego para seguir con la actual.',view=GamePanel(self))
  if result['state']=='already':
   return await reply(i,'Esa ya la acertaste y su premio está guardado. Vamos con la siguiente.',view=controls(token,['next']))
  embed=discord.Embed(title='✅ ¡Esa es!',color=RED,description=f'**{q["answer"]}**\n{q["explanation"]}\n\n🪙 **+{result["coins"]} monedas**\nTu saldo de la tienda: **{result["balance"]:,} monedas**.')
  embed.set_footer(text='Puedes usarlas en la Tienda Exclusive y verlas con /saldo o /perfil.')
  await reply(i,embed=embed,view=controls(token,['next']))
  log.info('MINIGAME paid question=%s user=%s coins=%s receipt=%s replayed=%s',q['id'],i.user.id,result['coins'],i.id,result.get('replayed',False))
 async def progress(self,i):
  await i.response.defer(ephemeral=True,thinking=True);await self.member(i)
  progress=await self.call('progress',i.user.id)
  embed=discord.Embed(title='📊 Tus minijuegos',color=RED,
   description='\n'.join(f'**{KINDS[k["kind"]]}:** {k["won"]}/{k["total"]} acertadas' for k in progress['kinds']))
  embed.add_field(name='Ganaste jugando',value=f'{progress["coins"]:,} monedas')
  embed.add_field(name='Saldo actual de la tienda',value=f'{progress["balance"]:,} monedas')
  await reply(i,embed=embed)
 async def ranking(self,i):
  await i.response.defer(ephemeral=True,thinking=True);await self.member(i);rows=await self.call('ranking')
  lines=[f'**{n}.** <@{r["user"]}> · **{r["correct"]}** aciertos · {r["coins"]:,} monedas ganadas' for n,r in enumerate(rows,1)]
  await reply(i,embed=discord.Embed(title='🏆 Ranking de minijuegos',description='\n'.join(lines) or 'Todavía no hay aciertos. ¡Puedes ser el primero!',color=RED))
 def register(self):
  @self.group.command(name='progreso',description='Ver tus aciertos y monedas ganadas')
  async def progress(i:discord.Interaction):await self.progress(i)
  @self.group.command(name='ranking',description='Ver quién lleva más aciertos')
  async def ranking(i:discord.Interaction):await self.ranking(i)
  @self.group.command(name='panel',description='Administración: recuperar el panel de juegos en General')
  async def panel(i:discord.Interaction):
   await i.response.defer(ephemeral=True,thinking=True);member=await self.member(i)
   if not member.guild_permissions.administrator:raise ValueError('Solo la administración puede recuperar el panel.')
   await self.ready(force=True,request=f'panel:{i.id}')
   await reply(i,'Panel comprobado en General. El progreso y los premios siguen guardados.')
  @self.group.error
  async def error(i,exc):
   original=getattr(exc,'original',exc)
   if not isinstance(original,ValueError):log.error('Minigame command failed',exc_info=original)
   await reply(i,str(original) if isinstance(original,ValueError) else 'No pude completar eso. Tu progreso sigue guardado.')
 async def find_panel(self,channel):
  saved=await self.call('config','panel')
  if saved:
   try:return await channel.fetch_message(int(saved))
   except discord.NotFound:pass
  async for candidate in channel.history(limit=150):
   if candidate.author.id==self.bot.user.id and any(e.footer.text==MARKER for e in candidate.embeds):return candidate
  return None
 async def panel_state(self):
  channel=await self.bot.fetch_channel(GENERAL)
  state={'channel':str(channel.id),'name':channel.name,'overwrites':[
   {'id':str(o.id),'type':o.type,'allow':str(o.allow),'deny':str(o.deny)} for o in channel._overwrites],
   'questions':await self.call('audit'),'panel':None}
  message=await self.find_panel(channel)
  if message:state['panel']={'id':str(message.id),'author':str(message.author.id),
   'content':message.content,'embeds':[e.to_dict() for e in message.embeds],'components':[c.to_dict() for c in message.components]}
  return state
 async def publish_panel(self):
  channel=await self.bot.fetch_channel(GENERAL)
  if channel.guild.id!=self.guild_id:raise ValueError('General no pertenece al servidor indicado.')
  message=await self.find_panel(channel)
  counts={kind:sum(q['kind']==kind for q in self.bank) for kind in KINDS}
  embed=discord.Embed(title='🧩 Un rato de juegos, bro',color=RED,
   description=f'📸 **Adivina el lugar:** {counts["foto"]} imágenes de sitios de GTA V.\n🎭 **Roleplay:** {counts["roleplay"]} preguntas para poner a prueba lo que sabes.\n🧩 **Acertijos:** {counts["acertijo"]} para darle al coco.\n\n'
   '**Cada acierto te da 25 monedas para la tienda.**\nCada pregunta paga una sola vez por jugador. Las respuestas se escriben por privado y tu progreso queda guardado.\n\nElige un modo para empezar 👇')
  embed.set_footer(text=MARKER)
  if message:
   if message.author.id!=self.bot.user.id:raise ValueError('El mensaje guardado no pertenece a este bot.')
   await message.edit(embed=embed,view=GamePanel(self))
  else:message=await channel.send(embed=embed,view=GamePanel(self),allowed_mentions=discord.AllowedMentions.none())
  await self.call('config','panel',message.id)
  verified=await channel.fetch_message(message.id)
  ids={c.custom_id for row in verified.components for c in getattr(row,'children',[]) if hasattr(c,'custom_id')}
  expected={'lv:game:start:foto','lv:game:start:roleplay','lv:game:start:acertijo','lv:game:progress','lv:game:ranking'}
  if ids!=expected:raise ValueError('Discord no guardó todos los botones del juego.')
  return message
 async def ready(self,force=False,request='minigames-general-v1'):
  async with self.lock:
   if self.prepared and not force:return
   await self.bot.changes.tracked('MINIGAME_PANEL','Preparar minijuegos en General',self.publish_panel,
    request_id=request,snapshot=self.panel_state)
   audit=await self.call('audit')
   if audit['invalid_rewards']:raise ValueError('Hay premios que no coinciden con su movimiento de monedas.')
   commands=await self.bot.tree.fetch_commands(guild=discord.Object(self.guild_id))
   if not {'jugar','minijuegos'}<={c.name for c in commands}:raise ValueError('Discord todavía no confirmó los comandos del juego.')
   self.prepared=True
   log.info('MINIGAME ready channel=%s panel=%s questions=%s reward=%s wins=%s invalid_rewards=%s images=%s persistent_controls=True roles_unchanged=True',
    GENERAL,await self.call('config','panel'),json.dumps(audit['questions']),REWARD,audit['wins'],audit['invalid_rewards'],len(list(ASSETS.glob('lugar-*.png'))))
