"""Small persistent controls for staff recruitment."""
import json
import logging
import discord
from recruitment_store import QUESTIONS, LABELS

log=logging.getLogger('LaVenganzaRP.recruitment')
RED=0xC52232

async def reply(i,text=None,**kwargs):
 sender=i.followup.send if i.response.is_done() else i.response.send_message
 return await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)

class SafeView(discord.ui.View):
 async def on_error(self,i,error,item):
  log.error('Recruitment control failed',exc_info=error)
  await reply(i,str(error) if isinstance(error,ValueError) else 'No pude completar eso. Tu solicitud sigue guardada; inténtalo otra vez.')

class SafeModal(discord.ui.Modal):
 async def on_error(self,i,error):
  log.error('Recruitment form failed',exc_info=error)
  await reply(i,str(error) if isinstance(error,ValueError) else 'No pude guardar eso. Inténtalo otra vez desde «Mi solicitud».')

ACTIONS={'continue':('Seguir formulario','📝'),'submit':('Enviar solicitud','📨'),
 'status':('Mi solicitud','📂'),'restart':('Cambiar respuestas','✏️'),'reply':('Responder al equipo','💬'),'withdraw':('Retirar solicitud','↩️'),
 'detail':('Ver solicitud','📋'),'claim':('Me encargo','🙋'),'interview':('Entrevista','🎙️'),
 'decision':('Decidir','✅'),'question':('Pedir información','❓'),'message':('Enviar mensaje','💬'),
 'note':('Nota para el equipo','📝'),'history':('Ver historial','📜'),'schedule':('Agendar entrevista','📅'),
 'attended':('Entrevista realizada','✔️'),'accept':('Aceptar','✅'),'reject':('No aceptar','❌')}

class RecruitAction(discord.ui.DynamicItem[discord.ui.Button],template=r'lv:recruit:(?P<case>[0-9]+):(?P<action>[a-z]+)'):
 def __init__(self,rid,action):
  label,emoji=ACTIONS.get(action,('Abrir solicitud','📂'))
  super().__init__(discord.ui.Button(label=label,emoji=emoji,custom_id=f'lv:recruit:{rid}:{action}',
   style=discord.ButtonStyle.primary if action in {'continue','submit','accept'} else discord.ButtonStyle.secondary))
  self.rid,self.action=rid,action
 @classmethod
 async def from_custom_id(cls,i,item,match):return cls(int(match['case']),match['action'])
 async def callback(self,i):
  try:await i.client.recruitment.action(i,self.rid,self.action)
  except ValueError as error:await reply(i,str(error))
  except Exception as error:
   log.error('Recruitment action failed case=%s action=%s',self.rid,self.action,exc_info=error)
   await reply(i,'No pude completar eso. La solicitud sigue guardada; vuelve a abrirla para revisar cómo quedó.')

def controls(rid,actions):
 view=SafeView(timeout=None)
 for n,action in enumerate(actions):
  item=RecruitAction(rid,action);item.item.row=n//4;view.add_item(item)
 return view

class RecruitPanel(SafeView):
 def __init__(self,system):super().__init__(timeout=None);self.system=system
 @discord.ui.button(label='Solicitar STAFF',emoji='🛡️',style=discord.ButtonStyle.primary,custom_id='lv:recruit:apply')
 async def apply(self,i,button):
  try:await self.system.open_form(i)
  except ValueError as error:await reply(i,str(error))
 @discord.ui.button(label='Mi solicitud',emoji='📂',custom_id='lv:recruit:mine')
 async def mine(self,i,button):await self.system.mine(i)

class ApplicationForm(SafeModal):
 def __init__(self,system,row):
  super().__init__(title=f'Solicitar STAFF · {row["step"]+1}/2',timeout=900)
  self.system,self.rid,self.revision,self.owner,self.step=system,row['id'],row['revision'],row['owner'],row['step']
  answers=json.loads(row['answers']);self.inputs={}
  for key,label,limit,hint,paragraph in QUESTIONS[:5] if self.step==0 else QUESTIONS[5:]:
   text=discord.ui.TextInput(label=label,placeholder=hint,max_length=limit,required=key!='extra',
    style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,default=answers.get(key) or None)
   self.inputs[key]=text;self.add_item(text)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  await self.system.save_form(i,self,{key:str(value.value) for key,value in self.inputs.items()})

class TextForm(SafeModal):
 def __init__(self,system,row,kind):
  labels={'reply':('Responder al equipo','¿Qué quieres decirle al equipo?'),
   'question':('Pedir información','¿Qué necesitas que te cuente?'),
   'message':('Mensaje al candidato','¿Qué quieres decirle?'),
   'note':('Nota para el equipo','Solo la ve el equipo que revisa solicitudes'),
   'attended':('Entrevista realizada','¿Cómo fue la entrevista? Solo lo ve el equipo'),
   'accept':('Aceptar solicitud','Mensaje que recibirá el candidato'),
   'reject':('Responder solicitud','Explícale por qué no fue seleccionado')}
  title,label=labels[kind];super().__init__(title=title,timeout=900)
  self.system,self.rid,self.revision,self.kind=system,row['id'],row['revision'],kind
  self.text=discord.ui.TextInput(label=label[:45],style=discord.TextStyle.paragraph,max_length=1500)
  self.add_item(self.text)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  if self.kind in {'accept','reject'}:
   await self.system.prepare_decision(i,self.rid,self.kind=='accept',self.text.value,self.revision)
  else:await self.system.text(i,self.rid,self.kind,self.text.value,self.revision)

