"""Per-member welcome cards for EssChino Studio's existing welcome channel."""
import asyncio
from collections import OrderedDict
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import sqlite3
import time
import unicodedata
from urllib.parse import urlsplit

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

log = logging.getLogger('EssChinoStudio.welcome')
GUILD_ID = 1514871828189941881
ASSETS = Path(__file__).parent / 'assets' / 'esschino'
VERSION = 'personal-welcome-v1'
TEXT = {
    'es': ('BIENVENIDO/A A ESSCHINO STUDIO', '👋 Tu bienvenida', 'Tu proyecto empieza aquí.'),
    'en': ('WELCOME TO ESSCHINO STUDIO', '👋 Your welcome card', 'Your project starts here.'),
    'pt-BR': ('BOAS-VINDAS À ESSCHINO STUDIO', '👋 Sua mensagem de boas-vindas', 'Seu projeto começa aqui.'),
    'fr': ('BIENVENUE CHEZ ESSCHINO STUDIO', '👋 Votre carte de bienvenue', 'Votre projet commence ici.'),
    'de': ('WILLKOMMEN BEI ESSCHINO STUDIO', '👋 Deine Willkommenskarte', 'Dein Projekt beginnt hier.'),
}


def clean_name(value):
    value = unicodedata.normalize('NFC', str(value))
    value = ''.join(c for c in value if unicodedata.category(c) not in {'Cc', 'Cf'})
    return ' '.join(value.split())[:100] or 'Miembro'


def name_font(text, maximum=930):
    path = ASSETS / 'fonts' / 'NotoSans-Bold.ttf'
    for size in range(42, 21, -1):
        font = ImageFont.truetype(str(path), size)
        if font.getlength(text) <= maximum:
            return text, font
    font = ImageFont.truetype(str(path), 22)
    while text and font.getlength(text + '…') > maximum:
        text = text[:-1]
    return text + '…', font


def render_card(display_name, username, avatar_data, locale='es'):
    """Compose the generated template with runtime Discord data; no AI calls per user."""
    if not 0 < len(avatar_data) <= 4 * 1024 * 1024:
        raise ValueError('No se pudo cargar una foto de perfil válida.')
    with Image.open(ASSETS / 'welcome-template.png') as image:
        canvas = image.convert('RGB').resize((1280, 720), Image.Resampling.LANCZOS)
    with Image.open(io.BytesIO(avatar_data)) as image:
        if image.width * image.height > 16_000_000:
            raise ValueError('La foto de perfil supera el tamaño permitido.')
        avatar = ImageOps.fit(image.convert('RGBA'), (104, 104), method=Image.Resampling.LANCZOS)
    # The template's purple ring remains visible around the real circular avatar.
    mask = Image.new('L', (416, 416), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 415, 415), fill=255)
    mask = mask.resize((104, 104), Image.Resampling.LANCZOS)
    canvas.paste(avatar, (79, 590), mask)
    draw = ImageDraw.Draw(canvas)
    regular = ASSETS / 'fonts' / 'NotoSans-Regular.ttf'
    heading, _, _ = TEXT.get(locale, TEXT['es'])
    draw.text((237, 590), heading, font=ImageFont.truetype(str(regular), 19), fill='#D6B5FF', anchor='lt')
    name, font = name_font(clean_name(display_name))
    draw.text((237, 618), name, font=font, fill='#FFFFFF', anchor='lt', stroke_width=1, stroke_fill='#161020')
    tag = '@' + clean_name(username)
    tag_font = ImageFont.truetype(str(regular), 18)
    while tag and tag_font.getlength(tag) > 930:
        tag = tag[:-1]
    draw.text((239, 671), tag, font=tag_font, fill='#B9ADC8', anchor='lt')
    output = io.BytesIO()
    canvas.save(output, 'JPEG', quality=92, subsampling=0, optimize=True)
    return output.getvalue()


