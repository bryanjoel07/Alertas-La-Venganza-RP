"""Original banner plus a smaller animated copy that Discord must recognize."""
import asyncio
import hashlib
import logging
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web
import discord

from sqlite_runtime import transaction

BANNER=Path(__file__).parent/'assets'/'banners'/'server-up.gif'
DIGEST='69e8b6cba68d6824ba837ac8dbe0f3fe1ac588571f154ffd167e84fe1e484f23'
ROUTE=f'/assets/server-up-{DIGEST}.gif'
RENDER_BANNER=BANNER.with_name('server-up-discord.gif')
RENDER_DIGEST='04b3a386b94cc4baf08ac6debb7cad1cfe510b33d941535868c90a0f12fbf09a'
RENDER_ROUTE=f'/assets/server-up-{RENDER_DIGEST}.gif'
FILENAME=f'la-venganza-server-up-{RENDER_DIGEST[:12]}.gif'
ATTACHMENT='attachment://'+FILENAME
CHANNEL=1567618156963430440
MESSAGE=1569841663361417331
BOT=1567658433497399408
GUILD=1244988345327550565
KEY=f'server-up-gif-render:{MESSAGE}:{RENDER_DIGEST}'
log=logging.getLogger('LaVenganzaRP.server-up')


async def banner_file(request):
    path=RENDER_BANNER if request.path==RENDER_ROUTE else BANNER
    return web.FileResponse(path,headers={'Content-Type':'image/gif',
        'Cache-Control':'public, max-age=31536000, immutable, no-transform',
        'X-Content-Type-Options':'nosniff','Content-Disposition':'inline; filename="la-venganza-server-up.gif"'})


def banner_url(bot):
    media=bot.bugs.media
    return media.base_url+RENDER_ROUTE if media.runner is not None and media.base_url else ''