class InterviewForm(SafeModal):
 def __init__(self,system,row):
  super().__init__(title='Agendar entrevista · Puerto Rico',timeout=900)
  self.system,self.rid,self.revision=system,row['id'],row['revision']
  self.date=discord.ui.TextInput(label='Día (AAAA-MM-DD)',placeholder='Ejemplo: 2026-11-12',max_length=10)
  self.hour=discord.ui.TextInput(label='Hora de Puerto Rico (24 horas)',placeholder='Ejemplo: 19:30',max_length=5)
  self.message=discord.ui.TextInput(label='¿Qué debe saber antes de entrar?',placeholder='Ejemplo: Entra a la sala con el micrófono listo.',
   default='Entra a la Sala Entrevista a esa hora con tu micrófono listo.',style=discord.TextStyle.paragraph,max_length=1000)
  for value in (self.date,self.hour,self.message):self.add_item(value)
 async def on_submit(self,i):
  await i.response.defer(ephemeral=True,thinking=True)
  await self.system.schedule(i,self.rid,self.date.value,self.hour.value,self.message.value,self.revision)

class Confirm(SafeView):
 def __init__(self,owner,callback):super().__init__(timeout=300);self.owner,self.callback=owner,callback
 async def interaction_check(self,i):
  if i.user.id==self.owner:return True
  await reply(i,'Esa confirmación no es tuya.');return False
 @discord.ui.button(label='Confirmar',emoji='✅',style=discord.ButtonStyle.danger)
 async def confirm(self,i,button):
  for child in self.children:child.disabled=True
  # Component responses can edit the ephemeral prompt. Channel Message.edit cannot.
  await i.response.edit_message(view=self)
  self.stop()
  await self.callback(i)
 @discord.ui.button(label='Cancelar')
 async def cancel(self,i,button):
  for child in self.children:child.disabled=True
  self.stop();await i.response.edit_message(content='Cancelado. No se guardó ningún cambio.',embed=None,view=self)

class Pages(SafeView):
 def __init__(self,system,row,actor,pages,staff):
  super().__init__(timeout=600);self.system,self.rid,self.actor,self.pages,self.staff=system,row['id'],actor,pages,staff;self.index=0
 async def interaction_check(self,i):
  if i.user.id!=self.actor:await reply(i,'Abre tu propia consulta.');return False
  try:await self.system.authorized(i,self.rid,staff=self.staff)
  except ValueError as error:await reply(i,str(error));return False
  return True
 def embed(self):
  embed=discord.Embed(title=f'📋 Solicitud #{self.rid}',description=self.pages[self.index],color=RED)
  embed.set_footer(text=f'Página {self.index+1}/{len(self.pages)} · Consulta privada');return embed
 @discord.ui.button(label='Anterior',emoji='⬅️')
 async def previous(self,i,button):self.index=max(0,self.index-1);await i.response.edit_message(embed=self.embed())
 @discord.ui.button(label='Siguiente',emoji='➡️')
 async def next(self,i,button):self.index=min(len(self.pages)-1,self.index+1);await i.response.edit_message(embed=self.embed())

def summary(row,staff=False):
 embed=discord.Embed(title=f'🛡️ Solicitud de staff #{row["id"]}',color=RED)
 embed.description=f'<@{row["owner"]}> · **{LABELS[row["status"]]}**'
 embed.add_field(name='Encargado',value=f'<@{row["assignee"]}>' if row['assignee'] else 'Todavía sin asignar')
 embed.add_field(name='Enviada',value=f'<t:{row["created"]}:f>')
 if row['interview_at']:
  embed.add_field(name='Entrevista',value=f'<t:{row["interview_at"]}:F> · '+('Realizada' if row['interview_done'] else 'Pendiente'),inline=False)
 if row['result']:embed.add_field(name='Respuesta del equipo',value=row['result'][:1024],inline=False)
 embed.set_footer(text=f'La Venganza RP · staff-case:{row["id"]}' if staff else 'Tus datos solo los ve el equipo que revisa solicitudes.')
 return embed

def detail_pages(row,events,staff=False):
 answers=json.loads(row['answers'])
 sections=[f'**Estado:** {LABELS[row["status"]]}\n**Jugador:** <@{row["owner"]}>']
 sections.extend(f'**{label}**\n{answers.get(key,"Sin respuesta")}' for key,label,*_ in QUESTIONS)
 for event in events:
  if event['private'] and not staff:continue
  if event['text']:
   sections.append(f'<t:{event["created"]}:f> · **{event["action"].replace("_"," ")}**'+(' · Solo equipo' if event['private'] else '')+f'\n{event["text"]}')
 pages=[];current=''
 for section in sections:
  if len(current)+len(section)+2>3400:pages.append(current);current=''
  current+=('\n\n' if current else '')+section
 if current:pages.append(current)
 return pages or ['Sin respuestas.']
