"""Private administrator settings with previews, confirmation and fresh authorization."""
import asyncio
from dataclasses import dataclass,field
import logging
import json
import math
import time
import re
import uuid

import discord
from discord import app_commands

from bot_settings import SettingsStore,TEXT_KEYS,friendly_hour,validate_values
from daily_up import daily_up_embed
from settings_catalog import BY_FORM,BY_SECTION,SECTIONS
from settings_app import AppView as RootView,SystemForm,display,searchable

log=logging.getLogger('LaVenganzaRP.settings')


async def private(i,text,**kwargs):
    sender=i.followup.send if i.response.is_done() else i.response.send_message
    await sender(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)


def prizes(values):
    return ' · '.join(f'{medal} {n:,}' for medal,n in zip(('🥇','🥈','🥉'),values))+' monedas'


@dataclass
class Draft:
    kind:str
    values:object
    before:dict
    target:str|None=None
    token:str=field(default_factory=lambda:uuid.uuid4().hex)


class SettingsView(discord.ui.View):
    def __init__(self,system,owner,origin):
        super().__init__(timeout=600);self.system,self.owner,self.origin=system,owner,origin

    async def interaction_check(self,i):
        if i.user.id!=self.owner:
            await private(i,'Este panel pertenece a quien lo abrió. Usa /ajustes panel.');return False
        try:await self.system.authorize(i)
        except ValueError as error:await private(i,str(error));return False
        self.origin=i;return True

    async def on_timeout(self):
        try:await self.origin.edit_original_response(content='Este panel expiró. Abre /ajustes panel para continuar.',embed=None,view=None)
        except discord.HTTPException:pass

    async def on_error(self,i,error,item):
        if not isinstance(error,ValueError):log.error('SETTINGS interaction_failed',exc_info=error)
        await private(i,str(error) if isinstance(error,ValueError) else 'No pude completar ese cambio. Abre /ajustes panel y vuelve a intentarlo.')


class ReloadView(SettingsView):
    @discord.ui.button(label='Volver al panel',emoji='⚙️')
    async def reload(self,i,button):
        await self.system.open(i,'home')
        self.stop()


class RewardScope(ReloadView):
    def __init__(self,system,owner,origin,state):
        super().__init__(system,owner,origin);self.state=state

    @discord.ui.button(label='Esta semana',emoji='📅',style=discord.ButtonStyle.primary)
    async def current(self,i,button):
        await i.response.send_modal(SettingsForm(self.system,self.owner,self.state,'rewards',self.state['week']))

    @discord.ui.button(label='Próxima semana',emoji='🗓️',style=discord.ButtonStyle.primary)
    async def next_week(self,i,button):
        await i.response.send_modal(SettingsForm(self.system,self.owner,self.state,'rewards',self.state['next_week']))


