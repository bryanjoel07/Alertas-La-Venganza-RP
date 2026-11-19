"""Private ticket categories and durable, staff-only responsibility assignments."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid

import discord

from vice_design import BOT_ID, CYAN, GUILD_ID, OWNER_ID


log = logging.getLogger('ViceDistrict.tickets')
VERSION = 'vice-ticket-center-v1'
STARTER_TITLE = '🎫 Te escuchamos'
FOOTER = 'VIce District • Ticket abierto'
LEGACY_FOOTER = 'GTA VI Latino • Puerto Rico + Latinoamérica • Fans no oficiales'
CLAIM_ID = 'vice:v1:ticket:claim'
RELEASE_ID = 'vice:v1:ticket:release'
CLOSE_ID = 'vice:v2:ticket:close'
LEGACY_CLOSE_ID = 'vice:v1:ticket:close'
NOTICE_TITLE = '🙋 Tu ticket ya tiene responsable'
NOTICE_FOOTER = 'VIce District • Seguimiento de ayuda'
NOTICE_RETRY_SECONDS = 60
NOTICE_RETRY_LIMIT = 20
KINDS = {
    'general': 'Ayuda general',
    'report': 'Reportar a un jugador',
    'appeal': 'Apelación',
    'technical': 'Problema técnico',
}
EMOJIS = {'general': '💬', 'report': '🛡️', 'appeal': '⚖️', 'technical': '🛠️'}
PROMPTS = {
    'general': 'Cuéntanos en qué podemos ayudarte.',
    'report': 'Explica lo ocurrido e incluye los datos y pruebas que tengas.',
    'appeal': 'Indica la medida que quieres revisar y explica tu caso.',
    'technical': 'Describe el problema, cuándo ocurre y qué has probado.',
}


def assignment_key(channel_id):
    return 'ticket_assignment:' + str(channel_id)


def panel_key(channel_id):
    return 'ticket_open_panel:' + str(channel_id)


def notice_key(channel_id, revision):
    return f'ticket_claim_notice:{channel_id}:{revision}'


def controls(message):
    return [(getattr(child, 'custom_id', None), bool(getattr(child, 'disabled', False)))
            for row in message.components for child in getattr(row, 'children', ())]


def message_snapshot(message):
    return dict(id=message.id, author=message.author.id, content=message.content,
                embeds=[embed.to_dict() for embed in message.embeds],
                controls=[dict(custom_id=key, disabled=disabled) for key, disabled in controls(message)])


class TicketView(discord.ui.View):
    def __init__(self, manager, *, timeout=None):
        super().__init__(timeout=timeout)
        self.manager = manager

    async def on_error(self, interaction, error, item):
        if interaction.guild_id != GUILD_ID:
            return
        if isinstance(error, ValueError):
            text = str(error)
        else:
            log.error('VICE_TICKET_CENTER_FAILED type=%s', type(error).__name__, exc_info=error)
            text = 'No se pudo completar la acción. Inténtalo de nuevo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(text[:1200], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class TicketCategories(TicketView):
    def __init__(self, manager, actor_id):
        super().__init__(manager, timeout=120)
        self.actor_id = int(actor_id)

    async def interaction_check(self, interaction):
        self.manager.check_interaction(interaction)
        if interaction.user.id != self.actor_id:
            raise ValueError('Abre tu propia selección desde el panel de ayuda.')
        return True

    @discord.ui.select(placeholder='¿En qué podemos ayudarte?', min_values=1, max_values=1,
        custom_id='vice:v1:ticket:category',
        options=[discord.SelectOption(label=label, value=key, emoji=EMOJIS[key])
                 for key, label in KINDS.items()])
    async def choose(self, interaction, select):
        await self.interaction_check(interaction)
        kind = self.manager.validate_kind(select.values[0] if len(select.values) == 1 else None)
        await interaction.response.defer(ephemeral=True)
        channel = await self.manager.system.open_ticket(interaction, kind=kind)
        await interaction.edit_original_response(content=f'Tu ticket está listo: <#{channel.id}>.',
            embed=None, view=None, allowed_mentions=discord.AllowedMentions.none())
        self.stop()


class OpenTicketPanel(TicketView):
    def __init__(self, manager, *, assigned=False):
        super().__init__(manager)
        self.attend.disabled = bool(assigned)
        self.release_ticket.disabled = not bool(assigned)

    @discord.ui.button(label='Atender', emoji='🙋', style=discord.ButtonStyle.primary, custom_id=CLAIM_ID)
    async def attend(self, interaction, button):
        await self.manager.claim(interaction)

    @discord.ui.button(label='Liberar', emoji='↩️', style=discord.ButtonStyle.secondary, custom_id=RELEASE_ID)
    async def release_ticket(self, interaction, button):
        await self.manager.release(interaction)

    @discord.ui.button(label='Cerrar y archivar', emoji='🔒', style=discord.ButtonStyle.secondary,
                       custom_id=CLOSE_ID)
    async def close_ticket(self, interaction, button):
        self.manager.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        await self.manager.system.close_ticket(interaction)
        await interaction.followup.send('Ticket cerrado; su historial quedó archivado.', ephemeral=True,
                                       allowed_mentions=discord.AllowedMentions.none())


class TicketCenter:
    def __init__(self, system):
        self.system = system
        self.registered = False
        self.notice_task = None
        self.notice_cursor = 0

    async def start(self):
        if not self.registered:
            self.system.bot.add_view(OpenTicketPanel(self))
            self.registered = True

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
            raise ValueError('Usa este panel dentro de VIce District.')
        self.system.validate_guild(interaction.guild)
        self.guild()

    @staticmethod
    def validate_kind(kind):
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError('Elige una de las categorías de ayuda disponibles.')
        return kind

    def row_kind(self, row):
        return self.validate_kind('general' if row['kind'] == 'comunidad' else row['kind'])

    async def show_categories(self, interaction):
        self.check_interaction(interaction)
        view = TicketCategories(self, interaction.user.id)
        embed = discord.Embed(title='🎫 ¿Cómo podemos ayudarte?',
            description='Elige el motivo para abrir una conversación privada con el equipo.', color=CYAN)
        embed.set_footer(text='VIce District • Centro de ayuda')
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(embed=embed, view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        return view

    def valid_channel(self, channel, row, *, closed=False):
        self.guild()
        self.system.validate_guild(getattr(channel, 'guild', None))
        category = self.system.store.get('category:closed' if closed else 'category:help')
        state = 'closed' if closed else 'open'
        topic = 'VIce ticket closed owner=' if closed else 'VIce ticket owner='
        if (not row or row['state'] != state or not isinstance(channel, discord.TextChannel)
                or int(row['channel']) != channel.id or not category or channel.category_id != int(category)
                or channel.topic != topic + str(row['owner'])):
            raise ValueError('Este ticket no está disponible para esta acción.')
        return row

    @staticmethod
    def bound(record, row):
        return (record.get('guild') == GUILD_ID and str(record.get('channel')) == str(row['channel'])
                and str(record.get('owner')) == str(row['owner']))

    async def assignment(self, row):
        value = await self.system.call('get', assignment_key(row['channel'])) or {}
        if value and (not self.bound(value, row)
                      or value.get('kind') != self.row_kind(row)
                      or (value.get('staff_id') is not None and
                          (not isinstance(value['staff_id'], int) or value['staff_id'] <= 0))):
            raise ValueError('La asignación de este ticket necesita revisión del equipo.')
        return dict(value)

    async def panel_record(self, row):
        value = await self.system.call('get', panel_key(row['channel'])) or {}
        if value and (not self.bound(value, row) or not value.get('panel_id')):
            raise ValueError('El panel de este ticket necesita revisión del equipo.')
        return dict(value)

    @staticmethod
    def starter_matches(message, *, archived=False):
        if (message.author.id != BOT_ID or message.content or message.attachments
                or len(message.embeds) != 1 or message.embeds[0].title != STARTER_TITLE):
            return False
        keys = [key for key, _ in controls(message)]
        footer = message.embeds[0].footer.text
        if footer == LEGACY_FOOTER:
            return keys == [LEGACY_CLOSE_ID]
        if footer == FOOTER:
            return (len(keys) == 3 and set(keys) == {CLAIM_ID, RELEASE_ID, CLOSE_ID}) or (archived and not keys)
        return False

    def starter_embed(self, row, assignment):
        kind = self.row_kind(row)
        embed = discord.Embed(title=STARTER_TITLE, color=CYAN,
            description=f'<@{row["owner"]}>, {PROMPTS[kind]}\nEsta conversación es privada con el equipo.')
        embed.add_field(name='Categoría', value=f'{EMOJIS[kind]} {KINDS[kind]}', inline=True)
        responsible = f'<@{assignment["staff_id"]}>' if assignment.get('staff_id') else 'Sin asignar'
        embed.add_field(name='Responsable', value=responsible, inline=True)
        return embed.set_footer(text=FOOTER)

    async def ensure_open_panel(self, channel, row=None):
        """Caller holds ticket_lock; recover or update the exact bot starter in place."""
        self.guild()
        self.system.validate_guild(getattr(channel, 'guild', None))
        current = await self.system.call('ticket', channel.id)
        self.valid_channel(channel, current)
        if row and (str(row['channel']) != str(current['channel']) or str(row['owner']) != str(current['owner'])):
            raise ValueError('El ticket cambió; vuelve a intentarlo.')
        assignment = await self.assignment(current)
        record = await self.panel_record(current)
        panel = None
        if record.get('panel_id'):
            try:
                panel = await channel.fetch_message(int(record['panel_id']))
            except discord.NotFound as error:
                if error.code != 10008:
                    raise
            else:
                if not self.starter_matches(panel, archived=True):
                    raise ValueError('El panel registrado necesita revisión del equipo.')
        if panel is None:
            async for candidate in channel.history(limit=None, oldest_first=True):
                if self.starter_matches(candidate, archived=True):
                    panel = candidate
                    break
        embed = self.starter_embed(current, assignment)
        view = OpenTicketPanel(self, assigned=assignment.get('staff_id') is not None)
        desired_controls = [(item.custom_id, item.disabled) for item in view.children]
        needs_edit = panel is not None and (panel.embeds[0].to_dict() != embed.to_dict()
                                            or controls(panel) != desired_controls)
        if (panel is not None and not needs_edit and record.get('panel_id') == panel.id
                and record.get('version') == VERSION):
            return panel
        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, category=channel.category_id,
                topic=channel.topic, ticket=await self.system.call('ticket', channel.id),
                assignment=await self.system.call('get', assignment_key(channel.id)),
                panel_record=await self.system.call('get', panel_key(channel.id)),
                panel=message_snapshot(panel) if panel else None)
        async def apply():
            nonlocal panel
            if panel is None:
                panel = await channel.send(embed=embed, view=view, nonce=f'vto{channel.id}',
                                           allowed_mentions=discord.AllowedMentions.none())
            elif needs_edit:
                panel = await panel.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            await self.system.call('put', panel_key(channel.id), dict(guild=GUILD_ID, channel=channel.id,
                owner=str(current['owner']), panel_id=panel.id, version=VERSION))
            return panel
        return await self.system.track('TICKET_OPEN_PANEL', 'Actualizar panel privado de ayuda', apply,
            f'{VERSION}:{channel.id}:{uuid.uuid4().hex}', snapshot=snapshot)

    async def fresh_staff(self, guild, actor_id):
        member = await guild.fetch_member(int(actor_id))
        if (member.id != int(actor_id) or member.guild.id != GUILD_ID or member.bot
                or not self.system.is_staff(member)):
            raise ValueError('Solo el equipo puede atender o liberar tickets.')
        self.system.validate_guild(member.guild)
        return member

    def is_admin(self, member):
        return (member.id == OWNER_ID or member.guild_permissions.administrator
                or any(role.id == self.system.store.get('role:admin') for role in member.roles))

    async def action_context(self, interaction):
        reopening = await self.system.call('get', 'ticket_reopen:' + str(interaction.channel_id))
        if reopening and reopening.get('state') == 'pending':
            raise ValueError('Espera a que termine de verificarse la reapertura.')
        guild = self.guild()
        member = await self.fresh_staff(guild, interaction.user.id)
        channel = await guild.fetch_channel(interaction.channel_id)
        if channel.id != interaction.channel_id:
            raise ValueError('Usa el panel actual de este ticket.')
        row = await self.system.call('ticket', channel.id)
        self.valid_channel(channel, row)
        record = await self.panel_record(row)
        source = interaction.message
        if (source is None or not record or source.id != record['panel_id']
                or source.author.id != BOT_ID or source.channel.id != channel.id):
            raise ValueError('Usa el panel actual de este ticket.')
        panel = await channel.fetch_message(int(record['panel_id']))
        if (panel.id != int(record['panel_id']) or panel.channel.id != channel.id
                or not self.starter_matches(panel) or panel.embeds[0].footer.text != FOOTER):
            raise ValueError('El panel registrado necesita revisión del equipo.')
        return member, channel, row, panel, await self.assignment(row)

    async def update_assignment(self, interaction, *, release):
        self.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        async with self.system.ticket_lock:
            member, channel, row, panel, assignment = await self.action_context(interaction)
            current_id = assignment.get('staff_id')
            if release:
                if current_id is not None and current_id != member.id and not self.is_admin(member):
                    raise ValueError('Solo la persona responsable o un administrador puede liberar este ticket.')
                changed = current_id is not None
                updated = dict(assignment, staff_id=None, staff_name=None,
                    released_at=datetime.now(timezone.utc).isoformat(), released_by=member.id)
                response = 'El ticket quedó sin responsable y está disponible para el equipo.'
            else:
                if current_id is not None and current_id != member.id:
                    raise ValueError('Este ticket ya está siendo atendido por otra persona del equipo.')
                changed = current_id != member.id
                updated = dict(assignment, staff_id=member.id, staff_name=str(member.display_name)[:100],
                    claimed_at=datetime.now(timezone.utc).isoformat(), released_at=None, released_by=None)
                if changed:
                    updated['notice_revision'] = uuid.uuid4().hex
                response = 'Ahora eres responsable de este ticket.'
            updated.update(guild=GUILD_ID, channel=channel.id, owner=str(row['owner']), kind=self.row_kind(row))
            if changed:
                before_panel = message_snapshot(panel)
                async def snapshot():
                    return dict(guild=GUILD_ID, channel=channel.id, ticket=await self.system.call('ticket', channel.id),
                        assignment=await self.system.call('get', assignment_key(channel.id)), panel=before_panel)
                async def apply():
                    # Persist first: ready() repairs a failed Discord edit without losing the assignee.
                    await self.system.call('put', assignment_key(channel.id), updated)
                    await self.ensure_open_panel(channel, row)
                await self.system.track('TICKET_RELEASE' if release else 'TICKET_CLAIM',
                    'Liberar ticket de ayuda' if release else 'Asignar responsable del ticket',
                    apply, interaction.id, snapshot=snapshot)
            else:
                await self.ensure_open_panel(channel, row)
            if not release:
                await self.try_claim_notice(channel, row)
        await interaction.followup.send(response, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    def notice_scope(self, channel, row):
        self.valid_channel(channel, row)
        allowed = {GUILD_ID, BOT_ID, OWNER_ID, int(row['owner'])}
        allowed.update(int(self.system.store.get('role:' + key) or 0)
                       for key in ('founder', 'admin', 'mod', 'support'))
        rules = {target.id: rule for target, rule in channel.overwrites.items()}
        if (GUILD_ID not in rules or rules[GUILD_ID].view_channel is not False
                or any(rule.view_channel is True and target not in allowed
                       for target, rule in rules.items())):
            raise ValueError('El aviso requiere un ticket privado para el autor y el equipo.')

    @staticmethod
    def notice_marker(channel_id, revision):
        return f'https://discord.com/channels/{GUILD_ID}/{channel_id}?claim={revision}'

    def notice_matches(self, message, row, assignment):
        return (message.author.id == BOT_ID and message.channel.id == int(row['channel'])
            and message.content == f'<@{row["owner"]}>' and not message.attachments
            and not message.components and len(message.embeds) == 1
            and message.embeds[0].title == NOTICE_TITLE
            and message.embeds[0].description == f'<@{assignment["staff_id"]}> está atendiendo tu caso.'
            and message.embeds[0].footer.text == NOTICE_FOOTER
            and message.embeds[0].url == self.notice_marker(row['channel'], assignment['notice_revision']))

    async def claim_notice(self, channel, row):
        """Caller holds ticket_lock; old assignments deliberately have no notice revision."""
        reopening = await self.system.call('get', 'ticket_reopen:' + str(channel.id))
        if reopening and reopening.get('state') == 'pending':
            return None
        current = await self.system.call('ticket', channel.id)
        self.valid_channel(channel, current)
        if str(current['owner']) != str(row['owner']):
            raise ValueError('El ticket cambió; se conserva el aviso pendiente.')
        assignment = await self.assignment(current)
        revision = assignment.get('notice_revision')
        if not revision or assignment.get('staff_id') is None:
            return None
        if (not isinstance(revision, str) or len(revision) != 32
                or any(char not in '0123456789abcdef' for char in revision)):
            raise ValueError('El registro del aviso necesita revisión del equipo.')
        key = notice_key(channel.id, revision)
        expected = dict(guild=GUILD_ID, channel=channel.id, owner=str(current['owner']),
                        staff_id=assignment['staff_id'], revision=revision)
        receipt = await self.system.call('get', key) or {}
        if receipt and any(receipt.get(name) != value for name, value in expected.items()):
            raise ValueError('El aviso registrado pertenece a otra asignación.')
        if receipt.get('state') not in (None, 'pending', 'sent'):
            raise ValueError('El estado del aviso necesita revisión del equipo.')
        if receipt.get('state') == 'sent':
            return receipt.get('message_id')
        guild = self.guild()
        await self.fresh_staff(guild, assignment['staff_id'])
        fresh = await guild.fetch_channel(channel.id)
        if fresh.id != channel.id:
            raise ValueError('El canal del aviso cambió.')
        self.notice_scope(fresh, current)
        receipt = dict(expected, **{k: v for k, v in receipt.items() if k not in expected})
        found = None
        if receipt.get('attempted_at'):
            attempted = datetime.fromisoformat(receipt['attempted_at'])
            async for message in fresh.history(limit=None, after=attempted - timedelta(seconds=5), oldest_first=True):
                if self.notice_matches(message, current, assignment):
                    found = message
                    break
            if found is None and datetime.now(timezone.utc) - attempted < timedelta(seconds=10):
                raise ValueError('La entrega del aviso aún está pendiente de verificación.')
        async def snapshot():
            return dict(guild=GUILD_ID, channel=fresh.id, ticket=await self.system.call('ticket', fresh.id),
                assignment=await self.system.call('get', assignment_key(fresh.id)),
                receipt=await self.system.call('get', key))
        async def publish():
            nonlocal found, fresh
            # Recheck the registered current assignment at the mutation boundary.
            fresh = await guild.fetch_channel(channel.id)
            if fresh.id != channel.id:
                raise ValueError('El canal del aviso cambió.')
            latest = await self.system.call('ticket', fresh.id)
            self.notice_scope(fresh, latest)
            live_assignment = await self.assignment(latest)
            if (live_assignment.get('notice_revision') != revision
                    or live_assignment.get('staff_id') != assignment['staff_id']):
                raise ValueError('La asignación cambió; no se enviará un aviso anterior.')
            if found is None:
                await self.fresh_staff(guild, assignment['staff_id'])
                receipt.update(state='pending', attempted_at=datetime.now(timezone.utc).isoformat())
                await self.system.call('put', key, receipt)
                embed = discord.Embed(title=NOTICE_TITLE,
                    description=f'<@{assignment["staff_id"]}> está atendiendo tu caso.', color=CYAN,
                    url=self.notice_marker(fresh.id, revision)).set_footer(text=NOTICE_FOOTER)
                found = await fresh.send(content=f'<@{current["owner"]}>', embed=embed,
                    nonce=str(int(revision[:16], 16)), allowed_mentions=discord.AllowedMentions(
                        users=[discord.Object(id=int(current['owner']))], roles=False, everyone=False,
                        replied_user=False))
            receipt.update(state='sent', message_id=found.id, sent_at=datetime.now(timezone.utc).isoformat())
            await self.system.call('put', key, receipt)
            return found.id
        result = await self.system.track('TICKET_CLAIM_NOTICE', 'Avisar al autor del responsable del ticket',
            publish, f'{channel.id}:{revision}', snapshot=snapshot)
        log.info('VICE_TICKET_CLAIM_NOTICE channel=%s message=%s', channel.id, result)
        return result

    async def try_claim_notice(self, channel, row):
        try:
            return await self.claim_notice(channel, row)
        except Exception as error:
            log.warning('VICE_TICKET_CLAIM_NOTICE_PENDING channel=%s error=%s', channel.id, type(error).__name__)
            return None

    async def pending_notice(self, row):
        if not row or row['state'] != 'open':
            return False
        reopening = await self.system.call('get', 'ticket_reopen:' + str(row['channel']))
        if reopening and reopening.get('state') == 'pending':
            return False
        assignment = await self.assignment(row)
        revision = assignment.get('notice_revision')
        if not revision or assignment.get('staff_id') is None:
            return False
        if (not isinstance(revision, str) or len(revision) != 32
                or any(char not in '0123456789abcdef' for char in revision)):
            raise ValueError('El registro del aviso necesita revisión del equipo.')
        receipt = await self.system.call('get', notice_key(row['channel'], revision)) or {}
        return receipt.get('state') != 'sent'

    async def retry_pending_notices(self):
        """Poll durable pending receipts only; delivered/legacy tickets use no Discord REST."""
        event = getattr(self.system, 'ready_event', None)
        if (not self.system.configured or not isinstance(event, asyncio.Event) or not event.is_set()):
            return 0
        guild = self.guild()
        rows = sorted((row for row in await self.system.call('tickets') if row['state'] == 'open'),
                      key=lambda row: int(row['channel']))
        rows = [row for row in rows if int(row['channel']) > self.notice_cursor] + [
            row for row in rows if int(row['channel']) <= self.notice_cursor]
        attempted = 0
        for row in rows:
            if attempted >= NOTICE_RETRY_LIMIT:
                break
            try:
                if not await self.pending_notice(row):
                    continue
                async with self.system.ticket_lock:
                    if not self.system.configured or not event.is_set():
                        break
                    self.guild()
                    current = await self.system.call('ticket', row['channel'])
                    if not await self.pending_notice(current):
                        continue
                    attempted += 1
                    self.notice_cursor = int(row['channel'])
                    channel = await guild.fetch_channel(int(row['channel']))
                    if channel.id != int(row['channel']):
                        raise ValueError('El canal del aviso cambió.')
                    self.notice_scope(channel, current)
                    # A pending assignment can follow a failed panel edit. Repair
                    # that exact panel only, rather than polling every open ticket.
                    await self.ensure_open_panel(channel, current)
                    await self.try_claim_notice(channel, current)
            except Exception as error:
                log.warning('VICE_TICKET_NOTICE_RETRY_PENDING channel=%s error=%s',
                            row['channel'], type(error).__name__)
        return attempted

    def start_notice_worker(self):
        if not isinstance(getattr(self.system, 'ready_event', None), asyncio.Event):
            return
        if self.notice_task is None or self.notice_task.done():
            self.notice_task = asyncio.create_task(self.notice_worker(), name='vice-ticket-claim-notices')

    async def notice_worker(self):
        await self.system.ready_event.wait()
        while True:
            await asyncio.sleep(NOTICE_RETRY_SECONDS)
            try:
                await self.retry_pending_notices()
            except Exception as error:
                log.warning('VICE_TICKET_NOTICE_WORKER error=%s', type(error).__name__)

    async def close(self):
        task, self.notice_task = self.notice_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def claim(self, interaction):
        await self.update_assignment(interaction, release=False)

    async def release(self, interaction):
        await self.update_assignment(interaction, release=True)

    async def archive_controls(self, channel, row=None):
        """Caller holds ticket_lock after closing; preserve the starter and assignment."""
        self.guild()
        self.system.validate_guild(getattr(channel, 'guild', None))
        current = await self.system.call('ticket', channel.id)
        self.valid_channel(channel, current, closed=True)
        if row and (str(row['channel']) != str(current['channel']) or str(row['owner']) != str(current['owner'])):
            raise ValueError('El ticket cambió; vuelve a intentarlo.')
        record = await self.panel_record(current)
        if not record:
            return None
        try:
            panel = await channel.fetch_message(int(record['panel_id']))
        except discord.NotFound as error:
            if error.code == 10008:
                return None
            raise
        if (not self.starter_matches(panel, archived=True) or panel.embeds[0].footer.text != FOOTER):
            raise ValueError('El panel registrado necesita revisión del equipo.')
        if not controls(panel):
            return panel
        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, topic=channel.topic, category=channel.category_id,
                ticket=await self.system.call('ticket', channel.id), panel=message_snapshot(panel),
                assignment=await self.system.call('get', assignment_key(channel.id)), panel_record=record)
        return await self.system.track('TICKET_ARCHIVE_CONTROLS', 'Archivar controles del ticket atendido',
            lambda: panel.edit(view=None, allowed_mentions=discord.AllowedMentions.none()),
            f'{channel.id}:{uuid.uuid4().hex}', snapshot=snapshot)

    async def ready(self):
        guild = self.guild()
        self.start_notice_worker()
        updated = 0
        for row in await self.system.call('tickets'):
            if row['state'] != 'open':
                continue
            async with self.system.ticket_lock:
                reopening = await self.system.call('get', 'ticket_reopen:' + str(row['channel']))
                if reopening and reopening.get('state') == 'pending':
                    continue
                try:
                    channel = await guild.fetch_channel(int(row['channel']))
                    await self.ensure_open_panel(channel, row)
                    await self.try_claim_notice(channel, row)
                    updated += 1
                except discord.NotFound as error:
                    if error.code != 10003:
                        raise
                except ValueError:
                    log.warning('VICE_TICKET_PANEL_SKIPPED channel=%s', row['channel'])
        log.info('VICE_TICKET_CENTER_READY open_panels=%s', updated)
        return updated
