"""Explicit staff confirmation for deleting registered, closed district tickets."""
from datetime import datetime, timezone
import logging
import uuid

import discord

from vice_design import GUILD_ID, BOT_ID

log = logging.getLogger('ViceDistrict.ticket_delete')
DELETE_VERSION = 'vice-closed-ticket-delete-v1'
DELETE_CUSTOM_ID = 'vice:v1:ticket:delete'
CLOSE_CUSTOM_ID = 'vice:v1:ticket:close'
ARCHIVE_TITLE = '🔒 Conversación archivada'
STARTER_TITLE = '🎫 Te escuchamos'
LEGACY_FOOTER = 'GTA VI Latino • Puerto Rico + Latinoamérica • Fans no oficiales'


def record_key(channel_id):
    return 'ticket_delete:' + str(channel_id)


def panel_footer(channel_id):
    return 'VIce District • ticket-delete:' + str(channel_id)


def has_control(message, custom_id):
    return any(getattr(child, 'custom_id', None) == custom_id
               and not getattr(child, 'disabled', False)
               for row in message.components for child in getattr(row, 'children', ()))


def message_snapshot(message):
    return dict(id=message.id, author=message.author.id, content=message.content,
                embeds=[embed.to_dict() for embed in message.embeds],
                controls=[dict(custom_id=getattr(child, 'custom_id', None),
                               disabled=bool(getattr(child, 'disabled', False)))
                          for row in message.components for child in getattr(row, 'children', ())])


class TicketDeleteView(discord.ui.View):
    def __init__(self, manager, *, timeout=None):
        super().__init__(timeout=timeout)
        self.manager = manager

    async def on_error(self, interaction, error, item):
        if interaction.guild_id != GUILD_ID:
            return
        if isinstance(error, ValueError):
            text = str(error)
        else:
            log.error('VICE_TICKET_DELETE_FAILED type=%s', type(error).__name__, exc_info=error)
            text = 'No se pudo completar la acción. Inténtalo de nuevo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(text[:1200], ephemeral=True)


class DeleteTicketPanel(TicketDeleteView):
    @discord.ui.button(label='Eliminar', emoji='🗑️', style=discord.ButtonStyle.danger,
                       custom_id=DELETE_CUSTOM_ID)
    async def delete_ticket(self, interaction, button):
        await self.manager.request(interaction)


class ConfirmDeleteView(TicketDeleteView):
    def __init__(self, manager, actor_id, channel_id, panel_id):
        super().__init__(manager, timeout=60)
        self.actor_id, self.channel_id, self.panel_id = int(actor_id), int(channel_id), int(panel_id)
        self.token = uuid.uuid4().hex
        self.finished = False

    async def interaction_check(self, interaction):
        self.manager.check_confirmation(interaction, self)
        return True

    async def on_timeout(self):
        self.finished = True
        self.stop()

    @discord.ui.button(label='Sí, eliminar', style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction, button):
        await self.manager.confirm(interaction, self)

    @discord.ui.button(label='Cancelar', style=discord.ButtonStyle.secondary)
    async def cancel_delete(self, interaction, button):
        await self.manager.cancel(interaction, self)