class WelcomeStore:
    def __init__(self, path):
        self.path = path

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def initialize(self):
        with closing(self.db()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS studio_welcomes(
                event TEXT PRIMARY KEY, member TEXT NOT NULL, joined TEXT NOT NULL,
                payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempted INTEGER NOT NULL DEFAULT 0, message TEXT, filename TEXT, sha256 TEXT)''')

    def reserve(self, event, member, joined, payload):
        with closing(self.db()) as db, db:
            cursor = db.execute('INSERT OR IGNORE INTO studio_welcomes(event,member,joined,payload) VALUES (?,?,?,?)',
                (event, str(member), joined, json.dumps(payload, ensure_ascii=False)))
            created = cursor.rowcount == 1
        return self.get(event), created

    def get(self, event):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM studio_welcomes WHERE event=?', (event,)).fetchone()
            return dict(row) if row else None

    def pending(self):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM studio_welcomes WHERE state='pending' ORDER BY joined LIMIT 100")]

    def attempt(self, event, filename, digest):
        with closing(self.db()) as db, db:
            db.execute('UPDATE studio_welcomes SET attempted=?,filename=?,sha256=? WHERE event=?',
                       (int(time.time()), filename, digest, event))

    def finish(self, event, state, message=None):
        with closing(self.db()) as db, db:
            db.execute('UPDATE studio_welcomes SET state=?,message=? WHERE event=?',
                       (state, str(message) if message is not None else None, event))


class WelcomeCards:
    def __init__(self, system, path):
        self.system, self.store = system, WelcomeStore(path)
        self.lock = asyncio.Lock()
        self.render_slots = asyncio.Semaphore(2)
        self.cache = OrderedDict()
        self.cooldowns = {}
        self.task = None

    async def call(self, name, *args):
        return await asyncio.to_thread(getattr(self.store, name), *args)

    async def start(self):
        await self.call('initialize')

    async def avatar_bytes(self, asset):
        try:
            return await asyncio.wait_for(asset.read(), timeout=20)
        except discord.Forbidden:
            # Some CDN edges reject the HTTP library's default user agent. Read
            # the same public Discord asset with this bot's explicit user agent;
            # no bot token is sent to the image host and redirects stay disabled.
            url = str(asset)
            parts = urlsplit(url)
            if parts.scheme != 'https' or parts.hostname not in {'cdn.discordapp.com', 'media.discordapp.net'}:
                raise ValueError('La imagen de perfil no pertenece al CDN de Discord.') from None
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                    headers={'User-Agent':'DiscordBot (EssChino Studio, 1.0)'}) as session:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ValueError('Discord no permitió cargar la foto de perfil. Inténtalo de nuevo.')
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > 4 * 1024 * 1024:
                            raise ValueError('La foto de perfil supera el tamaño permitido.')
                    return bytes(data)

    @staticmethod
    def event(member):
        if member.guild.id != GUILD_ID or member.bot or member.joined_at is None:
            raise ValueError('La bienvenida solo corresponde a miembros de EssChino Studio.')
        joined = member.joined_at.astimezone(timezone.utc).isoformat()
        return f'{member.id}:{joined}', joined

    async def card(self, member, locale='es'):
        if member.guild.id != GUILD_ID or member.bot:
            raise ValueError('La tarjeta pertenece a miembros de EssChino Studio.')
        asset = member.display_avatar.with_format('png').with_size(256)
        key = (member.id, member.display_name, member.name, str(asset), locale)
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            self.cache.move_to_end(key)
            return cached[1]
        async with self.render_slots:
            data = await self.avatar_bytes(asset)
            card = await asyncio.to_thread(render_card, member.display_name, member.name, data, locale)
        self.cache[key] = (time.monotonic(), card)
        self.cache.move_to_end(key)
        while len(self.cache) > 32:
            self.cache.popitem(last=False)
        return card

    async def preview(self, i, locale='es'):
        if (i.guild_id != GUILD_ID or not isinstance(i.user, discord.Member) or i.user.bot
                or i.channel_id != self.system.channel_id('welcome')):
            raise ValueError('Abre tu bienvenida desde el panel de EssChino Studio.')
        now = time.monotonic()
        if now - self.cooldowns.get(i.user.id, -10) < 5:
            raise ValueError('Espera unos segundos antes de volver a generar tu bienvenida.')
        self.cooldowns[i.user.id] = now
        if len(self.cooldowns) > 2000:
            self.cooldowns = {uid: at for uid, at in self.cooldowns.items() if now - at < 60}
        await i.response.defer(ephemeral=True)
        card = await self.card(i.user, locale)
        _, title, body = TEXT.get(locale, TEXT['es'])
        embed = self.system.embed(title, body).set_image(url='attachment://mi-bienvenida.jpg')
        await i.followup.send(embed=embed, file=discord.File(io.BytesIO(card), filename='mi-bienvenida.jpg'),
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def reconcile(self, channel, row):
        if not row['filename']:
            return None
        async for message in channel.history(limit=100):
            if message.author.id == self.system.bot.user.id and any(a.filename == row['filename'] for a in message.attachments):
                await self.call('finish', row['event'], 'sent', message.id)
                return message.id
        return None

    async def joined(self, member):
        if member.guild.id != GUILD_ID or member.bot:
            return
        event, joined = self.event(member)
        payload = dict(member=member.id, display_name=member.display_name, username=member.name,
            avatar=str(member.display_avatar), guild_id=member.guild.id)
        async with self.lock:
            row, created = await self.call('reserve', event, member.id, joined, payload)
            if row['state'] != 'pending':
                return row['message']
            channel = member.guild.get_channel(self.system.channel_id('welcome'))
            if channel is None:
                channel = await self.system.bot.fetch_channel(self.system.channel_id('welcome'))
            if channel.guild.id != GUILD_ID:
                raise ValueError('No se confirmó el canal de bienvenida de EssChino Studio.')
            if not created:
                existing = await self.reconcile(channel, row)
                if existing:
                    return existing
                if row['attempted'] and time.time() - row['attempted'] < 60:
                    return None
            filename = f'bienvenida-{member.id}-{hashlib.sha256(event.encode()).hexdigest()[:12]}.jpg'

            async def snapshot():
                return {'guild_id':GUILD_ID,'channel_id':channel.id,'member':payload,
                        'receipt':await self.call('get',event)}

            async def send():
                card = await self.card(member)
                await self.call('attempt', event, filename, hashlib.sha256(card).hexdigest())
                embed = self.system.embed('👋 ¡Bienvenido/a, ' + clean_name(member.display_name) + '!',
                    f'Nos alegra tenerte aquí, {member.mention}.\n\n'
                    f'📜 Empieza por <#{self.system.channel_id("rules")}>.\n'
                    f'📦 Descubre <#{self.system.channel_id("catalog")}>.\n'
                    f'🎫 Si necesitas ayuda, visita <#{self.system.channel_id("support")}>.')
                embed.set_image(url='attachment://' + filename)
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url,
                    url=f'https://discord.com/users/{member.id}')
                embed.timestamp = member.joined_at
                message = await channel.send(embed=embed,
                    file=discord.File(io.BytesIO(card), filename=filename),
                    allowed_mentions=discord.AllowedMentions.none())
                await self.call('finish', event, 'sent', message.id)
                log.info('WELCOME_CARD sent guild=%s member=%s message=%s bytes=%s', GUILD_ID, member.id, message.id, len(card))
                return message.id

            return await self.system.bot.changes.tracked('MEMBER_WELCOME', 'Dar bienvenida personalizada a un miembro',
                send, request_id=event, snapshot=snapshot)

    async def install(self, guild):
        key = 'welcome_personalization'
        if self.system.store.get(key) != VERSION:
            channel = guild.get_channel(self.system.channel_id('welcome'))
            message = await channel.fetch_message(self.system.store.get('panel:welcome'))
            if message.author.id != self.system.bot.user.id:
                raise ValueError('El panel de bienvenida no pertenece al nuevo bot.')
            async def snapshot():
                saved = await channel.fetch_message(message.id)
                return dict(channel=channel.id, message=saved.id, embeds=[e.to_dict() for e in saved.embeds],
                    components=[r.to_dict() for r in saved.components],
                    attachments=[dict(id=a.id,filename=a.filename,size=a.size) for a in saved.attachments],
                    system_channel_flags=guild.system_channel_flags.value)
            async def apply():
                await message.edit(view=self.system.languages.attach(self.system.panel_view('welcome'),'welcome'),
                    allowed_mentions=discord.AllowedMentions.none())
                # Disable Discord's extra generic greeting; this bot supplies the
                # requested individual welcome. Preserve all other system flags.
                flags = guild.system_channel_flags
                if flags.join_notifications:
                    flags.join_notifications = False
                    await guild.edit(system_channel_flags=flags, reason='Bienvenida individual con nombre y avatar de EssChino Studio')
                await self.system.call('put', key, VERSION)
            await self.system.bot.changes.tracked('WELCOME_PANEL', 'Añadir Mi bienvenida al panel existente', apply,
                request_id=VERSION, snapshot=snapshot)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.recover(), name='esschino-welcome-recovery')

    async def recover(self):
        while not self.system.bot.is_closed():
            for row in await self.call('pending'):
                if row['attempted'] and time.time() - row['attempted'] < 60:
                    continue
                try:
                    guild = self.system.bot.get_guild(GUILD_ID)
                    member = await guild.fetch_member(int(row['member']))
                    _, joined = self.event(member)
                    if joined != row['joined']:
                        await self.call('finish', row['event'], 'cancelled')
                        continue
                    await self.joined(member)
                except discord.NotFound:
                    await self.call('finish', row['event'], 'cancelled')
                except Exception:
                    log.exception('WELCOME_CARD recovery_failed event=%s', row['event'])
            await asyncio.sleep(30)
