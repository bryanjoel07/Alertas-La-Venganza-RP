"""Photo of the week in the existing Fotos channel. Original posts stay intact."""
import asyncio
from datetime import datetime, timezone
import io
import logging
import os
from pathlib import Path
import time

import discord
from discord import app_commands

from economy_store import SLOTS
from photo_store import PhotoStore, week_bounds

log = logging.getLogger('LaVenganzaRP.photos')
FOTOS_CHANNEL = 1513422142014754976
COLOR = 0xD60000
MAX_UPLOAD = 25 * 1024 * 1024
IMAGE_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'}
PANEL_TITLE = '📸 FOTO DE LA SEMANA | LA VENGANZA RP'


def images(message):
    return [a for a in message.attachments if Path(a.filename).suffix.lower() in IMAGE_TYPES
            and ((a.content_type or '').startswith('image/') or (a.width and a.height))]


def closed(entry, now=None):
    return not entry['active'] or entry['week_state'] != 'open' or (int(time.time()) if now is None else now) >= entry['ends']


async def answer(i, text, **kwargs):
    sender = i.followup.send if i.response.is_done() else i.response.send_message
    return await sender(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)


class PhotoButton(discord.ui.DynamicItem[discord.ui.Button], template=r'lv:photo:(?P<entry>[0-9]+):(?P<action>vote|remove)'):
    def __init__(self, entry, action, count=0, disabled=False):
        super().__init__(discord.ui.Button(
            label=f'Votar · {count}' if action == 'vote' else 'Quitar voto',
            emoji='❤️' if action == 'vote' else '↩️', custom_id=f'lv:photo:{entry}:{action}',
            style=discord.ButtonStyle.secondary, disabled=disabled))
        self.entry, self.action = entry, action

    @classmethod
    async def from_custom_id(cls, i, item, match):
        return cls(int(match['entry']), match['action'])

    async def callback(self, i):
        await i.response.defer(ephemeral=True)
        try:
            await i.client.photos.vote(i, self.entry, self.action == 'vote')
        except ValueError as error:
            await answer(i, str(error))
        except discord.HTTPException:
            await answer(i, 'No pudimos actualizar la votación ahora. Inténtalo otra vez.')
        except Exception:
            log.exception('PHOTOS vote_error entry=%s', self.entry)
            await answer(i, 'No pudimos completar el voto ahora. Inténtalo otra vez.')


class PhotoControls(discord.ui.View):
    def __init__(self, entry, count=0, disabled=False):
        super().__init__(timeout=None)
        self.add_item(PhotoButton(entry, 'vote', count, disabled))
        self.add_item(PhotoButton(entry, 'remove', count, disabled))