class TicketDeletion:
    def __init__(self, system):
        self.system = system
        self.registered = False

    async def start(self):
        if not self.registered:
            self.system.bot.add_view(DeleteTicketPanel(self))
            self.registered = True

    def guild(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        return guild

    def check_interaction(self, interaction):
        if (interaction.guild_id != GUILD_ID or interaction.guild is None
                or not isinstance(interaction.user, discord.Member) or interaction.user.bot):
            raise ValueError('Usa este botón dentro de VIce District.')
        self.system.validate_guild(interaction.guild)
        self.guild()

    def check_confirmation(self, interaction, view):
        self.check_interaction(interaction)
        if (view.manager is not self or interaction.user.id != view.actor_id
                or interaction.channel_id != view.channel_id):
            raise ValueError('Esta confirmación pertenece a otra persona o ticket.')
        if view.finished:
            raise ValueError('Esta confirmación ya terminó. Vuelve a pulsar Eliminar.')

    async def fresh_staff(self, guild, actor_id):
        member = await guild.fetch_member(int(actor_id))
        if (member.id != int(actor_id) or member.guild.id != GUILD_ID or member.bot
                or not self.system.is_staff(member)):
            raise ValueError('Solo el equipo puede eliminar tickets cerrados.')
        return member

    async def record(self, channel_id):
        return await self.system.call('get', record_key(channel_id)) or {}

    def valid_closed(self, channel, row):
        self.guild()
        category = self.system.store.get('category:closed')
        if (not row or row['state'] != 'closed' or not isinstance(channel, discord.TextChannel)
                or channel.guild.id != GUILD_ID or int(row['channel']) != channel.id
                or not category or channel.category_id != int(category)
                or channel.topic != 'VIce ticket closed owner=' + str(row['owner'])):
            raise ValueError('Solo se puede eliminar un ticket cerrado y registrado del distrito.')
        return row

    @staticmethod
    def archive_matches(message, channel_id):
        controls = [child for row in message.components for child in getattr(row, 'children', ())]
        return (message.author.id == BOT_ID and not message.content and not message.attachments
                and len(message.embeds) == 1 and message.embeds[0].title == ARCHIVE_TITLE
                and message.embeds[0].footer.text in (LEGACY_FOOTER, panel_footer(channel_id))
                and (not controls or (len(controls) == 1
                     and getattr(controls[0], 'custom_id', None) == DELETE_CUSTOM_ID)))

    @staticmethod
    def starter_matches(message):
        controls = [child for row in message.components for child in getattr(row, 'children', ())]
        return (message.author.id == BOT_ID and not message.content and not message.attachments
                and len(message.embeds) == 1 and message.embeds[0].title == STARTER_TITLE
                and message.embeds[0].footer.text == LEGACY_FOOTER
                and len(controls) == 1
                and has_control(message, CLOSE_CUSTOM_ID))

    async def ensure_closed_panel(self, channel, row=None):
        """Called under the ticket lock by ready/close; does not delete anything."""
        self.guild()
        current = await self.system.call('ticket', channel.id)
        self.valid_closed(channel, current)
        if row and (str(row['channel']) != str(current['channel']) or str(row['owner']) != str(current['owner'])):
            raise ValueError('El ticket cambió; vuelve a intentarlo.')
        record = await self.record(channel.id)
        if record.get('state') == 'deleted':
            raise ValueError('El ticket ya figura como eliminado.')
        panel = None
        if record.get('panel_id'):
            try:
                candidate = await channel.fetch_message(int(record['panel_id']))
            except discord.NotFound:
                pass
            else:
                if not self.archive_matches(candidate, channel.id):
                    raise ValueError('El panel registrado necesita revisión del equipo.')
                panel = candidate
        starters = []
        if panel is None or not record.get('starters_cleaned'):
            async for message in channel.history(limit=None, oldest_first=True):
                if self.starter_matches(message):
                    starters.append(message)
                if panel is None and self.archive_matches(message, channel.id):
                    panel = message
        if (panel is not None and has_control(panel, DELETE_CUSTOM_ID)
                and panel.embeds[0].footer.text == panel_footer(channel.id)
                and record.get('starters_cleaned') and not starters):
            return panel
        before = self.channel_snapshot(channel, current, record,
                                       panels=([panel] if panel else []) + starters)
        async def snapshot():
            return dict(before=before, state=await self.record(channel.id))
        async def apply():
            nonlocal panel
            for starter in starters:
                await starter.edit(view=None, allowed_mentions=discord.AllowedMentions.none())
            embed = self.system.embed(ARCHIVE_TITLE,
                'Ticket cerrado. Su historial sigue disponible para el autor y el equipo. '
                'Solo el equipo puede eliminarlo.')
            embed.set_footer(text=panel_footer(channel.id))
            if panel is None:
                panel = await channel.send(embed=embed, view=DeleteTicketPanel(self),
                    nonce=f'vtd{channel.id}', allowed_mentions=discord.AllowedMentions.none())
            else:
                await panel.edit(embed=embed, view=DeleteTicketPanel(self),
                                 allowed_mentions=discord.AllowedMentions.none())
            record.update(guild=GUILD_ID, channel=channel.id, owner=str(current['owner']),
                          panel_id=panel.id, version=DELETE_VERSION, starters_cleaned=True)
            record.setdefault('state', 'ready')
            await self.system.call('put', record_key(channel.id), record)
            return panel
        return await self.system.track('TICKET_DELETE_PANEL', 'Añadir Eliminar al ticket cerrado',
            apply, DELETE_VERSION + ':' + str(channel.id), snapshot=snapshot)

    def channel_snapshot(self, channel, row, record, *, panels=()):
        overwrites = []
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites.append(dict(id=str(target.id), type='role' if isinstance(target, discord.Role) else 'member',
                                   allow=str(allow.value), deny=str(deny.value)))
        return dict(guild=GUILD_ID, channel=channel.id, name=channel.name,
                    category=channel.category_id, topic=channel.topic, type='text',
                    position=channel.position, nsfw=channel.nsfw, slowmode_delay=channel.slowmode_delay,
                    overwrites=overwrites, ticket=dict(row), panel_id=record.get('panel_id'),
                    panels=[message_snapshot(message) for message in panels])

    @staticmethod
    def pending_proof(row, record):
        snapshot = record.get('snapshot') or {}
        before_ticket = snapshot.get('ticket') or {}
        return bool(row and row['state'] in ('closed', 'deleted')
            and record.get('state') in ('deleting', 'deleted')
            and record.get('guild') == GUILD_ID and str(record.get('channel')) == str(row['channel'])
            and str(record.get('owner')) == str(row['owner']) and record.get('request_id')
            and record.get('actor') and record.get('confirmation_token')
            and snapshot.get('guild') == GUILD_ID and str(snapshot.get('channel')) == str(row['channel'])
            and snapshot.get('category') and snapshot.get('type') == 'text'
            and snapshot.get('topic') == 'VIce ticket closed owner=' + str(row['owner'])
            and before_ticket.get('state') == 'closed'
            and str(before_ticket.get('channel')) == str(row['channel'])
            and str(before_ticket.get('owner')) == str(row['owner']))

    async def mark_deleted(self, row, record):
        record = dict(record, state='deleted', completed_at=datetime.now(timezone.utc).isoformat())
        await self.system.call('put', record_key(row['channel']), record)
        await self.system.call('ticket_state', row['channel'], 'deleted')

    async def recover_missing(self, row, record):
        if not self.pending_proof(row, record):
            return False
        async def snapshot():
            return dict(before=record['snapshot'], ticket=await self.system.call('ticket', row['channel']),
                        deletion_state=(await self.record(row['channel'])).get('state'))
        await self.system.track('TICKET_DELETE_RECOVERY', 'Confirmar la eliminación ya intentada del ticket',
            lambda: self.mark_deleted(row, record), record['request_id'], snapshot=snapshot)
        return True

    async def ready(self):
        guild = self.guild()
        updated = 0
        for row in await self.system.call('tickets'):
            if row['state'] != 'closed':
                continue
            async with self.system.ticket_lock:
                record = await self.record(row['channel'])
                try:
                    channel = await guild.fetch_channel(int(row['channel']))
                except discord.NotFound as error:
                    if error.code != 10003:
                        raise
                    await self.recover_missing(row, record)
                    continue
                try:
                    await self.ensure_closed_panel(channel, row)
                    updated += 1
                except ValueError:
                    log.warning('VICE_TICKET_DELETE_PANEL_SKIPPED channel=%s', row['channel'])
        log.info('VICE_TICKET_DELETE_READY closed_controls=%s', updated)
        return updated

    async def request(self, interaction):
        self.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        guild = self.guild()
        async with self.system.ticket_lock:
            await self.fresh_staff(guild, interaction.user.id)
            row = await self.system.call('ticket', interaction.channel_id)
            channel = await guild.fetch_channel(interaction.channel_id)
            self.valid_closed(channel, row)
            record = await self.record(channel.id)
            source = interaction.message
            if (not record.get('panel_id') or source is None or source.id != int(record['panel_id'])
                    or not self.archive_matches(source, channel.id)
                    or not has_control(source, DELETE_CUSTOM_ID)):
                raise ValueError('Usa el botón Eliminar del panel archivado de este ticket.')
            view = ConfirmDeleteView(self, interaction.user.id, channel.id, record['panel_id'])
        await interaction.followup.send('Eliminarás este canal y **todo su historial**. Esta acción es permanente.\n'
                                        '¿Quieres continuar?', view=view, ephemeral=True)
        return view

    async def confirm(self, interaction, view):
        self.check_confirmation(interaction, view)
        await interaction.response.defer(ephemeral=True)
        guild = self.guild()
        async with self.system.ticket_lock:
            self.check_confirmation(interaction, view)
            member = await self.fresh_staff(guild, view.actor_id)
            row = await self.system.call('ticket', view.channel_id)
            record = await self.record(view.channel_id)
            try:
                channel = await guild.fetch_channel(view.channel_id)
            except discord.NotFound as error:
                if error.code != 10003:
                    raise
                if (not self.pending_proof(row, record) or record.get('actor') != view.actor_id
                        or record.get('confirmation_token') != view.token):
                    raise ValueError('No hay un intento de eliminación verificable para este ticket.')
                await self.recover_missing(row, record)
            else:
                self.valid_closed(channel, row)
                if int(record.get('panel_id') or 0) != view.panel_id:
                    raise ValueError('El panel cambió. Vuelve a pulsar Eliminar.')
                panel = await channel.fetch_message(view.panel_id)
                if not self.archive_matches(panel, channel.id) or not has_control(panel, DELETE_CUSTOM_ID):
                    raise ValueError('El panel archivado necesita revisión del equipo.')
                before = self.channel_snapshot(channel, row, record, panels=[panel])
                async def snapshot():
                    return dict(before=before, ticket=await self.system.call('ticket', channel.id),
                                deletion_state=(await self.record(channel.id)).get('state'))
                async def remove():
                    intent = dict(record, guild=GUILD_ID, channel=channel.id, owner=str(row['owner']),
                        state='deleting', request_id=str(interaction.id), actor=member.id,
                        confirmation_token=view.token, started_at=datetime.now(timezone.utc).isoformat(),
                        snapshot=before)
                    await self.system.call('put', record_key(channel.id), intent)
                    try:
                        await channel.delete(reason=f'Ticket cerrado eliminado tras confirmación del equipo: {member.id}')
                    except discord.NotFound as error:
                        # This exact channel was validated immediately before the
                        # confirmed request and its deletion intent was persisted.
                        if error.code != 10003:
                            raise
                    await self.mark_deleted(row, intent)
                await self.system.track('TICKET_DELETE', 'Eliminar ticket cerrado confirmado por el equipo',
                    remove, str(interaction.id), snapshot=snapshot)
            view.finished = True
            view.stop()
        try:
            await interaction.edit_original_response(content='Ticket eliminado.', view=None)
        except discord.NotFound:
            pass

    async def cancel(self, interaction, view):
        self.check_confirmation(interaction, view)
        await interaction.response.defer(ephemeral=True)
        async with self.system.ticket_lock:
            self.check_confirmation(interaction, view)
            view.finished = True
            view.stop()
        await interaction.edit_original_response(content='Cancelado. El ticket se conserva.', view=None)
