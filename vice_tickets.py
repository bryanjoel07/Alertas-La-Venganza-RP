"""Private ticket categories and durable, staff-only responsibility assignments."""
from datetime import datetime, timezone
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
                if not self.starter_matches(panel):
                    raise ValueError('El panel registrado necesita revisión del equipo.')
        if panel is None:
            async for candidate in channel.history(limit=None, oldest_first=True):
                if self.starter_matches(candidate):
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
        await interaction.followup.send(response, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

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
        updated = 0
        for row in await self.system.call('tickets'):
            if row['state'] != 'open':
                continue
            async with self.system.ticket_lock:
                try:
                    channel = await guild.fetch_channel(int(row['channel']))
                    await self.ensure_open_panel(channel, row)
                    updated += 1
                except discord.NotFound as error:
                    if error.code != 10003:
                        raise
                except ValueError:
                    log.warning('VICE_TICKET_PANEL_SKIPPED channel=%s', row['channel'])
        log.info('VICE_TICKET_CENTER_READY open_panels=%s', updated)
        return updated
