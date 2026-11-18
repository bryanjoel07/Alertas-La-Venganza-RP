"""One private, durable staff dashboard for the district's open tickets."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import uuid

import discord

from vice_channel_style import stylize
from vice_design import BOT_ID, CYAN, GUILD_ID, OWNER_ID
from vice_readonly import WRITE_FLAGS
from vice_ticket_reminders import as_time


log = logging.getLogger('ViceDistrict.ticket_dashboard')
VERSION = 'vice-ticket-dashboard-v1'
KEY = 'ticket_dashboard:destination'
TOPIC = 'Pendientes privados del equipo: responsables, espera y acceso directo a cada ticket.'
TITLE = '📋 Tickets pendientes'
FOOTER = 'VIce District • Panel privado de Staff'
NAME = stylize('├・📋│pendientes')
PAGE_SIZE = 10
POLL_SECONDS = 60
BUTTONS = ('vice:v1:dashboard:previous', 'vice:v1:dashboard:refresh', 'vice:v1:dashboard:next')


def now():
    return datetime.now(timezone.utc)


def controls(message):
    return [(getattr(child, 'custom_id', None), bool(getattr(child, 'disabled', False)))
            for row in message.components for child in getattr(row, 'children', ())]


def message_state(message):
    return dict(id=message.id, author=message.author.id, content=message.content,
        embeds=[embed.to_dict() for embed in message.embeds],
        controls=[dict(custom_id=key, disabled=disabled) for key, disabled in controls(message)])


class DashboardView(discord.ui.View):
    def __init__(self, manager, *, page=0, pages=1):
        super().__init__(timeout=None)
        self.manager = manager
        self.previous.disabled = page <= 0
        self.next_page.disabled = page >= pages - 1

    async def on_error(self, interaction, error, item):
        if interaction.guild_id != GUILD_ID:
            return
        text = str(error) if isinstance(error, ValueError) else 'No se pudo actualizar el panel. Inténtalo de nuevo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(text[:1200], ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @discord.ui.button(label='Anterior', emoji='◀️', custom_id=BUTTONS[0], style=discord.ButtonStyle.secondary)
    async def previous(self, interaction, button):
        await self.manager.navigate(interaction, -1)

    @discord.ui.button(label='Actualizar', emoji='🔄', custom_id=BUTTONS[1], style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction, button):
        await self.manager.navigate(interaction, 0)

    @discord.ui.button(label='Siguiente', emoji='▶️', custom_id=BUTTONS[2], style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction, button):
        await self.manager.navigate(interaction, 1)


class TicketDashboard:
    def __init__(self, system):
        self.system = system
        self.lock = asyncio.Lock()
        self.task = None
        self.registered = False

    async def start(self):
        if not self.registered:
            self.system.bot.add_view(DashboardView(self))
            self.registered = True

    def guild(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        return guild

    def overwrites(self, guild):
        self.system.validate_guild(guild)
        readonly = dict(view_channel=True, read_message_history=True, **{key: False for key in WRITE_FLAGS})
        rules = {guild.default_role: discord.PermissionOverwrite(**dict(readonly,
            view_channel=False, read_message_history=False))}
        rules[discord.Object(id=OWNER_ID, type=discord.Member)] = discord.PermissionOverwrite(**readonly)
        for key in ('founder', 'admin', 'mod', 'support'):
            role = guild.get_role(int(self.system.store.get('role:' + key) or 0))
            if role is None or role.guild.id != GUILD_ID or role.id == GUILD_ID:
                raise ValueError('Falta un rol del equipo para proteger el panel.')
            rules[role] = discord.PermissionOverwrite(**readonly)
        if guild.me is None or guild.me.id != BOT_ID:
            raise ValueError('No se pudo comprobar al bot del panel.')
        rules[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
            send_messages=True, embed_links=True, manage_messages=True)
        return rules

    def record_valid(self, record):
        nonce = record.get('nonce')
        if (record.get('guild') != GUILD_ID or not isinstance(nonce, str) or len(nonce) != 32
                or any(character not in '0123456789abcdef' for character in nonce)):
            raise ValueError('El registro del panel necesita revisión del equipo.')

    def validate_destination(self, channel, record):
        guild = self.guild()
        self.record_valid(record)
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID
                or int(record.get('channel') or 0) != channel.id
                or channel.category_id != int(self.system.store.get('category:team') or 0)
                or channel.topic != TOPIC):
            raise ValueError('El panel debe permanecer en su canal privado de Staff.')
        actual = {target.id: rule.pair() for target, rule in channel.overwrites.items()}
        expected = {target.id: rule.pair() for target, rule in self.overwrites(guild).items()}
        if actual != expected:
            raise ValueError('Los permisos del panel no son exclusivos del equipo.')
        permissions = channel.permissions_for(guild.me)
        if not all(getattr(permissions, key, False) for key in
                   ('view_channel', 'read_message_history', 'send_messages', 'embed_links')):
            raise ValueError('El bot no puede actualizar el panel privado.')
        return channel

    async def ensure_destination(self):
        """Caller holds dashboard lock; channel adoption needs bot audit evidence."""
        guild = self.guild()
        record = await self.system.call('get', KEY) or {}
        if record:
            self.record_valid(record)
        if record.get('channel'):
            return self.validate_destination(await guild.fetch_channel(int(record['channel'])), record), record
        category = await guild.fetch_channel(int(self.system.store.get('category:team') or 0))
        if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
            raise ValueError('No se encontró la categoría registrada de Staff.')
        expected = self.overwrites(guild)
        if not record:
            record = dict(guild=GUILD_ID, nonce=uuid.uuid4().hex, started_at=now().isoformat(), page=0)
            await self.system.call('put', KEY, record)
        reason = 'VIce ticket dashboard ' + record['nonce']
        matches = []
        if record.get('attempted_at'):
            async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.channel_create,
                    after=as_time(record['started_at']) - timedelta(seconds=5)):
                if (getattr(entry.user, 'id', None) == BOT_ID and entry.reason == reason
                        and getattr(entry.target, 'id', None)):
                    candidate = await guild.fetch_channel(entry.target.id)
                    self.validate_destination(candidate, dict(record, channel=candidate.id))
                    matches.append(candidate)
            if len(matches) != 1:
                raise ValueError('La creación pendiente requiere verificación; no se creará otro canal.')
        async def snapshot():
            return dict(guild=GUILD_ID, category=category.id, destination=await self.system.call('get', KEY))
        async def create():
            fresh = await guild.fetch_channel(category.id)
            if not isinstance(fresh, discord.CategoryChannel) or fresh.guild.id != GUILD_ID:
                raise ValueError('La categoría de Staff cambió.')
            if matches:
                channel = matches[0]
            else:
                record['attempted_at'] = now().isoformat()
                await self.system.call('put', KEY, record)
                channel = await guild.create_text_channel(NAME, category=fresh, topic=TOPIC,
                    overwrites=expected, reason=reason)
            record['channel'] = channel.id
            self.validate_destination(channel, record)
            await self.system.call('put', KEY, record)
            await self.system.call('put', 'channel:ticket_dashboard', channel.id)
            return channel
        channel = await self.system.track('TICKET_DASHBOARD_SETUP', 'Preparar panel privado de pendientes',
            create, record['nonce'], snapshot=snapshot)
        return channel, record

    @staticmethod
    def marker(record):
        return f'https://discord.com/channels/{GUILD_ID}/{record["channel"]}?dashboard={record["nonce"]}'

    def panel_matches(self, message, record):
        return (message.author.id == BOT_ID and message.channel.id == int(record['channel'])
            and not message.content and not message.attachments and len(message.embeds) == 1
            and message.embeds[0].title == TITLE and message.embeds[0].url == self.marker(record)
            and str(message.embeds[0].footer.text or '').startswith(FOOTER + ' • Página ')
            and [key for key, _ in controls(message)] == list(BUTTONS))

    async def collect(self):
        async with self.system.ticket_lock:
            return await self._collect_locked()

    async def _collect_locked(self):
        """Resolve actual open cases without copying query text or sending reminders."""
        guild = self.guild()
        items, unavailable = [], 0
        for saved in await self.system.call('tickets'):
            if saved['state'] != 'open':
                continue
            row = await self.system.call('ticket', saved['channel'])
            if not row or row['state'] != 'open':
                continue
            try:
                channel = await guild.fetch_channel(int(row['channel']))
                self.system.tickets.notice_scope(channel, row)
                for key in ('founder', 'admin', 'mod', 'support'):
                    role = guild.get_role(int(self.system.store.get('role:' + key) or 0))
                    if role is None:
                        raise ValueError('No se pudo comprobar el acceso del equipo.')
                    permissions = channel.permissions_for(role)
                    if not permissions.view_channel or not permissions.read_message_history:
                        raise ValueError('El ticket tiene una audiencia más restringida que el panel.')
            except discord.NotFound:
                continue
            except (discord.Forbidden, ValueError):
                unavailable += 1
                continue
            responsible = 'Sin asignar'
            try:
                assignment = await self.system.tickets.assignment(row)
                if assignment.get('staff_id'):
                    staff = await self.system.tickets.fresh_staff(guild, assignment['staff_id'])
                    permissions = channel.permissions_for(staff)
                    if not permissions.view_channel or not permissions.read_message_history:
                        raise ValueError('Sin acceso')
                    responsible = f'<@{staff.id}>'
            except (discord.NotFound, discord.Forbidden, ValueError):
                responsible = 'Asignación por revisar'
            waiting, status = None, 'Por verificar'
            try:
                state = await self.system.ticket_reminders.load(row)
                state, complete = await self.system.ticket_reminders.reconcile(channel, row, state)
                if complete:
                    waiting = state.get('awaiting_since')
                    status = 'Esperando al equipo' if waiting else 'Esperando al usuario'
                    if waiting is None:
                        waiting = state.get('last_staff_reply_at')
                    if waiting:
                        waiting = int(as_time(waiting).timestamp())
            except (discord.HTTPException, ValueError, KeyError):
                waiting, status = None, 'Por verificar'
            items.append(dict(channel=channel.id, name=str(channel.name), responsible=responsible,
                status=status, waiting=waiting, opened=int(row['created'])))
        items.sort(key=lambda item: (item['status'] != 'Esperando al equipo',
                                    item['waiting'] or item['opened'], item['channel']))
        return items, unavailable

    def render(self, record, items, unavailable, page):
        pages = max(1, math.ceil(len(items) / PAGE_SIZE))
        page = min(max(0, int(page)), pages - 1)
        team = sum(item['status'] == 'Esperando al equipo' for item in items)
        description = (f'**{len(items)} abiertos** · **{team} esperando al equipo**\n'
                       'Usa el enlace de cada caso para entrar directamente.')
        if not items:
            description = '🌴 **No hay tickets abiertos verificados.**'
        if unavailable:
            description += f'\n⚠️ {unavailable} ticket(s) necesitan revisión de acceso.'
        result = discord.Embed(title=TITLE, description=description, color=CYAN, url=self.marker(record))
        for index, item in enumerate(items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page * PAGE_SIZE + 1):
            name = discord.utils.escape_markdown(item['name'])[:65]
            value = (f'[Abrir ticket](https://discord.com/channels/{GUILD_ID}/{item["channel"]})'
                     f' · **Responsable:** {item["responsible"]}\n**{item["status"]}**')
            value += (f' · desde <t:{item["waiting"]}:R>' if item['waiting'] is not None else
                      f'\nAbierto <t:{item["opened"]}:R>')
            result.add_field(name=f'{index}. {name}', value=value, inline=False)
        result.set_footer(text=f'{FOOTER} • Página {page + 1}/{pages}')
        return result, DashboardView(self, page=page, pages=pages), page

    async def panel(self, channel, record):
        if record.get('message'):
            message = await channel.fetch_message(int(record['message']))
            if not self.panel_matches(message, record):
                raise ValueError('El mensaje registrado no coincide con el panel de pendientes.')
            return message
        if not record.get('message_attempted_at'):
            return None
        matches = []
        async for message in channel.history(limit=None,
                after=as_time(record['message_attempted_at']) - timedelta(seconds=5), oldest_first=True):
            if self.panel_matches(message, record):
                matches.append(message)
        if len(matches) != 1:
            raise ValueError('La entrega pendiente debe verificarse; no se publicará otro panel.')
        return matches[0]

    @staticmethod
    def same(message, embed, view):
        current = message.embeds[0]
        desired_controls = [(item.custom_id, item.disabled) for item in view.children]
        return (current.title == embed.title and current.description == embed.description
            and current.url == embed.url and current.color == embed.color
            and current.footer.text == embed.footer.text and controls(message) == desired_controls
            and [(f.name, f.value, f.inline) for f in current.fields]
                == [(f.name, f.value, f.inline) for f in embed.fields])

    async def _refresh(self, channel, record, *, page=None):
        async with self.system.ticket_lock:
            return await self._refresh_locked(channel, record, page=page)

    async def _refresh_locked(self, channel, record, *, page=None):
        items, unavailable = await self._collect_locked()
        embed, view, page = self.render(record, items, unavailable,
            record.get('page', 0) if page is None else page)
        message = await self.panel(channel, record)
        if message and self.same(message, embed, view):
            if record.get('message') != message.id or record.get('page') != page:
                record.update(message=message.id, page=page)
                await self.system.call('put', KEY, record)
            return message
        before = message_state(message) if message else None
        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, before_message=before,
                        destination=await self.system.call('get', KEY))
        async def publish():
            nonlocal message, channel
            channel = self.validate_destination(await self.guild().fetch_channel(channel.id), record)
            if message:
                current = await channel.fetch_message(message.id)
                if not self.panel_matches(current, record):
                    raise ValueError('El panel cambió antes de la actualización.')
                message = await current.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            else:
                record['message_attempted_at'] = now().isoformat()
                await self.system.call('put', KEY, record)
                message = await channel.send(embed=embed, view=view,
                    nonce=str(int(record['nonce'][:16], 16)), allowed_mentions=discord.AllowedMentions.none())
            if not self.panel_matches(message, record) or not self.same(message, embed, view):
                raise ValueError('Discord no confirmó la identidad y contenido del panel.')
            record.update(message=message.id, page=page)
            await self.system.call('put', KEY, record)
            return message
        digest = hashlib.sha256(json.dumps(dict(embed=embed.to_dict(), page=page), sort_keys=True).encode()).hexdigest()
        return await self.system.track('TICKET_DASHBOARD_PANEL', 'Actualizar panel privado de pendientes',
            publish, record['nonce'] + ':' + digest, snapshot=snapshot)

    async def tick(self):
        if not self.system.configured or not self.system.ready_event.is_set():
            return None
        async with self.lock:
            channel, record = await self.ensure_destination()
            return await self._refresh(channel, record)

    async def navigate(self, interaction, delta):
        self.system.tickets.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            guild = self.guild()
            member = await self.system.tickets.fresh_staff(guild, interaction.user.id)
            record = await self.system.call('get', KEY) or {}
            self.record_valid(record)
            if (interaction.channel_id != record.get('channel') or interaction.message is None
                    or interaction.message.id != record.get('message')):
                raise ValueError('Usa el panel actual de pendientes.')
            channel = self.validate_destination(await guild.fetch_channel(record['channel']), record)
            if not channel.permissions_for(member).view_channel:
                raise ValueError('Ya no tienes acceso al panel de Staff.')
            await self._refresh(channel, record, page=int(record.get('page', 0)) + delta)
        await interaction.followup.send('Panel actualizado.', ephemeral=True,
                                        allowed_mentions=discord.AllowedMentions.none())

    async def ready(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.worker(), name='vice-ticket-dashboard')
        message = await self.tick()
        log.info('VICE_TICKET_DASHBOARD_READY channel=%s message=%s',
                 self.system.store.get('channel:ticket_dashboard'), getattr(message, 'id', None))
        return message

    async def worker(self):
        await self.system.ready_event.wait()
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                await self.tick()
            except Exception as error:
                log.warning('VICE_TICKET_DASHBOARD_PENDING type=%s', type(error).__name__)

    async def close(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
