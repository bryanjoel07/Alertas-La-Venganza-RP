"""Native Discord application-style settings; all views are private to their owner."""
import logging
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from settings_catalog import SECTIONS,BY_SECTION,BY_FORM,Form,Field,validate

RED=0xD60000
NONE=discord.AllowedMentions.none()
log=logging.getLogger('LaVenganzaRP.settings')


def display(field,value):
 if field.kind=='bool':return '✅ Activado' if value else '⏸️ Pausado'
 if field.kind=='multi':return ' · '.join(label for key,label in field.options if key in value) or 'Sin recordatorios'
 if field.kind=='channel':return f'<#{value}>'
 if field.kind=='int':return f'{value:,}'
 return str(value) or 'Sin palabras adicionales'


def searchable(text):
 return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if unicodedata.category(c)!='Mn')


class AppView(discord.ui.LayoutView):
 def __init__(self,system,owner,origin,state,section='home',*,page=0,query='',rows=(),details=None,notice=None):
  super().__init__(timeout=840)
  self.system,self.owner,self.origin,self.state=system,owner,origin,state
  self.section,self.page,self.query,self.rows,self.details=section,page,query,list(rows),details
  self.box=discord.ui.Container(accent_colour=RED);self.add_item(self.box)
  title='⚙️ La Venganza RP · Centro de ajustes'
  if section in BY_SECTION:
   spec=BY_SECTION[section];title=f'{spec.emoji} {spec.title}'
  elif section=='directory':title='🧰 Funciones del bot'
  elif section=='catalog':title='🛍️ Productos de la tienda'
  elif section=='history':title='🧾 Historial de ajustes'
  elif section=='detail':title='🧾 Detalle del cambio'
  self.text('## '+title+('\n'+notice if notice else ''))
  self.box.add_item(discord.ui.Separator())
  if section=='home':self.home()
  elif section=='directory':self.directory()
  elif section=='catalog':self.catalog()
  elif section=='history':self.history()
  elif section=='detail':self.detail()
  else:self.module()
  self.menu()
  self.nav()
  self.text('-# Solo tú puedes ver este panel · Los cambios requieren confirmación.')

 def text(self,text):self.box.add_item(discord.ui.TextDisplay(text))

 def row(self,buttons):
  if buttons:self.box.add_item(discord.ui.ActionRow(*buttons))

 def button(self,label,callback,emoji=None,style=discord.ButtonStyle.secondary):
  button=discord.ui.Button(label=label,emoji=emoji,style=style)
  button.callback=callback;return button

 async def interaction_check(self,i):
  from settings_panel import private
  if i.user.id!=self.owner:
   await private(i,'Este panel pertenece a quien lo abrió. Usa /ajustes panel.');return False
  try:await self.system.authorize(i)
  except ValueError as error:await private(i,str(error));return False
  self.origin=i;return True

 async def on_error(self,i,error,item):
  from settings_panel import private
  if not isinstance(error,ValueError):log.error('SETTINGS app_failed',exc_info=error)
  await private(i,str(error) if isinstance(error,ValueError) else 'No pude abrir esa opción. Actualiza el panel e inténtalo otra vez.')

 async def on_timeout(self):
  expired=discord.ui.LayoutView()
  expired.add_item(discord.ui.Container(discord.ui.TextDisplay('⚙️ Este panel expiró. Usa **/ajustes panel** para abrir otro.'),accent_colour=RED))
  try:await self.origin.edit_original_response(view=expired)
  except discord.HTTPException:pass

 def home(self):
  self.text('Todo el bot en un solo lugar. **Elige un sistema en el menú de abajo** para ver sus ajustes y funciones.\n'
   'Los formularios muestran los valores que ya estás usando. Primero revisas el cambio y después decides si guardarlo.')
  self.text('### Tus sistemas\n'+'\n'.join(' · '.join(f'{s.emoji} {s.title}' for s in SECTIONS[n:n+2]) for n in range(0,len(SECTIONS),2)))
  self.text(f'**Server Up:** {self.state["values"]["daily_server_up_time"]} · Puerto Rico\n'
   f'**Fotos:** 🥇 {self.state["rewards"][0]:,} · 🥈 {self.state["rewards"][1]:,} · 🥉 {self.state["rewards"][2]:,} monedas\n'
   '**La configuración actual se conserva hasta que guardes un cambio.**')
  async def search(i):await i.response.send_modal(SearchForm(self.system,self.owner))
  self.row([self.button('Buscar una función',search,'🔎'),self.button('Ver todos los comandos',self.go('directory'),'🧰')])

 def module(self):
  spec=BY_SECTION[self.section]
  self.text(spec.description)
  parts=[]
  for form in BY_FORM.values():
   if form.section!=self.section:continue
   values=self.state['systems'][form.key]
   lines=[f'**{f.label}:** {display(f,values[f.key])[:180]}' for f in form.fields]
   parts.append('### '+form.title+'\n'+'\n'.join(lines))
  if self.section=='server':
   parts.insert(0,'### Server Up diario\n**Hora:** '+self.state['values']['daily_server_up_time']+' · Puerto Rico\n**Título:** '+discord.utils.escape_markdown(self.state['values']['daily_server_up_title']))
  if self.section=='photos':
   parts.insert(0,'### Premios semanales\n**Esta semana:** '+self.system.prize_text(self.state['rewards'])+'\n**Próxima semana:** '+self.system.prize_text(self.state['next_rewards']))
  if self.section=='games':parts.append('🪙 **25 monedas por acierto.** Cada pregunta paga una vez por jugador. Los intentos son compartidos entre los tres modos.')
  if self.section=='bugs':parts.append('📎 **Pruebas obligatorias · Hasta diez fotos o videos · 120 MB por archivo.** Los archivos y casos existentes se conservan.')
  if self.section=='tickets':parts.append('🔒 Los reportes contra staff siguen reservados a administradores. Reclamar, resolver, prioridad, miembros y cierre se gestionan desde cada ticket.')
  if self.section=='activity':parts.append(self.system.status_text())
  if self.section=='backups':parts.append(self.system.backup_text())
  if self.section=='security':parts.append('El filtro conserva la lista base y las exenciones del servidor. Cambiar estos valores no modifica roles ni permisos.')
  self.text('\n\n'.join(parts)[:3500])
  controls=[]
  for form in BY_FORM.values():
   if form.section==self.section:
    async def edit(i,key=form.key):await i.response.send_modal(SystemForm(self.system,self.owner,self.state,key))
    controls.append(self.button(form.title,edit,'⚙️',discord.ButtonStyle.primary))
  if self.section=='server':
   for kind,label in (('schedule','Hora del Server Up'),('text','Mensaje del Server Up')):
    async def old_form(i,kind=kind):
     from settings_panel import SettingsForm
     await i.response.send_modal(SettingsForm(self.system,self.owner,self.state,kind))
    controls.append(self.button(label,old_form,'📝'))
  if self.section=='photos':
   async def prizes(i):
    from settings_panel import RewardScope,prizes
    await i.response.send_message(embed=discord.Embed(title='📸 Premios de Fotos',color=RED,
     description=f'**Esta semana:** {prizes(self.state["rewards"])}\n**Próxima semana:** {prizes(self.state["next_rewards"])}\n\nElige cuándo aplicarlos. Los premios ya pagados se conservan.'),
     view=RewardScope(self.system,self.owner,i,self.state),ephemeral=True,allowed_mentions=NONE)
   controls.append(self.button('Cambiar premios del podio',prizes,'🏆'))
  if self.section=='economy':controls.append(self.button('Editar productos',self.go('catalog'),'🛍️'))
  if self.section=='activity':controls.append(self.button('Ver cambios guardados',self.go('history'),'🧾'))
  for start in range(0,len(controls),5):self.row(controls[start:start+5])
  if spec.commands:
   async def commands(i):await self.move(i,'directory',query='@'+self.section)
   self.row([self.button('Funciones y comandos',commands,'🧰')])
  channel=self.system.destination(self.section,self.state)
  if channel:self.row([discord.ui.Button(label='Abrir canal',emoji='↗️',url=f'https://discord.com/channels/{self.system.guild_id}/{channel}')])

 def menu(self):
  select=discord.ui.Select(placeholder='Elige el sistema que quieres ajustar',options=[discord.SelectOption(label=s.title,value=s.key,emoji=s.emoji,description=s.description[:100],default=s.key==self.section) for s in SECTIONS])
  async def selected(i):await self.move(i,select.values[0])
  select.callback=selected;self.row([select])

 def nav(self):
  async def reload(i):await self.move(i,self.section,page=self.page,query=self.query,detail=self.details['op'] if self.details else None)
  self.row([self.button('Inicio',self.go('home'),'🏠'),self.button('Actualizar',reload,'🔄'),self.button('Historial',self.go('history'),'🧾')])

 async def move(self,i,section,**kwargs):
  await self.system.open(i,section,**kwargs)
  self.stop()

 def go(self,section):
  async def turn(i):await self.move(i,section)
  return turn

 def pages(self,count,size,section):
  buttons=[]
  if self.page>0:
   async def back(i):await self.move(i,section,page=self.page-1,query=self.query)
   buttons.append(self.button('Anterior',back,'◀️'))
  if (self.page+1)*size<count:
   async def next_page(i):await self.move(i,section,page=self.page+1,query=self.query)
   buttons.append(self.button('Siguiente',next_page,'▶️'))
  self.row(buttons)

 def directory(self):
  matches=self.system.functions(self.query)
  start=self.page*10;shown=matches[start:start+10]
  self.text('Pulsa el nombre de un comando para abrirlo en Discord. Conserva sus permisos y sus confirmaciones.\n'
   'Usa **Buscar** para encontrar una función por su nombre o por lo que hace.')
  lines=[f'**{row["mention"]}**\n{row["description"]}' for row in shown]
  self.text('\n\n'.join(lines) if lines else 'No encontré funciones con esa búsqueda. Prueba con otra palabra.')
  self.text(f'-# {len(matches)} funciones · Página {self.page+1}')
  async def search(i):await i.response.send_modal(SearchForm(self.system,self.owner))
  self.row([self.button('Buscar',search,'🔎')]);self.pages(len(matches),10,'directory')

 def catalog(self):
  rows=self.rows;start=self.page*20;shown=rows[start:start+20]
  self.text('Elige un producto para cambiar su precio o ponerlo disponible. **Las compras ya pagadas conservan su precio y su contenido.**')
  if not rows:self.text('El catálogo todavía no está preparado. Actualiza cuando la tienda termine de iniciar.');return
  select=discord.ui.Select(placeholder='Elige el producto',options=[discord.SelectOption(label=r['name'][:100],value=r['sku'],description=f'{r["price"]:,} monedas · '+('Disponible' if r['active'] else 'Pausado')) for r in shown])
  async def chosen(i):
   product=next(r for r in shown if r['sku']==select.values[0])
   await i.response.send_modal(SystemForm(self.system,self.owner,self.state,'product',product=product))
  select.callback=chosen;self.row([select])
  self.text(f'-# {len(rows)} productos · Página {self.page+1}');self.pages(len(rows),20,'catalog')

 def history(self):
  if not self.rows:self.text('Todavía no hay cambios guardados desde este panel.');return
  lines=[]
  for row in self.rows:
   title=self.system.change_title(row)
   status='Aplicado' if row.get('sync_state') in ('done',None) else 'Actualización pendiente'
   lines.append(f'**{title}**\n<t:{row["created"]}:f> · <@{row["actor"]}> · {status}')
  self.text('\n\n'.join(lines))
  select=discord.ui.Select(placeholder='Revisar un cambio',options=[discord.SelectOption(label=(self.system.change_title(r)+' · '+datetime.fromtimestamp(r['created'],ZoneInfo('America/Puerto_Rico')).strftime('%d/%m %H:%M'))[:100],value=r['op'],description='Revisar el antes y después de este cambio') for r in self.rows])
  async def detail(i):await self.move(i,'detail',detail=select.values[0])
  select.callback=detail;self.row([select])
  # Read one extra row to know whether another page exists.
  if self.page:
   async def prev(i):await self.move(i,'history',page=self.page-1)
   self.row([self.button('Anterior',prev,'◀️')])
  if len(self.rows)==8:
   async def next_page(i):await self.move(i,'history',page=self.page+1)
   self.row([self.button('Siguiente',next_page,'▶️')])

 def detail(self):
  row=self.details
  self.text('### '+self.system.change_title(row)+f'\nGuardado por <@{row["actor"]}> · <t:{row["created"]}:f>')
  old,new=self.system.change_values(row)
  self.text('**Antes**\n'+old[:1300]+'\n\n**Después**\n'+new[:1300])
  self.text('Restaurar abre otra vista previa. Solo recupera estos ajustes; conserva compras, monedas, mensajes y archivos.')
  async def restore(i):
   from settings_panel import ConfirmSettings
   await i.response.defer(ephemeral=True,thinking=True)
   await self.system.authorize(i,refresh=True)
   draft=await self.system.restore_draft(row['op'])
   await i.edit_original_response(embeds=self.system.review(draft),view=ConfirmSettings(self.system,self.owner,i,draft),allowed_mentions=NONE)
  self.row([self.button('Revisar restauración',restore,'↩️')])


