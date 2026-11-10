"""Bug report workflow in the existing Reportes forum; roles are read-only."""
import asyncio
import io
import json
import logging
import re
import discord
from discord import app_commands
from bug_store import BugStore,STATES
from bug_ui import BugAction,BugForm,StatePicker,buttons,failed
from feedback_ui import reply,RED,NONE
from tickets_store import PROTECTED

FORUM=1556488595131466000
GUIDE=1564719087798460466
TAGS={'pendiente':1564715642911981718,'revision':1564715732309250078,'proceso':1564715806330192012,
      'solucionado':1564715869026648237,'cerrado':1564715973465079951,'info':1564718816959660062}
PORTAL='🐛 REPORTAR UN ERROR | LA VENGANZA RP'
log=logging.getLogger('LaVenganzaRP.bugs')

class BugSystem:
    def __init__(self,bot,path,guild_id):
        self.bot,self.guild_id=bot,guild_id;self.store=BugStore(path)
        self.lock=asyncio.Lock();self.install_lock=asyncio.Lock();self.task=None
        self.group=app_commands.Group(name='errores',description='Reportar errores y seguir su solución')
        self.register()
    async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
    async def start(self):
        await self.call('initialize');self.bot.add_dynamic_items(BugAction)
        self.task=asyncio.create_task(self.loop(),name='bug-reports')
    async def member(self,i,admin=False):
        if i.guild_id not in (None,self.guild_id):raise ValueError('Usa los reportes en La Venganza RP.')
        guild=self.bot.get_guild(self.guild_id)
        if not guild:raise ValueError('El bot se está conectando. Inténtalo en un momento.')
        member=await guild.fetch_member(i.user.id)
        if member.bot:raise ValueError('Los reportes son para jugadores.')
        forum=await self.forum()
        if not forum.permissions_for(member).view_channel:raise ValueError('No tienes acceso al foro Reportes.')
        if admin and not (member.guild_permissions.administrator or {r.id for r in member.roles}&PROTECTED):
            raise ValueError('Solo Owner, Programador y administradores pueden gestionar estos reportes.')
        return member
    async def forum(self):
        forum=await self.bot.fetch_channel(FORUM)
        if not isinstance(forum,discord.ForumChannel) or forum.guild.id!=self.guild_id:raise ValueError('No encuentro el foro Reportes esperado.')
        if not set(TAGS.values())<={t.id for t in forum.available_tags}:raise ValueError('Las etiquetas del foro cambiaron. Hay que revisarlas antes de seguir.')
        return forum
    async def threads(self,forum):
        active=[t for t in await forum.guild.active_threads() if t.parent_id==FORUM]
        archived=[t async for t in forum.archived_threads(limit=None)]
        return {t.id:t for t in [*active,*archived]}
    def embed(self,row):
        data=json.loads(row['data']);embed=discord.Embed(title=f"🐛 Reporte #{row['id']} · {data.get('title','Error')}"[:256],color=RED)
        embed.description=f"Publicado por <@{row['owner']}>\n**Estado:** {STATES.get(row['status'],row['status'])}\n**Responsable:** "+(f"<@{row['assignee']}>" if row['assignee'] else 'Pendiente de atención')
        for label,key in [('ID en el servidor','player_id'),('¿Qué pasa?','description'),('¿Cómo ocurrió?','steps'),('Sistema afectado','system'),('Frecuencia','frequency')]:
            embed.add_field(name=label,value=discord.utils.escape_markdown(data.get(key,'Pendiente'))[:1024],inline=False)
        embed.add_field(name='🎥 Clip',value=data.get('clip') or ('Video adjunto al reporte' if row.get('video') else 'Falta adjuntar el clip'),inline=False)
        embed.set_footer(text=f"lvbug:{row['id']} · La Venganza RP")
        return embed
    async def tracked(self,rid,title,request,operation):
        async def snapshot():
            row=await self.call('get',rid) if rid else None
            if row:row={k:v for k,v in row.items() if k!='video'}
            return dict(forum=FORUM,report=row,portal=await self.call('config','portal'))
        return await self.bot.changes.tracked('BUG_REPORTS',title,operation,request_id=request,snapshot=snapshot)
    async def ready(self):
        async with self.install_lock:
            forum=await self.forum();saved=await self.call('config','portal')
            pin_limited=await self.call('config','pin_limited')=='1'
            thread=None
            if saved:
                try:thread=await self.bot.fetch_channel(int(saved))
                except discord.NotFound:pass
            if not thread:
                thread=next((t for t in (await self.threads(forum)).values() if t.owner_id==self.bot.user.id and t.name==PORTAL),None)
            async def install():
                nonlocal thread
                if thread is None:
                    embed=discord.Embed(title='🐛 ¿Encontraste un error?',color=RED,description='Repórtalo aquí, bro.\n\n**1.** Completa los datos del problema.\n**2.** Adjunta el video directamente o pega el enlace del clip.\n**3.** Revisa y publica tu reporte.\n\nEl bot guarda tu borrador y crea una publicación con la etiqueta 🔴 Pendiente. Owner, Programador y administradores actualizarán su estado.\n\nNo compartas contraseñas ni datos personales. Un reporte por error; continúa en el mismo si ya lo enviaste.')
                    result=await forum.create_thread(name=PORTAL,embed=embed,applied_tags=[forum.get_tag(TAGS['info'])],view=buttons('new','mine'),allowed_mentions=NONE,reason='Activar reportes con el bot')
                    thread=result.thread
                if thread.parent_id!=FORUM or thread.owner_id!=self.bot.user.id:raise ValueError('El panel guardado no pertenece a este bot en Reportes.')
                await self.call('config','portal',thread.id)
                if not thread.flags.pinned:
                    try:await thread.edit(pinned=True,reason='Panel de reportes solicitado por el dueño')
                    except discord.HTTPException as exc:
                        if exc.code!=30047:raise
                        await self.guide_buttons()
                        await self.call('config','pin_limited','1')
                        log.info('BUGS existing_guide_pin_preserved guide=%s controls_added=True',GUIDE)
            if not thread or (not thread.flags.pinned and not pin_limited):
                await self.tracked(None,'Instalar panel de reportes de errores','portal-v1',install)
            verified=await self.bot.fetch_channel(thread.id)
            if not saved:await self.call('config','portal',thread.id)
            starter=await verified.fetch_message(verified.id)
            ids=[c.custom_id for r in starter.components for c in r.children if hasattr(c,'custom_id')]
            if ids!=['lvbug:new:0','lvbug:mine:0']:raise RuntimeError('No se confirmaron los botones de reportes.')
            log.info('BUGS ready forum=%s portal=%s original_template_preserved=True clip_upload=True admin_controls=True controls=%s',FORUM,thread.id,ids)
    async def guide_buttons(self):
        guide=await self.bot.fetch_channel(GUIDE)
        if guide.parent_id!=FORUM:raise ValueError('La plantilla original ya no está en Reportes.')
        async for message in guide.history(limit=100):
            ids=[getattr(c,'custom_id',None) for row in message.components for c in row.children]
            if message.author.id==self.bot.user.id and ids==['lvbug:new:0','lvbug:mine:0']:
                await self.call('config','guide_buttons',message.id);return
        message=await guide.send('🐛 **Ahora puedes enviar el reporte con el bot, bro.**\nPulsa **Reportar un error**, completa el formulario y adjunta el video o pega su enlace. El bot guardará tu borrador y lo publicará con su estado.',view=buttons('new','mine'),allowed_mentions=NONE)
        await self.call('config','guide_buttons',message.id)
    async def form(self,i,rid=0):
        await self.member(i)
        rid=rid or await self.call('begin',i.user.id);row=await self.call('get',rid)
        if not row or row['owner']!=i.user.id or row['status']!='borrador':raise ValueError('Ese borrador ya fue publicado o no es tuyo.')
        await i.response.send_modal(BugForm(self,row))
    async def action(self,i,action,rid):
        if action in ('new','continue'):return await self.form(i,rid)
        await i.response.defer(ephemeral=True,thinking=True)
        await self.member(i,admin=action in ('claim','state'))
        if action=='mine':
            rows=await self.call('rows',owner=i.user.id)
            text='\n'.join(f"**#{r['id']}** · {STATES.get(r['status'],r['status'])}"+(f" · <#{r['thread']}>" if r['thread'] else ' · Borrador guardado') for r in rows)
            return await reply(i,text or 'Todavía no has enviado un reporte.',view=buttons('new'))
        row=await self.call('get',rid)
        if not row:raise ValueError('Ese reporte no existe.')
        if action=='publish':
            if row['owner']!=i.user.id:raise ValueError('Ese reporte no es tuyo.')
            async with self.lock:
                row=await self.call('get',rid)
                if not row['thread']:
                    await self.call('reserve',rid,i.user.id)
                    await self.create(rid)
            row=await self.call('get',rid)
            return await reply(i,f"Tu reporte está publicado, bro: <#{row['thread']}>.")
        if action=='claim':
            async with self.lock:
                async def claim():
                    await self.call('claim',rid,i.user.id);await self.refresh(rid)
                await self.tracked(rid,'Tomar reporte de error',f'claim:{rid}:{i.id}',claim)
            return await reply(i,'El reporte quedó a tu cargo.')
        if action=='state':return await reply(i,'Elige el nuevo estado.',view=StatePicker(self,i.user.id,rid))
        if action=='history':
            history=await self.call('events',rid)
            return await reply(i,('\n'.join(f"<t:{e['created']}:f> · <@{e['actor']}> · **{STATES.get(e['action'],e['action'])}**\n{discord.utils.escape_markdown(e['detail'])[:200]}" for e in history[-10:]) or 'Todavía no hay cambios.')[:1900])
    async def create(self,rid,recover=False):
        row=await self.call('get',rid);forum=await self.forum();thread=None
        if row['thread']:return
        if recover:
            for candidate in (await self.threads(forum)).values():
                if candidate.owner_id!=self.bot.user.id or not candidate.name.startswith(f"🐛 #{rid:04d} · "):continue
                first=await candidate.fetch_message(candidate.id)
                if any(e.footer.text==f'lvbug:{rid} · La Venganza RP' for e in first.embeds):thread=candidate;break
        async def publish():
            nonlocal thread
            if thread is None:
                kwargs={}
                if row['video']:kwargs['file']=discord.File(io.BytesIO(row['video']),filename=row['filename'])
                result=await forum.create_thread(name=f"🐛 #{rid:04d} · {json.loads(row['data'])['title']}"[:100],embed=self.embed(dict(row,status='pendiente')),
                    applied_tags=[forum.get_tag(TAGS['pendiente'])],view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE,**kwargs)
                thread=result.thread
            await self.call('published',rid,thread.id,thread.id)
        await self.tracked(rid,'Publicar reporte de error',f'create:{rid}',publish)
        log.info('BUGS published id=%s thread=%s recovered=%s',rid,thread.id,recover)
    async def refresh(self,rid):
        row=await self.call('get',rid);thread=await self.bot.fetch_channel(row['thread'])
        if thread.parent_id!=FORUM:raise ValueError('Ese hilo no pertenece a Reportes.')
        message=await thread.fetch_message(row['message'])
        if message.author.id!=self.bot.user.id:raise ValueError('El mensaje no es de este bot.')
        await message.edit(embed=self.embed(row),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
    async def apply_state(self,rid):
        row=await self.call('get',rid);pending=json.loads(row['pending']);forum=await self.forum()
        thread=await self.bot.fetch_channel(row['thread'])
        if thread.parent_id!=FORUM:raise ValueError('Ese hilo no pertenece a Reportes.')
        tags=[t for t in thread.applied_tags if t.id not in {TAGS[k] for k in STATES}]
        await thread.edit(applied_tags=[*tags,forum.get_tag(TAGS[pending['state']])],reason=pending['reason'][:400])
        message=await thread.fetch_message(row['message'])
        if message.author.id!=self.bot.user.id:raise ValueError('El mensaje no es de este bot.')
        await message.edit(embed=self.embed(dict(row,status=pending['state'])),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
        await self.call('finish',rid)
    async def change(self,i,rid,state,reason):
        from feedback import clean
        reason=clean(reason)
        await self.member(i,admin=True)
        async with self.lock:
            async def update():
                await self.call('intent',rid,i.user.id,state,reason);await self.apply_state(rid)
            await self.tracked(rid,'Cambiar estado de reporte',f'state:{rid}:{i.id}',update)
        await reply(i,f"Estado actualizado: **{STATES[state]}**.")
    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.ready()
                async with self.lock:
                    for row in await self.call('rows',recovery=True):
                        try:
                            if row['status']=='publicando':await self.create(row['id'],recover=True)
                            elif row['pending']:await self.apply_state(row['id'])
                            elif row['thread'] and not row['message']:await self.attach_manual(row)
                        except Exception:log.exception('BUGS recovery_pending id=%s',row['id'])
            except Exception:log.exception('BUGS maintenance_pending')
            await asyncio.sleep(120)
    async def observe(self,message):
        if not message.guild or message.guild.id!=self.guild_id or message.author.bot or not isinstance(message.channel,discord.Thread) or message.channel.parent_id!=FORUM:return
        if TAGS['info'] in {t.id for t in message.channel.applied_tags}:return
        async with self.lock:
            row=await self.call('by_thread',message.channel.id)
            links=re.findall(r'https://[^\s<>]+',message.content)
            videos=[a for a in message.attachments if (a.content_type or '').startswith('video/')]
            clip=videos[0].url if videos else links[0] if links else ''
            if row:
                if clip and message.author.id==row['owner']:
                    await self.call('manual_clip',row['id'],row['owner'],clip);await self.refresh(row['id'])
                return
            if message.id!=message.channel.id:return
            rid=await self.call('adopt',message.channel.id,message.author.id,message.channel.name,message.content,clip)
            await self.attach_manual(await self.call('get',rid))
    async def thread_update(self,thread):
        if thread.parent_id!=FORUM:return
        async with self.lock:
            row=await self.call('by_thread',thread.id)
            if not row:return
            states=[key for key in STATES if TAGS[key] in {t.id for t in thread.applied_tags}]
            if len(states)==1 and await self.call('external_state',row['id'],states[0]):await self.refresh(row['id'])
    async def attach_manual(self,row):
        rid=row['id'];thread=await self.bot.fetch_channel(row['thread'])
        if thread.parent_id!=FORUM:raise ValueError('Ese hilo no pertenece a Reportes.')
        async def attach():
            async for previous in thread.history(limit=100):
                if previous.author.id==self.bot.user.id and any(e.footer.text==f'lvbug:{rid} · La Venganza RP' for e in previous.embeds):
                    await self.call('controls',rid,previous.id);return
            forum=await self.forum();tags=[t for t in thread.applied_tags if t.id not in {TAGS[k] for k in STATES}]
            await thread.edit(applied_tags=[*tags,forum.get_tag(TAGS['pendiente'])],reason='Registrar nuevo reporte como Pendiente')
            panel=await thread.send('Registré tu reporte, bro. '+('El equipo lo revisará.' if json.loads(row['data']).get('clip') else '**Falta el clip del error. Adjunta el video o pega su enlace aquí.**'),embed=self.embed(row),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
            await self.call('controls',rid,panel.id)
        await self.tracked(rid,'Registrar reporte abierto desde el foro',f'adopt:{rid}',attach)
    def register(self):
        @self.group.command(name='reportar',description='Crear o continuar un reporte de error')
        async def report(i:discord.Interaction):await self.form(i)
        @self.group.command(name='mis',description='Ver tus reportes y sus estados')
        async def mine(i:discord.Interaction):await self.action(i,'mine',0)
        @self.group.command(name='estado',description='Cambiar el estado de un reporte; solo administración')
        async def state(i:discord.Interaction,numero:app_commands.Range[int,1,1000000],estado:str,motivo:str):
            await i.response.defer(ephemeral=True);await self.change(i,numero,estado,motivo)
        @state.autocomplete('estado')
        async def states(i,current):return [app_commands.Choice(name=v,value=k) for k,v in STATES.items() if current.casefold() in v.casefold()]
        @self.group.error
        async def error(i,exc):await failed(i,getattr(exc,'original',exc))
