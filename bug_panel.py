"""Replace only the explicitly identified old information post, after verifying its new bot-owned replacement."""
import logging

import discord

from bug_template import panel_embed
from bug_ui import buttons
from feedback_ui import NONE
from bug_limits import MAX_FILE_MB,MAX_REPORT_FILES

FORUM=1556488595131466000
LEGACY=1564719087798460466
OLD_PORTAL=1569698524654993449
TITLE='🐛 Reportes de errores · La Venganza RP'
MARKER='La Venganza RP · Equipo de desarrollo · Panel oficial de reportes'
CONTROLS=['lvbug:new:0','lvbug:mine:0']
log=logging.getLogger('LaVenganzaRP.bugs')

def message_state(message):
    return dict(id=message.id,author=message.author.id,content=message.content,
        embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components],
        attachments=[dict(id=a.id,name=a.filename,url=a.url) for a in message.attachments])

def thread_state(thread):
    return dict(id=thread.id,parent=thread.parent_id,name=thread.name,owner=thread.owner_id,
        pinned=thread.flags.pinned,archived=thread.archived,locked=thread.locked,
        tags=[t.id for t in thread.applied_tags])

def safe_old_post(thread,messages,bot_id):
    if thread.id!=LEGACY or thread.parent_id!=FORUM:return False
    root=next((m for m in messages if m.id==LEGACY),None)
    if not root or 'PLANTILLA OFICIAL' not in root.content.upper():return False
    if any(m.attachments or getattr(m,'stickers',[]) for m in messages):return False
    return all(m.id==LEGACY or (m.author.id==bot_id and
        [getattr(c,'custom_id',None) for r in m.components for c in r.children]==CONTROLS) for m in messages)

