"""Staff feedback in the existing channel, with explicit publication consent."""
import asyncio
from datetime import datetime, timezone
import json
import logging
import re
import time
import unicodedata

import discord
from discord import app_commands

from feedback_store import FeedbackStore
from feedback_ui import (RED, NONE, controls, reply, EntryChoice, Picker, FeedbackForm, FeedbackAction,
                         Mine, Withdraw, StaffReply)
from obscenities import WORDS, PATTERNS
from photo_members import MemberDirectory, DirectoryUnavailable
from tickets import is_staff_role
from feedback_access import enable_citizen_panel

CHANNEL_ID = 1539014594348064939
PANEL_MARKER = 'La Venganza RP · Feedback del staff · Panel'
log = logging.getLogger('LaVenganzaRP.feedback')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


LANGUAGE = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(w) for w in sorted({normalized(w) for w in WORDS}, key=len, reverse=True)) + r')(?!\w)')


def clean(text):
    text = text.strip()
    if LANGUAGE.search(normalized(text)) or any(re.search(pattern, text) for pattern in PATTERNS):
        raise ValueError('Cuéntanos qué pasó sin insultos, bro. Puedes dejar una mala valoración y explicar por qué.')
    return text


def is_staff(member):
    return not member.bot and (member.guild_permissions.administrator or any(is_staff_role(r) for r in member.roles))


def stars(score):
    return '⭐' * score + '✩' * (5-score)


