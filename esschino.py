"""EssChino's separate storefront guild; one explicitly scoped installation."""
import asyncio
from contextlib import closing
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

import discord

from studio_journal import server_snapshot

log = logging.getLogger('EssChino')
PROTECTED_CHANNEL = 1514871828672151573
ORIGINAL_GUILD = 1244988345327550565
REQUEST = 'esschino-store-20261115-v1'
ENV = 'ESSCHINO_SETUP_REQUEST_ID'
COLOR = 0xA535F5
ASSETS = Path(__file__).parent / 'assets' / 'esschino'
REASON = 'Solicitud del propietario: personalizar su servidor de tienda EssChino'

ROLE_SPECS = [
    ('founder', '👑 Fundador · Studio', 0xD9B3FF, dict(administrator=True)),
    ('admin', '⚜️ Administración · Studio', 0xB34DFF, dict(administrator=True)),
    ('dev', '💻 Desarrollo · Studio', 0x7B61FF, dict(manage_messages=True, manage_threads=True, moderate_members=True)),
    ('support', '🛠️ Soporte · Studio', 0x56C9E8, dict(manage_messages=True, moderate_members=True)),
    ('customer', '💎 Cliente verificado', 0xE4BB52, {}),
    ('member', '👤 Comunidad EssChino', 0xBAC0CC, {}),
    ('news', '📣 Avisos EssChino', 0x000000, {}),
    ('updates', '🔄 Scripts EssChino', 0x000000, {}),
]
CATEGORIES = [
    ('info', '📌 INFORMACIÓN', 'read'), ('store', '🛒 TIENDA', 'read'),
    ('help', '🛠️ SOPORTE', 'read'), ('community', '💬 COMUNIDAD', 'chat'),
    ('team', '🔒 EQUIPO', 'staff'),
]
# key, category, channel name, topic, permission policy, voice
CHANNELS = [
    ('welcome', 'info', '👋・bienvenida', 'Empieza aquí · EssChino, scripts y comunidad.', 'read', False),
    ('rules', 'info', '📜・normas', 'Normas de convivencia, compras y soporte.', 'read', False),
    ('announcements', 'info', '📢・anuncios', 'Comunicados oficiales de EssChino.', 'read', False),
    ('buying', 'info', '🧭・cómo-comprar', 'Compra y entrega de scripts a través de Tebex.', 'read', False),
    ('shop', 'store', '🛍️・tienda-tebex', 'Acceso a la tienda oficial y ayuda para comprar.', 'read', False),
    ('catalog', 'store', '📦・catálogo-scripts', 'Scripts · funciones, requisitos y compatibilidad por producto.', 'read', False),
    ('demos', 'store', '🎬・demostraciones', 'Vídeos y pruebas de los productos oficiales.', 'read', False),
    ('offers', 'store', '🏷️・ofertas', 'Promociones oficiales con sus condiciones y vigencia.', 'read', False),
    ('changelog', 'store', '🔄・actualizaciones', 'Versiones, correcciones y cambios de compatibilidad.', 'read', False),
    ('support', 'help', '🎫・abrir-ticket', 'Compras, instalación, errores y colaboraciones en privado.', 'read', False),
    ('install', 'help', '📚・guías-instalación', 'Preparación, dependencias y diagnóstico de recursos.', 'read', False),
    ('faq', 'help', '❓・preguntas-frecuentes', 'Respuestas antes y después de comprar.', 'read', False),
    ('general', 'community', '💬・general', 'Habla con la comunidad de EssChino.', 'chat', False),
    ('suggestions', 'community', '💡・sugerencias', 'Propón mejoras mediante el formulario y vota las ideas de la comunidad.', 'read', False),
    ('reviews', 'community', '⭐・reseñas', 'Opiniones de clientes con compra verificada.', 'review', False),
    ('staff', 'team', '👥・chat-staff', 'Coordinación privada del equipo de EssChino Studio.', 'staff', False),
    ('management', 'team', '📋・gestión-soporte', 'Panel privado de seguimiento de los tickets y pedidos.', 'staffread', False),
    ('log', 'team', '📑・registros', 'Aperturas, cierres, cambios y verificaciones de compra.', 'staffread', False),
]


def validate_target(channel, saved_guild=None):
    guild = channel.guild
    if channel.id != PROTECTED_CHANNEL or guild.id == ORIGINAL_GUILD:
        raise ValueError('La solicitud no puede ejecutarse sobre La Venganza RP ni otro canal.')
    if saved_guild is not None and guild.id != int(saved_guild):
        raise ValueError('El servidor no coincide con la copia original de EssChino.')
    # The owner's exact channel ID is the authoritative destination. Account
    # display names and alternate owner accounts are not an authorization test.
    if not isinstance(channel, discord.TextChannel):
        raise ValueError('El canal que se debe conservar tiene que ser un canal de texto.')
    if not guild.me or not guild.me.guild_permissions.administrator:
        raise ValueError('El bot necesita Administrador en el servidor EssChino para instalarlo.')
    return guild


def valid_shop_url(value):
    value = value.strip()
    parts = urlsplit(value)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or any(c.isspace() for c in value) or len(value) > 500):
        raise ValueError('Introduce el enlace HTTPS completo de tu tienda oficial.')
    return value


def deletion_plan(channels, original_ids, guild_id):
    if guild_id == ORIGINAL_GUILD or PROTECTED_CHANNEL in original_ids:
        raise ValueError('La lista de limpieza incluye un servidor o canal protegido.')
    selected = [c for c in channels if c.id in original_ids]
    if any(c.guild.id != guild_id for c in selected):
        raise ValueError('La lista de limpieza contiene canales de otro servidor.')
    return sorted(selected, key=lambda c: isinstance(c, discord.CategoryChannel))