class ReportPanel:
    def __init__(self,system):self.system=system;self.bot=system.bot
    async def call(self,*args,**kwargs):return await self.system.call(*args,**kwargs)
    async def capture_old(self):
        try:thread=await self.bot.fetch_channel(LEGACY)
        except discord.NotFound:return None,[],None
        if thread.parent_id!=FORUM or await self.call('by_thread',LEGACY):raise ValueError('La plantilla antigua no coincide con la publicación informativa autorizada.')
        messages=[m async for m in thread.history(limit=None,oldest_first=True)]
        payload=dict(thread=thread_state(thread),messages=[message_state(m) for m in messages])
        await self.call('panel_backup',LEGACY,payload)
        await self.call('panel_backup',LEGACY)  # Verify the durable digest before changing Discord.
        return thread,messages,payload
    async def ensure(self,forum):
        saved=await self.call('config','official_guide_v4');thread=None
        if saved:
            try:thread=await self.bot.fetch_channel(int(saved))
            except discord.NotFound:pass
        if thread is None:
            for candidate in (await self.system.threads(forum)).values():
                if candidate.owner_id!=self.bot.user.id or candidate.name!=TITLE:continue
                first=await candidate.fetch_message(candidate.id)
                if any(e.footer.text==MARKER for e in first.embeds):thread=candidate;break
        embed=panel_embed()
        avatar=getattr(self.bot.user,'display_avatar',None)
        if avatar:embed.set_thumbnail(url=avatar.url)
        async def publish():
            nonlocal thread
            if thread is None:
                result=await forum.create_thread(name=TITLE,embed=embed,view=buttons('new','mine'),applied_tags=[forum.get_tag(1564718816959660062)],allowed_mentions=NONE,reason='Reemplazo de plantilla solicitado por el dueño')
                thread=result.thread
            if thread.parent_id!=FORUM or thread.owner_id!=self.bot.user.id or thread.id in (LEGACY,OLD_PORTAL):raise ValueError('El panel nuevo no pertenece a este bot o no está en Reportes.')
            root=await thread.fetch_message(thread.id)
            if root.author.id!=self.bot.user.id:raise ValueError('El mensaje nuevo no pertenece al bot.')
            if await self.call('config','panel_revision')!='9' or self.system.entry_controls(root)!=CONTROLS:
                await root.edit(content=None,embed=embed,view=buttons('new','mine'),allowed_mentions=NONE)
            await self.call('config','official_guide_v4',thread.id)
            await self.call('config','guide_buttons',thread.id)
            await self.call('config','panel_revision','9')
        async def snapshot():
            if thread is None:return dict(guide=None)
            current=await self.bot.fetch_channel(thread.id)
            return dict(thread=thread_state(current),message=message_state(await current.fetch_message(current.id)),
                panel_revision=await self.call('config','panel_revision'))
        await self.bot.changes.tracked('BUG_REPORTS','Actualizar el límite a 120 MB y mostrar el contador de peso',publish,
            request_id='official-panel-v9',snapshot=snapshot)
        await self.verify(thread.id)
        log.info('BUGS panel_verified guide=%s max_clip_mb=%s max_files=10 weight_counter=True photos=True videos=True same_entry=True',thread.id,MAX_FILE_MB)
        return await self.bot.fetch_channel(thread.id)
    async def verify(self,tid):
        thread=await self.bot.fetch_channel(tid);root=await thread.fetch_message(tid)
        if thread.parent_id!=FORUM or thread.owner_id!=self.bot.user.id or root.author.id!=self.bot.user.id or self.system.entry_controls(root)!=CONTROLS or not any(e.footer.text==MARKER for e in root.embeds):
            raise RuntimeError('Discord no confirmó la nueva plantilla del bot y sus botones.')
        if not any(f'2.4 MB / {MAX_FILE_MB} MB' in field.value and f'{MAX_REPORT_FILES} archivos' in field.value and 'fotos' in field.value for embed in root.embeds for field in embed.fields):
            raise RuntimeError('Discord no confirmó el límite y el contador de peso de los archivos.')
        return thread
    async def ready(self):
        forum=await self.system.forum()
        old,messages,backup=await self.capture_old()
        new=await self.ensure(forum)
        safe=old is not None and safe_old_post(old,messages,self.bot.user.id)
        if old is not None:
            old_was_pinned=old.flags.pinned
            async def snapshot():
                return dict(old_backup=await self.call('panel_backup',LEGACY),new_guide=new.id,
                    legacy_removed=await self.call('config','legacy_guide_removed'))
            async def replace():
                current=await self.verify(new.id)
                if old_was_pinned:await old.edit(pinned=False,reason='Dar paso a la nueva plantilla oficial del bot')
                try:
                    if not current.flags.pinned:await current.edit(pinned=True,reason='Fijar plantilla nueva verificada')
                except Exception:
                    if old_was_pinned:await old.edit(pinned=True,reason='Conservar acceso a la plantilla anterior')
                    raise
                verified=await self.verify(new.id)
                if not verified.flags.pinned:raise RuntimeError('La plantilla nueva no quedó fijada; se conserva la anterior.')
                if not safe:
                    await old.edit(name='📁 Plantilla anterior · Archivo',archived=True,locked=True,reason='Conservar conversación anterior al migrar el panel')
                    await self.call('config','legacy_guide_blocked','Tiene conversación o archivos que deben conservarse')
                    log.warning('BUGS legacy_guide_preserved id=%s reason=conversation_or_files',LEGACY)
                    return
                await old.edit(archived=True,locked=True,reason='Preparar retirada de la plantilla antigua autorizada')
                fresh=[m async for m in old.history(limit=None,oldest_first=True)]
                current_payload=[message_state(m) for m in fresh]
                if not safe_old_post(old,fresh,self.bot.user.id) or current_payload!=backup['messages']:
                    raise ValueError('La plantilla antigua recibió cambios; se conserva sin eliminar.')
                durable=await self.call('panel_backup',LEGACY)
                if durable['messages']!=backup['messages']:raise ValueError('La copia de la plantilla no corresponde a su contenido actual.')
                # The owner explicitly requested deleting this old information post.
                # No real report, third-party reply, attachment or other thread is eligible.
                await old.delete(reason='Reemplazar plantilla antigua por mensaje del bot; copia privada verificada y nuevo panel confirmado')
                try:await self.bot.fetch_channel(LEGACY)
                except discord.NotFound:pass
                else:raise RuntimeError('La plantilla anterior sigue existiendo.')
                await self.call('config','legacy_guide_removed','1')
                log.info('BUGS legacy_guide_removed old=%s replacement=%s backup_verified=True no_reports_or_files_deleted=True',LEGACY,new.id)
            await self.bot.changes.tracked('BUG_OFFICIAL_REPLACE','Reemplazar plantilla antigua por panel del bot',replace,request_id=f'{LEGACY}:v4',snapshot=snapshot)
        else:
            if not new.flags.pinned:await new.edit(pinned=True,reason='Mantener fijada la plantilla oficial del bot')
            await self.call('config','legacy_guide_removed','1')
        await self.update_redirect(new.id)
        return await self.verify(new.id)
    async def update_redirect(self,new_id):
        if await self.call('config','redirect_v4')==str(new_id):return
        try:thread=await self.bot.fetch_channel(OLD_PORTAL)
        except discord.NotFound:return
        if thread.parent_id!=FORUM or thread.owner_id!=self.bot.user.id or await self.call('by_thread',OLD_PORTAL):return
        root=await thread.fetch_message(thread.id)
        if root.author.id!=self.bot.user.id or root.attachments:return
        async def snapshot():return dict(message=message_state(await thread.fetch_message(thread.id)),thread=thread_state(await self.bot.fetch_channel(thread.id)))
        async def update():
            if thread.archived:await thread.edit(archived=False,locked=False)
            await root.edit(content=f'📌 La plantilla oficial y el formulario están aquí:\nhttps://discord.com/channels/{self.system.guild_id}/{new_id}/{new_id}',embed=None,view=None,allowed_mentions=NONE)
            await thread.edit(archived=True,locked=True)
            await self.call('config','redirect_v4',new_id)
        await self.bot.changes.tracked('BUG_PANEL_REDIRECT','Actualizar el enlace al panel oficial',update,request_id=str(new_id),snapshot=snapshot)
