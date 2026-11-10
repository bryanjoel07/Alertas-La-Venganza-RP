"""The owner's original animated banner, served at a stable HTTPS URL."""
import asyncio
import hashlib
import logging
from pathlib import Path

import aiohttp
from aiohttp import web
import discord

from sqlite_runtime import transaction

BANNER=Path(__file__).parent/'assets'/'banners'/'server-up.gif'
DIGEST='69e8b6cba68d6824ba837ac8dbe0f3fe1ac588571f154ffd167e84fe1e484f23'
ROUTE=f'/assets/server-up-{DIGEST}.gif'
CHANNEL=1567618156963430440
MESSAGE=1569841663361417331
BOT=1567658433497399408
GUILD=1244988345327550565
KEY=f'server-up-gif-repair:{MESSAGE}:{DIGEST}'
log=logging.getLogger('LaVenganzaRP.server-up')


async def banner_file(request):
    return web.FileResponse(BANNER,headers={'Content-Type':'image/gif',
        'Cache-Control':'public, max-age=31536000, immutable, no-transform',
        'X-Content-Type-Options':'nosniff','Content-Disposition':'inline; filename="la-venganza-server-up.gif"'})


def banner_url(bot):
    media=bot.bugs.media
    return media.base_url+ROUTE if media.runner is not None and media.base_url else ''


async def probe(url):
    """Check the actual bytes, not only a successful HEAD or embed URL."""
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


class ServerUpBanner:
    def __init__(self,bot,path):self.bot,self.path=bot,path;self.lock=asyncio.Lock()

    def receipt(self,value=None):
        with transaction(self.path,readonly=value is None) as db:
            if value is not None:db.execute('INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(KEY,value))
            row=db.execute('SELECT value FROM settings WHERE key=?',(KEY,)).fetchone()
            return row[0] if row else ''

    async def repair(self):
        if self.bot.user.id!=BOT:return
        async with self.lock:
            url=banner_url(self.bot)
            if not url or await asyncio.to_thread(self.receipt)==url:return
            asset=await probe(url)
            if asset['status']!=200 or asset['content_type']!='image/gif' or asset['sha256']!=DIGEST:
                raise RuntimeError('No se confirmó el GIF original en su dirección estable; el aviso se conserva.')
            channel=await self.bot.fetch_channel(CHANNEL)
            if channel.guild.id!=GUILD:raise ValueError('El canal no pertenece a La Venganza RP.')
            message=await channel.fetch_message(MESSAGE)
            if message.author.id!=BOT or not message.embeds or 'SERVER UP' not in (message.embeds[0].title or ''):
                raise ValueError('El mensaje no es el aviso SERVER UP indicado por el dueño.')
            if any(a.filename!='server-up.gif' or a.size!=BANNER.stat().st_size for a in message.attachments):
                raise ValueError('El aviso tiene otros adjuntos; se conservan para revisión.')
            original_proxy=message.embeds[0].image.proxy_url
            try:before=await probe(original_proxy) if original_proxy else dict(status=None)
            except (aiohttp.ClientError,TimeoutError):before=dict(status='unavailable')
            rendering={}

            async def snapshot():
                current=await channel.fetch_message(MESSAGE)
                return dict(channel=CHANNEL,message=current.id,author=current.author.id,content=current.content,
                    embeds=[e.to_dict() for e in current.embeds],components=[c.to_dict() for c in current.components],
                    attachments=[dict(id=a.id,filename=a.filename,size=a.size,url=a.url) for a in current.attachments],
                    original_asset=dict(file=str(BANNER.relative_to(Path(__file__).parent)),sha256=DIGEST,bytes=BANNER.stat().st_size),
                    previous_proxy=before,verified_asset=asset,rendering=rendering)

            async def update():
                embeds=[discord.Embed.from_dict(e.to_dict()) for e in message.embeds]
                embeds[0].set_image(url=url)
                await message.edit(embeds=embeds,attachments=[],allowed_mentions=discord.AllowedMentions.none())
                for attempt in range(3):
                    verified=await channel.fetch_message(MESSAGE)
                    if not verified.embeds or verified.embeds[0].image.url!=url or verified.attachments or verified.content!=message.content:
                        raise RuntimeError('Discord no confirmó la corrección del GIF en el mismo aviso.')
                    proxy=verified.embeds[0].image.proxy_url
                    if proxy:
                        try:rendering.update(await probe(proxy))
                        except (aiohttp.ClientError,TimeoutError):rendering.update(status='unavailable')
                        if rendering.get('status')==200 and rendering.get('content_type','').startswith('image/') and rendering.get('bytes',0)>0:
                            rendering.update(width=verified.embeds[0].image.width,height=verified.embeds[0].image.height)
                            return
                    if attempt<2:await asyncio.sleep(3)
                raise RuntimeError('El enlace se actualizó, pero Discord todavía no confirmó que puede mostrar el GIF.')

            await self.bot.changes.tracked('SERVER_UP_GIF_REPAIR','Reparar el GIF del aviso SERVER UP existente',update,
                request_id=KEY,snapshot=snapshot)
            await asyncio.to_thread(self.receipt,url)
            log.info('SERVER_UP gif_repaired channel=%s message=%s original_proxy_status=%s asset_status=%s sha256=%s bytes=%s discord_proxy_status=%s discord_proxy_type=%s width=%s height=%s original_animation=True same_message=True new_mentions=False',
                CHANNEL,MESSAGE,before['status'],asset['status'],asset['sha256'],asset['bytes'],rendering.get('status'),rendering.get('content_type'),rendering.get('width'),rendering.get('height'))
