"""Guild-backed, paginated mention picker; no gateway intent changes."""
import asyncio
import time
import unicodedata

import discord
from discord.http import Route

PAGE_SIZE=25
APPLICATION_ID=1567658433497399408
GUILD_ID=1244988345327550565


def name_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value or '').casefold() if c.isalnum())


def matches(member,query):
    key=name_key(query)
    return not key or any(key in name_key(value) for value in
        (member.name,member.display_name,getattr(member,'global_name',None),str(member.id)))


class DirectoryUnavailable(Exception):
    def __init__(self,reason='temporary',status=None):
        super().__init__('No pudimos cargar la lista completa de personas ahora.')
        self.reason,self.status=reason,status


class MemberDirectory:
    def __init__(self,bot,guild_id):
        self.bot,self.guild_id=bot,guild_id
        self.lock=asyncio.Lock()
        self.members=[];self.loaded_at=0;self.source='';self.last_error=None

    async def enable_member_listing(self):
        """Enable only our app's documented limited member flag, with a durable snapshot."""
        if self.guild_id!=GUILD_ID or self.bot.user.id!=APPLICATION_ID:
            raise ValueError('Esta configuración pertenece al bot de La Venganza RP.')

        async def application():
            app=await self.bot.application_info()
            if app.id!=APPLICATION_ID:
                raise ValueError('La aplicación no corresponde a este bot.')
            return app

        app=await application()
        if app.flags.gateway_guild_members or app.flags.gateway_guild_members_limited:
            return False
        if app.approximate_guild_count>=100 or len(self.bot.guilds)>=100:
            return False

        async def snapshot():
            current=await application()
            return dict(application_id=str(current.id),flags=current.flags.value,
                gateway_member_subscription=self.bot.intents.members)

        async def enable():
            current=await application()
            if current.approximate_guild_count>=100:
                raise ValueError('Esta aplicación necesita habilitar miembros desde su portal.')
            flags=current.flags
            flags.gateway_guild_members_limited=True
            await current.edit(flags=flags,reason='Permitir la lista de menciones en Fotos')
            verified=await application()
            if not verified.flags.gateway_guild_members_limited:
                raise RuntimeError('Discord no confirmó el acceso a la lista de miembros.')

        await self.bot.changes.tracked('PHOTO_MEMBER_ACCESS','Habilitar lectura de miembros para menciones de Fotos',enable,
            request_id=f'{APPLICATION_ID}:members-v1',snapshot=snapshot)
        return True

    async def load(self,guild,force=False):
        if guild.id!=self.guild_id:
            raise ValueError('Esta lista pertenece a La Venganza RP.')
        async with self.lock:
            if not force and self.loaded_at and time.monotonic()-self.loaded_at<300:
                return list(self.members)
            http=self.bot.http
            try:
                raw=[];cursor=None;denied=False
                try:
                    while True:
                        page=await http.get_members(guild.id,1000,cursor)
                        raw.extend(page)
                        if len(page)<1000:break
                        next_cursor=int(page[-1]['user']['id'])
                        if cursor is not None and next_cursor<=cursor:raise DirectoryUnavailable()
                        cursor=next_cursor
                    source='member_list'
                except discord.Forbidden:
                    denied=True
                    # The documented search endpoint does not require the gateway member cache.
                    raw=await http.request(Route('GET','/guilds/{guild_id}/members/search',guild_id=guild.id),
                        params={'query':'','limit':1000})
                    if len(raw)>=1000:
                        raise DirectoryUnavailable('permission',403)
                    source='member_search'
                if not raw:
                    raise DirectoryUnavailable('permission',403)
                members={int(data['user']['id']):discord.Member(data=data,guild=guild,state=self.bot._connection) for data in raw}
                if source=='member_search' and len(members)<(getattr(guild,'member_count',None) or 0):
                    raise DirectoryUnavailable('permission',403)
                self.members=sorted(members.values(),key=lambda m:(name_key(m.display_name),name_key(m.name),m.id))
                self.loaded_at=time.monotonic();self.source=source;self.last_error=None
                return list(self.members)
            except discord.HTTPException as error:
                failure=DirectoryUnavailable('permission' if error.status==403 or (denied and error.status==400) else 'temporary',error.status)
                self.last_error=failure
                raise failure from None
            except DirectoryUnavailable as error:
                self.last_error=error
                raise


async def private(i,text,**kwargs):
    send=i.followup.send if i.response.is_done() else i.response.send_message
    return await send(text,ephemeral=True,allowed_mentions=discord.AllowedMentions.none(),**kwargs)