class SettingsForm(discord.ui.Modal):
    def __init__(self,system,owner,state,kind,target=None):
        super().__init__(title={'rewards':'Premios de Fotos','schedule':'Hora del Server Up','text':'Mensaje del Server Up'}[kind],timeout=600)
        self.system,self.owner,self.state,self.kind,self.target=system,owner,state,kind,target
        self.fields=[]
        if kind=='rewards':
            rates=state['rewards'] if target==state['week'] else state['next_rewards']
            specs=[(label,str(value),20,None) for label,value in zip(('🥇 Primer lugar','🥈 Segundo lugar','🥉 Tercer lugar'),rates)]
        elif kind=='schedule':
            specs=[('Hora de Puerto Rico',state['values']['daily_server_up_time'],20,'Ejemplo: 18:30 o 6:30 p. m.')]
        else:
            specs=[(label,state['values'][key],limit,'Puedes usar {enlace}, {servidor} y {hora}.') for label,key,limit in
                zip(('Título','Mensaje (conserva {enlace})','Pie del mensaje'),TEXT_KEYS,(150,3000,150))]
        for label,value,limit,description in specs:
            text=discord.ui.TextInput(default=value,max_length=limit,style=discord.TextStyle.paragraph if limit>1000 else discord.TextStyle.short)
            self.fields.append(text);self.add_item(discord.ui.Label(text=label,description=description,component=text))

    async def on_submit(self,i):
        await i.response.defer(ephemeral=True,thinking=True)
        try:
            if i.user.id!=self.owner:raise ValueError('Este formulario pertenece a quien lo abrió.')
            await self.system.authorize(i,refresh=True)
            values=[f.value for f in self.fields]
            values=values if self.kind=='rewards' else values[0] if self.kind=='schedule' else dict(zip(TEXT_KEYS,values))
            values=validate_values(self.kind,values)
            current=await self.system.call('snapshot')
            if current['revision']!=self.state['revision']:
                raise ValueError('Los ajustes cambiaron mientras tenías el formulario abierto. Vuelve al panel para revisarlos.')
            draft=Draft(self.kind,values,current,self.target)
            await i.edit_original_response(embeds=self.system.review(draft),view=ConfirmSettings(self.system,self.owner,i,draft),
                allowed_mentions=discord.AllowedMentions.none())
        except ValueError as error:
            await i.edit_original_response(content=str(error),view=ReloadView(self.system,self.owner,i))

    async def on_error(self,i,error):
        log.error('SETTINGS form_failed',exc_info=error)
        await private(i,'No pude abrir la confirmación. Tus ajustes siguen como estaban; abre /ajustes panel otra vez.')


class ConfirmSettings(SettingsView):
    def __init__(self,system,owner,origin,draft):
        super().__init__(system,owner,origin);self.draft=draft;self.lock=asyncio.Lock();self.done=False

    @discord.ui.button(label='Guardar cambios',emoji='✅',style=discord.ButtonStyle.success)
    async def save(self,i,button):
        await i.response.defer()
        if i.user.id!=self.owner:return await private(i,'Este cambio pertenece a quien abrió el panel.')
        async with self.lock:
            if self.done:return await private(i,'Este cambio ya se guardó o se canceló.')
            await i.edit_original_response(view=None)
            try:
                await self.system.authorize(i,refresh=True)
                draft=self.draft
                await self.system.validate_runtime(i,draft)
                async def snapshot():
                    return dict(settings=await self.system.call('snapshot'),receipt=await self.system.call('receipt',draft.token))
                async def apply():
                    return await self.system.call('apply',draft.kind,draft.values,draft.before['revision'],i.user.id,draft.token,target=draft.target,
                        expected_fields=draft.before['systems'][draft.target] if draft.kind=='system' else draft.before.get('product') if draft.kind=='product' else None)
                state=await self.system.bot.changes.tracked('ADMIN_SETTINGS','Cambiar ajustes del bot desde Discord',apply,
                    request_id=draft.token,snapshot=snapshot)
                self.done=True;self.stop()
                await i.edit_original_response(content='✅ Ajustes guardados. Actualizando los paneles…',embeds=[],view=None,allowed_mentions=discord.AllowedMentions.none())
                synced=await self.system.flush(i.guild,draft)
                state=await self.system.call('snapshot')
                notice=f'✅ Guardado. Estos premios se usarán desde la semana del {draft.target}.' if draft.kind=='rewards' else '✅ Guardado. El cambio se usará en los próximos avisos.'
                if draft.kind in ('system','product'):notice='✅ Ajustes guardados.'
                if not synced:notice+=' La actualización del panel público sigue pendiente y se reintentará automáticamente.'
                section=BY_FORM[draft.target].section if draft.kind=='system' else 'economy' if draft.kind=='product' else 'photos' if draft.kind=='rewards' else 'server'
                await self.system.open(i,section,state=state,notice=notice)
                log.info('SETTINGS saved kind=%s actor=%s revision=%s target=%s',draft.kind,i.user.id,state['revision'],draft.target)
            except ValueError as error:
                self.done=True;self.stop()
                await i.edit_original_response(content=str(error),embeds=[],view=ReloadView(self.system,self.owner,i))
            except Exception:
                log.exception('SETTINGS save_failed')
                # A receipt distinguishes a committed change from a failed confirmation response.
                receipt=await self.system.call('receipt',self.draft.token)
                self.done=True;self.stop()
                await i.edit_original_response(content='El cambio quedó guardado. Abre el panel para comprobarlo.' if receipt else
                    'No se guardó el cambio. Abre el panel y vuelve a intentarlo.',embeds=[],view=ReloadView(self.system,self.owner,i))

    @discord.ui.button(label='Cancelar',style=discord.ButtonStyle.secondary)
    async def cancel(self,i,button):
        await i.response.defer()
        if i.user.id!=self.owner:return await private(i,'Este cambio pertenece a quien abrió el panel.')
        async with self.lock:
            if self.done:return await private(i,'Este cambio ya se guardó o se canceló.')
            self.done=True;self.stop()
            await i.edit_original_response(content='Cancelado. Los ajustes siguen como estaban.',embeds=[],view=ReloadView(self.system,self.owner,i))