class FeedbackSystem:
    def __init__(self, bot, path, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.store = FeedbackStore(path)
        self.directory = MemberDirectory(bot, guild_id)
        self.install_lock, self.io_lock = asyncio.Lock(), asyncio.Lock()
        self.task = None
        self.prepared = False
        self.signature = None
        self.group = app_commands.Group(name='feedback', description='Opiniones sobre la atención del staff')
        self.register()

    async def call(self, name, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, name), *args, **kwargs)

    async def start(self):
        if self.task is not None and not self.task.done():return
        await self.call('initialize')
        self.bot.add_dynamic_items(FeedbackAction)
        self.task = asyncio.create_task(self.loop(), name='staff-feedback')

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.ready()
                for row in await self.call('removals'):
                    async with self.io_lock:
                        await self.remove_post(row)
                for row in await self.call('rows', pending=True, limit=10):
                    await self.publish(row['id'])
            except Exception:
                log.exception('FEEDBACK retry_pending')
            await asyncio.sleep(300)

    async def member(self, i, admin=False):
        if i.guild_id not in (None, self.guild_id):
            raise ValueError('Este sistema es de La Venganza RP.')
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise ValueError('El bot se está conectando. Inténtalo en un momento.')
        try:
            member = await guild.fetch_member(i.user.id)
        except discord.NotFound:
            raise ValueError('Tienes que estar en La Venganza RP para dejar feedback.') from None
        if member.bot:
            raise ValueError('El feedback es para los jugadores.')
        if admin and not member.guild_permissions.administrator:
            raise ValueError('Esto solo lo puede ver administración.')
        return member

    async def channel(self):
        channel = await self.bot.fetch_channel(CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
            raise ValueError('El canal de Feedback no corresponde a La Venganza RP.')
        perms = channel.permissions_for(channel.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links and perms.read_message_history):
            raise ValueError('El bot necesita ver, leer y enviar mensajes con embeds en Feedback.')
        return channel

    def invite(self, rid):
        return controls('ticket', rid=rid)

    async def handle(self, i, action, rid):
        if action == 'start':
            await i.response.defer(ephemeral=True)
            await self.member(i)
            await reply(i, '¿Cómo te atendieron, bro? Elige por dónde recibiste la ayuda.', view=EntryChoice(self, i.user.id))
        elif action == 'mine':
            await self.mine(i)
        elif action == 'stats':
            await self.stats(i)
        elif action == 'ticket':
            await self.ticket_form(i, rid)
        elif action == 'respond':
            await self.reply_form(i, rid)

    async def ticket_picker(self, i):
        await i.response.defer(ephemeral=True)
        await self.member(i)
        rows = await self.call('tickets', i.user.id)
        if not rows:
            return await reply(i, 'No tienes tickets cerrados pendientes de valorar. Si te ayudaron por voz, elige «Me atendieron fuera de tickets».')
        view = Picker(self, i.user.id, rows, 'ticket')
        await reply(i, view.text(), view=view)

    async def staff_picker(self, i):
        await i.response.defer(ephemeral=True, thinking=True)
        member = await self.member(i)
        try:
            members = await self.directory.load(member.guild, force=True)
        except DirectoryUnavailable:
            raise ValueError('No pude cargar la lista completa del staff ahora. Inténtalo otra vez en un momento.') from None
        staff = [m for m in members if is_staff(m) and m.id != member.id]
        if not staff:
            return await reply(i, 'No encontré miembros del staff disponibles para elegir. Inténtalo otra vez en un momento.')
        view = Picker(self, member.id, staff, 'staff')
        await reply(i, view.text(), view=view)

    async def ticket_form(self, i, rid):
        await self.member(i)
        row = await self.call('ticket', rid, i.user.id)
        await i.response.send_modal(FeedbackForm(self, ticket=rid, reserved=row['department'] == 'staff'))

    async def outside_form(self, i, staff_id):
        member = await self.member(i)
        try:
            staff = await member.guild.fetch_member(staff_id)
        except discord.NotFound:
            raise ValueError('Esa persona ya no está en el servidor.') from None
        if staff.id == member.id or not is_staff(staff):
            raise ValueError('Elige a alguien del staff que te haya atendido.')
        await i.response.send_modal(FeedbackForm(self, staff=staff.id, visibility='public'))

    async def submit(self, i, score, comment, visibility, *, ticket=None, staff=None, topic=''):
        member = await self.member(i)
        comment, topic = clean(comment), clean(topic)
        if ticket is None:
            try:
                target = await member.guild.fetch_member(staff)
            except discord.NotFound:
                raise ValueError('Esa persona ya no está en el servidor.') from None
            if target.id == member.id or not is_staff(target):
                raise ValueError('Esa persona ya no forma parte del staff o elegiste tu propia cuenta.')
        rid = await self.call('save', member.id, score, comment, visibility, ticket=ticket, staff=staff, topic=topic)
        row = await self.call('get', rid)
        published = False
        if row['visibility'] == 'public':
            try:
                await self.publish(rid)
                published = True
            except Exception:
                log.exception('FEEDBACK publication_pending id=%s', rid)
        await reply(i, 'Gracias por contar cómo te fue, bro. ' + (
            f'Tu opinión ya está en <#{CHANNEL_ID}>.' if published else
            'Quedó guardada; la publicación está pendiente y se reintentará sola.' if row['visibility'] == 'public' else
            'Solo la verán tú y administración.'))
        await self.refresh_safely()

    async def mine(self, i, page=0):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        await self.member(i)
        rows = await self.call('rows', owner=i.user.id, limit=8, offset=max(0, page)*8)
        if not rows:
            return await reply(i, 'No hay opiniones en esta página. Puedes empezar con «Dejar feedback».')
        lines = [f"**#{r['id']} · {stars(r['score'])}** · <t:{r['created']}:d>\n" + ('Retirada' if r['hidden_at'] else 'Pública' if r['visibility']=='public' else 'Solo administración') +
                 (' · Ticket verificado' if r['ticket'] else ' · Fuera de tickets') for r in rows]
        await reply(i, embed=discord.Embed(title='📋 Tus opiniones', description='\n\n'.join(lines), color=RED), view=Mine(self, i.user.id, rows, page))

    async def detail(self, i, rid):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        member = await self.member(i)
        row = await self.call('get', rid)
        if not row or (member.id != row['owner'] and not member.guild_permissions.administrator and (row['visibility'] != 'public' or row['hidden_at'])):
            raise ValueError('Esa opinión es privada o no está disponible.')
        embed = await self.review_embed(row)
        if row['ticket'] and (member.id == row['owner'] or member.guild_permissions.administrator):
            embed.add_field(name='Tu caso' if member.id == row['owner'] else 'Caso relacionado', value=f"Ticket #{row['ticket']}", inline=False)
        view = Withdraw(self, member.id, rid) if row['owner'] == member.id and not row['hidden_at'] else None
        await reply(i, 'Si eliges «Retirar opinión», dejará de aparecer en el canal y en los resultados.' if view else None, embed=embed, view=view)

    async def stats(self, i, *, admin=False, staff=None, days=None, page=1):
        if not i.response.is_done():
            await i.response.defer(ephemeral=True)
        await self.member(i, admin=admin)
        data = await self.call('summary', public=not admin, staff=staff, days=days)
        embed = self.results_embed(data)
        if admin and not data['total']:
            embed.description = 'No hay opiniones con este filtro.'
        embed.title = '📊 Atención del staff' + (' · Administración' if admin else '')
        if staff:
            embed.description = f'Opiniones sobre <@{staff}>.\n' + (embed.description or '')
        if admin:
            for row in await self.call('rows', staff=staff, days=days, limit=5, offset=(page-1)*5):
                embed.add_field(name=f"#{row['id']} · {stars(row['score'])} · "+('Pública' if row['visibility']=='public' else 'Privada'),
                    value=f"<@{row['owner']}> → "+(f"<@{row['staff']}>" if row['staff'] else 'Equipo de staff')+
                    f" · <t:{row['created']}:d>\n"+discord.utils.escape_markdown(row['comment'][:140] or 'Sin comentario.')+f"\n`/feedback ver numero:{row['id']}`", inline=False)
        embed.set_footer(text=('Incluye opiniones privadas. Solo administración.' if admin else 'Solo opiniones públicas; las privadas no entran en este resumen.') + (f' · Últimos {days} días' if days else ' · Todo el historial') + (f' · Página {page}' if admin else ''))
        await reply(i, embed=embed)

    @staticmethod
    def results_embed(data):
        embed = discord.Embed(color=RED, description=(f"**{data['average']:.1f}/5** · {data['total']} opiniones" if data['total'] else 'Todavía no hay opiniones públicas. La primera puede ser la tuya.'))
        if data['total']:
            embed.add_field(name='Así les fue a los jugadores', value='\n'.join(
                f"{'⭐'*n} **{data['counts'].get(n,0)}**" for n in range(5,0,-1)), inline=False)
        return embed

    async def panel_embed(self):
        data = await self.call('summary')
        embed = discord.Embed(title='✨ Tu opinión cuenta', color=RED,
            description='¿Te atendió alguien del staff? Cuéntanos cómo te fue, bro. Lo bueno se reconoce y lo que falle se mejora.\n\n'
            '⭐ Elige de **1 a 5 estrellas** y deja un comentario si quieres.\n'
            '🎫 Puedes valorar un **ticket cerrado** o la ayuda que recibiste **por voz o fuera de tickets**.\n'
            '🔒 Tú eliges: **publicarlo aquí** o dejarlo **solo para administración**.\n\n'
            'Los reportes contra staff siempre quedan privados. Habla de la atención sin compartir datos ni pruebas de tu caso.')
        embed.add_field(name='Cómo va la atención', value=f"**{data['average']:.1f}/5** · {data['total']} opiniones públicas" if data['total'] else 'Todavía no hay opiniones públicas.', inline=False)
        embed.add_field(name='Para que cuente de verdad', value='Una opinión por ticket. Fuera de tickets, una cada 24 horas. Solo sobre atención que recibiste; nadie puede valorarse a sí mismo.', inline=False)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=PANEL_MARKER)
        return embed

    async def ready(self, *, force=False):
        async with self.install_lock:
            checked=getattr(self,'panel_checked',None)
            if not force and checked is not None and time.monotonic()-checked<60:return
            await enable_citizen_panel(self)
            channel = await self.channel()
            embed = await self.panel_embed()
            signature = json.dumps(embed.to_dict(), sort_keys=True)
            saved = await self.call('config', 'panel_message')
            message = None
            if saved:
                try:
                    message = await channel.fetch_message(int(saved))
                except discord.NotFound:
                    pass
            if message and message.author.id != self.bot.user.id:
                raise ValueError('El mensaje guardado no pertenece a este bot.')
            if message and not any(e.footer.text == PANEL_MARKER for e in message.embeds):
                raise ValueError('El mensaje guardado no es un panel de Feedback.')
            if not message:
                async for candidate in channel.history(limit=100):
                    if candidate.author.id == self.bot.user.id and any(e.footer.text == PANEL_MARKER for e in candidate.embeds):
                        message = candidate
                        break
            if not message or signature != self.signature:
                async def snapshot():
                    return dict(channel_id=channel.id, name=channel.name, panel_message=await self.call('config', 'panel_message'),
                        original_message=message.id if message else None,
                        message=dict(content=message.content,embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components]) if message else None,
                        overwrites=[dict(id=o.id,type=o.type,allow=str(o.allow),deny=str(o.deny)) for o in channel._overwrites])

                async def install():
                    nonlocal message
                    if message:
                        message = await message.edit(embed=embed, view=controls('start','mine','stats'), allowed_mentions=NONE)
                    else:
                        message = await channel.send(embed=embed, view=controls('start','mine','stats'), allowed_mentions=NONE)
                    await self.call('config', 'panel_message', message.id)
                await self.bot.changes.tracked('FEEDBACK_PANEL', 'Instalar o actualizar panel de Feedback', install,
                    request_id=f"{message.id if message else saved or 'new'}:{hash_signature(signature)}", snapshot=snapshot)
                self.signature = signature
            verified = await channel.fetch_message(message.id)
            ids = [getattr(c,'custom_id',None) for row in verified.components for c in row.children]
            if ids != ['lvfb:start:0','lvfb:mine:0','lvfb:stats:0']:
                raise RuntimeError('Discord no confirmó los controles de Feedback.')
            if not self.prepared:
                members = await self.directory.load(channel.guild, force=True)
                roster = [m for m in members if is_staff(m)]
                standard, reserved = FeedbackForm(self, staff=1), FeedbackForm(self, ticket=1, reserved=True)
                if len(standard.to_dict()['components']) != 4 or len(reserved.visibility.options) != 1 or len(standard.stars.options) != 5:
                    raise RuntimeError('No se confirmaron los formularios de Feedback.')
                log.info('FEEDBACK directory_verified members=%s staff=%s offline_included=True source=%s forms=stars_comment_visibility_context reserved_private=True',
                         len(members), len(roster), self.directory.source)
            self.prepared = True
            self.panel_checked=time.monotonic()
            log.info('FEEDBACK ready channel=%s name=%s panel=%s staff_only=True tickets=True outside=True privacy_choice=True existing_ratings_private=True controls=%s',
                     channel.id, channel.name, verified.id, ids)

    async def refresh_safely(self):
        try:
            await self.ready(force=True)
        except Exception:
            log.exception('FEEDBACK panel_refresh_pending')

    async def review_embed(self, row):
        embed = discord.Embed(title=f"{stars(row['score'])} · Atención del staff", color=RED,
            description=discord.utils.escape_markdown(row['comment']) if row['comment'] else 'El jugador dejó sus estrellas sin comentario.',
            timestamp=datetime.fromtimestamp(row['created'], timezone.utc))
        guild = self.bot.get_guild(self.guild_id)
        try:
            member = await guild.fetch_member(row['owner'])
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        except discord.NotFound:
            embed.set_author(name=f"Jugador · {row['owner']}")
        embed.add_field(name='Atendió', value=f"<@{row['staff']}>" if row['staff'] else 'Equipo de staff', inline=True)
        embed.add_field(name='Atención recibida', value='🎫 Ticket verificado' if row['ticket'] else '🎙️ Fuera de tickets', inline=True)
        if not row['ticket']:
            embed.add_field(name='¿Con qué le ayudaron?', value=discord.utils.escape_markdown(row['topic']), inline=False)
        if row['response']:
            embed.add_field(name='💬 Respuesta del staff', value=f"<@{row['response_by']}>\n{discord.utils.escape_markdown(row['response'])}", inline=False)
        embed.set_footer(text=f"La Venganza RP · Feedback #{row['id']}" + (' · Retirado' if row['hidden_at'] else ' · Solo administración' if row['visibility']=='private' else ''))
        return embed

    async def publish(self, rid):
        async with self.io_lock:
            row = await self.call('get', rid)
            if not row or row['visibility'] != 'public' or row['hidden_at']:
                return
            channel = await self.channel()
            message = None
            if row['message']:
                try:
                    message = await channel.fetch_message(row['message'])
                except discord.NotFound:
                    await self.call('deleted', row['message'])
                    return
                if message.author.id != self.bot.user.id:
                    raise ValueError('Esta publicación no pertenece al bot.')
            elif row['publish_state'] == 'sending':
                marker = f"La Venganza RP · Feedback #{rid}"
                async for candidate in channel.history(limit=None, after=datetime.fromtimestamp(row['created']-120,timezone.utc)):
                    if candidate.author.id == self.bot.user.id and any(e.footer.text == marker for e in candidate.embeds):
                        message = candidate
                        break
            embed = await self.review_embed(row)
            await self.call('publication', rid, 'sending')
            view = controls('respond', rid=rid) if not row['response'] else None
            if message:
                await message.edit(embed=embed, view=view, allowed_mentions=NONE)
            else:
                message = await channel.send(embed=embed, view=view, allowed_mentions=NONE)
            await self.call('publication', rid, 'posted', message.id)
            log.info('FEEDBACK published id=%s message=%s stars=%s source=%s', rid, message.id, row['score'], row['source'])

    async def reply_form(self, i, rid):
        member = await self.member(i)
        row = await self.call('get', rid)
        if not row or row['hidden_at'] or row['visibility'] != 'public' or row['owner'] == member.id or not (member.guild_permissions.administrator or (row['staff'] == member.id and is_staff(member))):
            raise ValueError('Solo quien atendió al jugador o administración puede responder esta opinión pública.')
        if row['response']:
            raise ValueError('Esta opinión ya tiene una respuesta.')
        await i.response.send_modal(StaffReply(self, rid))

    async def respond(self, i, rid, text):
        member = await self.member(i)
        row = await self.call('get', rid)
        if not row or not (member.guild_permissions.administrator or (row['staff'] == member.id and is_staff(member))):
            raise ValueError('Ya no tienes acceso para responder esta opinión.')
        await self.call('respond', rid, member.id, clean(text), admin=member.guild_permissions.administrator)
        try:
            await self.publish(rid)
        except Exception:
            log.exception('FEEDBACK reply_publication_pending id=%s', rid)
        await reply(i, 'Tu respuesta quedó guardada, bro.')

    async def withdraw(self, i, rid, reason, admin=False):
        await i.response.defer(ephemeral=True)
        member = await self.member(i, admin=admin)
        async with self.io_lock:
            async def snapshot():
                return dict(feedback=await self.call('get', rid))

            async def remove():
                await self.call('hide', rid, member.id, reason, admin=admin)
                row = await self.call('get', rid)
                await self.remove_post(row)
            try:
                await self.bot.changes.tracked('FEEDBACK_WITHDRAW', 'Retirar una opinión de Feedback', remove,
                    request_id=f'{rid}:{i.id}', snapshot=snapshot)
                pending = False
            except (discord.HTTPException, TimeoutError):
                log.exception('FEEDBACK removal_pending id=%s', rid)
                pending = True
        await reply(i, 'La opinión dejó de contar. Estoy reintentando quitarla del canal.' if pending else 'La opinión ya no aparece en el canal ni en los resultados.')
        await self.refresh_safely()

    async def remove_post(self, row):
        if not row['hidden_at']:
            raise ValueError('Esta opinión todavía no fue retirada.')
        if row['message']:
            channel = await self.channel()
            try:
                message = await channel.fetch_message(row['message'])
                if message.author.id != self.bot.user.id:
                    raise ValueError('El mensaje no pertenece a este bot.')
                await message.delete()
            except discord.NotFound:
                pass
        await self.call('publication', row['id'], 'withdrawn')

    async def deleted(self, guild_id, channel_id, message_ids):
        if guild_id != self.guild_id or channel_id != CHANNEL_ID:
            return
        for message in message_ids:
            await self.call('deleted', message)

    def register(self):
        @self.group.command(name='panel', description='Revisar el panel de Feedback')
        @app_commands.default_permissions(administrator=True)
        async def panel(i: discord.Interaction):
            await i.response.defer(ephemeral=True)
            await self.member(i, admin=True)
            await self.ready()
            await reply(i, f'El panel está listo en <#{CHANNEL_ID}>.')

        @self.group.command(name='resumen', description='Ver resultados de atención del staff, incluidas opiniones privadas')
        @app_commands.default_permissions(administrator=True)
        async def summary(i: discord.Interaction, persona: discord.User = None, dias: app_commands.Range[int,0,365] = 30, pagina: app_commands.Range[int,1,100000] = 1):
            await self.stats(i, admin=True, staff=persona.id if persona else None, days=dias or None, page=pagina)

        @self.group.command(name='ver', description='Consultar una opinión a la que tengas acceso')
        async def detail(i: discord.Interaction, numero: app_commands.Range[int,1,1000000000]):
            await self.detail(i, numero)

        @self.group.command(name='retirar', description='Retirar una opinión indicando el motivo; queda guardado quién lo hizo')
        @app_commands.default_permissions(administrator=True)
        async def remove(i: discord.Interaction, numero: app_commands.Range[int,1,1000000000], motivo: str):
            await i.response.defer(ephemeral=True)
            await self.member(i, admin=True)
            if not motivo.strip() or len(motivo) > 1000:
                raise ValueError('Escribe un motivo de hasta 1000 letras.')
            row = await self.call('get', numero)
            if not row or row['hidden_at']:
                raise ValueError('Esa opinión no existe o ya fue retirada.')
            await reply(i, f'¿Retirar la opinión #{numero}?\nMotivo: {discord.utils.escape_markdown(motivo)}',
                        embed=await self.review_embed(row), view=Withdraw(self, i.user.id, numero, motivo, True))

        @self.group.error
        async def error(i, exc):
            from feedback_ui import failed
            await failed(i, getattr(exc, 'original', exc))


def hash_signature(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:20]
