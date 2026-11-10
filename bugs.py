"""Bug report workflow in the existing Reportes forum; roles are read-only."""
import asyncio
import io
import json
import logging
from pathlib import Path
import re
import time
import discord
from discord import app_commands
from bug_store import BugStore,STATES
from bug_ui import BugAction,BugForm,StatePicker,buttons,failed,size_summary
from feedback_ui import reply,RED,NONE
from tickets_store import PROTECTED
from bug_uploads import ClipUploads
from bug_media import ReportMedia
from bug_limits import IMAGE_TYPES,MAX_REPORT_FILES,MAX_FILE_MB,BYTES_PER_MB

FORUM=1556488595131466000
GUIDE=1564719087798460466
TAGS={'pendiente':1564715642911981718,'revision':1564715732309250078,'proceso':1564715806330192012,
      'solucionado':1564715869026648237,'cerrado':1564715973465079951,'info':1564718816959660062}
PORTAL='🐛 REPORTAR UN ERROR | LA VENGANZA RP'
OLD_PORTAL=1569698524654993449
log=logging.getLogger('LaVenganzaRP.bugs')

class BugSystem:
    def __init__(self,bot,path,guild_id):
        self.bot,self.guild_id=bot,guild_id;self.store=BugStore(path)
        self.lock=asyncio.Lock();self.install_lock=asyncio.Lock();self.task=None
        self.panel_checked=None;self.panel_id=None
        self.clips=ClipUploads(self)
        self.media=ReportMedia(self)
        self.group=app_commands.Group(name='errores',description='Reportar errores y seguir su solución')
        self.register()
    async def call(self,name,*args,**kwargs):return await asyncio.to_thread(getattr(self.store,name),*args,**kwargs)
    async def start(self):
        if self.task is not None and not self.task.done():return
        await self.call('initialize');self.bot.add_dynamic_items(BugAction)
        await self.media.start()
        self.task=asyncio.create_task(self.loop(),name='bug-reports')
    async def member(self,i,admin=False):
        if i.guild_id not in (None,self.guild_id):raise ValueError('Usa los reportes en La Venganza RP.')
        guild=self.bot.get_guild(self.guild_id)
        if not guild:raise ValueError('El bot se está conectando. Inténtalo en un momento.')
        member=i.user if not admin and i.guild_id==self.guild_id and isinstance(i.user,discord.Member) and i.user.guild.id==self.guild_id else await guild.fetch_member(i.user.id)
        if member.bot:raise ValueError('Los reportes son para jugadores.')
        cached=guild.get_channel(FORUM) if not admin and hasattr(guild,'get_channel') else None
        forum=cached if isinstance(cached,discord.ForumChannel) else await self.forum()
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
        structured=data.get('report_schema')==4
        fields=[('ID en el servidor','player_id')] if data.get('details') and not structured else [('ID en el servidor','player_id'),('Descripción del error','description'),('Cómo ocurrió','steps'),('Sistema afectado','system'),('Frecuencia','frequency')]
        if structured:embed.add_field(name='Cuenta de Discord',value=discord.utils.escape_markdown('@'+data['discord_username']) if data.get('discord_username') else f"<@{row['owner']}>",inline=False)
        for label,key in fields:
            text=discord.utils.escape_markdown(data.get(key,'Pendiente'))
            for start in range(0,len(text),1024):embed.add_field(name=label if start==0 else label+' (continúa)',value=text[start:start+1024],inline=False)
        if data.get('details') and not structured:
            text=discord.utils.escape_markdown(data['details'])
            for start in range(0,len(text),1024):embed.add_field(name='Detalles del problema' if start==0 else 'Detalles (continúa)',value=text[start:start+1024],inline=False)
        hosted=self.media.url(row)
        files=row.get('files',[])
        proof=size_summary(row.get('attachment_status',files))
        link=f'[Abrir archivo]({hosted})' if hosted else data.get('clip') if not files else ''
        value=proof or ('Preparando los archivos adjuntos…' if data.get('upload_pending') else link or ('Archivo adjunto al reporte' if row.get('video') else 'Falta adjuntar una foto o un video'))
        if proof and link and not data.get('upload_pending'):
            if len(value)+len(link)+1<=1024:value+='\n'+link
            else:embed.add_field(name='🔗 Abrir prueba',value=link,inline=False)
        embed.add_field(name='📎 Pruebas',value=value,inline=False)
        if hosted and Path(row['filename']).suffix.lower() in IMAGE_TYPES:embed.set_image(url=hosted)
        embed.set_footer(text=f"lvbug:{row['id']} · La Venganza RP")
        return embed
    def payload(self,row):
        files=row.get('files',[])
        if not files:return dict(embed=self.embed(row))
        main=self.embed(row);embeds=[main];links=[];images=0
        for n,item in enumerate(files,1):
            url=self.media.file_url(item)
            if not url:continue
            label='Foto' if item['kind']=='image' else 'Video'
            links.append(f"{n}. [{label} · {item['size']/BYTES_PER_MB:.1f} MB]({url})")
            if item['kind']=='image':
                if not images:main.set_image(url=url)
                else:embeds.append(discord.Embed(color=RED).set_image(url=url))
                images+=1
        return dict(content='\n'.join(links) or None,embeds=embeds)
    async def preview(self,i,row,processing=False):
        view=buttons('publish','continue',rid=row['id'])
        if processing:
            view.children[0].item.disabled=True;view.children[0].item.label='Preparando archivos';view.children[0].item.emoji='⏳'
        data=json.loads(row['data']);progress=f" ({data.get('files_done',0)}/{data['files_total']})" if data.get('files_total') else ''
        await i.edit_original_response(content=('**Datos guardados. Preparando tus archivos'+progress+'…**\nEste mensaje se actualizará cuando estén listos.' if processing else '**Revisa tu reporte. Se publicará en el foro para que lo vea la comunidad.**\nEvita contraseñas y datos personales.'),embed=self.embed(row),view=view,allowed_mentions=NONE)
    async def tracked(self,rid,title,request,operation):
        async def snapshot():
            row=await self.call('get',rid,include_video=False) if rid else None
            if row:row={k:v for k,v in row.items() if k!='video'}
            return dict(forum=FORUM,report=row,portal=await self.call('config','portal'),guide_buttons=await self.call('config','guide_buttons'))
        return await self.bot.changes.tracked('BUG_REPORTS',title,operation,request_id=request,snapshot=snapshot)
    async def ready(self):
        async with self.install_lock:
            if self.panel_checked is not None and time.monotonic()-self.panel_checked<60:return
            from bug_panel import ReportPanel
            panel=ReportPanel(self)
            if self.panel_id is not None:
                try:
                    await panel.verify(self.panel_id)
                except (discord.NotFound,RuntimeError):
                    await self.call('config','panel_revision','')
                    log.warning('BUGS panel_repair_pending guide=%s',self.panel_id)
                else:
                    self.panel_checked=time.monotonic()
                    return
            guide=await panel.ready()
            message=await guide.fetch_message(guide.id)
            if message.author.id!=self.bot.user.id or self.entry_controls(message)!=['lvbug:new:0','lvbug:mine:0']:
                raise RuntimeError('No se confirmó el único panel de Reportes.')
            form=BugForm(self,dict(id=0,revision=0,data='{}',video=None))
            components=form.to_dict()['components']
            if len(components)!=5 or components[3]['component']['type']!=19:raise RuntimeError('El formulario único no incluye el archivo adjunto.')
            if components[3]['component']['max_values']!=MAX_REPORT_FILES:raise RuntimeError('El formulario no permite los diez archivos esperados.')
            self.panel_id=guide.id;self.panel_checked=time.monotonic()
            log.info('BUGS ready forum=%s guide=%s entry_message=%s bot_owned_template=True single_entry=True single_form=True fields=5 detailed_sections=4 evidence_required=True photos=True videos=True max_files=10 weight_counter=True admin_controls=True legacy_removed=%s max_clip_mb=%s large_clip_links=%s',FORUM,guide.id,message.id,await self.call('config','legacy_guide_removed'),MAX_FILE_MB,bool(self.media.runner))
    @staticmethod
    def entry_controls(message):
        return [getattr(c,'custom_id',None) for row in message.components for c in row.children]
    async def guide_buttons(self):
        guide=await self.bot.fetch_channel(GUIDE)
        if guide.parent_id!=FORUM:raise ValueError('La plantilla original ya no está en Reportes.')
        found=[]
        async for message in guide.history(limit=None,oldest_first=True):
            if message.author.id==self.bot.user.id and self.entry_controls(message)==['lvbug:new:0','lvbug:mine:0']:
                found.append(message)
        if found:
            await self.call('config','guide_buttons',found[0].id)
            for duplicate in found[1:]:
                if duplicate.attachments:raise ValueError('Una copia tiene archivos; se conserva para revisión.')
                async def snapshot():
                    try:current=await guide.fetch_message(duplicate.id)
                    except discord.NotFound:return dict(id=duplicate.id,exists=False)
                    return dict(id=current.id,author=current.author.id,exists=True,content=current.content,embeds=[e.to_dict() for e in current.embeds],components=[c.to_dict() for c in current.components])
                async def remove():
                    fresh=await guide.fetch_message(duplicate.id)
                    if fresh.author.id!=self.bot.user.id or fresh.attachments or self.entry_controls(fresh)!=['lvbug:new:0','lvbug:mine:0']:
                        raise ValueError('La copia cambió; no se eliminará.')
                    await fresh.delete()
                await self.bot.changes.tracked('BUG_GUIDE_DUPLICATES','Retirar mensaje duplicado del bot',remove,request_id=str(duplicate.id),snapshot=snapshot)
            return
        message=await guide.send('🐛 **Ahora puedes enviar el reporte con el bot, bro.**\nPulsa **Reportar un error**, completa el formulario y adjunta el video o pega su enlace. El bot guardará tu borrador y lo publicará con su estado.',view=buttons('new','mine'),allowed_mentions=NONE)
        await self.call('config','guide_buttons',message.id)
    async def retire_duplicate_portal(self):
        if await self.call('config','retired_portal')==str(OLD_PORTAL):return
        try:thread=await self.bot.fetch_channel(OLD_PORTAL)
        except discord.NotFound:
            await self.call('config','retired_portal',OLD_PORTAL);return
        if thread.parent_id!=FORUM or thread.owner_id!=self.bot.user.id or await self.call('by_thread',OLD_PORTAL):
            raise ValueError('La publicación extra no es el panel vacío esperado; se conserva.')
        starter=await thread.fetch_message(thread.id)
        if starter.author.id!=self.bot.user.id or starter.attachments:
            raise ValueError('La publicación extra contiene un archivo o cambió de autor; se conserva.')
        async def snapshot():
            current=await self.bot.fetch_channel(thread.id)
            message=await current.fetch_message(current.id)
            return dict(id=current.id,name=current.name,archived=current.archived,locked=current.locked,
                message=dict(id=message.id,content=message.content,embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components]))
        async def retire():
            guide_message=await self.call('config','guide_buttons')
            if thread.archived:await thread.edit(archived=False,locked=False,reason='Actualizar la entrada duplicada antes de archivarla')
            await starter.edit(content=f'📌 El formulario está en la **plantilla oficial fijada**.\nhttps://discord.com/channels/{self.guild_id}/{GUIDE}/{guide_message}',embed=None,view=None,allowed_mentions=NONE)
            await thread.edit(name='📁 Acceso anterior · Reportes',archived=True,locked=True,reason='Consolidar la entrada duplicada del bot conservando el historial')
            await self.call('config','retired_portal',OLD_PORTAL)
        await self.bot.changes.tracked('BUG_PORTAL_RETIRE','Retirar entrada repetida de Reportes',retire,request_id=str(OLD_PORTAL),snapshot=snapshot)
        verified=await self.bot.fetch_channel(OLD_PORTAL)
        root=await verified.fetch_message(verified.id)
        if root.components or root.embeds or not verified.archived:raise RuntimeError('La entrada repetida no quedó retirada.')
        log.info('BUGS duplicate_portal_retired thread=%s archived=True controls_removed=True all_history_preserved=True',OLD_PORTAL)
    async def form(self,i,rid=0):
        await self.member(i)
        rid=rid or await self.call('begin',i.user.id);row=await self.call('get',rid,include_video=False)
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
        row=await self.call('get',rid,include_video=False)
        if not row:raise ValueError('Ese reporte no existe.')
        if action=='publish':
            if row['owner']!=i.user.id:raise ValueError('Ese reporte no es tuyo.')
            async with self.lock:
                row=await self.call('get',rid,include_video=False)
                if not row['thread']:
                    await self.call('reserve',rid,i.user.id)
                    await self.create(rid)
            row=await self.call('get',rid,include_video=False)
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
        row=await self.call('get',rid,include_video=False);forum=await self.forum();thread=None
        if row['thread']:return
        if row['status']!='publicando' or json.loads(row['data']).get('upload_pending') or (not json.loads(row['data']).get('clip') and not row['video'] and not row['file_count']):
            raise ValueError('Faltan las pruebas. Adjunta una foto o un video, o pega su enlace.')
        if recover:
            for candidate in (await self.threads(forum)).values():
                if candidate.owner_id!=self.bot.user.id or not candidate.name.startswith(f"🐛 #{rid:04d} · "):continue
                first=await candidate.fetch_message(candidate.id)
                if any(e.footer.text==f'lvbug:{rid} · La Venganza RP' for e in first.embeds):thread=candidate;break
        async def publish():
            nonlocal thread,row
            if thread is None:
                if row.get('files'):
                    row=await self.media.share_files(rid)
                    result=await forum.create_thread(name=f"🐛 #{rid:04d} · {json.loads(row['data'])['title']}"[:100],
                        **self.payload(dict(row,status='pendiente')),applied_tags=[forum.get_tag(TAGS['pendiente'])],
                        view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
                    thread=result.thread
                    await self.call('published',rid,thread.id,thread.id)
                    return
                kwargs={}
                limit=getattr(forum.guild,'filesize_limit',10*1024*1024)
                if row['video'] and row['video_size']>limit:
                    row=await self.media.share(rid)
                elif row['video']:
                    saved=await self.call('get',rid)
                    kwargs['file']=discord.File(io.BytesIO(saved['video']),filename=row['filename'])
                async def send():
                    return await forum.create_thread(name=f"🐛 #{rid:04d} · {json.loads(row['data'])['title']}"[:100],embed=self.embed(dict(row,status='pendiente')),
                        applied_tags=[forum.get_tag(TAGS['pendiente'])],view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE,**kwargs)
                try:
                    try:result=await send()
                    except discord.HTTPException as error:
                        if not kwargs.get('file') or (error.status!=413 and error.code!=40005):raise
                        # Discord can change its ceiling independently of the SDK.
                        row=await self.media.share(rid)
                        kwargs.pop('file').close()
                        result=await send()
                finally:
                    if kwargs.get('file'):kwargs['file'].close()
                thread=result.thread
            await self.call('published',rid,thread.id,thread.id)
        await self.tracked(rid,'Publicar reporte de error',f'create:{rid}',publish)
        log.info('BUGS published id=%s thread=%s recovered=%s file_count=%s clip_bytes=%s clip_delivery=%s',rid,thread.id,recover,len(row.get('files',[])) or bool(row['video']),row.get('video_size') or sum(f['size'] for f in row.get('files',[])),'link' if self.media.url(row) or row.get('files') else 'attachment_or_external_link')
    async def refresh(self,rid):
        row=await self.call('get',rid,include_video=False);thread=await self.bot.fetch_channel(row['thread'])
        if thread.parent_id!=FORUM:raise ValueError('Ese hilo no pertenece a Reportes.')
        message=await thread.fetch_message(row['message'])
        if message.author.id!=self.bot.user.id:raise ValueError('El mensaje no es de este bot.')
        await message.edit(**self.payload(row),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
    async def apply_state(self,rid):
        row=await self.call('get',rid,include_video=False);pending=json.loads(row['pending']);forum=await self.forum()
        thread=await self.bot.fetch_channel(row['thread'])
        if thread.parent_id!=FORUM:raise ValueError('Ese hilo no pertenece a Reportes.')
        tags=[t for t in thread.applied_tags if t.id not in {TAGS[k] for k in STATES}]
        await thread.edit(applied_tags=[*tags,forum.get_tag(TAGS[pending['state']])],reason=pending['reason'][:400])
        message=await thread.fetch_message(row['message'])
        if message.author.id!=self.bot.user.id:raise ValueError('El mensaje no es de este bot.')
        await message.edit(**self.payload(dict(row,status=pending['state'])),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
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
                await self.clips.recover()
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
            videos=[a for a in message.attachments if (a.content_type or '').startswith(('video/','image/'))]
            clip=videos[0].url if videos else links[0] if links else ''
            if row:
                if clip and message.author.id==row['owner']:
                    await self.call('manual_clip',row['id'],row['owner'],clip);await self.refresh(row['id'])
                return
            if message.id!=message.channel.id:return
            rid=await self.call('adopt',message.channel.id,message.author.id,message.channel.name,message.content,clip)
            await self.attach_manual(await self.call('get',rid,include_video=False))
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
            panel=await thread.send('Registré tu reporte, bro. '+('El equipo lo revisará.' if json.loads(row['data']).get('clip') else '**Faltan las pruebas del error. Adjunta una foto o un video, o pega su enlace aquí.**'),embed=self.embed(row),view=buttons('claim','state','history',rid=rid),allowed_mentions=NONE)
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
