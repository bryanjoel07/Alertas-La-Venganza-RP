"""Prepare uploaded clips after a durable, immediate acknowledgement of the form."""
import asyncio
import json
import logging
import time
from urllib.parse import urlsplit

import discord

log=logging.getLogger('LaVenganzaRP.bugs')

def validate_source(source):
    for key in ('url','proxy_url'):
        value=source.get(key)
        if not value:continue
        parsed=urlsplit(value)
        if parsed.scheme!='https' or parsed.hostname not in ('cdn.discordapp.com','cdn.discordapp.net','media.discordapp.net') or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ValueError('El archivo debe adjuntarse desde el formulario de Discord.')
        parts=parsed.path.strip('/').split('/')
        if len(parts)<4 or parts[0] not in ('attachments','ephemeral-attachments') or str(source.get('id')) not in parts[1:3]:
            raise ValueError('El archivo adjunto no corresponde a Discord.')
    if not source.get('url'):raise ValueError('No se recibió el archivo adjunto.')

class ClipUploads:
    def __init__(self,system):
        self.system=system;self.jobs={};self.slots=asyncio.Semaphore(2);self.closed=False
    def launch(self,rid,revision,i=None,attachment=None):
        key=(rid,revision)
        if self.closed:return None
        if key in self.jobs and not self.jobs[key].done():return self.jobs[key]
        for previous,task in list(self.jobs.items()):
            if previous[0]==rid and previous!=key:task.cancel()
        task=asyncio.create_task(self.run(rid,revision,i,attachment),name=f'bug-clip-{rid}')
        self.jobs[key]=task
        def finished(done):
            if self.jobs.get(key) is done:self.jobs.pop(key,None)
            if not done.cancelled() and done.exception():log.error('BUGS clip_worker_failed id=%s',rid,exc_info=done.exception())
        task.add_done_callback(finished)
        return task
    async def run(self,rid,revision,i=None,attachment=None):
        started=time.monotonic()
        try:
            async with self.slots:
                job=await self.system.call('upload_job',rid)
                if not job or job['revision']!=revision or job['state']!='pending':return
                source=json.loads(job['source']);validate_source(source)
                transfer=time.monotonic()
                async def read():
                    if attachment is not None:return await attachment.read()
                    return await self.system.bot.http.get_from_cdn(source['url'])
                data=await asyncio.wait_for(read(),timeout=180)
                transfer_seconds=time.monotonic()-transfer
                if not await self.system.call('complete_upload',rid,revision,data):return
            row=await self.system.call('get',rid,include_video=False)
            if i is not None:
                try:await self.system.preview(i,row)
                except discord.HTTPException:log.info('BUGS clip_ready_preview_unavailable id=%s draft_preserved=True',rid)
            log.info('BUGS clip_prepared id=%s bytes=%s transfer_seconds=%.2f total_seconds=%.2f',rid,len(data),transfer_seconds,time.monotonic()-started)
        except asyncio.CancelledError:
            # Metadata was committed before the task started; a new process resumes it.
            raise
        except Exception as error:
            await self.system.call('fail_upload',rid,revision,type(error).__name__)
            log.warning('BUGS clip_prepare_failed id=%s error=%s seconds=%.2f',rid,type(error).__name__,time.monotonic()-started)
            if i is not None:
                from bug_ui import buttons
                from feedback_ui import NONE
                try:await i.edit_original_response(content='Los datos están guardados, pero no pude preparar el video. Vuelve a adjuntarlo o pega el enlace del clip.',embed=None,view=buttons('continue',rid=rid),allowed_mentions=NONE)
                except discord.HTTPException:pass
    async def recover(self):
        for row in await self.system.call('pending_uploads'):self.launch(row['report'],row['revision'])
    async def close(self):
        self.closed=True
        tasks=list(self.jobs.values())
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