class SearchForm(discord.ui.Modal,title='Buscar una función'):
 def __init__(self,system,owner):
  super().__init__(timeout=600);self.system,self.owner=system,owner
  self.term=discord.ui.TextInput(placeholder='Ejemplo: ticket, precio, entrevista, respaldo',max_length=100)
  self.add_item(discord.ui.Label(text='¿Qué quieres hacer?',component=self.term))
 async def on_submit(self,i):
  if i.user.id!=self.owner:return
  await i.response.defer(ephemeral=True,thinking=True)
  await self.system.authorize(i,refresh=True)
  await self.system.open(i,'directory',query=self.term.value)
 async def on_error(self,i,error):
  from settings_panel import private
  log.error('SETTINGS search_failed',exc_info=error)
  await private(i,'No pude completar la búsqueda. Vuelve a abrir /ajustes panel para intentarlo otra vez.')


class SystemForm(discord.ui.Modal):
 def __init__(self,system,owner,state,key,*,product=None):
  spec=BY_FORM[key] if key!='product' else Form('product','economy','Precio y disponibilidad',
   'Solo cambia compras nuevas. Las compras ya cobradas conservan su precio.',(Field('price','Precio en monedas',0),Field('active','Disponible en la tienda',True,'bool')))
  super().__init__(title=spec.title[:45],timeout=600)
  self.system,self.owner,self.state,self.spec,self.product=system,owner,state,spec,product
  self.controls={}
  values=state['systems'][key] if key!='product' else product
  for field in spec.fields:
   current=values[field.key]
   if field.kind=='bool':control=discord.ui.Select(options=[discord.SelectOption(label='Sí',value='1',default=bool(current)),discord.SelectOption(label='No',value='0',default=not current)])
   elif field.kind=='multi':control=discord.ui.Select(min_values=0,max_values=len(field.options),required=False,
    options=[discord.SelectOption(label=label,value=str(n),default=n in current) for n,label in field.options])
   elif field.kind=='channel':control=discord.ui.ChannelSelect(channel_types=[discord.ChannelType.text,discord.ChannelType.news],default_values=[discord.Object(id=current)],required=True)
   else:
    limit=min(field.high,4000) if field.kind in ('text','words') else 30
    control=discord.ui.TextInput(default=str(current),max_length=limit,required=field.kind!='words',
     style=discord.TextStyle.paragraph if field.kind in ('text','words') and field.high>300 else discord.TextStyle.short)
   self.controls[field.key]=control
   self.add_item(discord.ui.Label(text=field.label[:45],description=(field.help or spec.description)[:100],component=control))

 async def on_submit(self,i):
  from settings_panel import Draft,ConfirmSettings,ReloadView
  await i.response.defer(ephemeral=True,thinking=True)
  try:
   if i.user.id!=self.owner:raise ValueError('Este formulario pertenece a quien lo abrió.')
   await self.system.authorize(i,refresh=True)
   values={}
   for field in self.spec.fields:
    control=self.controls[field.key]
    if field.kind=='bool':
     if len(control.values)!=1:raise ValueError('Elige Sí o No en todos los campos.')
     values[field.key]=control.values[0]=='1'
    elif field.kind=='multi':values[field.key]=[int(v) for v in control.values]
    elif field.kind=='channel':
     if len(control.values)!=1:raise ValueError('Elige un canal de la lista.')
     values[field.key]=control.values[0].id
    else:values[field.key]=control.value
   current=await self.system.call('snapshot')
   if current['revision']!=self.state['revision']:raise ValueError('Los ajustes cambiaron. Actualiza el panel y revisa el formulario otra vez.')
   target=self.spec.key
   if target=='product':
    current['product']={k:self.product[k] for k in ('sku','name','price','active','revision')}
    draft=Draft('product',values,current,self.product['sku'])
    draft.values=self.system.validate_product(values)
   else:
    values=validate(target,values)
    if current['systems'][target]!=self.state['systems'][target]:raise ValueError('Estos ajustes cambiaron desde otro comando. Abre el formulario otra vez.')
    draft=Draft('system',values,current,target)
   await self.system.validate_runtime(i,draft)
   await i.edit_original_response(embeds=self.system.review(draft),view=ConfirmSettings(self.system,self.owner,i,draft),allowed_mentions=NONE)
  except ValueError as error:
   await i.edit_original_response(content=str(error),view=ReloadView(self.system,self.owner,i))

 async def on_error(self,i,error):
  from settings_panel import private
  log.error('SETTINGS system_form_failed',exc_info=error)
  await private(i,'No pude abrir la vista previa. Tus ajustes siguen como estaban; vuelve al panel para intentarlo otra vez.')