class MentionSearch(discord.ui.Modal):
    def __init__(self,picker):
        super().__init__(title='Buscar personas',timeout=600)
        self.picker=picker
        self.query=discord.ui.TextInput(label='Nombre, usuario o apodo',placeholder='Puedes escribirlo con letras normales.',required=False,max_length=100,default=picker.query or None)
        self.add_item(discord.ui.Label(text='¿A quién buscas?',description='Déjalo vacío para volver a ver la lista completa.',component=self.query))

    async def on_submit(self,i):
        if not await self.picker.interaction_check(i):return
        self.picker.query=self.query.value.strip();self.picker.page=0;self.picker.build()
        await i.response.edit_message(content=self.picker.content(),view=self.picker,allowed_mentions=discord.AllowedMentions.none())


class MemberPicker(discord.ui.View):
    def __init__(self,system,owner,members):
        super().__init__(timeout=600)
        self.system,self.owner=system,owner
        self.members={m.id:m for m in members}
        self.selected=set();self.query='';self.page=0
        self.build()

    def filtered(self):
        return [m for m in self.members.values() if matches(m,self.query)]

    def content(self):
        rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
        selected=', '.join(self.members[uid].display_name for uid in sorted(self.selected)) or 'Nadie todavía'
        return ('**¿Quieres mencionar a alguien?**\nElige hasta 5 personas o continúa sin elegir. '
            'Usa **Buscar** para escribir su usuario o apodo, también si tiene letras especiales.\n\n'
            f'**Elegidos:** {discord.utils.escape_markdown(selected)[:700]}\n'
            f'Página {self.page+1}/{pages} · {len(rows)} personas'+
            (f' · Búsqueda: {discord.utils.escape_markdown(self.query)}' if self.query else '')+
            '\nCuando termines, pulsa **Elegir foto**.')

    async def interaction_check(self,i):
        if i.user.id==self.owner and i.guild_id==self.system.guild_id and i.channel_id==self.system.photo_channel_id:
            return True
        await private(i,'Esta selección pertenece a quien pulsó Subir foto.')
        return False

    def build(self):
        self.clear_items()
        rows=self.filtered();pages=max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
        self.page=min(self.page,pages-1)
        page=rows[self.page*PAGE_SIZE:(self.page+1)*PAGE_SIZE]
        if page:
            select=discord.ui.Select(placeholder='Elige personas (opcional)',min_values=0,max_values=min(5,len(page)),row=0,
                options=[discord.SelectOption(label=m.display_name[:100],value=str(m.id),description=('@'+m.name)[:100],default=m.id in self.selected) for m in page])
            async def choose(i):
                page_ids={m.id for m in page};values={int(v) for v in select.values}
                updated=(self.selected-page_ids)|values
                warning=''
                if not values<=page_ids or len(updated)>5:warning='**Puedes elegir hasta 5 personas en total.**\n\n'
                else:self.selected=updated
                self.build()
                await i.response.edit_message(content=warning+self.content(),view=self,allowed_mentions=discord.AllowedMentions.none())
            select.callback=choose;self.add_item(select)
        for label,delta,disabled in [('Anterior',-1,self.page==0),('Siguiente',1,self.page>=pages-1)]:
            button=discord.ui.Button(label=label,style=discord.ButtonStyle.secondary,disabled=disabled,row=1)
            async def turn(i,delta=delta):
                self.page+=delta;self.build()
                await i.response.edit_message(content=self.content(),view=self,allowed_mentions=discord.AllowedMentions.none())
            button.callback=turn;self.add_item(button)
        search=discord.ui.Button(label='Buscar',emoji='🔎',row=1)
        async def search_callback(i):await i.response.send_modal(MentionSearch(self))
        search.callback=search_callback;self.add_item(search)
        upload=discord.ui.Button(label='Elegir foto',emoji='📸',style=discord.ButtonStyle.primary,row=2)
        async def continue_callback(i):
            await self.system.show_upload_form(i,[self.members[uid] for uid in sorted(self.selected)])
        upload.callback=continue_callback;self.add_item(upload)

    async def on_error(self,i,error,item):
        await private(i,str(error) if isinstance(error,ValueError) else 'No pudimos completar la selección. Inténtalo otra vez.')


class NativePickerFallback(discord.ui.View):
    def __init__(self,system,owner):
        super().__init__(timeout=600);self.system,self.owner=system,owner
    async def interaction_check(self,i):
        if i.user.id==self.owner:return True
        await private(i,'Este botón pertenece a quien abrió la subida.');return False
    @discord.ui.button(label='Continuar con la subida',emoji='📸',style=discord.ButtonStyle.primary)
    async def continue_upload(self,i,button):
        await self.system.show_upload_form(i,None)
