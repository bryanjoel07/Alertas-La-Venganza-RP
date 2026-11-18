"""Owner-submitted ticket ratings, visible only to the district administration."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid

import discord
from vice_channel_style import format_name

from vice_design import BOT_ID, GUILD_ID, OWNER_ID, CYAN
from vice_readonly import WRITE_FLAGS
from vice_tickets import KINDS


log = logging.getLogger('ViceDistrict.ticket_feedback')
FEEDBACK_CUSTOM_ID = 'vice:v1:ticket:feedback'
DESTINATION_KEY = 'ticket_feedback:destination'
TOPIC = 'Valoraciones privadas de atención. Acceso exclusivo de Administración.'
TITLE = '⭐ Valoración de atención'
FOOTER = 'VIce District • Valoración privada'
PRIVACY = 'Solo Administración podrá ver tu puntuación y comentario. Una valoración por ticket.'


def close_key(ticket_id):
    return 'ticket_feedback:closed:' + str(ticket_id)


def review_key(ticket_id):
    return 'ticket_feedback:review:' + str(ticket_id)


def safe_text(value):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(str(value)))


class FeedbackView(discord.ui.View):
    def __init__(self, manager, ticket_id, owner_id):
        super().__init__(timeout=120)
        self.manager, self.ticket_id, self.owner_id = manager, int(ticket_id), int(owner_id)

    async def interaction_check(self, interaction):
        self.manager.check_interaction(interaction)
        if interaction.user.id != self.owner_id or interaction.channel_id != self.ticket_id:
            raise ValueError('Esta valoración pertenece al autor de otro ticket.')
        return True

    async def on_error(self, interaction, error, item):
        await self.manager.interaction_error(interaction, error)

    @discord.ui.select(placeholder='¿Cómo fue la atención?', min_values=1, max_values=1,
        custom_id='vice:v1:ticket:feedback:score', options=[
            discord.SelectOption(label=f'{score} ' + ('estrella' if score == 1 else 'estrellas'),
                                 value=str(score), emoji='⭐') for score in range(1, 6)])
    async def choose(self, interaction, select):
        await self.interaction_check(interaction)
        if len(select.values) != 1 or select.values[0] not in ('1', '2', '3', '4', '5'):
            raise ValueError('Elige una puntuación de 1 a 5 estrellas.')
        await interaction.response.send_modal(FeedbackModal(
            self.manager, self.ticket_id, self.owner_id, int(select.values[0])))


class FeedbackModal(discord.ui.Modal):
    def __init__(self, manager, ticket_id, owner_id, score):
        super().__init__(title=f'Valorar atención · {score}/5', timeout=300)
        self.manager, self.ticket_id, self.owner_id, self.score = manager, int(ticket_id), int(owner_id), score
        self.comment = discord.ui.TextInput(label='Comentario privado (opcional)',
            placeholder='Solo Administración verá tu comentario.',
            style=discord.TextStyle.paragraph, required=False, max_length=1000)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner_id or interaction.channel_id != self.ticket_id:
            raise ValueError('Esta valoración pertenece al autor de otro ticket.')
        await self.manager.submit(interaction, self.ticket_id, self.score, str(self.comment.value))

    async def on_error(self, interaction, error):
        await self.manager.interaction_error(interaction, error)


class TicketFeedback:
    def __init__(self, system):
        self.system = system
        self.setup_lock = asyncio.Lock()
        self.delivery_lock = asyncio.Lock()
        self.task = None
        self.retry_cursor = 0

    async def start(self):
        # The persistent entry button belongs to the existing closed-ticket panel.
        pass

    def guild(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        return guild

    def check_interaction(self, interaction):
        if (interaction.guild_id != GUILD_ID or interaction.guild is None
                or not isinstance(interaction.user, discord.Member) or interaction.user.bot
                or interaction.user.guild.id != GUILD_ID):
            raise ValueError('Usa esta valoración dentro de VIce District.')
        self.system.validate_guild(interaction.guild)
        self.guild()

    async def interaction_error(self, interaction, error):
        if interaction.guild_id != GUILD_ID:
            return
        if isinstance(error, ValueError):
            message = str(error)
        else:
            log.error('VICE_TICKET_FEEDBACK_FAILED type=%s', type(error).__name__)
            message = 'No se pudo completar la valoración. Inténtalo de nuevo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    def valid_closed(self, channel, row):
        self.guild()
        if (not row or row['state'] != 'closed' or not isinstance(channel, discord.TextChannel)
                or channel.guild.id != GUILD_ID or int(row['channel']) != channel.id
                or channel.category_id != int(self.system.store.get('category:closed') or 0)
                or channel.topic != 'VIce ticket closed owner=' + str(row['owner'])):
            raise ValueError('Solo puedes valorar un ticket cerrado y registrado del distrito.')

    @staticmethod
    def bound(record, row):
        return (record.get('guild') == GUILD_ID and str(record.get('channel')) == str(row['channel'])
                and str(record.get('owner')) == str(row['owner']))

    async def capture_close(self, channel, row, actor_id):
        """Caller holds ticket_lock; freeze who handled the case without posting a rating."""
        current = await self.system.call('ticket', channel.id)
        self.valid_closed(channel, current)
        if not row or str(row['owner']) != str(current['owner']) or str(row['channel']) != str(current['channel']):
            raise ValueError('El ticket cambió; vuelve a intentarlo.')
        previous = await self.system.call('get', close_key(channel.id))
        if previous:
            if not self.bound(previous, current):
                raise ValueError('El cierre registrado necesita revisión de Administración.')
            return previous
        assignment = await self.system.call('get', 'ticket_assignment:' + str(channel.id)) or {}
        if assignment and not self.bound(assignment, current):
            raise ValueError('La asignación registrada necesita revisión de Administración.')
        staff_id = assignment.get('staff_id')
        if staff_id is not None and (type(staff_id) is not int or staff_id <= 0):
            raise ValueError('La asignación registrada necesita revisión de Administración.')
        record = dict(guild=GUILD_ID, channel=channel.id, owner=str(current['owner']), kind=current['kind'],
            staff_id=staff_id, staff_name=assignment.get('staff_name'),
            closed_by=int(actor_id) if actor_id is not None else None,
            captured_at=datetime.now(timezone.utc).isoformat())
        await self.system.call('put', close_key(channel.id), record)
        return record

    async def owner_context(self, interaction, ticket_id, *, require_source=False):
        self.check_interaction(interaction)
        if interaction.channel_id != int(ticket_id):
            raise ValueError('Usa el botón dentro de tu ticket cerrado.')
        guild = self.guild()
        row = await self.system.call('ticket', ticket_id)
        if not row or int(row['owner']) != interaction.user.id or row['state'] != 'closed':
            raise ValueError('Solo el autor puede valorar su ticket cerrado.')
        member = await guild.fetch_member(interaction.user.id)
        if member.id != interaction.user.id or member.guild.id != GUILD_ID or member.bot:
            raise ValueError('No se pudo verificar al autor del ticket.')
        channel = await guild.fetch_channel(int(ticket_id))
        if channel.id != int(ticket_id):
            raise ValueError('No se pudo verificar el ticket.')
        self.valid_closed(channel, row)
        record = await self.system.call('get', 'ticket_delete:' + str(ticket_id)) or {}
        if (not self.bound(record, row) or record.get('state') not in (None, 'ready')
                or not record.get('panel_id')):
            raise ValueError('Usa el panel actual del ticket cerrado.')
        panel = await channel.fetch_message(int(record['panel_id']))
        keys = [getattr(child, 'custom_id', None) for action_row in panel.components
                for child in getattr(action_row, 'children', ()) if not getattr(child, 'disabled', False)]
        if (panel.id != int(record['panel_id']) or panel.author.id != BOT_ID
                or panel.channel.id != channel.id or panel.content or panel.attachments
                or len(panel.embeds) != 1 or panel.embeds[0].title != '🔒 Conversación archivada'
                or panel.embeds[0].footer.text != 'VIce District • Ticket cerrado'
                or len(keys) != 2 or set(keys) != {FEEDBACK_CUSTOM_ID, 'vice:v1:ticket:delete'}):
            raise ValueError('El panel de valoración necesita revisión de Administración.')
        if require_source and (interaction.message is None or interaction.message.id != panel.id
                or interaction.message.author.id != BOT_ID or interaction.message.channel.id != channel.id):
            raise ValueError('Usa el panel actual del ticket cerrado.')
        return channel, row, member

    async def request(self, interaction):
        self.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        async with self.system.ticket_lock:
            channel, row, unused = await self.owner_context(interaction, interaction.channel_id, require_source=True)
            if await self.system.call('get', review_key(channel.id)):
                raise ValueError('Ya enviaste una valoración para este ticket. Gracias por tu opinión.')
            await self.capture_close(channel, row, None)
        embed = discord.Embed(title='⭐ ¿Cómo fue la atención?',
            description=PRIVACY + '\nElige de 1 a 5 estrellas; después podrás añadir un comentario.', color=CYAN)
        embed.set_footer(text=FOOTER)
        view = FeedbackView(self, channel.id, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())
        return view

    async def submit(self, interaction, ticket_id, score, comment):
        self.check_interaction(interaction)
        if type(score) is not int or not 1 <= score <= 5:
            raise ValueError('Elige una puntuación de 1 a 5 estrellas.')
        if not isinstance(comment, str) or len(comment) > 1000:
            raise ValueError('El comentario puede tener hasta 1000 caracteres.')
        comment = comment.strip().replace('\x00', '')
        await interaction.response.defer(ephemeral=True)
        async with self.system.ticket_lock:
            channel, row, member = await self.owner_context(interaction, ticket_id)
            if await self.system.call('get', review_key(ticket_id)):
                raise ValueError('Ya enviaste una valoración para este ticket. Gracias por tu opinión.')
            closure = await self.capture_close(channel, row, None)
            # Confirm the private destination before accepting any user feedback.
            await self.destination()
            review = dict(closure, score=score, comment=comment, author_name=str(member.display_name)[:100],
                nonce=uuid.uuid4().hex, submitted_at=datetime.now(timezone.utc).isoformat(), state='pending')
            await self.system.call('put', review_key(ticket_id), review)
        try:
            review = await self.deliver(ticket_id)
            text = 'Gracias. Tu valoración se envió de forma privada a Administración.'
        except Exception as error:
            log.warning('VICE_TICKET_FEEDBACK_PENDING channel=%s type=%s', ticket_id, type(error).__name__)
            text = 'Tu valoración quedó guardada de forma privada. Está pendiente de entrega a Administración.'
        await interaction.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return review

    def overwrites(self, guild):
        self.system.validate_guild(guild)
        admin = guild.get_role(int(self.system.store.get('role:admin') or 0))
        if admin is None or admin.guild.id != GUILD_ID or guild.me is None or guild.me.id != BOT_ID:
            raise ValueError('No se pudo verificar el acceso de Administración a las valoraciones.')
        readonly = dict(view_channel=True, read_message_history=True, **{name: False for name in WRITE_FLAGS})
        rules = {guild.default_role: discord.PermissionOverwrite(**dict(readonly, view_channel=False,
                                                                        read_message_history=False))}
        rules[discord.Object(id=OWNER_ID, type=discord.Member)] = discord.PermissionOverwrite(**readonly)
        rules[admin] = discord.PermissionOverwrite(**readonly)
        rules[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
            send_messages=True, embed_links=True, manage_messages=True)
        return rules

    def validate_destination(self, channel, record):
        guild = self.guild()
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID
                or record.get('guild') != GUILD_ID or int(record.get('channel') or 0) != channel.id
                or channel.category_id != int(self.system.store.get('category:team') or 0)
                or channel.topic != TOPIC):
            raise ValueError('El canal privado de valoraciones necesita revisión de Administración.')
        actual = {target.id: overwrite.pair() for target, overwrite in channel.overwrites.items()}
        expected = {target.id: overwrite.pair() for target, overwrite in self.overwrites(guild).items()}
        if actual != expected:
            raise ValueError('Los permisos de las valoraciones no son privados; no se publicará tu opinión.')
        return channel

    async def destination(self):
        record = await self.system.call('get', DESTINATION_KEY) or {}
        if not record.get('channel'):
            raise ValueError('Las valoraciones aún no están listas. Inténtalo de nuevo más tarde.')
        return self.validate_destination(await self.guild().fetch_channel(int(record['channel'])), record)

    async def ensure_destination(self):
        async with self.setup_lock:
            guild = self.guild()
            record = await self.system.call('get', DESTINATION_KEY) or {}
            if record.get('channel'):
                return await self.destination()
            category = await guild.fetch_channel(int(self.system.store.get('category:team') or 0))
            if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
                raise ValueError('No se encontró la categoría privada de Administración.')
            expected = self.overwrites(guild)
            if not record:
                record = dict(guild=GUILD_ID, nonce=uuid.uuid4().hex, started_at=datetime.now(timezone.utc).isoformat())
                await self.system.call('put', DESTINATION_KEY, record)
            if record.get('guild') != GUILD_ID or not record.get('nonce'):
                raise ValueError('El registro de valoraciones necesita revisión de Administración.')
            reason = 'VIce ticket feedback ' + record['nonce']
            matches = []
            after = datetime.fromisoformat(record['started_at']) - timedelta(seconds=5)
            async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.channel_create, after=after):
                if getattr(entry.user, 'id', None) == BOT_ID and entry.reason == reason and getattr(entry.target, 'id', None):
                    candidate = await guild.fetch_channel(entry.target.id)
                    self.validate_destination(candidate, dict(record, channel=candidate.id))
                    matches.append(candidate)
            if len(matches) > 1 or (not matches and record.get('attempted_at')):
                raise ValueError('La creación del canal de valoraciones requiere revisión; no se creará otro.')
            channels = await guild.fetch_channels()
            position = min((c.position for c in channels if isinstance(c, discord.VoiceChannel)
                            and c.category_id == category.id), default=category.position + 1)
            async def snapshot():
                return dict(destination=await self.system.call('get', DESTINATION_KEY))
            async def create():
                if matches:
                    channel = matches[0]
                else:
                    record['attempted_at'] = datetime.now(timezone.utc).isoformat()
                    await self.system.call('put', DESTINATION_KEY, record)
                    channel = await guild.create_text_channel(format_name('├・⭐│valoraciones'), category=category,
                        position=position, topic=TOPIC, overwrites=expected, reason=reason)
                record['channel'] = channel.id
                self.validate_destination(channel, record)
                await self.system.call('put', DESTINATION_KEY, record)
                await self.system.call('put', 'channel:ticket_feedback', channel.id)
                return channel
            return await self.system.track('TICKET_FEEDBACK_SETUP', 'Preparar valoraciones privadas de atención',
                create, record['nonce'], snapshot=snapshot)

    def marker(self, review):
        return f'https://discord.com/channels/{GUILD_ID}/{review["channel"]}?feedback={review["nonce"]}'

    def embed(self, review):
        description = ('⭐' * review['score']) + f' **{review["score"]}/5**'
        if review['comment']:
            description += '\n\n**Comentario privado**\n' + safe_text(review['comment'])
        embed = discord.Embed(title=TITLE, description=description, color=CYAN,
            timestamp=datetime.fromisoformat(review['submitted_at']), url=self.marker(review))
        embed.add_field(name='Autor', value=f'<@{review["owner"]}>')
        embed.add_field(name='Categoría', value=KINDS.get(review['kind'], KINDS['general']))
        staff = f'<@{review["staff_id"]}>' if review.get('staff_id') else 'Sin responsable asignado'
        embed.add_field(name='Atendió', value=staff)
        embed.add_field(name='Ticket', value=f'`{review["channel"]}`', inline=False)
        return embed.set_footer(text=FOOTER)

    def matches(self, message, review):
        if (message.author.id != BOT_ID or message.content or message.attachments or message.components
                or len(message.embeds) != 1):
            return False
        expected, actual = self.embed(review).to_dict(), message.embeds[0].to_dict()
        return all(actual.get(key) == expected.get(key) for key in ('title', 'description', 'url', 'fields', 'footer'))

    async def deliver(self, ticket_id):
        # Do not hold this lock while acquiring ticket_lock: reviews are immutable once accepted.
        async with self.delivery_lock:
            row = await self.system.call('ticket', ticket_id)
            review = await self.system.call('get', review_key(ticket_id))
            if not row or not review or not self.bound(review, row):
                raise ValueError('La valoración registrada necesita revisión de Administración.')
            if review.get('state') == 'delivered':
                return review
            if review.get('state') != 'pending':
                raise ValueError('El estado de la valoración necesita revisión de Administración.')
            destination = await self.destination()
            message = None
            if review.get('message_id'):
                message = await destination.fetch_message(int(review['message_id']))
                if not self.matches(message, review):
                    raise ValueError('La entrega registrada necesita revisión de Administración.')
            elif review.get('attempted_at'):
                after = datetime.fromisoformat(review['attempted_at']) - timedelta(seconds=5)
                async for candidate in destination.history(limit=None, after=after, oldest_first=True):
                    if self.matches(candidate, review):
                        message = candidate
                        break
            async def snapshot():
                # The comment is already in private storage; keep journal metadata minimal.
                current = await self.system.call('get', review_key(ticket_id))
                return dict(guild=GUILD_ID, channel=str(ticket_id), destination=destination.id,
                            state=current.get('state'), message_id=current.get('message_id'))
            async def publish():
                nonlocal message, destination
                destination = await self.destination()
                if message is None:
                    review['attempted_at'] = datetime.now(timezone.utc).isoformat()
                    await self.system.call('put', review_key(ticket_id), review)
                    message = await destination.send(embed=self.embed(review),
                        nonce=str(int(review['nonce'][:16], 16)), allowed_mentions=discord.AllowedMentions.none())
                fresh = await destination.fetch_message(message.id)
                if not self.matches(fresh, review):
                    raise ValueError('No se pudo verificar la entrega privada de la valoración.')
                review.update(state='delivered', destination=destination.id, message_id=fresh.id,
                              delivered_at=datetime.now(timezone.utc).isoformat())
                await self.system.call('put', review_key(ticket_id), review)
            await self.system.track('TICKET_FEEDBACK_DELIVER', 'Entregar valoración privada a Administración',
                publish, review['nonce'], snapshot=snapshot)
            return review

    async def ready(self):
        destination = await self.ensure_destination()
        for row in await self.system.call('tickets'):
            if row['state'] != 'closed':
                continue
            try:
                async with self.system.ticket_lock:
                    channel = await self.guild().fetch_channel(int(row['channel']))
                    await self.capture_close(channel, row, None)
            except Exception as error:
                log.warning('VICE_TICKET_FEEDBACK_RECOVERY channel=%s type=%s', row['channel'], type(error).__name__)
        delivered = await self.retry_pending()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.worker(), name='vice-ticket-feedback-delivery')
        log.info('VICE_TICKET_FEEDBACK_READY channel=%s pending_delivered=%s', destination.id, delivered)
        return destination

    async def retry_pending(self):
        pending = []
        for row in await self.system.call('tickets'):
            review = await self.system.call('get', review_key(row['channel']))
            if review and review.get('state') != 'delivered':
                pending.append(row['channel'])
        if not pending:
            self.retry_cursor = 0
            return 0
        start = self.retry_cursor % len(pending)
        batch = (pending[start:] + pending[:start])[:20]
        self.retry_cursor = (start + len(batch)) % len(pending)
        delivered = 0
        for ticket_id in batch:
            try:
                await self.deliver(ticket_id)
                delivered += 1
            except Exception as error:
                log.warning('VICE_TICKET_FEEDBACK_PENDING channel=%s type=%s', ticket_id, type(error).__name__)
        return delivered

    async def worker(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self.retry_pending()
            except Exception as error:
                log.warning('VICE_TICKET_FEEDBACK_RETRY type=%s', type(error).__name__)

    async def close(self):
        if self.task:
            task, self.task = self.task, None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