async def probe(url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(url) as response:
            digest=hashlib.sha256();size=0
            if response.status==200:
                async for chunk in response.content.iter_chunked(65536):
                    size+=len(chunk)
                    if size>10*1024*1024:raise ValueError('La imagen supera el tamaño esperado.')
                    digest.update(chunk)
            return dict(status=response.status,content_type=response.headers.get('Content-Type','').split(';')[0],
                bytes=size,sha256=digest.hexdigest() if size else '')


def source_matches(url,expected):
    if expected==ATTACHMENT:
        return url==ATTACHMENT or Path(urlsplit(url or '').path).name==FILENAME
    return url==expected


async def verify_image(channel,mid,expected,content):
    """HTTP 200 alone is insufficient: the embed must have real dimensions."""
    for attempt in range(3):
        current=await channel.fetch_message(mid)
        if not current.embeds or current.content!=content or not source_matches(current.embeds[0].image.url,expected):
            raise RuntimeError('Discord no confirmó la imagen en el mismo aviso.')
        image=current.embeds[0].image
        proof={}
        if image.proxy_url:
            try:proof=await probe(image.proxy_url)
            except (aiohttp.ClientError,TimeoutError):pass
            # Reading the proxy may finish processing; fetch fresh dimensions.
            current=await channel.fetch_message(mid)
            if not current.embeds or current.content!=content:
                raise RuntimeError('El aviso cambió mientras se comprobaba su imagen.')
            image=current.embeds[0].image
        if source_matches(image.url,expected) and (image.width or 0)>0 and (image.height or 0)>0 and proof.get('status')==200 and proof.get('content_type')=='image/gif' and proof.get('bytes',0)>0:
            return dict(proof,width=image.width,height=image.height,mode='attachment' if expected==ATTACHMENT else 'hosted')
        if attempt<2:await asyncio.sleep(3)
    raise RuntimeError('Discord todavía devuelve una imagen sin dimensiones; no se marcará como reparada.')


class ServerUpBanner:
    def __init__(self,bot,path):self.bot,self.path=bot,path;self.lock=asyncio.Lock()

    def receipt(self,value=None):
        with transaction(self.path,readonly=value is None) as db:
            if value is not None:db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,value))
            row=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
            return row[0] if row else ''

    async def replace(self,channel,message,*,native=True):
        allowed={'server-up.gif':BANNER.stat().st_size,FILENAME:RENDER_BANNER.stat().st_size}
        if any(allowed.get(a.filename)!=a.size for a in message.attachments):
            raise ValueError('El aviso tiene otros adjuntos; se conservan para revisión.')
        rendering={}
        async def snapshot():
            current=await channel.fetch_message(message.id)
            return dict(channel=channel.id,message=current.id,author=current.author.id,content=current.content,
                embeds=[e.to_dict() for e in current.embeds],components=[c.to_dict() for c in current.components],
                attachments=[dict(id=a.id,filename=a.filename,size=a.size,url=a.url) for a in current.attachments],
                original_asset=dict(file=str(BANNER.relative_to(Path(__file__).parent)),sha256=DIGEST),
                compatible_asset=dict(file=str(RENDER_BANNER.relative_to(Path(__file__).parent)),sha256=RENDER_DIGEST),rendering=rendering)
        async def update():
            current=await channel.fetch_message(message.id)
            if current.author.id!=BOT or not current.embeds:raise ValueError('El aviso cambió; se conserva sin reemplazarlo.')
            embeds=[discord.Embed.from_dict(e.to_dict()) for e in current.embeds]
            if native:
                embeds[0].set_image(url=ATTACHMENT)
                with closing(discord.File(RENDER_BANNER,filename=FILENAME)) as file:
                    await message.edit(embeds=embeds,attachments=[file],allowed_mentions=discord.AllowedMentions.none())
                try:
                    rendering.update(await verify_image(channel,message.id,ATTACHMENT,current.content))
                    return
                except RuntimeError:log.warning('SERVER_UP native_image_pending message=%s; checking hosted copy',message.id)
            url=banner_url(self.bot)
            if not url:raise RuntimeError('No se confirmó el GIF adjunto y no hay dirección alternativa configurada.')
            asset=await probe(url)
            if asset['status']!=200 or asset['content_type']!='image/gif' or asset['sha256']!=RENDER_DIGEST:
                raise RuntimeError('No se confirmó la copia compatible del GIF.')
            current=await channel.fetch_message(message.id)
            if current.author.id!=BOT or not current.embeds:raise ValueError('El aviso cambió; se conserva sin reemplazarlo.')
            embeds=[discord.Embed.from_dict(e.to_dict()) for e in current.embeds]
            embeds[0].set_image(url=url)
            await message.edit(embeds=embeds,attachments=[],allowed_mentions=discord.AllowedMentions.none())
            rendering.update(await verify_image(channel,message.id,url,current.content))
        await self.bot.changes.tracked('SERVER_UP_GIF_RENDER','Corregir la visualización del GIF de SERVER UP',update,
            request_id=f'{message.id}:{RENDER_DIGEST}',snapshot=snapshot)
        return rendering

    async def send(self,channel,embed):
        embed.set_image(url=ATTACHMENT)
        with closing(discord.File(RENDER_BANNER,filename=FILENAME)) as file:
            message=await channel.send(content='@everyone',embed=embed,file=file,
                allowed_mentions=discord.AllowedMentions(everyone=True,users=False,roles=False,replied_user=False))
        try:rendering=await verify_image(channel,message.id,ATTACHMENT,message.content)
        except RuntimeError:rendering=await self.replace(channel,message,native=False)
        log.info('SERVER_UP image_verified message=%s mode=%s width=%s height=%s gif=True',message.id,rendering['mode'],rendering['width'],rendering['height'])
        return message

    async def repair(self):
        if self.bot.user.id!=BOT:return
        async with self.lock:
            if await asyncio.to_thread(self.receipt)==RENDER_DIGEST:return
            channel=await self.bot.fetch_channel(CHANNEL)
            if channel.guild.id!=GUILD:raise ValueError('El canal no pertenece a La Venganza RP.')
            message=await channel.fetch_message(MESSAGE)
            if message.author.id!=BOT or not message.embeds or 'SERVER UP' not in (message.embeds[0].title or ''):
                raise ValueError('El mensaje no es el aviso SERVER UP indicado por el dueño.')
            rendering=await self.replace(channel,message)
            await asyncio.to_thread(self.receipt,RENDER_DIGEST)
            log.info('SERVER_UP gif_render_verified channel=%s message=%s mode=%s bytes=%s width=%s height=%s proxy_status=%s proxy_type=%s sha256=%s same_message=True new_mentions=False',
                CHANNEL,MESSAGE,rendering['mode'],RENDER_BANNER.stat().st_size,rendering['width'],rendering['height'],rendering['status'],rendering['content_type'],RENDER_DIGEST)
