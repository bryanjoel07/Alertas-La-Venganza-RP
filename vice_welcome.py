"""Personalized GTA welcome artwork and durable delivery receipts."""
import asyncio
from collections import OrderedDict
from datetime import timezone
import hashlib
import io
import logging
import time

import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

from vice_design import ASSETS, FONTS, GUILD_ID
from welcome_cards import WelcomeStore, WelcomeCards, clean_name

log = logging.getLogger('ViceDistrict.welcome')


def fit_name(value, max_width=995):
    value = clean_name(value)
    for size in range(38, 21, -1):
        font = ImageFont.truetype(str(FONTS / 'NotoSans-Bold.ttf'), size)
        if font.getlength(value) <= max_width:
            return value, font
    while value and font.getlength(value + '…') > max_width:
        value = value[:-1]
    return value + '…', font


def render_card(display_name, username, avatar_data, *, template='welcome-template.jpg',
                heading='PUERTO RICO + LATINOAMÉRICA · BIENVENIDO/A'):
    if not 0 < len(avatar_data) <= 4 * 1024 * 1024:
        raise ValueError('No se pudo cargar una foto de perfil válida.')
    with Image.open(ASSETS / template) as source:
        canvas = source.convert('RGB').resize((1280, 720), Image.Resampling.LANCZOS)
    with Image.open(io.BytesIO(avatar_data)) as source:
        if source.width * source.height > 16_000_000:
            raise ValueError('La foto de perfil es demasiado grande.')
        avatar = ImageOps.fit(source.convert('RGB'), (100, 100), method=Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((39, 578, 1240, 705), radius=23, fill='#170C25', outline='#FF168A', width=2)
    draw.ellipse((60, 589, 172, 701), fill='#00D9E8')
    draw.ellipse((63, 592, 169, 698), fill='#271132')
    mask = Image.new('L', (400, 400), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 399, 399), fill=255)
    canvas.paste(avatar, (66, 595), mask.resize((100, 100), Image.Resampling.LANCZOS))
    regular = str(FONTS / 'NotoSans-Regular.ttf')
    draw.text((201, 587), heading, font=ImageFont.truetype(regular, 17), fill='#FFB8D8')
    name, font = fit_name(display_name)
    draw.text((200, 608), name, font=font, fill='#FFFBEA', stroke_width=1, stroke_fill='#170C25')
    tag = '@' + clean_name(username)
    small = ImageFont.truetype(regular, 18)
    while small.getlength(tag) > 990:
        tag = tag[:-1]
    draw.text((202, 666), tag, font=small, fill='#72E9EE')
    output = io.BytesIO()
    canvas.save(output, 'JPEG', quality=91, subsampling=0, optimize=True)
    return output.getvalue()