class PhotoSystem:
    def __init__(self, bot, path, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.store = PhotoStore(path)
        self.lock = asyncio.Lock()
        self.ready_lock = asyncio.Lock()
        self.prepared = False
        self.task = None
        self.group = app_commands.Group(name='foto', description='Fotos, votos y ganador de la semana')
        self.register()

    def enabled(self):
        return os.getenv('PHOTO_CONTEST_ENABLED', '1') == '1'

    async def call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, method), *args, **kwargs)

    async def start(self):
        await self.call('initialize')
        self.bot.add_dynamic_items(PhotoButton)
        self.task = asyncio.create_task(self.loop(), name='photo-of-the-week')

    async def channel(self):
        channel = await self.bot.fetch_channel(FOTOS_CHANNEL)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('El canal de Fotos no corresponde a La Venganza RP.')
        return channel

    def source_link(self, entry):
        return f"https://discord.com/channels/{self.guild_id}/{FOTOS_CHANNEL}/{entry['source']}"

    def control_embed(self, row):
        embed = discord.Embed(title=f"📸 Foto #{row['id']} · Votación semanal", color=COLOR,
            description=f"Publicada por <@{row['author']}> · **{row['votes']} votos**\n" +
                ('Votación cerrada.' if closed(row) else f"Cierra <t:{row['ends']}:F>.") +
                f"\n[Ver la foto]({self.source_link(row)})")
        embed.set_thumbnail(url=row['url'])
        embed.set_footer(text=f"La Venganza RP · Foto #{row['id']} · {row['week']}")
        return embed

    def panel_embed(self, week):
        embed = discord.Embed(title=PANEL_TITLE, color=COLOR, description=
            'Sube tus fotos aquí y el bot pondrá **❤️ Votar** y **↩️ Quitar voto** debajo de cada una.\n\n'
            'Puedes votar una vez por cada foto de los demás y cambiar de opinión quitando tu voto. '
            'Las fotos compiten de lunes a domingo, hora de Puerto Rico. '
            'Al terminar la semana destacamos la más votada con el nombre de quien la publicó. '
            'Si empatan, gana la que se publicó primero.\n\n'
            f"**Cierre de esta semana:** <t:{week['ends']}:F>\n"
            'Usa `/foto semana` para ver cómo va la votación.')
        if week['prize_name']:
            embed.add_field(name='🎁 Premio de esta semana', value=week['prize_name'], inline=False)
        embed.set_footer(text='LA VENGANZA RP · Fotos de la semana')
        return embed

    async def pin(self, message, value=True):
        if message.author.id != self.bot.user.id or message.pinned == value:
            return
        async def snapshot():
            current = await message.channel.fetch_message(message.id)
            return {'channel': message.channel.id, 'message': message.id, 'pinned': current.pinned}
        async def operation():
            if value:
                await message.pin(reason='Foto de la semana solicitada por el propietario')
            else:
                await message.unpin(reason='Dar paso a la nueva foto ganadora del bot')
        await self.bot.changes.tracked('PHOTO_PIN', 'Destacar publicación de Fotos', operation,
            request_id=f"{message.id}:{int(value)}", snapshot=snapshot)

    async def panel(self, channel):
        week = await self.call('current')
        message = None
        saved = self.store.config('panel')
        if saved:
            try:
                message = await channel.fetch_message(int(saved))
            except discord.NotFound:
                pass
        if not message:
            async for previous in channel.history(limit=100):
                if previous.author.id == self.bot.user.id and any(e.title == PANEL_TITLE for e in previous.embeds):
                    message = previous
                    break
        if message and message.author.id != self.bot.user.id:
            raise ValueError('El panel guardado no pertenece a este bot.')
        if message:
            await message.edit(embed=self.panel_embed(week), allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(embed=self.panel_embed(week), allowed_mentions=discord.AllowedMentions.none())
        self.store.config('panel', message.id)
        self.store.config('panel_week', week['week'])
        try:
            await self.pin(message)
        except discord.HTTPException:
            log.warning('PHOTOS panel_pin_pending channel=%s message=%s', channel.id, message.id)

    async def source(self, channel, row):
        try:
            message = await channel.fetch_message(row['source'])
        except discord.NotFound:
            await self.call('deleted', row['source'])
            return None, None
        attachments = images(message)
        await self.call('sync_source', message.id, {a.id for a in attachments})
        item = next((a for a in attachments if a.id == row['attachment']), None)
        if message.author.id != row['author']:
            raise ValueError('La publicación de la foto no coincide con su autor.')
        if item:
            row['url'] = item.url
            await self.call('image_url', row['id'], item.url)
        return message, item

    async def ensure_control(self, row, source):
        channel = source.channel
        control = None
        if row['control']:
            try:
                control = await channel.fetch_message(row['control'])
            except discord.NotFound:
                await self.call('deleted', row['control'])
        if not control and row['notice_started']:
            after = datetime.fromtimestamp(row['notice_started'] - 5, timezone.utc)
            async for previous in channel.history(after=after, oldest_first=True, limit=None):
                ids = [getattr(c, 'custom_id', '') for r in previous.components for c in r.children]
                if previous.author.id == self.bot.user.id and f"lv:photo:{row['id']}:vote" in ids:
                    control = previous
                    break
        if control:
            if control.author.id != self.bot.user.id:
                raise ValueError('El control de votos no pertenece al bot.')
            await self.call('control', row['id'], control.id)
            if row['rendered_count'] != row['votes'] or row['rendered_closed'] != int(closed(row)):
                await control.edit(embed=self.control_embed(row), view=PhotoControls(row['id'], row['votes'], closed(row)), allowed_mentions=discord.AllowedMentions.none())
        else:
            await self.call('control_started', row['id'], int(time.time()))
            control = await source.reply(embed=self.control_embed(row), view=PhotoControls(row['id'], row['votes'], closed(row)),
                mention_author=False, allowed_mentions=discord.AllowedMentions.none())
            await self.call('control', row['id'], control.id)
        await self.call('rendered', row['id'], row['votes'], closed(row))
        return control

    async def observe(self, message):
        if not self.enabled() or not message.guild or message.guild.id != self.guild_id or message.channel.id != FOTOS_CHANNEL or message.author.bot:
            return
        async with self.lock:
            attachments = images(message)
            await self.call('sync_source', message.id, {a.id for a in attachments})
            for attachment in attachments:
                created = int(max(message.created_at.timestamp(), discord.utils.snowflake_time(attachment.id).timestamp()))
                entry = await self.call('register', message.id, attachment.id, message.author.id, attachment.filename, attachment.url, created)
                if entry is not None:
                    row = await self.call('entry', entry)
                    await self.ensure_control(row, message)

    async def edited(self, payload):
        if self.enabled() and payload.guild_id == self.guild_id and payload.channel_id == FOTOS_CHANNEL:
            channel = await self.channel()
            try:
                await self.observe(await channel.fetch_message(payload.message_id))
            except discord.NotFound:
                await self.call('deleted', payload.message_id)

    async def deleted(self, guild, channel, messages):
        if self.enabled() and guild == self.guild_id and channel == FOTOS_CHANNEL:
            for message in messages:
                await self.call('deleted', message)

    async def scan(self, channel):
        week, start, _ = week_bounds(int(time.time()))
        cursor = self.store.config('cursor') if self.store.config('scan_week') == week else ''
        after = discord.Object(id=int(cursor)) if cursor else datetime.fromtimestamp(start, timezone.utc)
        async for message in channel.history(after=after, oldest_first=True, limit=None):
            await self.observe(message)
            self.store.config('cursor', message.id)
            self.store.config('scan_week', week)

    async def refresh_controls(self, channel):
        for row in await self.call('refresh_entries', int(time.time())):
            if row['control'] and row['rendered_count'] == row['votes'] and row['rendered_closed'] == int(closed(row)):
                continue
            try:
                async with self.lock:
                    row = await self.call('entry', row['id'])
                    if row['control']:
                        message = await channel.fetch_message(row['control'])
                        if message.author.id != self.bot.user.id:
                            raise ValueError('Ese mensaje no pertenece al bot.')
                        await message.edit(embed=self.control_embed(row), view=PhotoControls(row['id'], row['votes'], closed(row)), allowed_mentions=discord.AllowedMentions.none())
                        await self.call('rendered', row['id'], row['votes'], closed(row))
                    elif not closed(row):
                        source, image = await self.source(channel, row)
                        if source and image:
                            await self.ensure_control(row, source)
                    else:
                        await self.call('rendered', row['id'], row['votes'], True)
            except discord.NotFound:
                await self.call('deleted', row['control'])
            except Exception:
                log.exception('PHOTOS control_refresh_pending entry=%s', row['id'])

    async def vote(self, i, entry, add):
        if not self.enabled() or i.guild_id != self.guild_id or i.channel_id != FOTOS_CHANNEL or i.user.bot:
            raise ValueError('Vota desde la foto en el canal de Fotos de La Venganza RP.')
        async with self.lock:
            row = await self.call('entry', entry)
            if not row or not i.message or i.message.id != row['control']:
                raise ValueError('Este control de votos ya no está disponible.')
            channel = await self.channel()
            if not channel.permissions_for(i.user).view_channel:
                raise ValueError('No tienes acceso a esta votación.')
            source, image = await self.source(channel, row)
            if not source or not image:
                raise ValueError('La foto fue retirada y ya no participa.')
            changed = await self.call('vote', entry, i.user.id, add)
            current = await self.call('entry', entry)
            try:
                await self.ensure_control(current, source)
            except discord.HTTPException:
                log.warning('PHOTOS count_update_pending entry=%s', entry)
        await answer(i, ('❤️ Tu voto quedó guardado.' if add else 'Quitaste tu voto.') if changed else
            ('Ya votaste por esta foto.' if add else 'No tenías un voto en esta foto.'))

    def winner_embed(self, week):
        row = self.store.entry(week['winner']) if week['winner'] else None
        if row:
            embed = discord.Embed(title='🏆 FOTO DE LA SEMANA | LA VENGANZA RP', color=COLOR,
                description=f"📸 Publicada por <@{row['author']}>\n❤️ **{week['winning_votes']} votos**\n[Ver la publicación original]({self.source_link(row)})")
            if week['image_url']:
                embed.set_image(url=week['image_url'])
            if week['prize_name']:
                embed.add_field(name='🎁 Premio', value=week['prize_name'] + ('\nYa está en tu inventario. Usa `/inventario` para verlo.' if week['prize_receipt'] else '\nEl staff está pendiente de su entrega.'), inline=False)
        else:
            embed = discord.Embed(title='📸 FOTO DE LA SEMANA', color=COLOR,
                description='Esta semana no hubo fotos con votos para elegir una ganadora. La nueva ronda ya está abierta: ¡sube tu foto y participa!')
        embed.add_field(name='Semana', value=f"<t:{week['starts']}:d> — <t:{week['ends']-1}:d>", inline=False)
        embed.set_footer(text=f"LA VENGANZA RP · Foto de la semana · {week['week']}")
        return embed

    async def settle(self, channel, week):
        async with self.lock:
            rows = await self.call('entries', week['week'])
            winner_image = None
            for row in rows:
                if row['active'] and row['votes']:
                    _, image = await self.source(channel, row)
                    if image:
                        winner_image = image
                        break
            week = await self.call('freeze', week['week'])
            if not rows:
                await self.call('published', week['week'], None)
                return
            if week['winner'] and not week['filename']:
                limit = min(getattr(channel.guild, 'filesize_limit', MAX_UPLOAD), MAX_UPLOAD)
                data = None
                if winner_image.size <= limit:
                    try:
                        data = await winner_image.read()
                    except discord.HTTPException:
                        data = await winner_image.read(use_cached=True)
                    if len(data) > limit:
                        data = None
                filename = f"foto-{week['winner']}{Path(winner_image.filename).suffix.lower()}"
                await self.call('stage', week['week'], data, filename, winner_image.url)
                week = await self.call('week', week['week'])
            elif week['winner'] and week['image'] is None:
                await self.call('stage', week['week'], None, week['filename'], winner_image.url)
                week = await self.call('week', week['week'])
            message = None
            if week['publishing']:
                after = datetime.fromtimestamp(week['publishing'] - 5, timezone.utc)
                marker = f"LA VENGANZA RP · Foto de la semana · {week['week']}"
                async for previous in channel.history(after=after, oldest_first=True, limit=None):
                    if previous.author.id == self.bot.user.id and any(e.footer.text == marker for e in previous.embeds):
                        message = previous
                        break
            if not message:
                await self.call('publishing', week['week'], int(time.time()))
                embed = self.winner_embed(week)
                kwargs = {}
                if week['image'] is not None:
                    embed.set_image(url='attachment://' + week['filename'])
                    kwargs['file'] = discord.File(io.BytesIO(week['image']), filename=week['filename'])
                row = self.store.entry(week['winner']) if week['winner'] else None
                message = await channel.send(content=f"🏆 <@{row['author']}>, ¡tu foto ganó esta semana!" if row else None,
                    embed=embed, allowed_mentions=discord.AllowedMentions(users=[discord.Object(row['author'])] if row else False, roles=False, everyone=False), **kwargs)
            url = message.attachments[0].url if message.attachments else week['image_url']
            await self.call('published', week['week'], message.id, url)
            log.info('PHOTOS winner_published week=%s winner=%s votes=%s message=%s', week['week'], week['winner'], week['winning_votes'], message.id)
        previous = self.store.config('winner_pin')
        if previous and int(previous) != message.id:
            try:
                old = await channel.fetch_message(int(previous))
                await self.pin(old, False)
            except discord.HTTPException:
                log.warning('PHOTOS previous_winner_unpin_pending message=%s', previous)
        if week['winner']:
            try:
                await self.pin(message)
                self.store.config('winner_pin', message.id)
            except discord.HTTPException:
                log.warning('PHOTOS winner_pin_pending message=%s', message.id)

    async def deliver_prize(self, channel, week):
        try:
            await self.call('award', week['week'], self.bot.user.id)
        except ValueError as error:
            if week['prize_error'] != str(error):
                log.warning('PHOTOS prize_pending week=%s reason=%s', week['week'], str(error))
                await self.call('prize_error', week['week'], error)
            return
        current = await self.call('week', week['week'])
        if current['announcement']:
            message = await channel.fetch_message(current['announcement'])
            if message.author.id == self.bot.user.id:
                if message.attachments:
                    current['image_url'] = message.attachments[0].url
                await message.edit(embed=self.winner_embed(current), allowed_mentions=discord.AllowedMentions.none())

    async def ready(self):
        if not self.enabled():
            return
        async with self.ready_lock:
            if self.prepared:
                return
            channel = await self.channel()
            permissions = channel.permissions_for(channel.guild.me)
            if not all(getattr(permissions, p) for p in ('view_channel', 'read_message_history', 'send_messages', 'embed_links', 'attach_files')):
                raise ValueError('El bot necesita ver Fotos, leer el historial y enviar mensajes, imágenes y enlaces.')
            await self.panel(channel)
            await self.scan(channel)
            # Recheck existing controls after offline deletions without touching original posts.
            week = await self.call('current')
            verified = 0
            for row in await self.call('entries', week['week']):
                if row['active']:
                    async with self.lock:
                        source, image = await self.source(channel, row)
                        if source and image:
                            message = await self.ensure_control(row, source)
                            confirmed = await channel.fetch_message(message.id)
                            ids = [getattr(c, 'custom_id', None) for r in confirmed.components for c in r.children]
                            if ids != [f"lv:photo:{row['id']}:vote", f"lv:photo:{row['id']}:remove"]:
                                raise RuntimeError('Discord no confirmó los dos botones de la foto.')
                            verified += 1
            commands = await self.bot.tree.fetch_commands(guild=discord.Object(id=self.guild_id))
            command = next((c.to_dict() for c in commands if c.name == 'foto'), {})
            if not {'semana', 'premio'} <= {o['name'] for o in command.get('options', [])}:
                raise RuntimeError('Discord no confirmó los comandos de Fotos.')
            self.prepared = True
            log.info('PHOTOS controls_verified channel=%s entries=%s buttons=vote,remove commands=semana,premio self_votes=False', channel.id, verified)
            log.info('PHOTOS ready channel=%s name=%s week=%s entries=%s closes=%s timezone=America/Puerto_Rico originals_preserved=True persistent_buttons=True',
                channel.id, channel.name, week['week'], len(self.store.entries(week['week'])), week['ends'])

    async def tick(self):
        channel = await self.channel()
        await self.scan(channel)
        for week in await self.call('due'):
            try:
                await self.settle(channel, week)
            except Exception:
                log.exception('PHOTOS weekly_close_pending week=%s', week['week'])
        await self.refresh_controls(channel)
        for week in await self.call('pending_prizes'):
            try:
                await self.deliver_prize(channel, week)
            except discord.HTTPException:
                log.warning('PHOTOS prize_message_pending week=%s', week['week'])
        if self.store.config('panel_week') != week_bounds(int(time.time()))[0]:
            await self.panel(channel)

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            if self.enabled():
                try:
                    await self.ready()
                    await self.tick()
                except Exception:
                    log.exception('PHOTOS background_error; votes and photos preserved')
            await asyncio.sleep(60)

    def register(self):
        @self.group.command(name='semana', description='Ver las fotos más votadas y cuándo cierra la semana')
        async def standings(i: discord.Interaction):
            if i.guild_id != self.guild_id:
                raise ValueError('Consulta la votación desde La Venganza RP.')
            await i.response.defer(ephemeral=True)
            week = await self.call('current')
            rows = [r for r in await self.call('entries', week['week']) if r['active']]
            embed = self.panel_embed(week)
            for n, row in enumerate(rows[:5], 1):
                embed.add_field(name=f"{n}. Foto #{row['id']} · {row['votes']} votos", value=f"<@{row['author']}> · [Ver foto]({self.source_link(row)})", inline=False)
            await answer(i, None, embed=embed)

        @self.group.command(name='premio', description='Elegir o quitar el premio de la tienda para una semana')
        async def prize(i: discord.Interaction, articulo: str, semana: str = None):
            self.bot.economy.authorized(i)
            await i.response.defer(ephemeral=True)
            current = await self.call('current')
            target = semana or current['week']
            sku = None if articulo == 'ninguno' else articulo
            from economy import Confirm
            async def confirmed(click):
                self.bot.economy.authorized(click)
                async with self.lock:
                    async def snapshot():
                        row = self.store.week(target)
                        return {k: row[k] for k in ('week', 'prize_sku', 'prize_actor', 'prize_receipt')} if row else {}
                    async def change():
                        await self.call('prize', target, sku, click.user.id)
                    await self.bot.changes.tracked('PHOTO_PRIZE', 'Elegir premio de Fotos', change, request_id=str(click.id), snapshot=snapshot)
                channel = await self.channel()
                row = self.store.week(target)
                if row['state'] == 'published' and row['winner']:
                    await self.deliver_prize(channel, row)
                await self.panel(channel)
                return 'Premio guardado. Se entrega al ganador en su inventario, sin cobrarle ni equiparlo.' if sku else 'Esta semana queda sin premio de tienda.'
            item = next((p for p in self.bot.economy.store.products() if p['sku'] == sku and p['active'] and p['kind'] in SLOTS), None)
            if sku and not item:
                raise ValueError('Elige un artículo de perfil del catálogo.')
            await answer(i, f"¿Guardar **{discord.utils.escape_markdown(item['name']) if item else 'Sin premio'}** para la semana del {target}?",
                view=Confirm(i.user.id, confirmed))

        @prize.autocomplete('articulo')
        async def prize_choices(i, current):
            self.bot.economy.authorized(i)
            products = await asyncio.to_thread(self.bot.economy.store.products)
            choices = [app_commands.Choice(name='Sin premio de tienda', value='ninguno')]
            choices.extend(app_commands.Choice(name=p['name'][:100], value=p['sku']) for p in products
                if p['active'] and p['kind'] in SLOTS and current.casefold() in (p['name']+' '+p['sku']).casefold())
            return choices[:25]

        @self.group.error
        async def error(i, failure):
            error = getattr(failure, 'original', failure)
            if not isinstance(error, ValueError):
                log.error('PHOTOS command_error', exc_info=error)
            await answer(i, str(error) if isinstance(error, ValueError) else 'No pudimos completar eso ahora. Inténtalo otra vez.')