class SettingsPanel:
    def __init__(self,bot,path,guild_id,connect_url):
        self.bot,self.guild_id,self.connect_url=bot,guild_id,connect_url
        self.store=SettingsStore(path)
        self.task=None;self.sync_lock=asyncio.Lock();self.command_book=[]
        self.group=app_commands.Group(name='ajustes',description='Panel privado de ajustes del bot',
            default_permissions=discord.Permissions(administrator=True))
        @self.group.command(name='panel',description='Abrir el centro de ajustes de todas las funciones del bot')
        async def panel(i:discord.Interaction):
            await i.response.defer(ephemeral=True,thinking=True)
            await self.authorize(i,refresh=True)
            await self.open(i,'home')
        @self.group.command(name='funciones',description='Buscar y abrir cualquier función del bot')
        async def functions(i:discord.Interaction,buscar:str=''):
            await i.response.defer(ephemeral=True,thinking=True)
            await self.authorize(i,refresh=True)
            await self.open(i,'directory',query=buscar)
        @self.group.command(name='historial',description='Revisar los ajustes guardados y preparar una restauración')
        async def history(i:discord.Interaction):
            await i.response.defer(ephemeral=True,thinking=True)
            await self.authorize(i,refresh=True)
            await self.open(i,'history')
        @self.group.error
        async def error(i,failure):
            original=getattr(failure,'original',failure)
            if not isinstance(original,ValueError):log.error('SETTINGS command_failed',exc_info=original)
            await private(i,str(original) if isinstance(original,ValueError) else 'No pude abrir los ajustes. Inténtalo otra vez.')

    async def call(self,method,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,method),*args,**kwargs)

    async def authorize(self,i,refresh=False):
        if i.guild_id!=self.guild_id or not i.guild:raise ValueError('Abre los ajustes desde La Venganza RP.')
        member=await i.guild.fetch_member(i.user.id) if refresh else i.user
        if not member.guild_permissions.administrator:raise ValueError('Este panel es solo para administradores del servidor.')

    def embed(self,state):
        embed=discord.Embed(title='⚙️ Ajustes de La Venganza RP',color=0xD60000,
            description='Elige lo que quieres cambiar. Verás una vista previa y tendrás que pulsar **Guardar cambios** para aplicarlo.')
        embed.add_field(name='📸 Premios de Fotos',value=f"**Esta semana ({state['week']}):** {prizes(state['rewards'])}\n"
            f"**Próxima semana ({state['next_week']}):** {prizes(state['next_rewards'])}",inline=False)
        embed.add_field(name='🕒 Server Up diario',value=f"**{friendly_hour(state['values']['daily_server_up_time'])} · Puerto Rico**\n"
            'Un aviso al día, cuando el servidor esté arriba y no esté en mantenimiento.',inline=False)
        embed.add_field(name='📝 Mensaje del Server Up',value=state['values']['daily_server_up_title'][:200]+
            '\nPuedes editar el título, el mensaje y su pie.',inline=False)
        embed.set_footer(text='Solo administradores · /ajustes panel · El cierre de Fotos sigue siendo al terminar el domingo.')
        return embed

    def review(self,draft):
        embed=discord.Embed(title='¿Guardamos este cambio?',color=0xD60000)
        if draft.kind in ('system','product'):
            if draft.kind=='system':
                spec=BY_FORM[draft.target];before=draft.before['systems'][draft.target]
                fields=spec.fields;embed.title='Revisar cambios · '+spec.title;embed.description=spec.description
            else:
                from settings_catalog import Field
                before=draft.before['product'];fields=(Field('price','Precio',0),Field('active','Disponible',True,'bool'))
                embed.title='Revisar producto · '+before['name'];embed.description='Las compras ya pagadas conservan su precio. El precio nuevo se usa en compras nuevas.'
            for field in fields:
                for label,value in (('Ahora',before[field.key]),('Nuevo',draft.values[field.key])):
                    text=display(field,value)
                    for start in range(0,len(text),1000):
                        embed.add_field(name=f'{field.label} · {label}'+(' (continúa)' if start else ''),value=text[start:start+1000],inline=False)
            return [embed]
        if draft.kind=='rewards':
            old=draft.before['rewards'] if draft.target==draft.before['week'] else draft.before['next_rewards']
            embed.description=f"**Desde la semana del {draft.target}.** Se usará hasta el próximo cambio programado. Los premios ya pagados se conservan."
            embed.add_field(name='Ahora',value=prizes(old),inline=False)
            embed.add_field(name='Nuevo',value=prizes(draft.values),inline=False)
            embed.add_field(name='Total si hay tres ganadores',value=f'{sum(draft.values):,} monedas por semana',inline=False)
        elif draft.kind=='schedule':
            embed.add_field(name='Ahora',value=friendly_hour(draft.before['values']['daily_server_up_time']),inline=False)
            embed.add_field(name='Nuevo',value=friendly_hour(draft.values)+' · Puerto Rico',inline=False)
            embed.description='Guardar no envía un Server Up ahora ni repite uno ya revisado hoy. Si la hora de hoy ya pasó, el próximo aviso será mañana.'
        else:
            embed.description='El mensaje nuevo está debajo. Guardar cambia los próximos Server Up; esta vista previa no menciona a nadie.'
            embed.add_field(name='Texto actual',value=draft.before['values']['daily_server_up_body'][:400],inline=False)
            values=dict(draft.before['values']);values.update(draft.values)
            return [embed,daily_up_embed(lambda key,default='':values.get(key,default),self.connect_url)]
        return [embed]

    async def refresh(self,guild,draft=None):
        target=draft.target if draft and draft.kind=='system' else None
        if target=='security':
            await self.bot.obscenity_filter.install()
            expected=draft.values['enabled']
            rid=self.bot.obscenity_filter.get_setting('obscenity_rule_id')
            if not rid:raise ValueError('El filtro todavía no tiene una regla verificada.')
            rule=await guild.fetch_automod_rule(int(rid))
            if rule.creator_id!=self.bot.user.id:raise ValueError('La regla encontrada no pertenece a este bot.')
            managed=json.loads(self.bot.obscenity_filter.get_setting('obscenity_managed_extras') or '[]')
            trigger,actions=self.bot.obscenity_filter.desired(rule,draft.values['words'].splitlines(),managed)
            if not self.bot.obscenity_filter.matches(rule,trigger,actions,expected):raise ValueError('Discord todavía no confirmó el filtro de palabras.')
        if target=='rules':
            self.bot.rules.source_id=draft.values['source_channel'];self.bot.rules.cache_seconds=draft.values['cache_minutes']*60
            self.bot.rules.invalid=True;self.bot.rules.generation+=1
            await self.bot.rules.refresh(force=True)
        if target=='games':await self.bot.minigames.ready(force=True,request='settings:'+draft.token)
        if target=='feedback':await self.bot.feedback.ready(force=True)
        affects_photos=draft is None or draft.kind=='rewards' or target=='photo_entries'
        affects_guide=draft is None or draft.kind in ('rewards','schedule') or target=='guide'
        affects_shop=draft is None or draft.kind in ('rewards','product') or target=='event_rewards'
        if affects_photos:
            self.bot.photos.store.config('panel_week','')
            await self.bot.photos.panel(await self.bot.photos.channel())
        if affects_guide:
            self.bot.economy.community.guide_published=False
            await self.bot.economy.community.ensure_guide(guild)
        if affects_shop:
            self.bot.economy.signature=None
            await self.bot.economy.panel(guild)

    async def ready(self):
        commands=await self.bot.tree.fetch_commands(guild=discord.Object(self.guild_id))
        self.index_commands(commands)
        registered=next((c for c in commands if c.name=='ajustes'),None)
        command=registered.to_dict() if registered else {}
        if not any(o.get('name')=='panel' for o in command.get('options',[])):
            raise RuntimeError('Discord no confirmó /ajustes panel.')
        permissions=registered.default_member_permissions
        if permissions is None or not permissions.administrator:
            raise RuntimeError('Discord no confirmó el acceso de administradores para /ajustes.')
        state=await self.call('snapshot')
        for kind,target in (('schedule',None),('text',None),('rewards',state['week'])):
            form=SettingsForm(self,0,state,kind,target).to_dict()
            if any(c.get('type')!=18 or c.get('component',{}).get('type')!=4 for c in form['components']):
                raise RuntimeError('No se confirmó el formulario de ajustes.')
        for key,spec in BY_FORM.items():
            form=SystemForm(self,0,state,key).to_dict()
            components=form['components']
            if len(components)!=len(spec.fields) or any(c['type']!=18 or c['component']['type'] not in (3,4,8) for c in components):
                raise RuntimeError('No se confirmó un formulario del centro de ajustes.')
        for section in ('home',*BY_SECTION):
            view=RootView(self,0,None,state,section)
            if len(list(view.walk_children()))>40:raise RuntimeError('Una página supera el tamaño permitido de Discord.')
            view.to_components();view.stop()
        log.info('SETTINGS app_verified sections=%s forms=%s functions=%s native_layout=True private=True owner_bound=True confirmation=True persistent_values=True catalog_prices=True history=True restore_preview=True queued_sync=True protected_roles_unchanged=True',len(SECTIONS),len(BY_FORM)+4,len(self.command_book))
        log.info('SETTINGS ready command="/ajustes panel" administrator_only=True private=True confirmation=True revision=%s '
            'current_rewards=%s next_rewards=%s daily_time=%s timezone=America/Puerto_Rico values_preserved=True forms_verified=True',
            state['revision'],state['rewards'],state['next_rewards'],state['values']['daily_server_up_time'])

    prize_text=staticmethod(prizes)

    async def start(self):
        await self.call('initialize')
        if self.task is None or self.task.done():self.task=asyncio.create_task(self.loop(),name='admin-settings-sync')

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                guild=self.bot.get_guild(self.guild_id)
                if guild:
                    for row in await self.call('pending'):
                        draft=Draft(row['kind'],json.loads(row['values_json']),json.loads(row['before_json']),row['target'],row['op'])
                        await self.flush(guild,draft)
            except Exception:log.exception('SETTINGS sync_pending')
            await asyncio.sleep(30)

    async def flush(self,guild,draft):
        async with self.sync_lock:
            try:
                if await self.call('job_status',draft.token)=='done':return True
                effective=draft
                if draft.kind=='system':
                    current=await self.call('snapshot')
                    effective=Draft('system',current['systems'][draft.target],current,draft.target,draft.token)
                await self.refresh(guild,effective)
                await self.call('synced',draft.token)
                return True
            except Exception as error:
                await self.call('synced',draft.token,type(error).__name__)
                log.warning('SETTINGS public_sync_pending kind=%s target=%s error=%s',draft.kind,draft.target,type(error).__name__)
                return False

    async def open(self,i,section='home',*,page=0,query='',detail=None,state=None,notice=None):
        await self.authorize(i)
        if not i.response.is_done():await i.response.defer(ephemeral=True)
        if section=='directory' and not self.command_book and hasattr(self.bot,'tree'):
            self.index_commands(await self.bot.tree.fetch_commands(guild=discord.Object(self.guild_id)))
        state=state or await self.call('snapshot')
        rows=[];details=None
        if section=='catalog':rows=await self.call('catalog');page=min(max(0,page),max(0,(len(rows)-1)//20))
        elif section=='history':rows=await self.call('history',offset=max(0,page)*8)
        elif section=='detail':
            details=await self.call('receipt',detail)
            if not details:raise ValueError('No encuentro ese cambio en el historial.')
        elif section not in ('home','directory') and section not in BY_SECTION:raise ValueError('Ese sistema no está en el panel.')
        if section=='directory':page=min(max(0,page),max(0,(len(self.functions(query))-1)//10))
        view=RootView(self,i.user.id,i,state,section,page=page,query=query,rows=rows,details=details,notice=notice)
        await i.edit_original_response(content=None,embeds=[],view=view,allowed_mentions=discord.AllowedMentions.none())

    def destination(self,section,state):
        if section=='rules':return state['systems']['rules']['source_channel']
        if section=='economy':
            store=getattr(getattr(self.bot,'economy',None),'store',None)
            return int(store.config('shop_channel') or 0) if store is not None else None
        return BY_SECTION[section].channel if section in BY_SECTION else None

    def status_text(self):
        lines=['### Estado de los sistemas']
        for attr,label in (('economy','Tienda'),('tickets','Tickets'),('photos','Fotos'),('bugs','Reportes'),('feedback','Feedback'),
            ('suggestions','Sugerencias'),('rules','Normas'),('recruitment','Staff'),('meetings','Reuniones'),('event_features','Eventos'),('backups','Respaldos')):
            module=getattr(self.bot,attr,None)
            if module is None:continue
            task=getattr(module,'task',None)
            text='🟢 Activo' if task and not task.done() else '⚪ Sin tarea activa'
            lines.append(f'**{label}:** {text}')
        latency=getattr(self.bot,'latency',None)
        if isinstance(latency,(int,float)) and math.isfinite(latency):lines.append(f'**Respuesta de Discord:** {latency*1000:.0f} ms')
        lines.append('Los fallos de una actualización pública se reintentan y quedan visibles en el historial.')
        return '\n'.join(lines)

    def backup_text(self):
        backup=getattr(self.bot,'backups',None)
        if backup is None:return 'La conexión de respaldos todavía no está preparada.'
        if not backup.enabled or backup.config_error:return '⚠️ Los respaldos automáticos necesitan una conexión válida en Railway. Aquí no se solicitan claves ni contraseñas.'
        return '✅ Conexión de respaldos preparada. Los comandos **crear** y **probar** están en Funciones y comandos.'

    def index_commands(self,commands):
        book=[]
        for root in commands:
            data=root.to_dict();rid=getattr(root,'id',None)
            def walk(node,names):
                subs=[o for o in node.get('options',[]) if o.get('type') in (1,2)]
                if subs:
                    for child in subs:walk(child,[*names,child['name']])
                else:
                    name=' '.join(names)
                    book.append(dict(name=name,root=names[0],description=node.get('description','')[:180],
                        mention=f'</{name}:{rid}>' if rid else f'`/{name}`'))
            walk(data,[data['name']])
        self.command_book=sorted(book,key=lambda r:r['name'])

    def functions(self,query=''):
        book=self.command_book or [dict(name='ajustes panel',root='ajustes',description='Centro de ajustes del bot',mention='`/ajustes panel`')]
        if query.startswith('@') and query[1:] in BY_SECTION:
            roots=BY_SECTION[query[1:]].commands
            return [r for r in book if r['root'] in roots]
        term=searchable(query.strip())
        return [r for r in book if term in searchable(r['name']+' '+r['description'])]

    @staticmethod
    def validate_product(values):
        if set(values)!={'price','active'} or type(values['active']) is not bool:raise ValueError('Revisa el precio y la disponibilidad.')
        price=str(values['price']).strip()
        if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',price):price=price.replace(',','').replace('.','')
        if not price.isdecimal() or not 0<=int(price)<=1000000:raise ValueError('El precio debe estar entre 0 y 1,000,000 monedas.')
        return dict(price=int(price),active=values['active'])

    async def validate_runtime(self,i,draft):
        if draft.kind!='system':return
        if draft.target=='rules':
            channel=await self.bot.fetch_channel(draft.values['source_channel'])
            if not isinstance(channel,discord.TextChannel) or channel.guild.id!=self.guild_id:
                raise ValueError('Elige un canal de texto de La Venganza RP.')
            rights=channel.permissions_for(channel.guild.me)
            if not rights.view_channel or not rights.read_message_history:raise ValueError('El bot necesita poder leer ese canal y su historial.')
        if draft.target=='backups' and draft.values['automatic']:
            backup=getattr(self.bot,'backups',None)
            if backup is None or not backup.enabled or backup.config_error:
                raise ValueError('El respaldo automático todavía no está conectado en Railway. Primero hay que preparar esa conexión; tus demás ajustes se conservan.')

    @staticmethod
    def change_title(row):
        if row['kind']=='system':return BY_FORM[row['target']].title if row['target'] in BY_FORM else row['target']
        if row['kind']=='product':return 'Producto · '+json.loads(row['after_json']).get('product',{}).get('name',row['target'])
        return {'schedule':'Hora del Server Up','text':'Mensaje del Server Up','rewards':'Premios de Fotos'}.get(row['kind'],row['kind'])

    def change_values(self,row):
        before=json.loads(row['before_json']);after=json.loads(row['after_json']);kind=row['kind'];target=row['target']
        if kind=='system':
            fields=BY_FORM[target].fields
            def describe(state):return '\n'.join(f'**{f.label}:** {display(f,state["systems"][target][f.key])}' for f in fields)
            return describe(before),describe(after)
        if kind=='product':
            def describe(state):
                p=state['product'];return f'{p["name"]}\n{p["price"]:,} monedas · '+('Disponible' if p['active'] else 'Pausado')
            return describe(before),describe(after)
        if kind=='schedule':return before['values']['daily_server_up_time'],after['values']['daily_server_up_time']
        if kind=='text':return '\n'.join(before['values'][k] for k in TEXT_KEYS),'\n'.join(after['values'][k] for k in TEXT_KEYS)
        return self.prize_text(before['rewards'] if target==before['week'] else before['next_rewards']),self.prize_text(after['rewards'] if target==after['week'] else after['next_rewards'])

    async def restore_draft(self,op):
        row=await self.call('receipt',op)
        if not row:raise ValueError('No encuentro ese cambio.')
        before=json.loads(row['before_json']);current=await self.call('snapshot');kind=row['kind'];target=row['target']
        if kind=='system':values=before['systems'][target]
        elif kind=='product':
            product=next((p for p in await self.call('catalog') if p['sku']==target),None)
            if not product:raise ValueError('Ese producto ya no está en el catálogo.')
            current['product']={k:product[k] for k in ('sku','name','price','active','revision')}
            values=dict(price=before['product']['price'],active=bool(before['product']['active']))
        elif kind=='schedule':values=before['values']['daily_server_up_time']
        elif kind=='text':values={k:before['values'][k] for k in TEXT_KEYS}
        elif kind=='rewards':values=before['rewards'] if target==before['week'] else before['next_rewards']
        else:raise ValueError('Ese tipo de ajuste no se puede restaurar desde este panel.')
        return Draft(kind,values,current,target)
