"""Private administrator settings with previews, confirmation and fresh authorization."""
import asyncio
from dataclasses import dataclass,field
import logging
import uuid

import discord
from discord import app_commands

from bot_settings import SettingsStore,TEXT_KEYS,friendly_hour,validate_values
from daily_up import daily_up_embed

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
        await i.response.defer()
        state=await self.system.call('snapshot')
        await i.edit_original_response(content=None,embeds=[self.system.embed(state)],view=RootView(self.system,self.owner,i,state))
        self.stop()


class RootView(SettingsView):
    def __init__(self,system,owner,origin,state):
        super().__init__(system,owner,origin);self.state=state

    @discord.ui.button(label='Premios de Fotos',emoji='📸')
    async def photos(self,i,button):
        await i.response.edit_message(embed=discord.Embed(title='📸 ¿Desde cuándo cambiamos los premios?',color=0xD60000,
            description=f"**Esta semana ({self.state['week']}):** {prizes(self.state['rewards'])}\n\n"
                f"**Próxima semana ({self.state['next_week']}):** {prizes(self.state['next_rewards'])}\n\n"
                'Elige una. Los premios ya pagados se conservan.'),view=RewardScope(self.system,self.owner,i,self.state))
        self.stop()

    @discord.ui.button(label='Hora del Server Up',emoji='🕒')
    async def schedule(self,i,button):await i.response.send_modal(SettingsForm(self.system,self.owner,self.state,'schedule'))

    @discord.ui.button(label='Texto del Server Up',emoji='📝')
    async def text(self,i,button):await i.response.send_modal(SettingsForm(self.system,self.owner,self.state,'text'))


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
                async def snapshot():
                    return dict(settings=await self.system.call('snapshot'),receipt=await self.system.call('receipt',draft.token))
                async def apply():
                    return await self.system.call('apply',draft.kind,draft.values,draft.before['revision'],i.user.id,draft.token,target=draft.target)
                state=await self.system.bot.changes.tracked('ADMIN_SETTINGS','Cambiar ajustes del bot desde Discord',apply,
                    request_id=draft.token,snapshot=snapshot)
                self.done=True;self.stop()
                await self.system.refresh(i.guild)
                notice=f'✅ Guardado. Estos premios se usarán desde la semana del {draft.target}.' if draft.kind=='rewards' else '✅ Guardado. El cambio se usará en los próximos avisos.'
                await i.edit_original_response(content=notice,
                    embeds=[self.system.embed(state)],view=ReloadView(self.system,self.owner,i),allowed_mentions=discord.AllowedMentions.none())
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
        self.group=app_commands.Group(name='ajustes',description='Panel privado de ajustes del bot',
            default_permissions=discord.Permissions(administrator=True))
        @self.group.command(name='panel',description='Cambiar premios de Fotos, horario y textos del Server Up')
        async def panel(i:discord.Interaction):
            await i.response.defer(ephemeral=True,thinking=True)
            await self.authorize(i,refresh=True)
            state=await self.call('snapshot')
            await i.edit_original_response(embed=self.embed(state),view=RootView(self,i.user.id,i,state),allowed_mentions=discord.AllowedMentions.none())
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

    async def refresh(self,guild):
        self.bot.photos.store.config('panel_week','')
        self.bot.economy.signature=None;self.bot.economy.community.guide_published=False
        try:await self.bot.photos.panel(await self.bot.photos.channel())
        except Exception:log.exception('SETTINGS public_photo_panel_pending')
        for job in (self.bot.economy.panel,self.bot.economy.community.ensure_guide):
            try:await job(guild)
            except Exception:log.exception('SETTINGS public_panel_pending')

    async def ready(self):
        commands=await self.bot.tree.fetch_commands(guild=discord.Object(self.guild_id))
        command=next((c.to_dict() for c in commands if c.name=='ajustes'),{})
        if not any(o.get('name')=='panel' for o in command.get('options',[])):
            raise RuntimeError('Discord no confirmó /ajustes panel.')
        if not int(command.get('default_member_permissions') or 0)&discord.Permissions(administrator=True).value:
            raise RuntimeError('Discord no confirmó el acceso de administradores para /ajustes.')
        state=await self.call('snapshot')
        for kind,target in (('schedule',None),('text',None),('rewards',state['week'])):
            form=SettingsForm(self,0,state,kind,target).to_dict()
            if any(c.get('type')!=18 or c.get('component',{}).get('type')!=4 for c in form['components']):
                raise RuntimeError('No se confirmó el formulario de ajustes.')
        log.info('SETTINGS ready command=/ajustes_panel administrator_only=True private=True confirmation=True revision=%s '
            'current_rewards=%s next_rewards=%s daily_time=%s timezone=America/Puerto_Rico values_preserved=True forms_verified=True',
            state['revision'],state['rewards'],state['next_rewards'],state['values']['daily_server_up_time'])