def render_cover():
    with Image.open(ASSETS / 'welcome-template.jpg') as source:
        canvas = source.convert('RGB').resize((1280, 720), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((39, 578, 1240, 705), radius=23, fill='#170C25', outline='#FF168A', width=2)
    font = ImageFont.truetype(str(FONTS / 'NotoSans-Bold.ttf'), 29)
    small = ImageFont.truetype(str(FONTS / 'NotoSans-Regular.ttf'), 18)
    draw.text((640, 616), 'TU PRÓXIMA CREW EMPIEZA AQUÍ', anchor='mm', font=font, fill='#FFFBEA')
    draw.text((640, 662), 'PUERTO RICO  •  LATINOAMÉRICA  •  PASIÓN POR GTA', anchor='mm', font=small, fill='#72E9EE')
    output = io.BytesIO()
    canvas.save(output, 'JPEG', quality=91, subsampling=0, optimize=True)
    return output.getvalue()


class ViceWelcome:
    def __init__(self, system, path):
        self.system = system
        self.store = WelcomeStore(path)
        self.lock = asyncio.Lock()
        self.slots = asyncio.Semaphore(2)
        self.cache = OrderedDict()
        self.cooldowns = {}
        self.task = None

    async def call(self, name, *args):
        return await asyncio.to_thread(getattr(self.store, name), *args)

    async def start(self):
        await self.call('initialize')

    @staticmethod
    def event(member):
        if member.guild.id != GUILD_ID or member.bot or member.joined_at is None:
            raise ValueError('La bienvenida pertenece a GTA VI Latino.')
        joined = member.joined_at.astimezone(timezone.utc).isoformat()
        return f'{GUILD_ID}:{member.id}:{joined}', joined

    async def card(self, member):
        if member.guild.id != GUILD_ID or member.bot:
            raise ValueError('La tarjeta pertenece a un miembro de GTA VI Latino.')
        asset = member.display_avatar.with_format('png').with_size(256)
        key = (member.id, member.display_name, member.name, str(asset))
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            self.cache.move_to_end(key)
            return cached[1]
        async with self.slots:
            avatar = await WelcomeCards.avatar_bytes(self, asset)
            data = await asyncio.to_thread(render_card, member.display_name, member.name, avatar)
        self.cache[key] = time.monotonic(), data
        while len(self.cache) > 24:
            self.cache.popitem(last=False)
        return data

    def embed(self, member, filename, example=False):
        c = self.system.channel_id
        name = discord.utils.escape_markdown(clean_name(member.display_name))
        embed = self.system.embed('🌴 ¡Bienvenido/a, ' + name + '!',
            ('**Así recibe el distrito a cada nuevo miembro.**\n\n' if example else '') +
            f'{member.mention}, tu historia en **VIce District** empieza aquí.\n\n'
            f'📜 Conoce <#{c("rules")}>.\n🎭 Elige tus roles en <#{c("roles")}>.\n'
            f'🙌 Saluda en <#{c("introductions")}>.\n🤝 Encuentra tu gente en <#{c("crew")}>.')
        embed.set_author(name=clean_name(member.display_name), icon_url=member.display_avatar.url)
        embed.set_image(url='attachment://' + filename)
        if example:
            embed.set_footer(text='GTA VI Latino • Muestra de bienvenida personalizada')
        return embed

    async def preview(self, interaction):
        self.system.authorize(interaction)
        now = time.monotonic()
        if now - self.cooldowns.get(interaction.user.id, -10) < 8:
            raise ValueError('Espera unos segundos antes de generar otra tarjeta.')
        self.cooldowns[interaction.user.id] = now
        if len(self.cooldowns) > 2000:
            self.cooldowns = {uid: at for uid, at in self.cooldowns.items() if now - at < 60}
        await interaction.response.defer(ephemeral=True)
        member = await interaction.guild.fetch_member(interaction.user.id)
        card = await self.card(member)
        filename = 'mi-bienvenida-vice.jpg'
        await interaction.followup.send(embed=self.embed(member, filename),
            file=discord.File(io.BytesIO(card), filename=filename), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())

    async def joined(self, member):
        if member.guild.id != GUILD_ID or member.bot:
            return
        event, joined = self.event(member)
        channel = member.guild.get_channel(self.system.channel_id('welcome'))
        if channel is None or channel.guild.id != GUILD_ID:
            raise ValueError('No se confirmó el canal de bienvenida del distrito.')
        async with self.lock:
            row, created = await self.call('reserve', event, member.id, joined, dict(guild_id=GUILD_ID))
            if row['state'] != 'pending':
                return row['message']
            if not created and row['filename']:
                async for message in channel.history(limit=100):
                    if message.author.id == self.system.bot.user.id and any(a.filename == row['filename'] for a in message.attachments):
                        await self.call('finish', event, 'sent', message.id)
                        return message.id
                if row['attempted'] and time.time() - row['attempted'] < 60:
                    return
            filename = f'vice-{member.id}-{hashlib.sha256(event.encode()).hexdigest()[:12]}.jpg'
            async def snapshot():
                return dict(guild=GUILD_ID, channel=channel.id, receipt=await self.call('get', event))
            async def send():
                card = await self.card(member)
                await self.call('attempt', event, filename, hashlib.sha256(card).hexdigest())
                message = await channel.send(embed=self.embed(member, filename),
                    file=discord.File(io.BytesIO(card), filename=filename),
                    allowed_mentions=discord.AllowedMentions.none())
                await self.call('finish', event, 'sent', message.id)
                log.info('VICE_WELCOME_SENT guild=%s member=%s message=%s', GUILD_ID, member.id, message.id)
                return message.id
            return await self.system.track('WELCOME', 'Bienvenida personalizada de GTA VI Latino',
                send, event, snapshot=snapshot)

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
                    else:
                        await self.joined(member)
                except discord.NotFound:
                    await self.call('finish', row['event'], 'cancelled')
                except Exception:
                    log.exception('VICE_WELCOME_RECOVERY_FAILED')
            await asyncio.sleep(30)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