class StudioStore:
    def __init__(self, path):
        self.path = path

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def initialize(self):
        with closing(self.db()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS esschino_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS esschino_tickets(
                    channel TEXT PRIMARY KEY, owner TEXT NOT NULL, kind TEXT NOT NULL,
                    state TEXT NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS esschino_messages(
                    scope TEXT NOT NULL, channel TEXT NOT NULL, message TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(scope,channel,message));
                CREATE TABLE IF NOT EXISTS esschino_files(
                    attachment TEXT PRIMARY KEY, filename TEXT NOT NULL,
                    data BLOB NOT NULL, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS esschino_purchases(
                    reference TEXT PRIMARY KEY, owner TEXT NOT NULL, verified_by TEXT NOT NULL,
                    verified INTEGER NOT NULL);
            ''')

    def get(self, key, default=None):
        with closing(self.db()) as db:
            row = db.execute('SELECT value FROM esschino_config WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with closing(self.db()) as db, db:
            db.execute('INSERT OR REPLACE INTO esschino_config VALUES (?,?)',
                       (key, json.dumps(value, ensure_ascii=False)))

    def ticket(self, channel):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM esschino_tickets WHERE channel=?', (str(channel),)).fetchone()
            return dict(row) if row else None

    def tickets(self, owner=None):
        with closing(self.db()) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM esschino_tickets'
                + (' WHERE owner=?' if owner is not None else ''), (str(owner),) if owner is not None else ())]

    def add_ticket(self, channel, owner, kind):
        with closing(self.db()) as db, db:
            db.execute('INSERT OR IGNORE INTO esschino_tickets VALUES (?,?,?,\'open\',?)',
                       (str(channel), str(owner), kind, int(time.time())))

    def ticket_state(self, channel, state):
        with closing(self.db()) as db, db:
            db.execute('UPDATE esschino_tickets SET state=? WHERE channel=?', (state, str(channel)))

    def save_message(self, scope, channel, message, payload):
        with closing(self.db()) as db, db:
            db.execute('INSERT OR REPLACE INTO esschino_messages VALUES (?,?,?,?)',
                       (scope, str(channel), str(message), json.dumps(payload, ensure_ascii=False)))

    def save_file(self, attachment, filename, data):
        digest = hashlib.sha256(data).hexdigest()
        with closing(self.db()) as db, db:
            db.execute('INSERT OR REPLACE INTO esschino_files VALUES (?,?,?,?)',
                       (str(attachment), filename, data, digest))
            saved = db.execute('SELECT data,sha256 FROM esschino_files WHERE attachment=?', (str(attachment),)).fetchone()
            if hashlib.sha256(saved[0]).hexdigest() != saved[1]:
                raise ValueError('El adjunto no pasó la verificación de la copia.')

    def transcript(self, channel):
        with closing(self.db()) as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT payload FROM esschino_messages WHERE scope='ticket' AND channel=? ORDER BY length(message),message",
                (str(channel),))]

    def purchase(self, reference, owner, verifier):
        reference = reference.strip().casefold()
        if not reference or len(reference) > 100:
            raise ValueError('Introduce la referencia del pedido verificado en Tebex.')
        with closing(self.db()) as db, db:
            row = db.execute('SELECT owner FROM esschino_purchases WHERE reference=?', (reference,)).fetchone()
            if row and row[0] != str(owner):
                raise ValueError('Ese pedido ya está asociado a otra cuenta; revísalo en Tebex.')
            db.execute('INSERT OR IGNORE INTO esschino_purchases VALUES (?,?,?,?)',
                       (reference, str(owner), str(verifier), int(time.time())))


class StudioView(discord.ui.View):
    def __init__(self, system):
        super().__init__(timeout=None)
        self.system = system

    async def interaction_check(self, i):
        if i.guild_id != self.system.store.get('guild') or not isinstance(i.user, discord.Member) or i.user.bot:
            await i.response.send_message('Este panel pertenece al servidor EssChino.', ephemeral=True)
            return False
        return True

    async def on_error(self, i, error, item):
        log.exception('ESSCHINO interaction failed', exc_info=error)
        send = i.followup.send if i.response.is_done() else i.response.send_message
        text = str(error) if isinstance(error, ValueError) else 'No se pudo completar la acción. Contacta con el equipo.'
        await send(text[:1500], ephemeral=True)


class EntryView(StudioView):
    @discord.ui.button(label='Unirme a la comunidad', emoji='👤', custom_id='ec:member', style=discord.ButtonStyle.primary)
    async def join(self, i, button):
        await self.system.toggle_role(i, 'member', toggle=False)

    @discord.ui.button(label='Ayuda y compras', emoji='🎫', custom_id='ec:help')
    async def help(self, i, button):
        await i.response.send_message(f"Abre tu consulta en <#{self.system.channel_id('support')}>.", ephemeral=True)

    @discord.ui.button(label='Avisos', emoji='📣', custom_id='ec:welcome-news')
    async def news(self, i, button):
        await self.system.toggle_role(i, 'news')

    @discord.ui.button(label='Actualizaciones', emoji='🔄', custom_id='ec:welcome-updates')
    async def updates(self, i, button):
        await self.system.toggle_role(i, 'updates')


class NotificationsView(StudioView):
    @discord.ui.button(label='Avisos generales', emoji='📣', custom_id='ec:news')
    async def news(self, i, button):
        await self.system.toggle_role(i, 'news')

    @discord.ui.button(label='Actualizaciones', emoji='🔄', custom_id='ec:updates')
    async def updates(self, i, button):
        await self.system.toggle_role(i, 'updates')


class SupportView(StudioView):
    @discord.ui.select(custom_id='ec:open', placeholder='Selecciona el motivo de tu consulta', options=[
        discord.SelectOption(label='Compras y pedidos', value='compras', emoji='🛒'),
        discord.SelectOption(label='Instalación y soporte', value='soporte', emoji='🛠️'),
        discord.SelectOption(label='Reportar un error', value='error', emoji='🐛'),
        discord.SelectOption(label='Colaboraciones', value='colaboracion', emoji='🤝')])
    async def choose(self, i, select):
        await i.response.send_modal(TicketModal(self.system, select.values[0]))


class TicketModal(discord.ui.Modal, title='EssChino · Consulta privada'):
    product = discord.ui.TextInput(label='Producto o asunto', max_length=100)
    order = discord.ui.TextInput(label='Referencia de pedido Tebex (si tienes)', required=False, max_length=100)
    details = discord.ui.TextInput(label='Describe tu consulta', style=discord.TextStyle.paragraph, max_length=1800)

    def __init__(self, system, kind):
        super().__init__()
        self.system, self.kind = system, kind

    async def on_submit(self, i):
        await self.system.open_ticket(i, self.kind, str(self.product), str(self.order), str(self.details))

    async def on_error(self, i, error):
        await StudioView(self.system).on_error(i, error, None)


class AdminView(StudioView):
    @discord.ui.button(label='Configurar enlace de Tebex', emoji='🛒', custom_id='ec:configure', style=discord.ButtonStyle.primary)
    async def configure(self, i, button):
        if not i.user.guild_permissions.administrator:
            raise ValueError('Solo la administración puede cambiar el enlace de compra.')
        await i.response.send_modal(ShopModal(self.system))


class ManagementView(StudioView):
    async def show(self, i, state):
        if not self.system.staff(i.user):
            raise ValueError('Solo el equipo puede consultar el seguimiento de soporte.')
        await i.response.defer(ephemeral=True)
        rows = [r for r in await self.system.call('tickets') if r['state'] == state]
        lines = [f'<#{r["channel"]}> · <@{r["owner"]}> · {r["kind"]}' for r in rows[-25:]]
        await i.followup.send('\n'.join(lines) or 'No hay tickets en ese estado.', ephemeral=True)

    @discord.ui.button(label='Tickets abiertos', emoji='🎫', custom_id='ec:manage:open', style=discord.ButtonStyle.primary)
    async def opened(self, i, button):
        await self.show(i, 'open')

    @discord.ui.button(label='Tickets cerrados', emoji='🔒', custom_id='ec:manage:closed')
    async def closed(self, i, button):
        await self.show(i, 'closed')


class ShopModal(discord.ui.Modal, title='EssChino · Tienda oficial'):
    url = discord.ui.TextInput(label='Enlace HTTPS de la tienda Tebex', max_length=500)

    def __init__(self, system):
        super().__init__()
        self.system = system
        self.url.default = system.store.get('shop_url', '')

    async def on_submit(self, i):
        if i.guild_id != self.system.store.get('guild') or not i.user.guild_permissions.administrator:
            raise ValueError('Solo la administración de EssChino puede cambiar la tienda.')
        value = valid_shop_url(str(self.url))
        await i.response.defer(ephemeral=True)
        async def apply():
            await self.system.call('put', 'shop_url', value)
            await self.system.publish_panel(i.guild, 'shop', refresh=True)
        await self.system.tracked(f'shop:{i.id}', 'Actualizar tienda de EssChino', apply)
        await i.followup.send('Enlace oficial actualizado en el panel de compra.', ephemeral=True)

    async def on_error(self, i, error):
        await StudioView(self.system).on_error(i, error, None)


class TicketView(StudioView):
    @discord.ui.button(label='Cerrar ticket', emoji='🔒', custom_id='ec:close')
    async def close(self, i, button):
        await self.system.set_ticket_state(i, False)

    @discord.ui.button(label='Reabrir', emoji='🔓', custom_id='ec:reopen')
    async def reopen(self, i, button):
        await self.system.set_ticket_state(i, True)

    @discord.ui.button(label='Transcripción', emoji='📄', custom_id='ec:transcript')
    async def transcript(self, i, button):
        self.system.ticket_access(i)
        await i.response.defer(ephemeral=True)
        await self.system.archive_channel(i.channel, 'ticket')
        data = await self.system.call('transcript', i.channel_id)
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode()
        if len(payload) > i.guild.filesize_limit:
            raise ValueError('La transcripción supera el límite de Discord; solicita al propietario la copia privada del volumen.')
        await i.followup.send(file=discord.File(io.BytesIO(payload), filename=f'esschino-ticket-{i.channel_id}.json'), ephemeral=True)

    @discord.ui.button(label='Verificar compra', emoji='💎', custom_id='ec:verify', style=discord.ButtonStyle.success)
    async def verify(self, i, button):
        self.system.ticket_access(i, staff=True)
        await i.response.send_modal(PurchaseModal(self.system))


class PurchaseModal(discord.ui.Modal, title='Compra comprobada en Tebex'):
    reference = discord.ui.TextInput(label='Referencia que comprobaste en Tebex', max_length=100)
    confirmation = discord.ui.TextInput(label='Escribe VERIFICADO para confirmar', max_length=10)

    def __init__(self, system):
        super().__init__()
        self.system = system

    async def on_submit(self, i):
        row = self.system.ticket_access(i, staff=True)
        if str(self.confirmation).strip().upper() != 'VERIFICADO':
            raise ValueError('Primero comprueba el pedido en el panel de Tebex y escribe VERIFICADO.')
        await i.response.defer(ephemeral=True)
        async with self.system.lock:
            member = await i.guild.fetch_member(int(row['owner']))
            role = self.system.role(i.guild, 'customer')
            if role is None:
                raise ValueError('No encuentro el rol Cliente; contacta con el propietario.')
            async def apply():
                await self.system.call('purchase', str(self.reference), member.id, i.user.id)
                await member.add_roles(role, reason='Compra comprobada manualmente por soporte en Tebex')
            await self.system.tracked(f'purchase:{i.id}', 'Verificar cliente de EssChino', apply, members=(member.id, i.user.id))
        await i.followup.send('Compra registrada y rol Cliente asignado.', ephemeral=True)
        await self.system.audit(i.guild, f'💎 Compra verificada · cliente <@{member.id}> · revisó <@{i.user.id}> · ticket <#{i.channel_id}>.')

    async def on_error(self, i, error):
        await StudioView(self.system).on_error(i, error, None)


class EssChino:
    def __init__(self, bot, path):
        self.bot, self.store = bot, StudioStore(path)
        self.lock = asyncio.Lock()
        self.roles = {}
        self.channels = {}

    async def call(self, method, *args):
        return await asyncio.to_thread(getattr(self.store, method), *args)

    async def start(self):
        await self.call('initialize')
        for view in (EntryView, NotificationsView, SupportView, AdminView, TicketView, ManagementView):
            self.bot.add_view(view(self))

    def channel_id(self, key):
        return self.store.get('channel:' + key)

    def role(self, guild, key):
        rid = self.store.get('role:' + key, 0)
        return self.roles.get(rid) or guild.get_role(rid)

    def channel(self, guild, key):
        cid = self.store.get(key, 0)
        return self.channels.get(cid) or guild.get_channel(cid)

    def staff(self, member):
        return bool(member.guild_permissions.administrator or member.id == member.guild.owner_id
                    or {r.id for r in member.roles} & {
                        self.store.get('role:' + k) for k in ('founder', 'admin', 'dev', 'support')})

    def ticket_access(self, i, staff=False):
        if i.guild_id != self.store.get('guild') or not isinstance(i.user, discord.Member):
            raise ValueError('Esta acción pertenece a EssChino.')
        row = self.store.ticket(i.channel_id)
        if not row or not (self.staff(i.user) or (not staff and str(i.user.id) == row['owner'])):
            raise ValueError('No tienes acceso a este ticket.')
        return row

    async def snapshot(self, guild, members=()):
        member_states = []
        for uid in {guild.owner_id, self.bot.user.id, *members}:
            try:
                member = await guild.fetch_member(uid)
                member_states.append(dict(id=uid, roles=[r.id for r in member.roles], nick=member.nick))
            except discord.NotFound:
                member_states.append(dict(id=uid, left=True))
        return dict(guild_id=guild.id, guild_name=guild.name, owner_id=guild.owner_id,
                    icon=str(guild.icon) if guild.icon else None,
                    banner=str(guild.banner) if guild.banner else None,
                    server=await server_snapshot(guild),
                    config={key: self.store.get(key) for key in ('guild', 'original_channels', 'setup_complete', 'shop_url')},
                    members=member_states, tickets=await self.call('tickets'),
                    community=await self.community.call('snapshot') if hasattr(self, 'community') else {})

    async def tracked(self, request, title, operation, members=()):
        guild = self.bot.get_guild(self.store.get('guild'))
        if guild is None or guild.id == ORIGINAL_GUILD:
            raise ValueError('No se confirmó el servidor EssChino para el registro.')
        return await self.bot.changes.tracked('ESSCHINO_ACTION', title, operation,
            request_id=request, snapshot=lambda: self.snapshot(guild, members))

    def overwrites(self, guild, policy, owner=None):
        private = policy in {'owner', 'staff', 'staffread', 'customer', 'customerchat'}
        writing = policy in {'chat', 'customerchat', 'staff'}
        overwrites = {guild.default_role: discord.PermissionOverwrite(
            view_channel=not private, read_message_history=True,
            send_messages=writing and not private, add_reactions=not private,
            create_public_threads=False, create_private_threads=False,
            send_messages_in_threads=False, mention_everyone=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                read_message_history=True, embed_links=True, attach_files=True,
                connect=True, speak=True, manage_channels=True, manage_messages=True)}
        if owner:
            overwrites[owner] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if policy == 'owner':
            return overwrites
        for key in ('founder', 'admin', 'dev', 'support'):
            role = self.role(guild, key)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                    read_message_history=True, add_reactions=True, connect=True, speak=True)
        if policy in {'customer', 'customerchat', 'review'}:
            role = self.role(guild, 'customer')
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=policy == 'customerchat', add_reactions=True)
        return overwrites

    async def archive_message(self, message, scope):
        payload = dict(id=str(message.id), author=str(message.author.id), username=str(message.author),
            content=message.content, created=message.created_at.isoformat(),
            edited=message.edited_at.isoformat() if message.edited_at else None,
            embeds=[e.to_dict() for e in message.embeds], components=[c.to_dict() for c in message.components],
            attachments=[dict(id=str(a.id), filename=a.filename, size=a.size, url=a.url) for a in message.attachments])
        for attachment in message.attachments:
            try:
                data = await attachment.read()
            except discord.HTTPException:
                data = await attachment.read(use_cached=True)
            await self.call('save_file', attachment.id, attachment.filename, data)
        await self.call('save_message', scope, message.channel.id, message.id, payload)

    async def archive_channel(self, channel, scope):
        if isinstance(channel, discord.abc.Messageable):
            async for message in channel.history(limit=None, oldest_first=True):
                await self.archive_message(message, scope)

    async def archive_originals(self, guild, originals):
        ids = {c.id for c in originals}
        threads = {t.id: t for t in await guild.active_threads() if t.parent_id in ids}
        for channel in originals:
            await self.archive_channel(channel, REQUEST)
            if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                async for thread in channel.archived_threads(limit=None):
                    threads[thread.id] = thread
                if isinstance(channel, discord.TextChannel):
                    async for thread in channel.archived_threads(limit=None, private=True):
                        threads[thread.id] = thread
        for thread in threads.values():
            await self.archive_channel(thread, REQUEST)
        await self.call('put', 'archive_complete', int(time.time()))
        log.info('ESSCHINO archive_verified guild=%s channels=%s threads=%s', guild.id, len(originals), len(threads))

    async def ready(self):
        if os.getenv(ENV, '').strip() != REQUEST:
            return
        async with self.lock:
            try:
                protected = await self.bot.fetch_channel(PROTECTED_CHANNEL)
            except discord.HTTPException as error:
                log.error('ESSCHINO blocked protected_channel=%s http=%s code=%s', PROTECTED_CHANNEL, error.status, error.code)
                return
            log.info('ESSCHINO candidate channel=%s guild=%s name=%s owner=%s',
                     protected.id, protected.guild.id, protected.guild.name, protected.guild.owner_id)
            guild = validate_target(protected, self.store.get('guild'))
            self.roles = {r.id: r for r in await guild.fetch_roles()}
            self.channels = {c.id: c for c in await guild.fetch_channels()}
            log.info('ESSCHINO target guild=%s name=%s owner=%s administrator=%s channels=%s',
                guild.id, guild.name, guild.owner_id, guild.me.guild_permissions.administrator, len(guild.channels))
            if self.store.get('setup_complete'):
                await self.verify(guild)
                return
            for filename in ('logo.jpg', 'banner.jpg'):
                if not (ASSETS / filename).is_file():
                    raise ValueError('Falta una imagen original de EssChino; no se cambió el servidor.')
            originals = self.store.get('original_channels')
            if originals is None:
                # Freeze only the five other channels in the owner's original server.
                authorized = {1514871828672151572,1514871828672151574,
                              1514871828672151575,1514871828672151576,1514871828672151577}
                originals = [c.id for c in await guild.fetch_channels() if c.id in authorized]
                await self.call('put', 'original_channels', originals)
            await self.call('put', 'guild', guild.id)
            async def apply():
                await self.install(guild, protected, originals)
            await self.bot.changes.tracked(ENV, 'Personalización completa del servidor EssChino', apply,
                request_id=REQUEST, snapshot=lambda: self.snapshot(guild))

    async def install(self, guild, protected, original_ids):
        owner = await guild.fetch_member(guild.owner_id)
        # First mutation: preserve the requested channel and make it owner-only.
        await protected.edit(category=None, overwrites=self.overwrites(guild, 'owner', owner), reason=REASON)
        fresh = await self.bot.fetch_channel(PROTECTED_CHANNEL)
        if fresh.permissions_for(guild.default_role).view_channel:
            raise ValueError('No se confirmó la privacidad del canal; no se borraron otros canales.')
        log.info('ESSCHINO protected_private channel=%s guild=%s', protected.id, guild.id)
        originals = [c for c in await guild.fetch_channels() if c.id in original_ids and c.id != PROTECTED_CHANNEL]
        await self.archive_originals(guild, originals)

        for key, name, color, permissions in ROLE_SPECS:
            saved = self.store.get('role:' + key)
            role = self.roles.get(saved) if saved else None
            if role is None:
                matches = [r for r in await guild.fetch_roles() if r.name == name and not r.managed]
                if len(matches) > 1:
                    raise ValueError(f'Hay varios roles {name}; no se modificaron.')
                role = matches[0] if matches else await guild.create_role(name=name, color=color,
                    permissions=discord.Permissions(**permissions), hoist=key in {'founder', 'admin', 'dev', 'support', 'customer'},
                    mentionable=False, reason=REASON)
                await self.call('put', 'role:' + key, role.id)
            self.roles[role.id] = role
        founder = self.role(guild, 'founder')
        if founder not in owner.roles:
            await owner.add_roles(founder, reason=REASON)

        for key, name, policy in CATEGORIES:
            category = await self.ensure_channel(guild, 'category:' + key, name, category=True,
                overwrites=self.overwrites(guild, policy, owner))
            await category.edit(position=[c[0] for c in CATEGORIES].index(key), reason=REASON)
        for key, parent, name, topic, policy, voice in CHANNELS:
            category = self.channel(guild, 'category:' + parent)
            await self.ensure_channel(guild, 'channel:' + key, name, parent=category, voice=voice,
                topic=topic, overwrites=self.overwrites(guild, policy, owner))
        await protected.edit(name='🔒・dirección', category=self.channel(guild, 'category:team'),
            overwrites=self.overwrites(guild, 'owner', owner), sync_permissions=False, reason=REASON)
        kwargs = dict(name='EssChino Studio', icon=(ASSETS / 'logo.jpg').read_bytes(),
            verification_level=discord.VerificationLevel.low,
            default_notifications=discord.NotificationLevel.only_mentions,
            explicit_content_filter=discord.ContentFilter.all_members,
            system_channel=self.channel(guild, 'channel:welcome'),
            system_channel_flags=discord.SystemChannelFlags(join_notifications=False, premium_subscriptions=False))
        if 'BANNER' in guild.features:
            kwargs['banner'] = (ASSETS / 'banner.jpg').read_bytes()
        if 'INVITE_SPLASH' in guild.features:
            kwargs['splash'] = (ASSETS / 'banner.jpg').read_bytes()
        if 'COMMUNITY' in guild.features:
            kwargs['rules_channel'] = self.channel(guild, 'channel:rules')
            kwargs['public_updates_channel'] = self.channel(guild, 'channel:staff')
        await guild.edit(**kwargs, reason=REASON)
        await guild.me.edit(nick='EssChino · Soporte', reason=REASON)
        supplied_url = os.getenv('ESSCHINO_TEBEX_URL', '').strip()
        if supplied_url:
            await self.call('put', 'shop_url', valid_shop_url(supplied_url))
        for key, *rest in CHANNELS:
            if not rest[-1]:
                await self.publish_panel(guild, key)
        await self.publish_admin(protected)

        # Delete only the frozen original inventory, never newly created channels.
        current = {c.id: c for c in await guild.fetch_channels()}
        ordered = deletion_plan(current.values(), original_ids, guild.id)
        for channel in ordered:
            if channel.guild.id != guild.id or guild.id == ORIGINAL_GUILD or channel.id == PROTECTED_CHANNEL:
                raise ValueError('Eliminación fuera del alcance de EssChino bloqueada.')
            await channel.delete(reason=REASON + ' · copia privada previa verificada')
            log.info('ESSCHINO deleted_original guild=%s channel=%s', guild.id, channel.id)
        # Empty categories created by the interrupted shared-bot attempt, before
        # the owner supplied the final five-category layout. Never delete new
        # user channels or populated categories here.
        abandoned = {1571639437400608910,1571639441452175373,1571639445009207337,
            1571639448339349514,1571639451094876160,1571639643491926116,1571639648680288407}
        present = await guild.fetch_channels()
        for category in present:
            if (category.id in abandoned and isinstance(category, discord.CategoryChannel)
                    and not any(c.category_id == category.id for c in present)):
                await category.delete(reason='Aplicar las cinco categorías solicitadas por el propietario')
        await self.verify(guild)
        if not self.store.get('completion_message'):
            message = await protected.send(embed=self.embed('✅ EssChino configurado',
                'Se ha conservado este canal y su historial como espacio privado. Los demás canales originales '
                'se han archivado y retirado; ya están disponibles Información, Tienda, Soporte, Comunidad y Equipo.\n\n'
                '**Identidad:** logo del servidor y banner en los paneles principales.\n'
                '**Soporte:** tickets privados, cierres con historial, transcripciones y rol Cliente tras revisión de un pedido real.\n'
                '**Avisos:** roles opcionales para anuncios y actualizaciones.\n\n' +
                ('El enlace oficial de Tebex ya está conectado al panel de compra.' if self.store.get('shop_url') else
                 'Falta el enlace oficial de Tebex para conectar el botón de compra. Puedes indicarlo en el botón de configuración de arriba.')),
                allowed_mentions=discord.AllowedMentions.none())
            await self.call('put', 'completion_message', message.id)
        await self.call('put', 'setup_complete', int(time.time()))
        log.info('ESSCHINO complete guild=%s store_url_configured=%s banner_available=%s',
                 guild.id, bool(self.store.get('shop_url')), 'BANNER' in guild.features)

    async def ensure_channel(self, guild, key, name, parent=None, category=False, voice=False, topic='', overwrites=None):
        channels = await guild.fetch_channels()
        saved = self.store.get(key)
        matches = [c for c in channels if c.id == saved] if saved else []
        if not matches:
            matches = [c for c in channels if c.name == name and c.id not in self.store.get('original_channels', [])
                       and (category or c.category_id == parent.id)]
        if len(matches) > 1:
            raise ValueError('Hay más de un canal de instalación con el mismo nombre.')
        if matches:
            channel = matches[0]
            await channel.edit(overwrites=overwrites, reason=REASON)
        elif category:
            channel = await guild.create_category(name, overwrites=overwrites, reason=REASON)
        elif voice:
            channel = await guild.create_voice_channel(name, category=parent, overwrites=overwrites, reason=REASON)
        else:
            channel = await guild.create_text_channel(name, category=parent, topic=topic,
                overwrites=overwrites, slowmode_delay=10 if key.endswith(('general', 'suggestions', 'showcase')) else 0,
                reason=REASON)
        await self.call('put', key, channel.id)
        self.channels[channel.id] = channel
        return channel

    async def verify(self, guild):
        actual = await self.bot.fetch_guild(guild.id)
        if actual.name != 'EssChino Studio' or actual.icon is None:
            raise ValueError('Discord no confirmó el nombre o el icono del servidor EssChino.')
        if 'BANNER' in actual.features and actual.banner is None:
            raise ValueError('El servidor admite banner, pero Discord no lo confirmó.')
        channels = {c.id: c for c in await guild.fetch_channels()}
        protected = channels.get(PROTECTED_CHANNEL)
        if protected is None or protected.permissions_for(guild.default_role).view_channel:
            raise ValueError('No se confirmó el canal conservado como privado.')
        original_ids = set(self.store.get('original_channels', []))
        if original_ids & channels.keys():
            raise ValueError('Todavía quedan canales originales por retirar.')
        for key, _, _, _, policy, voice in CHANNELS:
            channel = channels.get(self.channel_id(key))
            if channel is None:
                raise ValueError(f'Falta el canal {key}.')
            public = channel.permissions_for(guild.default_role)
            if policy in {'owner', 'staff', 'staffread', 'customer', 'customerchat'} and public.view_channel:
                raise ValueError(f'El canal privado {key} es visible para todos.')
            if not voice and policy in {'read', 'review'} and public.send_messages:
                raise ValueError(f'El canal informativo {key} permite escribir a todos.')
            customer = self.role(guild, 'customer')
            if policy in {'customer', 'customerchat', 'review'} and not channel.permissions_for(customer).view_channel:
                raise ValueError(f'Los clientes no pueden acceder a {key}.')
            if not voice and key not in {'lounge', 'staffvoice'}:
                panel = await channel.fetch_message(self.store.get('panel:' + key))
                if panel.author.id != self.bot.user.id or not panel.embeds:
                    raise ValueError(f'Falta el panel oficial de {key}.')
        log.info('ESSCHINO verified guild=%s protected_private=True original_remaining=0 channels=%s roles=%s',
                 guild.id, len(channels), len(await guild.fetch_roles()))
        log.info('ESSCHINO_RESULT %s', json.dumps(dict(guild_id=str(guild.id), name=actual.name,
            preserved_channel=str(PROTECTED_CHANNEL), original_remaining=0, total_channels=len(channels),
            new_channels=len(CHANNELS), categories=len(CATEGORIES), icon=bool(actual.icon),
            native_banner=bool(actual.banner), panel_banners=True, shop_url_configured=bool(self.store.get('shop_url')),
            welcome=str(self.channel_id('welcome')), support=str(self.channel_id('support'))), ensure_ascii=False))

    def embed(self, title, body):
        return discord.Embed(title=title, description=body, color=COLOR).set_footer(text='EssChino · Scripts, comunidad y soporte')

    def panel(self, key):
        c = lambda name: f'<#{self.channel_id(name)}>'
        panels = {
            'welcome': ('👑 Bienvenido a EssChino Studio', f'Scripts para dar forma a tu proyecto.\n\n**Empieza aquí**\n📜 Lee {c("rules")}.\n📦 Explora {c("catalog")} y {c("demos")}.\n🛒 Compra desde {c("shop")}.\n🎫 Pide ayuda en {c("support")}.\n🔔 Elige tus avisos con los botones de este mensaje.\n\nEl equipo te atiende mediante tickets privados.'),
            'rules': ('📜 Normas de EssChino', '1. Respeta a los miembros y al equipo. Sin acoso, discriminación ni spam.\n2. Publica cada consulta en su canal. El soporte y los pedidos van por ticket.\n3. No compartas scripts de pago, filtraciones, licencias ajenas ni material sin autorización.\n4. Nunca publiques contraseñas, tokens, claves de licencia ni datos de pago.\n5. Compra únicamente desde la tienda oficial enlazada en este servidor. El equipo no solicita pagos por mensajes privados.\n6. Antes de comprar, revisa requisitos, dependencias, compatibilidad, entrega y condiciones indicadas en el producto y en Tebex.\n7. Para recibir el rol Cliente, soporte debe verificar tu pedido. Una captura o referencia por sí sola no acredita una compra.\n8. Las reseñas deben reflejar experiencias reales; las incidencias se atienden por ticket.\n\nLa moderación podrá retirar contenido que incumpla estas normas.'),
            'announcements': ('📢 Comunicados oficiales', f'Aquí se publican las novedades importantes de EssChino Studio.\n\nActiva los avisos que te interesan en {c("welcome")}. Para cambios técnicos consulta {c("changelog")}; para ayuda usa {c("support")}. No enviamos promociones por privado.'),
            'notifications': ('🔔 Tus notificaciones', 'Elige qué novedades quieres seguir.\n\n📣 **Avisos generales:** lanzamientos y comunicados.\n🔄 **Actualizaciones:** versiones y correcciones de scripts.\n\nPulsa para activar o desactivar cada rol. La selección se guarda en tu cuenta del servidor.'),
            'shop': ('🛒 Tienda oficial de EssChino', ('Explora los productos y completa tu compra de forma segura en nuestra tienda Tebex.\n\n' + self.store.get('shop_url') if self.store.get('shop_url') else f'Estamos preparando el acceso a la tienda oficial. Mientras tanto, consulta los productos en {c("catalog")} y abre una consulta privada en {c("support")}.') + '\n\nComprueba la compatibilidad y las condiciones del producto antes de pagar. Los pedidos se tramitan mediante Tebex; no publiques datos de pago en Discord.'),
            'catalog': ('📦 Catálogo de scripts', f'Este canal reúne las fichas oficiales de nuestros productos.\n\nCada publicación indicará **nombre, funciones, framework compatible, dependencias, versión, demostración y enlace de compra**. El precio vigente y las condiciones se consultan en Tebex.\n\n¿Buscas un recurso concreto? Pregunta en {c("support")}. Solo los productos publicados están disponibles; este mensaje no anuncia existencias ni compatibilidades.'),
            'demos': ('🎬 Demostraciones', f'Aquí encontrarás vídeos y ejemplos de funcionamiento de los scripts publicados.\n\nAntes de comprar, compara la demostración con la ficha del producto y sus requisitos. Si necesitas comprobar una función concreta, abre un ticket en {c("support")}. No hay demostraciones publicadas todavía.'),
            'offers': ('🏷️ Ofertas oficiales', 'Las promociones se anunciarán aquí con el producto incluido, las condiciones y la fecha de finalización.\n\nEl importe final siempre es el que muestra Tebex al completar el pedido. Actualmente no hay promociones anunciadas en este canal.'),
            'changelog': ('🔄 Versiones y actualizaciones', f'Cada actualización incluirá **producto · versión · cambios · requisitos nuevos · pasos de actualización**.\n\nHaz una copia de tu servidor y configuración antes de actualizar. Activa tus avisos en {c("welcome")}. No hay versiones publicadas todavía.'),
            'buying': ('🧾 Cómo comprar', f'**1. Elige tu script** en {c("catalog")} y revisa su demostración.\n**2. Comprueba requisitos**: framework, versiones, dependencias y modalidad de licencia.\n**3. Accede a la tienda oficial** desde {c("shop")}.\n**4. Completa el pedido en Tebex** con la identidad o cuenta que pida ese producto. Conserva el correo y la referencia del pedido.\n**5. Revisa la entrega** siguiendo las instrucciones de Tebex y del producto.\n**6. Abre un ticket** en {c("support")} para incidencias o para verificar tu compra y obtener el rol Cliente.\n\nNo envíes tarjetas, contraseñas ni claves privadas por Discord. Los impuestos, entrega y condiciones aplicables se muestran en el checkout.'),
            'support': ('🎫 Centro de soporte EssChino', 'Selecciona el motivo en el menú para abrir un canal privado.\n\n🛒 **Compras y pedidos** · dudas, entrega y verificación de cliente.\n🛠️ **Instalación y soporte** · requisitos, configuración y diagnóstico.\n🐛 **Errores** · pasos para reproducir, versión y registro del fallo.\n🤝 **Colaboraciones** · propuestas y consultas comerciales.\n\nIncluye el producto, la referencia del pedido si existe y una explicación. Oculta contraseñas, tokens y claves de licencia. Evita duplicar tickets; el equipo responde según disponibilidad.'),
            'faq': ('❓ Preguntas frecuentes', '**¿Es compatible con mi servidor?**\nRevisa el framework, versiones y dependencias de la ficha. Pregunta antes de comprar si no está claro.\n\n**¿Dónde descargo mi compra?**\nSigue el correo y las instrucciones de entrega de Tebex; depende del producto.\n\n**¿Cómo obtengo el rol Cliente?**\nAbre un ticket de compras. El equipo comprobará tu pedido en Tebex.\n\n**¿Puedo compartir o revender un script?**\nRevisa la licencia del producto; comprar no autoriza a redistribuirlo.\n\n**¿Hay devoluciones o transferencias de licencia?**\nConsulta las condiciones publicadas en la tienda y el checkout. Para revisar tu caso, abre un ticket privado.\n\n**¿Qué datos necesita soporte?**\nProducto, versión, entorno, pasos del fallo y errores relevantes con los datos sensibles ocultos.'),
            'install': ('📚 Guía de instalación', '**Antes de empezar**\nHaz una copia de tus archivos, configuración y base de datos. Revisa los requisitos exactos del producto.\n\n**Instala el recurso**\nUsa únicamente la entrega oficial. Sigue el README del script, instala las dependencias y aplica SQL solo cuando su documentación lo indique. Respeta el orden de carga.\n\n**Configura y prueba**\nAjusta las opciones documentadas, prueba primero en un entorno de pruebas y revisa consola y registros. No sobrescribas configuraciones antiguas sin compararlas.\n\n**Si algo falla**\nAbre un ticket con el producto, versión, framework, pasos y el texto del error. Oculta claves y credenciales. Esta guía general no sustituye las instrucciones específicas de cada script.'),
            'general': ('💬 Comunidad EssChino', f'Preséntate, comparte ideas y conversa con la comunidad.\n\nPara compras o problemas técnicos usa {c("support")}, así el equipo puede seguir tu caso en privado.'),
            'suggestions': ('💡 Tu próxima idea', 'Propón mejoras con este formato:\n\n**Necesidad:** ¿qué quieres resolver?\n**Propuesta:** ¿cómo funcionaría?\n**Ejemplo:** ¿en qué situación lo usarías?\n\nPuedes apoyar otras ideas con reacciones. Las sugerencias no implican un compromiso de desarrollo ni una fecha de entrega.'),
            'reviews': ('⭐ Experiencias de clientes', 'Este espacio permite publicar a miembros con rol Cliente, concedido tras verificar una compra.\n\nComparte el producto, el uso que le das y tu experiencia real. No publiques referencias de pedido, datos personales ni archivos de pago. Para resolver incidencias, abre un ticket. No hay reseñas publicadas todavía.'),
            'showcase': ('📸 Muestra tu proyecto', 'Comparte capturas o vídeos de tus proyectos con scripts de EssChino.\n\nIndica el recurso utilizado y lo que has construido. Respeta los derechos de los demás y evita spam o archivos de pago.'),
            'downloads': ('📥 Tus compras y licencias', 'La entrega oficial depende de cada producto y de las instrucciones de Tebex. Consulta el correo del pedido y la cuenta vinculada a la compra.\n\nEste canal no distribuye archivos de pago ni claves. Si falta una entrega, abre un ticket con tu referencia de pedido. Nunca compartas tu contraseña ni la clave de tu licencia.'),
            'customerchat': ('💎 Espacio de clientes', 'Comparte experiencias y consejos con otros clientes verificados.\n\nPara soporte de un pedido abre un ticket: así tus datos y el diagnóstico permanecen en privado.'),
            'staff': ('👥 Equipo EssChino', 'Coordina aquí la atención y los contenidos oficiales.\n\n**Antes de publicar:** comprueba requisitos, enlaces, precio en Tebex y condiciones del producto.\n**Antes de verificar un cliente:** comprueba el pedido en el panel real de Tebex; no aceptes solo una captura.\n**Tickets:** recoge el diagnóstico, evita pedir secretos y conserva la transcripción al cerrar.\n**Privacidad:** no copies información de pedidos a canales públicos.'),
            'management': ('📋 Gestión de soporte', 'Los tickets se crean de forma privada en **Tickets Abiertos**, arriba del servidor. Al cerrarlos pasan a **Tickets Cerrados**.\n\nCada caso permite cerrar, reabrir, descargar su transcripción y verificar una compra después de comprobarla en Tebex.\n\nUsa `/studio tickets` para consultar los casos abiertos y cerrados. Asigna los roles del equipo solo a las personas que deban atender pedidos.'),
            'log': ('📋 Registro de soporte', 'Aquí se registran aperturas, cierres, reaperturas y verificaciones de cliente.\n\nLos tickets cerrados se conservan con acceso privado. El estado anterior de la instalación y las copias de canales se guardan en el volumen privado del bot.'),
        }
        return panels[key]

    async def publish_panel(self, guild, key, refresh=False):
        channel = self.bot.get_channel(self.channel_id(key)) or await self.bot.fetch_channel(self.channel_id(key))
        marker = 'EssChino · panel:' + key
        existing = None
        async for message in channel.history(limit=100):
            if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                existing = message
                break
        if existing and not refresh:
            return
        title, body = self.panel(key)
        embed = self.embed(title, body).set_footer(text=marker)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        view = {'welcome': EntryView, 'notifications': NotificationsView, 'support': SupportView, 'management': ManagementView}.get(key)
        view = view(self) if view else None
        if key in {'suggestions', 'reviews'} and hasattr(self, 'community'):
            view = self.community.panel_view(key)
        if key == 'shop' and self.store.get('shop_url'):
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='Visitar tienda oficial', emoji='🛒', style=discord.ButtonStyle.link,
                                           url=self.store.get('shop_url')))
        kwargs = dict(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        if view is not None:
            kwargs['view'] = view
        if key in {'welcome', 'shop', 'support'}:
            embed.set_image(url='attachment://esschino-banner.jpg')
            file = discord.File(ASSETS / 'banner.jpg', filename='esschino-banner.jpg')
            if existing:
                kwargs['attachments'] = [file]
            else:
                kwargs['file'] = file
        message = await existing.edit(**kwargs) if existing else await channel.send(**kwargs)
        await self.call('put', 'panel:' + key, message.id)

    async def publish_admin(self, channel):
        marker = 'EssChino · Dirección privada'
        async for message in channel.history(limit=100):
            if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                return
        embed = self.embed('👑 Dirección de EssChino',
            'Este canal original conserva su historial y queda privado para el propietario y el bot '
            '(Discord permite el acceso a cuentas con Administrador).\n\n'
            '**Tienda:** configura el enlace oficial con el botón inferior.\n'
            '**Productos:** publica las fichas reales en Catálogo y sus demostraciones en el canal correspondiente.\n'
            '**Equipo:** asigna los roles de Administración, Desarrollador y Soporte únicamente a personas de confianza.\n'
            '**Clientes:** comprueba el pedido en Tebex y usa Verificar compra dentro de su ticket. '
            'No hay una integración de verificación automática de Tebex configurada.\n'
            '**Imagen:** el logo está en el icono; el banner se muestra en los paneles. '
            'La cabecera nativa del servidor depende de que Discord habilite BANNER.\n\n'
            'Las copias de la instalación y los canales anteriores permanecen en el volumen privado del bot.')
        embed.set_footer(text=marker)
        await channel.send(embed=embed, view=AdminView(self), allowed_mentions=discord.AllowedMentions.none())

    async def toggle_role(self, i, key, toggle=True):
        await i.response.defer(ephemeral=True)
        role = self.role(i.guild, key)
        if role is None:
            raise ValueError('No se encuentra ese rol de EssChino.')
        remove = toggle and role in i.user.roles
        async def apply():
            if remove:
                await i.user.remove_roles(role, reason='Preferencia del miembro en el panel de EssChino')
            elif role not in i.user.roles:
                await i.user.add_roles(role, reason='Preferencia del miembro en el panel de EssChino')
        await self.tracked(f'role:{i.id}', 'Preferencia de comunidad EssChino', apply, members=(i.user.id,))
        await i.followup.send(f'{"Desactivado" if remove else "Activado"}: **{role.name}**.', ephemeral=True)

    async def open_ticket(self, i, kind, product, order, details):
        if i.guild_id != self.store.get('guild') or not isinstance(i.user, discord.Member) or i.user.bot:
            raise ValueError('Solo se pueden abrir tickets dentro de EssChino.')
        await i.response.defer(ephemeral=True)
        async with self.lock:
            existing = [r for r in await self.call('tickets', i.user.id) if r['state'] == 'open']
            for row in existing:
                channel = i.guild.get_channel(int(row['channel']))
                if channel:
                    await i.followup.send(f'Ya tienes un ticket abierto: {channel.mention}.', ephemeral=True)
                    return
            owner = await i.guild.fetch_member(i.guild.owner_id)
            overwrites = self.overwrites(i.guild, 'staff', owner)
            overwrites[i.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                read_message_history=True, attach_files=True, embed_links=True, add_reactions=True)
            async def apply():
                category = await self.ticket_category(i.guild, False, owner)
                channel = await i.guild.create_text_channel(f'{kind}-{i.user.id}',
                    category=category,
                    topic=f'EssChino · ticket · propietario:{i.user.id} · solicitud:{i.id}', overwrites=overwrites,
                    reason='Consulta privada solicitada por el miembro en EssChino')
                await self.call('add_ticket', channel.id, i.user.id, kind)
                embed = self.embed('🎫 Tu consulta privada · EssChino',
                    f'**Miembro:** <@{i.user.id}>\n**Motivo:** {kind}\n**Asunto:** {product}\n'
                    f'**Pedido indicado (sin verificar):** {order or "No indicado"}\n\n{details}\n\n'
                    'El equipo revisará tu consulta. Añade errores o capturas con datos sensibles ocultos. '
                    'La referencia introducida no concede el rol Cliente automáticamente.')
                await channel.send(embed=embed, view=TicketView(self), allowed_mentions=discord.AllowedMentions.none())
                await self.audit(i.guild, f'🎫 Abierto · <#{channel.id}> · miembro <@{i.user.id}> · {kind}.')
                return channel
            channel = await self.tracked(f'ticket:{i.id}', 'Abrir ticket privado de EssChino', apply)
        await i.followup.send(f'Tu consulta está lista: {channel.mention}.', ephemeral=True)

    async def set_ticket_state(self, i, reopen):
        row = self.ticket_access(i, staff=reopen)
        desired = 'open' if reopen else 'closed'
        await i.response.defer(ephemeral=True)
        async with self.lock:
            row = self.ticket_access(i, staff=reopen)
            if row['state'] == desired:
                await i.followup.send('El ticket ya está en ese estado.', ephemeral=True)
                return
            await self.archive_channel(i.channel, 'ticket')
            try:
                member = await i.guild.fetch_member(int(row['owner']))
            except discord.NotFound:
                member = None
            owner = await i.guild.fetch_member(i.guild.owner_id)
            overwrites = self.overwrites(i.guild, 'staff', owner)
            if member:
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=reopen, add_reactions=reopen, attach_files=reopen, embed_links=reopen)
            async def apply():
                category = await self.ticket_category(i.guild, not reopen, owner)
                await i.channel.edit(category=category,
                    overwrites=overwrites, sync_permissions=False, reason='Cambio de estado de ticket EssChino')
                await self.call('ticket_state', i.channel_id, desired)
                await i.channel.send(embed=self.embed('🔓 Ticket reabierto' if reopen else '🔒 Ticket cerrado',
                    'El historial y los adjuntos se conservan. El equipo puede reabrir este caso.'),
                    view=TicketView(self), allowed_mentions=discord.AllowedMentions.none())
                await self.audit(i.guild, f'{"🔓 Reabierto" if reopen else "🔒 Cerrado"} · <#{i.channel_id}> · por <@{i.user.id}>.')
            await self.tracked(f'state:{i.id}', 'Cambiar estado de ticket EssChino', apply)
        await i.followup.send('Ticket reabierto.' if reopen else 'Ticket cerrado y copia guardada.', ephemeral=True)

    async def ticket_category(self, guild, closed, owner):
        category = await self.ensure_channel(guild, 'category:' + ('closed' if closed else 'tickets'),
            'Tickets Cerrados' if closed else 'Tickets Abiertos', category=True,
            overwrites=self.overwrites(guild, 'staff', owner))
        await category.edit(position=1 if closed else 0, reason='Tickets abiertos arriba y cerrados separados')
        if closed:
            opened = self.channel(guild, 'category:tickets')
            if opened:
                await opened.edit(position=0, reason='Mantener Tickets Abiertos arriba del servidor')
        return category

    async def audit(self, guild, text):
        channel = guild.get_channel(self.channel_id('log'))
        if channel:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def observe(self, message):
        if (message.guild and message.guild.id != ORIGINAL_GUILD
                and message.guild.id == self.store.get('guild') and self.store.ticket(message.channel.id)):
            await self.archive_message(message, 'ticket')
