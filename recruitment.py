"""Staff recruitment using the existing channels; protected roles are read-only."""
import asyncio
from contextlib import closing
from datetime import datetime
import json
import logging
import sqlite3
import time
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from recruitment_store import RecruitmentStore, ACTIVE, LABELS
from recruitment_survey import RecruitmentSource,survey_recruitment
from recruitment_ui import (RecruitPanel,RecruitAction,ApplicationForm,TextForm,InterviewForm,
 Confirm,Pages,controls,reply,summary,detail_pages,RED)
from tickets_store import ALL_STAFF,NORMAL_STAFF,PROTECTED

log=logging.getLogger('LaVenganzaRP.recruitment')
PR=ZoneInfo('America/Puerto_Rico')
CHANNELS={'apply':1567399097500041237,'review':1567399281680191579,
 'interviews':1567399614384967720,'voice':1567399822267519156}
LEGACY_PANEL=1567401986670858344
LEGACY_AUTHOR=1567401981461405756
MIGRATION='staff-transfer-20261109-v2'
NONE=discord.AllowedMentions.none()

def can_review(member):
 return bool(member.guild_permissions.administrator or {r.id for r in member.roles}&ALL_STAFF)

def pair(channel,target):
 overwrite=channel.overwrites_for(target);allow,deny=overwrite.pair()
 return {'present':any(o.id==target.id for o in channel._overwrites),'allow':str(allow.value),'deny':str(deny.value)}

def overwrite_from(saved):
 return discord.PermissionOverwrite.from_pair(discord.Permissions(int(saved['allow'])),discord.Permissions(int(saved['deny']))) if saved['present'] else None

def parse_date(day,hour):
 try:
  at=datetime.strptime(day.strip()+' '+hour.strip(),'%Y-%m-%d %H:%M').replace(tzinfo=PR)
  return int(at.timestamp())
 except ValueError:raise ValueError('Pon el día como 2026-11-12 y la hora como 19:30 (Puerto Rico).') from None

