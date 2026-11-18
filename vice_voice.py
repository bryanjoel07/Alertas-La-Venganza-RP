"""Owned temporary voice rooms, isolated to the GTA VI community."""
import asyncio
from contextlib import closing
import logging
import sqlite3
import time
import uuid

import discord

from vice_design import GUILD_ID, BOT_ID, OWNER_ID, CYAN
from vice_channel_style import stylize, format_name
from welcome_cards import clean_name

log = logging.getLogger('ViceDistrict.voice')
VOICE_VERSION = 'vice-temporary-voice-v1'
CATEGORY_NAME = '━━ 🎙️ SALAS DEL CORILLO ━━'
PANEL_NAME = '╭・🎛️│crear-mi-sala'
MAX_ROOMS, CREATE_COOLDOWN, NEW_GRACE, EMPTY_GRACE = 20, 60, 120, 30
RENAME_COOLDOWN = 300


class VoiceStore:
    def __init__(self, path):
        self.path = path

    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self):
        with closing(self.db()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS vice_voice_rooms (
                    token TEXT PRIMARY KEY, owner INTEGER NOT NULL, channel INTEGER UNIQUE,
                    state TEXT NOT NULL, created REAL NOT NULL, empty_since REAL,
                    used INTEGER NOT NULL DEFAULT 0, locked INTEGER NOT NULL DEFAULT 0,
                    renamed REAL NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS vice_voice_one_owner
                ON vice_voice_rooms(owner) WHERE state IN ('creating','active');
            ''')

    def rows(self):
        with closing(self.db()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM vice_voice_rooms WHERE state IN ('creating','active')")]

    def get(self, token):
        with closing(self.db()) as db:
            row = db.execute('SELECT * FROM vice_voice_rooms WHERE token=?', (token,)).fetchone()
            return dict(row) if row else None

    def owned(self, owner):
        with closing(self.db()) as db:
            row = db.execute("SELECT * FROM vice_voice_rooms WHERE owner=? AND state IN ('creating','active')", (owner,)).fetchone()
            return dict(row) if row else None

    def channel(self, channel):
        with closing(self.db()) as db:
            row = db.execute("SELECT * FROM vice_voice_rooms WHERE channel=? AND state='active'", (channel,)).fetchone()
            return dict(row) if row else None

    def reserve(self, owner, now):
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM vice_voice_rooms WHERE owner=? AND state IN ('creating','active')", (owner,)).fetchone()
            if row:
                return dict(row), False
            count = db.execute("SELECT COUNT(*) FROM vice_voice_rooms WHERE state IN ('creating','active')").fetchone()[0]
            if count >= MAX_ROOMS:
                raise ValueError('Las salas temporales están llenas. Inténtalo cuando se libere una.')
            latest = db.execute('SELECT MAX(created) FROM vice_voice_rooms WHERE owner=?', (owner,)).fetchone()[0]
            if latest is not None and now - latest < CREATE_COOLDOWN:
                raise ValueError('Espera un minuto entre la creación de salas.')
            token = uuid.uuid4().hex
            db.execute("INSERT INTO vice_voice_rooms(token,owner,state,created,empty_since) VALUES (?,?,'creating',?,?)", (token, owner, now, now))
            return dict(db.execute('SELECT * FROM vice_voice_rooms WHERE token=?', (token,)).fetchone()), True

    def update(self, token, **values):
        if not values or not set(values) <= {'channel','state','empty_since','used','locked','renamed'}:
            raise ValueError('Actualización de sala no válida.')
        with closing(self.db()) as db, db:
            db.execute('UPDATE vice_voice_rooms SET ' + ','.join(key + '=?' for key in values) + ' WHERE token=?', (*values.values(), token))


class VoiceView(discord.ui.View):
    def __init__(self, manager, *, timeout=None):
        super().__init__(timeout=timeout)
        self.manager = manager

    async def interaction_check(self, interaction):
        self.manager.authorize(interaction)
        return True

    async def on_error(self, interaction, error, item):
        if isinstance(error, ValueError):
            message = str(error)
        else:
            log.error('VICE_VOICE_INTERACTION_FAILED', exc_info=error)
            message = 'No se pudo completar la acción. Inténtalo otra vez o contacta al equipo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(message[:1500], ephemeral=True)


class VoicePanel(VoiceView):
    @discord.ui.button(label='Crear mi sala', emoji='🎙️', style=discord.ButtonStyle.primary, custom_id='vice:voice:v1:create')
    async def create(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        channel = await self.manager.create_room(interaction)
        await interaction.followup.send(f'🎙️ Tu sala: {channel.mention}\nEntra cuando quieras; empieza con 6 plazas.\n'
            'La administración conserva acceso para moderar.', view=RoomControls(self.manager, interaction.user.id, channel.id), ephemeral=True)

    @discord.ui.button(label='Administrar mi sala', emoji='🎛️', style=discord.ButtonStyle.secondary, custom_id='vice:voice:v1:manage')
    async def manage(self, interaction, button):
        row, channel = await self.manager.owned_room(interaction)
        await interaction.response.send_message(f'🎛️ Gestiona {channel.mention}.\nCerrar acceso limita las nuevas entradas; '
            'las personas que ya están dentro permanecen conectadas.',
            view=RoomControls(self.manager, interaction.user.id, channel.id), ephemeral=True)


class RoomControls(VoiceView):
    def __init__(self, manager, owner, channel):
        super().__init__(manager, timeout=600)
        self.owner, self.channel = owner, channel

    async def interaction_check(self, interaction):
        await super().interaction_check(interaction)
        if interaction.user.id != self.owner:
            raise ValueError('Este panel pertenece al creador de la sala.')
        await self.manager.owned_room(interaction, self.channel)
        return True

    @discord.ui.button(label='Cerrar acceso', emoji='🔒', row=0)
    async def lock(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self.manager.set_locked(interaction, self.channel, True)
        await interaction.followup.send('🔒 Entrada cerrada. Pueden entrar tus invitados y el equipo de moderación.', ephemeral=True)

    @discord.ui.button(label='Abrir acceso', emoji='🔓', row=0)
    async def unlock(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self.manager.set_locked(interaction, self.channel, False)
        await interaction.followup.send('🔓 Entrada abierta a la comunidad. Los bloqueos individuales se conservan.', ephemeral=True)

    @discord.ui.button(label='Cambiar cupo', emoji='👥', row=0)
    async def limit(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.manager, self.owner, self.channel, 'limit'))

    @discord.ui.button(label='Cambiar nombre', emoji='✏️', row=0)
    async def rename(self, interaction, button):
        await interaction.response.send_modal(RoomModal(self.manager, self.owner, self.channel, 'name'))

    @discord.ui.button(label='Permitir acceso', emoji='✅', row=1)
    async def allow(self, interaction, button):
        await interaction.response.send_message('Elige a quién permitir la entrada.',
            view=MemberPicker(self.manager, self.owner, self.channel, True), ephemeral=True)

    @discord.ui.button(label='Quitar acceso', emoji='🚫', row=1)
    async def revoke(self, interaction, button):
        await interaction.response.send_message('Elige a quién bloquear en tu sala. Si está dentro, se desconectará de ella.',
            view=MemberPicker(self.manager, self.owner, self.channel, False), ephemeral=True)


class RoomModal(discord.ui.Modal):
    def __init__(self, manager, owner, channel, kind):
        super().__init__(title='Cupo de tu sala' if kind == 'limit' else 'Nombre de tu sala', timeout=300)
        self.manager, self.owner, self.channel, self.kind = manager, owner, channel, kind
        self.value = discord.ui.TextInput(label='Personas (1 a 20)' if kind == 'limit' else 'Nombre (máximo 40 caracteres)',
            max_length=2 if kind == 'limit' else 40, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction):
        if interaction.user.id != self.owner:
            raise ValueError('Este formulario pertenece al creador de la sala.')
        await interaction.response.defer(ephemeral=True)
        if self.kind == 'limit':
            await self.manager.set_limit(interaction, self.channel, str(self.value))
        else:
            await self.manager.rename(interaction, self.channel, str(self.value))
        await interaction.followup.send('✅ Sala actualizada.', ephemeral=True)

    async def on_error(self, interaction, error):
        await VoiceView(self.manager).on_error(interaction, error, None)


class MemberPicker(VoiceView):
    def __init__(self, manager, owner, channel, allow):
        super().__init__(manager, timeout=300)
        self.owner, self.channel, self.allow = owner, channel, allow
        self.add_item(RoomMemberSelect())

    async def interaction_check(self, interaction):
        await super().interaction_check(interaction)
        if interaction.user.id != self.owner:
            raise ValueError('Solo el creador puede gestionar el acceso.')
        await self.manager.owned_room(interaction, self.channel)
        return True


class RoomMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder='Selecciona una persona', min_values=1, max_values=1)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        view = self.view
        await view.manager.set_access(interaction, view.channel, self.values[0].id, view.allow)
        await interaction.followup.send('✅ Acceso actualizado.', ephemeral=True)


class TempVoice:
    def __init__(self, system):
        self.system, self.bot = system, system.bot
        self.store = VoiceStore(system.path)
        self.lock = asyncio.Lock()
        self.ready_lock = asyncio.Lock()
        self.task = None
        self.configured = False

    async def call(self, name, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, name), *args, **kwargs)

    def authorize(self, interaction):
        self.system.authorize(interaction)
        if not self.configured:
            raise ValueError('Las salas están terminando de arrancar. Inténtalo en unos segundos.')

    async def start(self):
        await self.call('initialize')
        self.bot.add_view(VoicePanel(self))

    async def ready(self):
        async with self.ready_lock:
            if self.configured:
                return
            guild = self.bot.get_guild(GUILD_ID)
            self.system.validate_guild(guild)
            if self.bot.user.id != BOT_ID or not self.bot.intents.voice_states:
                raise ValueError('Se requiere el bot del distrito con estados de voz activos.')
            if self.system.store.get('voice_release') != VOICE_VERSION:
                await self.system.track('VOICE_SETUP', 'Activar salas de voz temporales del corillo',
                    lambda: self.provision(guild), VOICE_VERSION)
            self.configured = True
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self.recover(), name='vice-tempvoice-recovery')
            log.info('VICE_VOICE_READY guild=%s panel=%s release=%s', GUILD_ID,
                self.system.channel_id('voicepanel'), VOICE_VERSION)

    async def provision(self, guild):
        channels = await guild.fetch_channels()
        category = discord.utils.get(channels, id=self.system.store.get('category:tempvoice'))
        category = category or discord.utils.get(channels, name=CATEGORY_NAME)
        category = category or discord.utils.get(channels, name=stylize(CATEGORY_NAME))
        category = category or discord.utils.get(channels, name='၊၊||၊ 🎙️ꜱᴀʟᴀꜱ ᴅᴇʟ ᴄᴏʀɪʟʟᴏ')
        category = category or discord.utils.get(channels, name=format_name(CATEGORY_NAME, category=True))
        if category is not None and (not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID):
            raise ValueError('La categoría de salas necesita revisión; no se modificó el canal existente.')
        if category is None:
            category = await guild.create_category(format_name(CATEGORY_NAME, category=True), position=4,
                overwrites=self.system.overwrites(guild, 'read'), reason='Salas temporales solicitadas por el propietario')
        await self.system.call('put', 'category:tempvoice', category.id)
        panel = discord.utils.get(channels, id=self.system.channel_id('voicepanel'))
        panel = panel or discord.utils.get(channels, name=PANEL_NAME)
        panel = panel or discord.utils.get(channels, name=stylize(PANEL_NAME))
        panel = panel or discord.utils.get(channels, name='🎛️│ᴄʀᴇᴀʀ-ᴍɪ-ꜱᴀʟᴀ')
        panel = panel or discord.utils.get(channels, name=format_name(PANEL_NAME))
        if panel is not None and (not isinstance(panel, discord.TextChannel) or panel.guild.id != GUILD_ID):
            raise ValueError('El panel de salas necesita revisión; no se modificó el canal existente.')
        if panel is None:
            panel = await guild.create_text_channel(format_name(PANEL_NAME), category=category,
                topic='Crea una sala de voz temporal y gestiona su acceso desde los botones.',
                overwrites=self.system.overwrites(guild, 'read'), reason='Panel de salas temporales solicitado por el propietario')
        await self.system.call('put', 'channel:voicepanel', panel.id)
        self.system.channel_cache['voicepanel'] = panel
        await self.system.panel(guild, 'voicepanel', ('🎙️ TU CREW, TU SALA',
            '**Desde Puerto Rico para todo el corillo latino.**\n\n'
            'Pulsa **Crear mi sala** y entra usando el enlace que recibirás. Empieza con **6 plazas**; puedes elegir entre **1 y 20**.\n\n'
            '**Administrar mi sala** permite abrir o cerrar la entrada, invitar personas, quitar acceso y cambiar el nombre. '
            'Cerrar la entrada no desconecta a quienes ya están dentro.\n\n'
            '**Una sala por persona.** Se elimina cuando queda vacía: 30 segundos después de usarla, '
            'o 2 minutos si todavía nadie ha entrado.\n\n'
            'Son salas de voz: el chat de texto está desactivado y la gestión se hace desde este panel. '
            'La administración y moderación conservan acceso para cuidar la comunidad.', CYAN), VoicePanel(self))
        await self.system.call('put', 'voice_release', VOICE_VERSION)

    def room_overwrites(self, guild, owner):
        rules = {guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True,
            speak=True, stream=True, use_voice_activation=True, send_messages=False,
            send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)}
        rules[owner] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
            stream=True, use_voice_activation=True, send_messages=False, send_messages_in_threads=False,
            manage_channels=False, manage_roles=False, manage_webhooks=False,
            move_members=False, mute_members=False, deafen_members=False)
        for key in ('founder', 'admin', 'mod'):
            role = self.system.role(guild, key)
            if role:
                rules[role] = discord.PermissionOverwrite(view_channel=True, connect=True,
                    speak=True, send_messages=False, move_members=True)
        rules[guild.me] = discord.PermissionOverwrite(view_channel=True, connect=True,
            manage_channels=True, manage_roles=True, move_members=True, send_messages=False)
        return rules

    def scoped(self, guild, channel):
        return (guild.id == GUILD_ID and isinstance(channel, discord.VoiceChannel) and channel.guild.id == GUILD_ID
                and channel.category_id == self.system.store.get('category:tempvoice'))

    async def snapshot(self, row, guild):
        channel = guild.get_channel(row['channel']) if row.get('channel') else None
        return dict(guild=GUILD_ID, room=row, channel=None if channel is None else
            dict(id=channel.id, name=channel.name, category=channel.category_id,
                occupied=list(channel.voice_states), user_limit=channel.user_limit,
                overwrites=[dict(id=t.id, allow=o.pair()[0].value, deny=o.pair()[1].value)
                            for t,o in channel.overwrites.items()]))

    async def tracked(self, kind, title, row, guild, operation, request):
        return await self.system.track(kind, title, operation, request,
            snapshot=lambda: self.snapshot(self.store.get(row['token']) or row, guild))

    async def owned_room(self, interaction, channel_id=None):
        self.authorize(interaction)
        row = await self.call('owned', interaction.user.id)
        if row is None:
            raise ValueError('Todavía no tienes una sala. Pulsa Crear mi sala.')
        if row['state'] != 'active' or not row['channel']:
            raise ValueError('Estamos comprobando la creación de tu sala. Inténtalo en unos segundos.')
        if channel_id is not None and row['channel'] != channel_id:
            raise ValueError('Este control pertenece a una sala anterior. Usa Administrar mi sala.')
        channel = interaction.guild.get_channel(row['channel'])
        if not self.scoped(interaction.guild, channel):
            raise ValueError('La sala necesita revisión del equipo; no se aplicó ningún cambio.')
        return row, channel

    async def create_room(self, interaction):
        self.authorize(interaction)
        guild = interaction.guild
        async with self.lock:
            existing = await self.call('owned', interaction.user.id)
            if existing:
                if existing['state'] == 'active':
                    _, channel = await self.owned_room(interaction)
                    return channel
                await self.reconcile_pending(guild, existing)
                _, channel = await self.owned_room(interaction)
                return channel
            category = guild.get_channel(self.system.store.get('category:tempvoice'))
            if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
                raise ValueError('No se encontró la categoría de salas del corillo.')
            row, created = await self.call('reserve', interaction.user.id, time.time())
            if not created:
                raise ValueError('Tu sala ya se está creando. Espera unos segundos.')
            name = clean_name(interaction.user.display_name)[:32] or 'Mi crew'
            async def create():
                channel = await guild.create_voice_channel(format_name('┊・🎙️│' + name), category=category,
                    bitrate=64000, user_limit=6, overwrites=self.room_overwrites(guild, interaction.user),
                    reason='VICE_TEMP:' + row['token'])
                await self.call('update', row['token'], channel=channel.id, state='active')
                return channel
            return await self.tracked('VOICE_CREATE', 'Crear sala temporal de voz', row, guild, create, row['token'])

    async def set_locked(self, interaction, channel_id, locked):
        async with self.lock:
            row, channel = await self.owned_room(interaction, channel_id)
            overwrite = channel.overwrites_for(interaction.guild.default_role)
            overwrite.connect = not locked
            async def apply():
                await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason='El creador cambia el acceso a su sala temporal')
                await self.call('update', row['token'], locked=int(locked))
            await self.tracked('VOICE_ACCESS', 'Abrir o cerrar entrada a sala temporal', row, interaction.guild, apply, interaction.id)

    async def set_limit(self, interaction, channel_id, value):
        if not str(value).isdecimal() or not 1 <= int(value) <= 20:
            raise ValueError('El cupo debe ser un número del 1 al 20.')
        async with self.lock:
            row, channel = await self.owned_room(interaction, channel_id)
            await self.tracked('VOICE_LIMIT', 'Cambiar cupo de sala temporal', row, interaction.guild,
                lambda: channel.edit(user_limit=int(value), reason='Cupo elegido por el creador de la sala'), interaction.id)

    async def rename(self, interaction, channel_id, value):
        value = clean_name(value).strip()
        if not value or len(value) > 40:
            raise ValueError('Escribe un nombre entre 1 y 40 caracteres.')
        async with self.lock:
            row, channel = await self.owned_room(interaction, channel_id)
            now = time.time()
            if row['renamed'] and now - row['renamed'] < RENAME_COOLDOWN:
                raise ValueError('Puedes cambiar el nombre una vez cada 5 minutos.')
            async def apply():
                await channel.edit(name=format_name('┊・🎙️│' + value), reason='Nombre elegido por el creador de la sala')
                await self.call('update', row['token'], renamed=now)
            await self.tracked('VOICE_RENAME', 'Renombrar sala temporal', row, interaction.guild, apply, interaction.id)

    async def set_access(self, interaction, channel_id, user_id, allow):
        async with self.lock:
            row, channel = await self.owned_room(interaction, channel_id)
            target = await interaction.guild.fetch_member(int(user_id))
            protected = {self.system.store.get('role:founder'), self.system.store.get('role:admin'), self.system.store.get('role:mod')}
            if target.bot or target.id in {row['owner'], OWNER_ID, BOT_ID} or target.guild_permissions.administrator or any(r.id in protected for r in target.roles):
                raise ValueError('No puedes cambiar el acceso del creador, los bots o el equipo de moderación.')
            overwrite = channel.overwrites_for(target)
            overwrite.view_channel = True
            overwrite.connect = bool(allow)
            overwrite.send_messages = False
            async def apply():
                await channel.set_permissions(target, overwrite=overwrite, reason='Acceso elegido por el creador de la sala temporal')
                if not allow and target.voice and target.voice.channel and target.voice.channel.id == channel.id:
                    await target.move_to(None, reason='El creador retiró el acceso a su sala temporal')
            await self.tracked('VOICE_MEMBER_ACCESS', 'Gestionar invitado de sala temporal', row, interaction.guild, apply, interaction.id)

    async def reconcile_pending(self, guild, row):
        """Only adopt an exact bot-authored create action with our durable nonce."""
        self.system.validate_guild(guild)
        try:
            async for entry in guild.audit_logs(limit=100, action=discord.AuditLogAction.channel_create):
                if (getattr(entry.user, 'id', None) == BOT_ID and entry.reason == 'VICE_TEMP:' + row['token']):
                    channel = guild.get_channel(getattr(entry.target, 'id', None))
                    if self.scoped(guild, channel):
                        await self.call('update', row['token'], channel=channel.id, state='active')
                        return channel
        except discord.HTTPException:
            log.warning('VICE_VOICE_PENDING_AUDIT_FAILED token=%s', row['token'])
        # Do not retry creation or infer ownership from a room name. Keep the
        # reservation until exact audit evidence or manual operator review.
        return None

    async def inspect_room(self, guild, row, now):
        self.system.validate_guild(guild)
        if not self.bot.is_ready() or guild.unavailable:
            return
        if row['state'] == 'creating':
            await self.reconcile_pending(guild, row)
            return
        channel = guild.get_channel(row['channel'])
        if channel is None:
            try:
                channel = await guild.fetch_channel(row['channel'])
            except discord.NotFound:
                await self.call('update', row['token'], state='closed')
                return
            # HTTP channel fetches contain no authoritative voice occupancy.
            # Wait for the gateway to populate the room, never delete here.
            return
        if not self.scoped(guild, channel):
            log.warning('VICE_VOICE_SCOPE_CHANGED channel=%s', row['channel'])
            return
        if channel.voice_states:
            if row['empty_since'] is not None or not row['used']:
                await self.call('update', row['token'], used=1, empty_since=None)
            return
        if row['empty_since'] is None:
            await self.call('update', row['token'], empty_since=now)
            return
        grace = EMPTY_GRACE if row['used'] else NEW_GRACE
        if now - row['empty_since'] < grace:
            return
        async def remove():
            latest = await self.call('channel', row['channel'])
            current = guild.get_channel(row['channel'])
            if (latest is None or not self.scoped(guild, current) or current.voice_states
                    or not self.bot.is_ready() or guild.unavailable):
                return
            try:
                await current.delete(reason='Sala temporal registrada vacía; limpieza automática autorizada')
            except discord.NotFound:
                pass
            await self.call('update', row['token'], state='closed')
            log.info('VICE_VOICE_REMOVED channel=%s owner=%s', row['channel'], row['owner'])
        await self.tracked('VOICE_DELETE', 'Eliminar sala temporal vacía', row, guild, remove, row['token'])

    async def sweep(self):
        if not self.configured or not self.bot.is_ready():
            return
        guild = self.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if guild.unavailable:
            return
        async with self.lock:
            for row in await self.call('rows'):
                try:
                    await self.inspect_room(guild, row, time.time())
                except Exception:
                    log.exception('VICE_VOICE_RECOVERY_FAILED channel=%s', row['channel'])

    async def recover(self):
        # Gateway state must settle after a connection/restart before cleanup.
        await asyncio.sleep(30)
        while not self.bot.is_closed():
            await self.sweep()
            await asyncio.sleep(15)

    async def voice_state_update(self, member, before, after):
        if member.guild.id != GUILD_ID or not self.configured:
            return
        ids = {c.id for c in (before.channel, after.channel) if c is not None}
        async with self.lock:
            for channel_id in ids:
                row = await self.call('channel', channel_id)
                if row:
                    await self.inspect_room(member.guild, row, time.time())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