class RecruitmentSystem:
 def __init__(self,bot,path,guild_id):
  self.bot,self.path,self.guild_id=bot,path,guild_id;self.store=RecruitmentStore(path)
  self.lock=asyncio.Lock();self.install_lock=asyncio.Lock();self.io_lock=asyncio.Lock()
  self.prepared=False;self.task=None
  self.group=app_commands.Group(name='staff',description='Solicitudes para entrar al staff y entrevistas')
  self.register()
 async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
 async def start(self):
  if self.task is not None and not self.task.done():return
  await self.call('initialize');self.bot.add_view(RecruitPanel(self));self.bot.add_dynamic_items(RecruitAction)
  self.task=asyncio.create_task(self.loop(),name='staff-recruitment')
 async def member(self,i):
  if i.guild_id not in (None,self.guild_id):raise ValueError('Este sistema es de La Venganza RP.')
  guild=self.bot.get_guild(self.guild_id)
  if guild is None:raise ValueError('El bot se está conectando. Inténtalo en unos segundos.')
  try:return await guild.fetch_member(i.user.id)
  except discord.NotFound:raise ValueError('Tienes que estar en La Venganza RP para usar esto.') from None
 async def authorized(self,i,rid,staff=False):
  member=await self.member(i);row=await self.call('get',rid)
  if staff:
   if not can_review(member):raise ValueError('Solo el equipo autorizado puede revisar solicitudes.')
   if row['owner']==member.id:raise ValueError('No puedes revisar tu propia solicitud.')
   if not row['submitted']:raise ValueError('Esa solicitud todavía no se ha enviado.')
  elif row['owner']!=member.id:raise ValueError('Solo puedes ver tu propia solicitud desde aquí.')
  return member,row
 async def channel(self,key):
  channel=await self.bot.fetch_channel(CHANNELS[key])
  if channel.guild.id!=self.guild_id:raise ValueError('El canal no es de La Venganza RP.')
  if key in {'review','interviews','voice'} and channel.permissions_for(channel.guild.default_role).view_channel:
   raise ValueError('El canal de revisión o entrevistas dejó de ser privado. Hay que corregirlo antes de seguir.')
  return channel
 async def tracked(self,title,request,operation,keys=(),extra=None):
  async def snapshot():
   state={'channels':[]}
   for key in keys:
    channel=await self.bot.fetch_channel(CHANNELS[key])
    state['channels'].append({'id':str(channel.id),'name':channel.name,'overwrites':[
     {'id':str(o.id),'type':o.type,'allow':str(o.allow),'deny':str(o.deny)} for o in channel._overwrites]})
   if extra:state['data']=await extra()
   return state
  return await self.bot.changes.tracked('RECRUITMENT',title,operation,request_id=request,snapshot=snapshot)
 async def open_form(self,i,rid=None):
  member=await self.member(i)
  if can_review(member):raise ValueError('Ya formas parte del equipo. Las solicitudes son para jugadores que quieren entrar.')
  if not self.prepared:raise ValueError('Estamos preparando las solicitudes. Inténtalo en un momento.')
  row=await self.call('get',rid) if rid else await self.call('begin',member.id)
  if row['owner']!=member.id:raise ValueError('Esa solicitud no es tuya.')
  if row['status']!='borrador' or row['step']==2:
   await i.response.defer(ephemeral=True);return await self.show_status(i,row)
  await i.response.send_modal(ApplicationForm(self,row))
 async def save_form(self,i,form,values):
  await self.authorized(i,form.rid)
  await self.call('save_step',form.rid,i.user.id,form.step,values,form.revision)
  row=await self.call('get',form.rid)
  await self.show_status(i,row,details=row['step']==2)
 async def mine(self,i):
  await i.response.defer(ephemeral=True,thinking=True);await self.member(i)
  rows=await self.call('rows',owner=i.user.id,limit=8)
  if not rows:return await reply(i,'Todavía no has enviado una solicitud. Pulsa «Solicitar STAFF» para empezar.')
  await self.show_status(i,rows[0])
  if len(rows)>1:
   await reply(i,'**Tus solicitudes anteriores**\n'+'\n'.join(f'#{r["id"]} · {LABELS[r["status"]]} · <t:{r["created"]}:d>' for r in rows[1:]))
 async def show_status(self,i,row,details=False):
  status=row['status'];actions=[]
  if status=='borrador':actions=['continue','withdraw'] if row['step']<2 else ['submit','restart','withdraw']
  elif status in ACTIVE:actions=['reply','history','withdraw']
  else:actions=['history']
  embed=summary(row)
  if status=='borrador':embed.add_field(name='Formulario',value='Tus respuestas están guardadas. '+('Pulsa «Seguir formulario» para continuar.' if row['step']<2 else 'Revisa tus respuestas y pulsa «Enviar solicitud».'),inline=False)
  events=await self.call('events',row['id'])
  messages=[e for e in events if e['action'] in {'pregunta','mensaje','respuesta'}]
  if messages:
   last=messages[-1];embed.add_field(name='Último mensaje' if last['action']!='respuesta' else 'Tu última respuesta',value=last['text'][:1024],inline=False)
  view=controls(row['id'],actions)
  if row['interview_at'] and status=='entrevista' and row['interview_at']-3600<=time.time()<=row['interview_at']+7200:
   view.add_item(discord.ui.Button(label='Entrar a la entrevista',emoji='🎙️',url=f'https://discord.com/channels/{self.guild_id}/{CHANNELS["voice"]}',row=1))
  await reply(i,embed=embed,view=view)
  if details:
   pages=detail_pages(row,[],False);view=Pages(self,row,i.user.id,pages,False)
   await reply(i,embed=view.embed(),view=view)
 async def action(self,i,rid,action):
  if action not in {'continue','submit','restart','status','reply','withdraw','detail','claim','interview','decision','question','message','note','history','schedule','attended','accept','reject'}:raise ValueError('Ese botón ya no se usa.')
  if action=='continue':return await self.open_form(i,rid)
  candidate=action in {'submit','restart','status','reply','withdraw'}
  if action=='history':
   row=await self.call('get',rid);candidate=row['owner']==i.user.id
  modal=action in {'reply','question','message','note','attended','accept','reject','schedule'}
  if not modal:await i.response.defer(ephemeral=True,thinking=True)
  member,row=await self.authorized(i,rid,staff=not candidate)
  if action in {'status','continue'}:return await self.show_status(i,row)
  if action in {'detail','history'}:
   events=await self.call('events',rid,private=not candidate)
   view=Pages(self,row,i.user.id,detail_pages(row,events,not candidate),not candidate)
   await reply(i,embed=view.embed(),view=view)
   if not candidate and row['status'] in ACTIVE-{'borrador'}:await reply(i,'¿Necesitas preguntarle algo o dejar una nota?',view=controls(rid,['question','message','note']))
  elif action=='restart':
   await self.call('restart',rid,i.user.id,row['revision'])
   await self.show_status(i,await self.call('get',rid))
  elif action=='submit':
   async with self.lock:await self.call('submit',rid,i.user.id,row['revision'])
   await reply(i,'Listo, tu solicitud ya llegó al equipo. Puedes ver cómo va en «Mi solicitud».')
   await self.sync()
  elif action=='withdraw':
   async def confirm(next_i):
    _,current=await self.authorized(next_i,rid)
    async with self.lock:await self.call('withdraw',rid,next_i.user.id,row['revision'])
    await reply(next_i,'Retiraste tu solicitud. El equipo ya verá que no sigue abierta.');await self.sync()
   await reply(i,'¿Seguro que quieres retirar tu solicitud?',view=Confirm(i.user.id,confirm))
  elif action=='claim':
   async with self.lock:await self.call('claim',rid,i.user.id,row['revision'])
   await reply(i,'Listo, quedaste encargado de esta solicitud.');await self.sync()
  elif action=='interview':
   if row['status'] not in ACTIVE-{'borrador'}:raise ValueError('Esta solicitud ya terminó.')
   await reply(i,embed=summary(row),view=controls(rid,['schedule','attended']))
  elif action=='decision':
   if row['status'] not in ACTIVE-{'borrador'}:raise ValueError('Esta solicitud ya terminó.')
   await reply(i,'¿Qué respuesta quieres darle? Para aceptar, la entrevista debe estar marcada como realizada.\nLa administración le asigna el rol después.',view=controls(rid,['accept','reject']))
  elif action=='schedule':await i.response.send_modal(InterviewForm(self,row))
  elif modal:await i.response.send_modal(TextForm(self,row,action))
 async def text(self,i,rid,kind,text,revision):
  await self.authorized(i,rid,staff=kind!='reply')
  async with self.lock:
   if kind=='reply':await self.call('answer',rid,i.user.id,text,revision)
   elif kind=='attended':await self.call('interviewed',rid,i.user.id,text,revision)
   else:await self.call('staff_text',rid,i.user.id,{'question':'pregunta','message':'mensaje','note':'nota'}[kind],text,revision)
  await reply(i,{'reply':'Tu respuesta quedó guardada y el equipo la verá en la solicitud.','note':'Nota guardada. Solo la verá el equipo.','attended':'Entrevista marcada como realizada.'}.get(kind,'Mensaje guardado. El candidato lo verá en «Mi solicitud» y recibirá un aviso por privado si tiene los mensajes abiertos.'))
  await self.sync()
 async def schedule(self,i,rid,day,hour,text,revision):
  member,row=await self.authorized(i,rid,staff=True)
  at=parse_date(day,hour)
  async with self.lock:await self.call('schedule',rid,i.user.id,at,i.user.id,text,revision)
  await reply(i,f'Entrevista agendada para <t:{at}:F>. Tú quedas como entrevistador. El jugador recibirá el aviso por privado y podrá verla en «Mi solicitud».')
  await self.sync()
 async def prepare_decision(self,i,rid,accepted,text,revision):
  _,row=await self.authorized(i,rid,staff=True)
  if row['revision']!=revision:raise ValueError('La solicitud cambió. Revísala otra vez.')
  if accepted and not row['interview_done']:raise ValueError('Primero hay que hacer la entrevista y marcarla como realizada.')
  async def confirm(next_i):
   await self.authorized(next_i,rid,staff=True)
   async def operation():
    async with self.lock:await self.call('decide',rid,next_i.user.id,accepted,text,revision)
   await self.tracked('Responder solicitud de staff',f'decision:{next_i.id}',operation,
    extra=lambda:self.call('get',rid))
   await reply(next_i,('Aceptado. La administración debe asignarle su rol de entrada al staff.' if accepted else 'Respuesta guardada.')+' El candidato podrá verla en «Mi solicitud» y recibirá un aviso por privado si los tiene abiertos.')
   await self.sync()
  embed=discord.Embed(title='Confirmar respuesta',description=text[:2000],color=RED)
  embed.add_field(name='Jugador',value=f'<@{row["owner"]}> · Solicitud #{rid}')
  embed.add_field(name='Decisión',value='Aceptar · Rol asignado después por administración' if accepted else 'No aceptar')
  await reply(i,embed=embed,view=Confirm(i.user.id,confirm))
 async def list_cases(self,i,user=None,page=1):
  await i.response.defer(ephemeral=True,thinking=True);member=await self.member(i)
  if not can_review(member):raise ValueError('Solo el equipo autorizado puede consultar solicitudes.')
  rows=await self.call('rows',owner=user.id if user else None,active=user is None,limit=10,offset=(page-1)*10,submitted=True)
  rows=[r for r in rows if r['owner']!=i.user.id and r['status']!='borrador']
  lines=[f'**#{r["id"]}** · <@{r["owner"]}> · {LABELS[r["status"]]}'+(f' · <@{r["assignee"]}>' if r['assignee'] else '') for r in rows]
  await reply(i,embed=discord.Embed(title='📩 Solicitudes de staff',description='\n'.join(lines) or 'No hay solicitudes en esta página.',color=RED))
  if rows:
   view=RecruitList(self,rows,i.user.id);await reply(i,'Elige la solicitud que quieres abrir:',view=view)
 def register(self):
  @self.group.command(name='solicitar',description='Solicitar entrar al staff')
  async def apply(i:discord.Interaction):await self.open_form(i)
  @self.group.command(name='mi_solicitud',description='Ver tu solicitud y los mensajes del equipo')
  async def mine(i:discord.Interaction):await self.mine(i)
  @self.group.command(name='pendientes',description='Para el equipo: solicitudes que siguen abiertas')
  async def pending(i:discord.Interaction,pagina:app_commands.Range[int,1,10000]=1):await self.list_cases(i,page=pagina)
  @self.group.command(name='historial',description='Para el equipo: buscar solicitudes de un jugador')
  async def history(i:discord.Interaction,jugador:discord.Member,pagina:app_commands.Range[int,1,10000]=1):await self.list_cases(i,jugador,pagina)
  @self.group.command(name='ver',description='Abrir una solicitud por su número')
  async def view(i:discord.Interaction,numero:app_commands.Range[int,1,1000000000]):
   row=await self.call('get',numero);await self.action(i,numero,'status' if row['owner']==i.user.id else 'detail')
  @self.group.command(name='abrir',description='Administración: abrir o pausar las solicitudes nuevas')
  async def intake(i:discord.Interaction,abierto:bool):
   await i.response.defer(ephemeral=True);member=await self.member(i)
   if not member.guild_permissions.administrator:raise ValueError('Solo administradores de Discord pueden abrir o pausar las solicitudes.')
   async def confirm(next_i):
    member=await self.member(next_i)
    if not member.guild_permissions.administrator:raise ValueError('Ya no tienes permisos de administrador.')
    async def operation():
     await self.call('config','open','1' if abierto else '0');await self.panel()
    await self.tracked('Abrir o pausar reclutamiento',f'intake:{next_i.id}',operation,('apply',),extra=lambda:self.intake_state())
    await reply(next_i,'Solicitudes abiertas.' if abierto else 'Solicitudes pausadas. Las que ya llegaron siguen en revisión.')
   await reply(i,'¿Quieres '+('abrir las solicitudes?' if abierto else 'pausar las solicitudes nuevas?'),view=Confirm(i.user.id,confirm))
  @self.group.error
  async def error(i,exc):
   original=getattr(exc,'original',exc)
   if not isinstance(original,ValueError):log.error('Recruitment command failed',exc_info=original)
   await reply(i,str(original) if isinstance(original,ValueError) else 'No pude completar eso. La solicitud sigue guardada.')
 async def intake_state(self):return {'open':await self.call('config','open')}
 async def panel(self):
  channel=await self.channel('apply');saved=await self.call('config','panel');message=None
  if saved:
   try:message=await channel.fetch_message(int(saved))
   except discord.NotFound:pass
  if not message:
   async for candidate in channel.history(limit=100):
    if candidate.author.id==self.bot.user.id and any(e.footer.text=='La Venganza RP · staff-recruitment-panel' for e in candidate.embeds):message=candidate;break
  opened=await self.call('config','open')=='1'
  embed=discord.Embed(title='🛡️ ¿Quieres entrar al staff?',color=RED,
   description=('**Estamos recibiendo solicitudes.**' if opened else '**Las solicitudes nuevas están pausadas.**')+
   '\n\nCuéntanos un poco de ti y cómo ayudarías en el servidor. El formulario tiene dos partes y puedes seguirlo desde «Mi solicitud».\n\n'
   '**Así funciona**\n📝 Envías tu solicitud.\n🔎 El equipo la revisa y puede hacerte preguntas.\n🎙️ Si sigues en el proceso, te citamos a una entrevista por voz.\n📩 Te avisamos la decisión por privado. También podrás verla aquí.\n\n'
   '**Antes de aplicar**\nConoce las reglas y responde con tus palabras. La entrevista es obligatoria. Enviar el formulario no garantiza que te acepten.\n\n'
   'Tus respuestas las ven Owner, Programador, Jefe de Staff, Súper Admin, Admin, Moderador y Soporte.\nSi tienes los mensajes privados cerrados, revisa «Mi solicitud».')
  embed.set_footer(text='La Venganza RP · staff-recruitment-panel');view=RecruitPanel(self);view.apply.disabled=not opened
  if message:
   if message.author.id!=self.bot.user.id:raise ValueError('El panel guardado pertenece a otro bot.')
   await message.edit(embed=embed,view=view)
  else:message=await channel.send(embed=embed,view=view,allowed_mentions=NONE)
  verified=await channel.fetch_message(message.id)
  ids=[c.custom_id for row in verified.components for c in getattr(row,'children',[]) if hasattr(c,'custom_id')]
  if not {'lv:recruit:apply','lv:recruit:mine'}<=set(ids):raise ValueError('Discord no guardó los botones del panel de staff.')
  await self.call('config','panel',message.id);return message
 async def access(self):
  for key in ('review','interviews','voice'):
   channel=await self.channel(key)
   before={o.id:(o.type,o.allow,o.deny) for o in channel._overwrites if o.id in PROTECTED}
   for rid in sorted(NORMAL_STAFF):
    role=channel.guild.get_role(rid)
    if role is None:raise ValueError(f'Falta un rol de revisión: {rid}.')
    overwrite=channel.overwrites_for(role);old=overwrite.pair()
    overwrite.view_channel=True;overwrite.read_message_history=True
    if key=='voice':overwrite.connect=True;overwrite.speak=True
    else:overwrite.send_messages=True
    if overwrite.pair()!=old:await channel.set_permissions(role,overwrite=overwrite,reason='Reclutamiento: revisores indicados por el owner')
   fresh=await self.channel(key)
   after={o.id:(o.type,o.allow,o.deny) for o in fresh._overwrites if o.id in PROTECTED}
   if before!=after:raise ValueError('Cambió un acceso protegido. Se detiene la instalación.')
   for rid in NORMAL_STAFF:
    role=fresh.guild.get_role(rid)
    if not fresh.permissions_for(role).view_channel:raise ValueError('No quedó visible para todo el equipo indicado.')
 async def retire_legacy(self):
  source=RecruitmentSource(self.path)
  with closing(sqlite3.connect(self.path,timeout=10)) as db:
   saved=db.execute('SELECT payload FROM lv_recruit_sources WHERE channel=? AND message=?',(str(CHANNELS['apply']),str(LEGACY_PANEL))).fetchone()
  if not saved:raise ValueError('Falta el respaldo del panel anterior. No se retira.')
  backup=json.loads(saved[0])
  if backup['attachments'] or int(backup['author'])!=LEGACY_AUTHOR or not backup['components']:raise ValueError('El panel anterior necesita una revisión antes de sustituirlo.')
  channel=await self.channel('apply')
  try:message=await channel.fetch_message(LEGACY_PANEL)
  except discord.NotFound:return
  if (message.author.id!=LEGACY_AUTHOR or [c.to_dict() for c in message.components]!=backup['components']
   or message.content!=backup['content'] or [e.to_dict() for e in message.embeds]!=backup['embeds'] or message.attachments):raise ValueError('El panel anterior cambió. Se conserva.')
  review=await self.channel('review')
  async for candidate in review.history(limit=1):
   if candidate.author.id!=self.bot.user.id:raise ValueError('Llegó una solicitud al sistema anterior durante la transferencia; se conserva el panel anterior para revisarla.')
  await message.delete()
 async def ready(self):
  async with self.install_lock:
   report=await survey_recruitment(self.bot,self.path,self.guild_id)
   if report['counts'].get(str(CHANNELS['review']),0):raise ValueError('Hay solicitudes antiguas que requieren importación antes de transferir el panel.')
   if not self.prepared:
    await self.tracked('Dar acceso a los revisores de solicitudes de staff',MIGRATION+':access',self.access,('review','interviews','voice'))
    async def swap():
     message=await self.panel();await self.retire_legacy();return message
    await self.tracked('Transferir el panel de solicitudes de staff',MIGRATION+':panel',swap,('apply',),extra=lambda:self.intake_state())
   review=await self.channel('review');roles=await review.guild.fetch_roles()
   permitted=[str(r.id) for r in roles if r.id in ALL_STAFF and review.permissions_for(r).view_channel]
   if set(permitted)!={str(r) for r in ALL_STAFF}:raise ValueError('Falta acceso de alguno de los siete cargos indicados.')
   registered=await self.bot.tree.fetch_commands(guild=discord.Object(self.guild_id))
   command=next((c for c in registered if c.name=='staff'),None)
   if command is None or {o.name for o in command.options}!={c.name for c in self.group.commands}:
    raise ValueError('Discord todavía no confirmó los comandos de reclutamiento.')
   test_row={'id':1,'owner':1,'revision':0,'answers':'{}','step':0}
   forms=[ApplicationForm(self,test_row),ApplicationForm(self,dict(test_row,step=1)),InterviewForm(self,test_row)]
   for kind in ('reply','question','message','note','attended','accept','reject'):forms.append(TextForm(self,test_row,kind))
   for form in forms:
    payload=form.to_dict()
    if len(payload['components'])>5:raise ValueError('Hay demasiadas preguntas en un formulario.')
    form.stop()
   self.prepared=True
   await self.sync()
   log.info('RECRUIT ready apply=%s review=%s interviews=%s voice=%s panel=%s reviewers=%s old_panel_retired=True source_messages=%s acceptance_role=manual commands=%s',
    CHANNELS['apply'],CHANNELS['review'],CHANNELS['interviews'],CHANNELS['voice'],await self.call('config','panel'),','.join(permitted),sum(report['counts'].values()),','.join(c.name for c in self.group.commands))
   log.info('RECRUIT verified persistent_controls=True forms=%s private_channels=True protected_overwrites_unchanged=True auto_role=False',len(forms))
 async def publish_case(self,row,key,field):
  channel=await self.channel(key);message=None
  if row[field+'_message']:
   try:message=await channel.fetch_message(row[field+'_message'])
   except discord.NotFound:pass
  marker=f'La Venganza RP · staff-case:{row["id"]}'
  if not message:
   async for candidate in channel.history(limit=200):
    if candidate.author.id==self.bot.user.id and any(e.footer.text==marker for e in candidate.embeds):message=candidate;break
  active=row['status'] in ACTIVE-{'borrador'}
  embed=summary(row,True)
  if field=='review':
   events=await self.call('events',row['id'],private=True)
   latest=[e for e in events if e['text']]
   if latest:
    e=latest[-1];embed.add_field(name='Último movimiento · '+e['action'].replace('_',' '),value=e['text'][:1000],inline=False)
   actions=['detail','claim','interview','decision'] if active else ['detail']
  else:
   embed.title=f'🎙️ Entrevista · Solicitud #{row["id"]}';embed.add_field(name='Entrevistador',value=f'<@{row["interviewer"]}>')
   actions=['detail','interview'] if active else ['detail']
  if message:
   if message.author.id!=self.bot.user.id:raise ValueError('El mensaje de revisión pertenece a otro bot.')
   await message.edit(embed=embed,view=controls(row['id'],actions))
  else:message=await channel.send(embed=embed,view=controls(row['id'],actions),allowed_mentions=NONE)
  await self.call('receipt',row['id'],field,message.id,row['revision'])
 async def notices(self):
  for notice in await self.call('pending'):
   try:
    user=await self.bot.fetch_user(notice['user']);channel=await user.create_dm()
    marker=f'La Venganza RP · staff-notice:{notice["id"]}';found=None
    async for old in channel.history(limit=100):
     if old.author.id==self.bot.user.id and any(e.footer.text==marker for e in old.embeds):found=old;break
    if not found:
     embed=discord.Embed(title=f'🛡️ Tu solicitud de staff #{notice["application"]}',description=notice['text'][:3500],color=RED);embed.set_footer(text=marker)
     view=controls(notice['application'],['status'])
     row=await self.call('get',notice['application'])
     if row['status'] in ACTIVE-{'borrador'}:view.add_item(RecruitAction(row['id'],'reply'))
     view.add_item(discord.ui.Button(label='Ir a Aplicar Staff',url=f'https://discord.com/channels/{self.guild_id}/{CHANNELS["apply"]}'))
     found=await channel.send(embed=embed,view=view,allowed_mentions=NONE)
    await self.call('notice_done',notice['id'],'sent',found.id)
   except (discord.Forbidden,discord.NotFound):
    await self.call('notice_done',notice['id'],'blocked')
    log.info('RECRUIT notice blocked id=%s application=%s; candidate_status_available=True',notice['id'],notice['application'])
 async def voice_access(self,row):
  channel=await self.channel('voice');records=await self.call('voice',row['id']);record=records[0] if records else None
  now=int(time.time());active=row['status']=='entrevista' and not row['interview_done'] and row['interview_at']-3600<=now<=row['interview_at']+2*3600
  if not active and (not record or record['state'] in {'restored','conflict'}):return
  try:member=await channel.guild.fetch_member(row['owner'])
  except discord.NotFound:
   # A departed member's overwrite can still be restored using the typed snowflake.
   member=discord.Object(id=row['owner'],type=discord.Member)
  if active:
   if isinstance(member,discord.Member) and can_review(member):return
   if record and record['state']=='conflict':return
   current=pair(channel,member)
   if record and record['state']=='active':
    if current!=json.loads(record['after_json']):
     await self.call('voice_state',row['id'],'conflict');log.warning('RECRUIT voice manual change preserved case=%s',row['id'])
    elif record['expires']!=row['interview_at']+7200:
     await self.call('voice_save',row['id'],row['owner'],json.loads(record['before_json']),current,row['interview_at']+7200)
     await self.call('voice_state',row['id'],'active')
    return
   if record and record['state']=='restored':
    if record['expires']==row['interview_at']+7200:return
    record=None
   if record:
    before=json.loads(record['before_json']);after=json.loads(record['after_json'])
    if current not in (before,after):await self.call('voice_state',row['id'],'conflict');return
   else:
    before=current;overwrite=channel.overwrites_for(member);overwrite.view_channel=True;overwrite.connect=True;overwrite.speak=True
    allow,deny=overwrite.pair();after={'present':True,'allow':str(allow.value),'deny':str(deny.value)}
    await self.call('voice_save',row['id'],row['owner'],before,after,row['interview_at']+7200)
   async def grant():
    if current!=after:await channel.set_permissions(member,overwrite=overwrite_from(after),reason=f'Entrevista de staff #{row["id"]}; acceso temporal')
    check=await self.channel('voice')
    if pair(check,member)!=after:raise ValueError('Discord no confirmó el acceso de entrevista.')
    await self.call('voice_state',row['id'],'active')
   await self.tracked('Dar acceso temporal a entrevista',f'voice:{row["id"]}:{row["interview_at"]}',grant,('voice',))
  elif record and record['state'] in {'active','pending'}:
   before=json.loads(record['before_json']);after=json.loads(record['after_json']);current=pair(channel,member)
   if current==before:await self.call('voice_state',row['id'],'restored');return
   if current!=after:await self.call('voice_state',row['id'],'conflict');return
   async def restore():
    await channel.set_permissions(member,overwrite=overwrite_from(before),reason=f'Entrevista de staff #{row["id"]} terminada; restaurar acceso anterior')
    if pair(await self.channel('voice'),member)!=before:raise ValueError('Discord no confirmó la restauración del acceso.')
    await self.call('voice_state',row['id'],'restored')
   await self.tracked('Restaurar acceso al terminar entrevista',f'voice-restore:{row["id"]}:{row["interview_at"]}',restore,('voice',))
 async def sync(self):
  if not self.prepared:return
  async with self.io_lock:
   await self.call('remind')
   # Query only outstanding publications, not an unbounded history on every tick.
   with closing(sqlite3.connect(self.path,timeout=10)) as db:
    db.row_factory=sqlite3.Row
    rows=[dict(r) for r in db.execute("SELECT * FROM lv_recruit_cases WHERE submitted IS NOT NULL AND (review_revision!=revision OR (interview_at IS NOT NULL AND interview_revision!=revision)) ORDER BY id LIMIT 100")]
   for row in rows:
    try:
     if row['review_revision']!=row['revision']:await self.publish_case(row,'review','review')
     if row['interview_at'] and row['interview_revision']!=row['revision']:await self.publish_case(row,'interviews','interview')
    except discord.HTTPException:log.exception('RECRUIT publication pending case=%s',row['id'])
   rows=await self.call('rows',active=True,limit=1000)
   by_id={r['id']:r for r in rows}
   for record in await self.call('voice'):
    if record['state'] in {'pending','active'} and record['application'] not in by_id:by_id[record['application']]=await self.call('get',record['application'])
   for row in by_id.values():
    if row['interview_at']:
     try:await self.voice_access(row)
     except discord.HTTPException:log.exception('RECRUIT interview access pending case=%s',row['id'])
   await self.notices()
 async def loop(self):
  await self.bot.wait_until_ready()
  while not self.bot.is_closed():
   try:
    if not self.prepared:await self.ready()
    else:await self.sync()
   except Exception:log.exception('RECRUIT pending retry; records preserved')
   await asyncio.sleep(60)

class RecruitList(discord.ui.View):
 def __init__(self,system,rows,actor):
  super().__init__(timeout=300);self.actor,self.system=actor,system
  picker=discord.ui.Select(placeholder='Abrir solicitud',options=[discord.SelectOption(label=f'#{r["id"]} · {LABELS[r["status"]]}',value=str(r['id'])) for r in rows])
  async def select(i):
   if i.user.id!=self.actor:return await reply(i,'Abre tu propia consulta.')
   try:await system.action(i,int(picker.values[0]),'detail')
   except ValueError as error:await reply(i,str(error))
  picker.callback=select;self.add_item(picker)
