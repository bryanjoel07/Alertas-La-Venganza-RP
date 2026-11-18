"""Guild-isolated GTA VI community, persistent panels and private support."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
from pathlib import Path

import discord
from discord import app_commands

from esschino import StudioStore
from studio_journal import ChangeLog, server_snapshot
from vice_design import (GUILD_ID, BOT_ID, OWNER_ID, VERSION, STAFF_VERSION, PINK, CYAN, CORAL, DESCRIPTION,
                         ROLES, GROUPS, SELF_ROLES, CATEGORIES, CHANNELS, panel_copy,
                         DECORATION_VERSION, CLOSED_CATEGORY, TICKET_OPEN_PREFIX, TICKET_CLOSED_PREFIX)
from vice_welcome import ViceWelcome, render_card, render_cover
from vice_voice import TempVoice
from vice_community import CommunityExtras, EventModal
from vice_readonly import ReadOnlyChannels, lock_overwrites
from vice_audit import ViceAudit
from vice_activity import ViceActivity
from vice_ticket_delete import TicketDeletion
from welcome_cards import WelcomeCards, clean_name

log = logging.getLogger('ViceDistrict')
REASON = 'Solicitud del propietario: comunidad GTA VI Latino | VIce District'


class SafeView(discord.ui.View):
    def __init__(self, system):
        super().__init__(timeout=None)
        self.system = system

    async def interaction_check(self, interaction):
        self.system.authorize(interaction)
        if not self.system.configured:
            raise ValueError('El distrito está terminando de arrancar. Inténtalo en unos segundos.')
        return True

    async def on_error(self, interaction, error, item):
        if isinstance(error, ValueError):
            text = str(error)
        else:
            log.error('VICE_INTERACTION_FAILED type=%s', type(error).__name__, exc_info=error)
            text = 'No se pudo completar la acción. Inténtalo de nuevo o contacta con el equipo.'
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(text[:1500], ephemeral=True)


class WelcomePanel(SafeView):
    @discord.ui.button(label='Unirme a la comunidad', emoji='🌴', style=discord.ButtonStyle.primary,
                       custom_id='vice:v1:join', row=0)
    async def join(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self.system.join_community(interaction)
        await interaction.followup.send('🌴 ¡Ya eres Ciudadano del distrito! Al unirte aceptas las normas. '
            f'Ahora personaliza tu perfil en <#{self.system.channel_id("roles")}>.', ephemeral=True)

    @discord.ui.button(label='Mi bienvenida', emoji='🖼️', style=discord.ButtonStyle.secondary,
                       custom_id='vice:v1:preview', row=1)
    async def preview(self, interaction, button):
        await self.system.welcome.preview(interaction)

    def __init__(self, system, links=True):
        super().__init__(system)
        if links:
            for key, label, emoji in [('rules','Normas','📜'), ('general','Entrar al chat','💬'), ('support','Ayuda','🎫')]:
                cid = system.channel_id(key)
                if cid:
                    self.add_item(discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.link,
                        url=f'https://discord.com/channels/{GUILD_ID}/{cid}', row=2))


class RoleSelect(discord.ui.Select):
    def __init__(self, system, group):
        self.system, self.group = system, group
        placeholder, keys, maximum = GROUPS[group]
        names = {key: name for key, name, *_ in ROLES}
        super().__init__(placeholder=placeholder, custom_id='vice:v1:select:' + group,
            min_values=0, max_values=maximum,
            options=[discord.SelectOption(label=names[key], value=key) for key in keys])

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await self.system.select_roles(interaction, self.group, self.values)
        await interaction.followup.send('✅ Preferencias actualizadas. Puedes cambiarlas cuando quieras.', ephemeral=True)


class RolesPanel(SafeView):
    def __init__(self, system):
        super().__init__(system)
        for group in GROUPS:
            self.add_item(RoleSelect(system, group))


class SupportPanel(SafeView):
    @discord.ui.button(label='Abrir ticket', emoji='🎫', style=discord.ButtonStyle.primary,
                       custom_id='vice:v1:ticket:open')
    async def open(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        channel = await self.system.open_ticket(interaction)
        await interaction.followup.send(f'Tu conversación privada está aquí: {channel.mention}', ephemeral=True)


class CloseTicketPanel(SafeView):
    @discord.ui.button(label='Cerrar y archivar', emoji='🔒', style=discord.ButtonStyle.secondary,
                       custom_id='vice:v1:ticket:close')
    async def close_ticket(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        await self.system.close_ticket(interaction)
        await interaction.followup.send('Ticket cerrado. El historial se conserva en privado.', ephemeral=True)


class ViceDistrict:
    def __init__(self, bot, path):
        self.bot, self.path = bot, Path(path)
        self.store = StudioStore(self.path)
        self.changes = ChangeLog(bot, self.path, GUILD_ID)
        self.welcome = ViceWelcome(self, self.path)
        self.voice = TempVoice(self)
        self.community = CommunityExtras(self)
        self.readonly = ReadOnlyChannels(self)
        self.audit = ViceAudit(self)
        self.activity = ViceActivity(self.audit)
        self.ticket_deletion = TicketDeletion(self)
        self.ready_lock = asyncio.Lock()
        self.roles_lock = asyncio.Lock()
        self.ticket_lock = asyncio.Lock()
        self.goodbye_lock = asyncio.Lock()
        self.ready_event = asyncio.Event()
        self.configured = False
        self.role_cache = {}
        self.channel_cache = {}
        self.register_commands()

    async def call(self, name, *args):
        return await asyncio.to_thread(getattr(self.store, name), *args)

    def channel_id(self, key):
        return self.store.get('channel:' + key)

    def channel(self, guild, key):
        self.validate_guild(guild)
        return guild.get_channel(self.channel_id(key)) or self.channel_cache.get(key)

    def role(self, guild, key):
        self.validate_guild(guild)
        return guild.get_role(self.store.get('role:' + key)) or self.role_cache.get(key)

    @staticmethod
    def validate_guild(guild):
        if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('Esta función solo pertenece a GTA VI Latino | VIce District.')
        return guild

    def authorize(self, interaction, staff=False):
        self.validate_guild(interaction.guild)
        if interaction.guild_id != GUILD_ID or not isinstance(interaction.user, discord.Member) or interaction.user.bot:
            raise ValueError('Usa el panel dentro de GTA VI Latino.')
        if staff and not self.is_staff(interaction.user):
            raise ValueError('Esta acción está reservada al equipo del distrito.')

    def is_staff(self, member):
        if member.guild.id != GUILD_ID:
            return False
        allowed = {self.store.get('role:admin'), self.store.get('role:mod'), self.store.get('role:support')}
        return member.id == OWNER_ID or member.guild_permissions.administrator or any(r.id in allowed for r in member.roles)

    def embed(self, title, description, color=PINK):
        return discord.Embed(title=title, description=description, color=color).set_footer(
            text='GTA VI Latino • Puerto Rico + Latinoamérica • Fans no oficiales')

    async def track(self, kind, title, operation, request, snapshot=None):
        self.validate_guild(self.bot.get_guild(GUILD_ID))
        return await self.changes.tracked('VICE_' + kind, title, operation, request_id=str(request), snapshot=snapshot)

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await self.call('initialize')
        await asyncio.to_thread(self.changes.journal.initialize)
        await self.welcome.start()
        await self.voice.start()
        await self.community.start()
        await self.audit.start()
        await self.ticket_deletion.start()
        for view in [WelcomePanel(self, links=False), RolesPanel(self), SupportPanel(self), CloseTicketPanel(self)]:
            self.bot.add_view(view)

    def overwrites(self, guild, policy, owner=None):
        self.validate_guild(guild)
        private = policy in {'staff', 'staffread', 'adminread', 'ticket', 'closed'}
        readonly = policy in {'read', 'staffread', 'adminread', 'closed'}
        rules = {guild.default_role: discord.PermissionOverwrite(view_channel=not private,
            read_message_history=not private, send_messages=not (private or readonly),
            send_messages_in_threads=not (private or readonly), create_public_threads=False,
            create_private_threads=False, mention_everyone=False)}
        rules[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
            send_messages=True, embed_links=True, attach_files=True, connect=True, speak=True,
            manage_channels=True, manage_messages=True, pin_messages=True)
        for key in ['founder', 'admin', 'mod', 'support']:
            role = self.role(guild, key)
            if role:
                if policy == 'adminread' and key in {'mod', 'support'}:
                    rules[role] = discord.PermissionOverwrite(view_channel=False, read_message_history=False,
                        send_messages=False, send_messages_in_threads=False)
                    continue
                rules[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=policy not in {'closed', 'staffread', 'adminread'} and (key != 'support' or policy != 'read'),
                    send_messages_in_threads=policy not in {'closed', 'staffread', 'adminread', 'read'},
                    connect=True, speak=True, attach_files=True, embed_links=True)
                if key == 'support' and policy == 'ticket':
                    rules[role].manage_messages = True
        if owner:
            rules[owner] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                send_messages=policy != 'closed', attach_files=True, embed_links=True,
                send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
        return lock_overwrites(guild, rules) if readonly else rules

    async def ready(self):
        async with self.ready_lock:
            if self.configured:
                await self.voice.ready()
                await self.readonly.ready()
                await self.community.ready()
                await self.ticket_deletion.ready()
                await self.audit.ready()
                return
            guild = self.bot.get_guild(GUILD_ID)
            self.validate_guild(guild)
            if self.bot.user.id != BOT_ID:
                raise ValueError('Se requiere EssChino Studio Bot.')
            if not self.bot.intents.members:
                raise ValueError('Las bienvenidas requieren el intent de miembros.')
            if self.store.get('release') != VERSION:
                await self.track('INSTALL', 'Diseñar GTA VI Latino y publicar sus paneles',
                    lambda: self.install(guild), VERSION)
            if self.store.get('staff_release') != STAFF_VERSION:
                await self.track('STAFF_SETUP', 'Configurar equipo y despedidas privadas',
                    lambda: self.install_staff(guild), STAFF_VERSION)
            if self.store.get('decoration_release') != DECORATION_VERSION:
                await self.track('DECORATION', 'Decorar categorías y canales del distrito',
                    lambda: self.decorate(guild), DECORATION_VERSION)
            self.configured = True
            self.ready_event.set()
            if self.welcome.task is None or self.welcome.task.done():
                self.welcome.task = asyncio.create_task(self.welcome.recover(), name='vice-welcome-recovery')
            log.info('VICE_READY guild=%s roles=%s channels=%s release=%s staff=%s', GUILD_ID, len(ROLES) + 1, len(CHANNELS), VERSION, STAFF_VERSION)
            await self.voice.ready()
            await self.readonly.ready()
            await self.community.ready()
            await self.ticket_deletion.ready()
            await self.audit.ready()

    async def decorate(self, guild):
        """Rename existing objects only; preserve parents, IDs and permissions."""
        self.validate_guild(guild)
        channels = await guild.fetch_channels()
        by_id = {channel.id: channel for channel in channels}
        plan = []
        for key, name, _ in CATEGORIES:
            category = by_id.get(self.store.get('category:' + key))
            if category is None:
                raise ValueError('No se encontró la categoría del distrito: ' + key)
            plan.append((category, name))
        for key, _, name, *_ in CHANNELS:
            channel = by_id.get(self.channel_id(key))
            if channel is None:
                raise ValueError('No se encontró el canal del distrito: ' + key)
            plan.append((channel, name))
        archive = by_id.get(self.store.get('category:closed'))
        archive = archive or discord.utils.get(channels, name='🔒 TICKETS ARCHIVADOS')
        if archive:
            plan.append((archive, CLOSED_CATEGORY))
        for channel in channels:
            topic = getattr(channel, 'topic', '') or ''
            if topic.startswith('VIce ticket owner=') or topic.startswith('VIce ticket closed owner='):
                owner = topic.rsplit('=', 1)[-1]
                if owner.isdecimal():
                    prefix = TICKET_CLOSED_PREFIX if topic.startswith('VIce ticket closed ') else TICKET_OPEN_PREFIX
                    plan.append((channel, prefix + owner[-6:]))
        changed = 0
        for channel, name in plan:
            if channel.name != name:
                await channel.edit(name=name, reason=REASON)
                changed += 1
        await self.call('put', 'decoration_release', DECORATION_VERSION)
        log.info('VICE_DECORATION_READY guild=%s changed=%s release=%s', GUILD_ID, changed, DECORATION_VERSION)

    async def install_staff(self, guild):
        """Small additive migration; preserve community panels and all histories."""
        self.validate_guild(guild)
        roles = await guild.fetch_roles()
        for key, name, color, permissions, hoist, old in ROLES:
            if key not in {'admin', 'mod', 'support'}:
                continue
            role = discord.utils.get(roles, id=self.store.get('role:' + key))
            role = role or discord.utils.get(roles, name=name)
            values = dict(name=name, colour=discord.Colour(color), permissions=discord.Permissions(**permissions),
                          hoist=hoist, mentionable=False, reason=REASON)
            role = await role.edit(**values) if role else await guild.create_role(**values)
            await self.call('put', 'role:' + key, role.id)
            self.role_cache[key] = role
        roles = await guild.fetch_roles()
        admin = discord.utils.get(roles, id=self.store.get('role:admin'))
        mod = discord.utils.get(roles, id=self.store.get('role:mod'))
        bot_role = max(r for r in roles if r.id in {r.id for r in guild.me.roles})
        if not mod < bot_role or admin >= bot_role:
            raise ValueError('El bot debe estar por encima de los roles del equipo.')
        if admin <= mod:
            target = min(mod.position + 1, bot_role.position - 1)
            await guild.edit_role_positions(positions={admin: target}, reason=REASON)
        roles = await guild.fetch_roles()
        for key in ('admin', 'mod', 'support'):
            self.role_cache[key] = discord.utils.get(roles, id=self.store.get('role:' + key))
        if not self.role_cache['admin'] > self.role_cache['mod'] > self.role_cache['support']:
            raise ValueError('Revisa el orden: Administrador, Moderación, Soporte.')
        channels = await guild.fetch_channels()
        team = discord.utils.get(channels, id=self.store.get('category:team'))
        if team is None:
            raise ValueError('No se encontró la categoría privada del equipo.')
        await team.edit(overwrites=self.overwrites(guild, 'staff'), reason=REASON)
        for key in ('staff', 'log', 'staffvoice', 'goodbye'):
            spec = next(x for x in CHANNELS if x[0] == key)
            _, _, name, topic, policy, voice, limit = spec
            channel = discord.utils.get(channels, id=self.channel_id(key)) or discord.utils.get(channels, name=name)
            values = dict(overwrites=self.overwrites(guild, policy), reason=REASON)
            if not voice:
                values['topic'] = topic
            if channel:
                channel = await channel.edit(**values)
            elif key == 'goodbye':
                channel = await guild.create_text_channel(name, category=team, **values)
            else:
                raise ValueError('Falta un canal del equipo: ' + key)
            await self.call('put', 'channel:' + key, channel.id)
            self.channel_cache[key] = channel
        # Existing ticket participants/history stay intact. Add only staff access.
        for channel in channels:
            topic = getattr(channel, 'topic', '') or ''
            if not topic.startswith('VIce ticket '):
                continue
            closed = topic.startswith('VIce ticket closed ')
            rules = channel.overwrites
            rules[self.role_cache['admin']] = self.overwrites(guild, 'closed' if closed else 'ticket')[self.role_cache['admin']]
            rules[self.role_cache['support']] = self.overwrites(guild, 'closed' if closed else 'ticket')[self.role_cache['support']]
            await channel.edit(overwrites=rules, reason=REASON)
        await self.panel(guild, 'goodbye', panel_copy('goodbye', self.channel_id), None)
        await self.panel(guild, 'roles', panel_copy('roles', self.channel_id), RolesPanel(self))
        await self.panel(guild, 'log', ('🛡️ PERMISOS DEL EQUIPO',
            '**⚙️ Administrador:** control completo del servidor. Solo se asigna manualmente a personas de confianza.\n\n'
            '**🛡️ Moderación:** mensajes, hilos, apodos, tiempos de espera, expulsiones, vetos, auditoría y moderación de voz.\n\n'
            '**🛟 Soporte:** atención de tickets y coordinación del equipo. Puede moderar mensajes dentro de tickets abiertos.\n\n'
            '**🚪 Despedidas:** canal exclusivo de Fundador y Administrador, con banner y motivo según auditoría.\n\n'
            'Los roles del equipo están excluidos de los menús públicos. Administrador tiene acceso completo; '
            'Moderación y Soporte no pueden administrar roles ni configurar el servidor.', CYAN), None)
        await self.call('put', 'staff_release', STAFF_VERSION)
        log.info('VICE_STAFF_READY guild=%s channel=%s release=%s', GUILD_ID, self.channel_id('goodbye'), STAFF_VERSION)

    async def install(self, guild):
        roles = await guild.fetch_roles()
        # Preserve the original community role when converting the early design
        # to the owner's requested rank ladder. Miembro gets its own lowest role.
        previous_member = discord.utils.get(roles, id=self.store.get('role:member'))
        if previous_member and previous_member.name in {'Comunidad', '🌴 Comunidad'}:
            await self.call('put', 'role:citizen', previous_member.id)
            await self.call('put', 'role:member', None)
        founder = discord.utils.get(roles, name='Fundador') or discord.utils.get(roles, name='👑 Fundador')
        if founder:
            await self.call('put', 'role:founder', founder.id)
            self.role_cache['founder'] = founder
        bot_role = discord.utils.get(roles, id=guild.me.top_role.id)
        existing_mod = discord.utils.get(roles, name='Moderación') or discord.utils.get(roles, name='🛡️ Moderación')
        if existing_mod and existing_mod >= bot_role:
            raise ValueError('Coloca el rol de EssChino Studio Bot encima de Moderación.')
        ordered = []
        for key, name, color, permissions, hoist, old in ROLES:
            role = discord.utils.get(roles, id=self.store.get('role:' + key))
            role = role or discord.utils.get(roles, name=name) or (discord.utils.get(roles, name=old) if old else None)
            values = dict(name=name, colour=discord.Colour(color), permissions=discord.Permissions(**permissions),
                          hoist=hoist, mentionable=False, reason=REASON)
            role = await role.edit(**values) if role else await guild.create_role(**values)
            await self.call('put', 'role:' + key, role.id)
            self.role_cache[key] = role
            ordered.append(role)
        await guild.edit_role_positions(positions={role: len(ordered) - index for index, role in enumerate(ordered)}, reason=REASON)
        # Fetch after role creation so overwrite identities use the current cache.
        await guild.fetch_roles()
        everyone = guild.default_role.permissions
        everyone.update(mention_everyone=False, manage_webhooks=False, manage_channels=False, manage_roles=False,
                        administrator=False, create_public_threads=False, create_private_threads=False,
                        send_messages=True, view_channel=True, read_message_history=True,
                        embed_links=True, attach_files=True, add_reactions=True, connect=True, speak=True)
        await guild.default_role.edit(permissions=everyone, reason=REASON)
        existing = await guild.fetch_channels()
        categories = {}
        for index, (key, name, policy) in enumerate(CATEGORIES):
            category = discord.utils.get(existing, id=self.store.get('category:' + key)) or discord.utils.get(existing, name=name)
            if category is None and key == 'community':
                category = discord.utils.get(existing, name='🌆 COMUNIDAD')
            values = dict(name=name, position=index, overwrites=self.overwrites(guild, policy), reason=REASON)
            category = await category.edit(**values) if category else await guild.create_category(**values)
            categories[key] = category
            await self.call('put', 'category:' + key, category.id)
        positions = {}
        for key, parent, name, topic, policy, voice, limit in CHANNELS:
            channel = discord.utils.get(existing, id=self.channel_id(key)) or discord.utils.get(existing, name=name)
            position = positions.get(parent, 0)
            positions[parent] = position + 1
            values = dict(name=name, category=categories[parent], position=position,
                          overwrites=self.overwrites(guild, policy), reason=REASON)
            if voice:
                values.update(user_limit=limit, bitrate=64000)
            else:
                values.update(topic=topic, slowmode_delay=limit, nsfw=False)
            if channel:
                channel = await channel.edit(**values)
            else:
                create = guild.create_voice_channel if voice else guild.create_text_channel
                channel = await create(**values)
            await self.call('put', 'channel:' + key, channel.id)
            self.channel_cache[key] = channel
        flags = guild.system_channel_flags
        flags.join_notifications = False
        await guild.edit(description=DESCRIPTION, verification_level=discord.VerificationLevel.low,
            explicit_content_filter=discord.ContentFilter.all_members,
            default_notifications=discord.NotificationLevel.only_mentions,
            system_channel=self.channel(guild, 'welcome'), system_channel_flags=flags, reason=REASON)
        await guild.me.edit(nick='EssChino · VIce District', reason=REASON)
        for key, *_ in CHANNELS:
            copy = panel_copy(key, self.channel_id)
            if copy:
                view = WelcomePanel(self) if key == 'welcome' else RolesPanel(self) if key == 'roles' else SupportPanel(self) if key == 'support' else None
                await self.panel(guild, key, copy, view)
        await self.owner_example(guild)
        await self.bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        await self.panel(guild, 'log', ('🛠 EL DISTRITO ESTÁ LISTO',
            '**Bienvenidas:** automáticas, con nombre y avatar.\n'
            '**Roles:** panel de plataformas, región y avisos.\n'
            '**Soporte:** tickets privados con cierre y archivo.\n'
            '**Permisos:** información de lectura y equipo privado.\n\n'
            'Usa **/vice estado** para comprobar el bot y **/vice publicar** para anuncios, noticias o eventos. '
            'Asigna Moderación, Soporte y Creadores manualmente a personas de confianza.\n\n'
            'Los mensajes y canales existentes se conservan. Los cambios de configuración quedan registrados en la base privada del distrito.', CYAN), None)
        await self.call('put', 'release', VERSION)

    async def find_panel(self, channel, key):
        message_id = self.store.get('panel:' + key)
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
                if message.author.id != BOT_ID:
                    raise ValueError('El panel guardado no pertenece al bot.')
                return message
            except discord.NotFound:
                pass
        marker = 'VIce District • panel:' + key
        async for message in channel.history(limit=100):
            if message.author.id == BOT_ID and any(e.footer.text == marker for e in message.embeds):
                return message
        return None

    async def panel(self, guild, key, copy, view):
        channel = self.channel(guild, key)
        if channel is None:
            channel = await guild.fetch_channel(self.channel_id(key))
        title, body, color = copy
        embed = self.embed(title, body, color).set_footer(text='VIce District • panel:' + key)
        files = []
        if key == 'welcome':
            data = await asyncio.to_thread(render_cover)
            files = [discord.File(io.BytesIO(data), filename='vice-district.jpg')]
            embed.set_image(url='attachment://vice-district.jpg')
        elif key == 'goodbye':
            owner = await guild.fetch_member(OWNER_ID)
            data = await self.departure_card(owner)
            files = [discord.File(io.BytesIO(data), filename='vice-despedida-muestra.jpg')]
            embed.set_image(url='attachment://vice-despedida-muestra.jpg')
            embed.add_field(name='Vista previa del banner',
                value='Muestra con el perfil del propietario. No corresponde a una salida real.', inline=False)
        message = await self.find_panel(channel, key)
        if message:
            message = await message.edit(embed=embed, view=view, attachments=files,
                                         allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(embed=embed, view=view, files=files,
                                         allowed_mentions=discord.AllowedMentions.none())
        await self.call('put', 'panel:' + key, message.id)
        if not message.pinned:
            await message.pin(reason=REASON)
        log.info('VICE_PANEL key=%s channel=%s message=%s', key, channel.id, message.id)

    async def owner_example(self, guild):
        if self.store.get('owner_example') and self.store.get('owner_example_version') == VERSION:
            return
        member = await guild.fetch_member(OWNER_ID)
        filename = 'vice-bienvenida-muestra.jpg'
        channel = self.channel(guild, 'welcome')
        existing = None
        async for message in channel.history(limit=100):
            if message.author.id == BOT_ID and any(a.filename == filename for a in message.attachments):
                existing = message
                break
        card = await self.welcome.card(member)
        file = discord.File(io.BytesIO(card), filename=filename)
        embed = self.welcome.embed(member, filename, example=True)
        if existing:
            message = await existing.edit(embed=embed, attachments=[file], allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(embed=embed, file=file, allowed_mentions=discord.AllowedMentions.none())
        await self.call('put', 'owner_example', message.id)
        await self.call('put', 'owner_example_version', VERSION)

    async def role_snapshot(self, guild, user_id):
        member = await guild.fetch_member(user_id)
        return dict(guild=GUILD_ID, member=user_id, roles=[r.id for r in member.roles])

    async def join_community(self, interaction):
        self.authorize(interaction)
        role = self.role(interaction.guild, 'citizen')
        if role is None or role.permissions.value != 0:
            raise ValueError('El rol de Ciudadano necesita revisión del equipo.')
        async with self.roles_lock:
            member = await interaction.guild.fetch_member(interaction.user.id)
            async def apply():
                await member.add_roles(role, reason='El miembro acepta las normas y se une a la comunidad')
                entry = self.role(interaction.guild, 'member')
                if entry and entry in member.roles:
                    await member.remove_roles(entry, reason='Pasa de Miembro a Ciudadano al aceptar las normas')
            await self.track('MEMBER', 'Unirse a la comunidad', apply, interaction.id,
                snapshot=lambda: self.role_snapshot(interaction.guild, member.id))

    async def select_roles(self, interaction, group, selected):
        self.authorize(interaction)
        if group not in GROUPS:
            raise ValueError('Grupo de roles desconocido.')
        _, keys, maximum = GROUPS[group]
        if len(selected) > maximum or not set(selected) <= (set(keys) & SELF_ROLES):
            raise ValueError('Selección de roles no válida.')
        roles = {key: self.role(interaction.guild, key) for key in keys}
        if any(role is None or role.permissions.value != 0 or role.managed for role in roles.values()):
            raise ValueError('Estos roles necesitan revisión del equipo.')
        async with self.roles_lock:
            member = await interaction.guild.fetch_member(interaction.user.id)
            async def apply():
                remove = [role for key, role in roles.items() if key not in selected and role in member.roles]
                add = [role for key, role in roles.items() if key in selected and role not in member.roles]
                if remove:
                    await member.remove_roles(*remove, reason='Preferencias elegidas por el miembro')
                if add:
                    await member.add_roles(*add, reason='Preferencias elegidas por el miembro')
            await self.track('ROLES', 'Actualizar roles opcionales del miembro', apply, interaction.id,
                snapshot=lambda: self.role_snapshot(interaction.guild, member.id))

    async def open_ticket(self, interaction):
        self.authorize(interaction)
        async with self.ticket_lock:
            for row in await self.call('tickets', interaction.user.id):
                if row['state'] == 'open':
                    channel = interaction.guild.get_channel(int(row['channel']))
                    if channel:
                        return channel
            marker = 'VIce ticket owner=' + str(interaction.user.id)
            for channel in interaction.guild.text_channels:
                if channel.topic == marker:
                    await self.call('add_ticket', channel.id, interaction.user.id, 'comunidad')
                    return channel
            async def apply():
                guild = interaction.guild
                category = guild.get_channel(self.store.get('category:help'))
                channel = await guild.create_text_channel(TICKET_OPEN_PREFIX + str(interaction.user.id)[-6:],
                    category=category, topic=marker, overwrites=self.overwrites(guild, 'ticket', interaction.user), reason=REASON)
                await self.call('add_ticket', channel.id, interaction.user.id, 'comunidad')
                await channel.send(embed=self.embed('🎫 Te escuchamos',
                    f'{interaction.user.mention}, explica tu consulta o reporte. Solo tú y el equipo podéis ver este canal.\n\n'
                    'Añade contexto y enlaces de mensajes si los tienes. Cuando esté resuelto, usa **Cerrar y archivar**.'),
                    view=CloseTicketPanel(self), allowed_mentions=discord.AllowedMentions.none())
                return channel
            return await self.track('TICKET_OPEN', 'Abrir ticket privado de comunidad', apply, interaction.id)

    async def close_ticket(self, interaction):
        self.authorize(interaction)
        async with self.ticket_lock:
            row = await self.call('ticket', interaction.channel_id)
            if not row or (int(row['owner']) != interaction.user.id and not self.is_staff(interaction.user)):
                raise ValueError('Solo el autor del ticket o el equipo puede cerrarlo.')
            if row['state'] == 'closed':
                await self.ticket_deletion.ensure_closed_panel(interaction.channel, row)
                return
            if row['state'] != 'open':
                raise ValueError('Este ticket ya no está disponible para cerrar.')
            async def apply():
                guild = interaction.guild
                category = guild.get_channel(self.store.get('category:closed'))
                category = category or discord.utils.get(guild.categories, name=CLOSED_CATEGORY)
                category = category or discord.utils.get(guild.categories, name='🔒 TICKETS ARCHIVADOS')
                if category is None:
                    category = await guild.create_category(CLOSED_CATEGORY, overwrites=self.overwrites(guild, 'staff'), reason=REASON)
                await self.call('put', 'category:closed', category.id)
                try:
                    owner = await guild.fetch_member(int(row['owner']))
                except discord.NotFound:
                    owner = discord.Object(id=int(row['owner']), type=discord.Member)
                closed_channel = await interaction.channel.edit(name=TICKET_CLOSED_PREFIX + str(row['owner'])[-6:], category=category,
                    topic='VIce ticket closed owner=' + str(row['owner']),
                    overwrites=self.overwrites(guild, 'closed', owner), reason=REASON)
                await self.call('ticket_state', interaction.channel_id, 'closed')
                await self.ticket_deletion.ensure_closed_panel(closed_channel)
            await self.track('TICKET_CLOSE', 'Cerrar ticket conservando su historial privado', apply, interaction.id)

    async def member_join(self, member):
        if member.guild.id != GUILD_ID or member.bot:
            return
        await self.ready_event.wait()
        current = await member.guild.fetch_member(member.id)
        if current.joined_at:
            await self.call('put', 'member_joined:' + str(current.id), current.joined_at.isoformat())
        role = self.role(member.guild, 'member')
        if role is None or role.permissions.value != 0:
            raise ValueError('El rol automático Miembro necesita revisión del equipo.')
        if role not in current.roles:
            event, _ = self.welcome.event(current)
            async def assign():
                await current.add_roles(role, reason='Rol inicial automático al entrar a GTA VI Latino')
            await self.track('AUTO_MEMBER', 'Entregar rol Miembro al entrar', assign, event,
                snapshot=lambda: self.role_snapshot(member.guild, current.id))
        await self.welcome.joined(current)

    async def resolve_departure(self, guild, user, left):
        self.validate_guild(guild)
        since = left - timedelta(seconds=15)
        until = left + timedelta(seconds=10)
        for attempt in range(3):
            matches = []
            try:
                for action, label in [(discord.AuditLogAction.kick, 'Expulsión'), (discord.AuditLogAction.ban, 'Baneo')]:
                    async for entry in guild.audit_logs(limit=20, action=action, after=since):
                        if (getattr(entry.target, 'id', None) == user.id and entry.action == action
                                and since <= entry.created_at <= until):
                            matches.append((entry, label))
                if matches:
                    entry, label = min(matches, key=lambda item: abs((item[0].created_at - left).total_seconds()))
                    reason = entry.reason or 'No se indicó una razón en el registro de auditoría.'
                    return label, reason, entry.user
            except discord.Forbidden:
                return 'Salida del servidor', 'No se pudo confirmar el motivo: Discord no permitió consultar la auditoría.', None
            except discord.HTTPException:
                if attempt == 2:
                    return 'Salida del servidor', 'No se pudo confirmar el motivo porque la auditoría no está disponible.', None
            if attempt < 2:
                await asyncio.sleep(2)
        return ('Salida del servidor',
                'No se detectó una expulsión ni un baneo en la auditoría. Discord no proporciona el motivo personal de una salida voluntaria.', None)

    async def departure_card(self, user):
        asset = user.display_avatar.with_format('png').with_size(256)
        async with self.welcome.slots:
            avatar = await WelcomeCards.avatar_bytes(self.welcome, asset)
            return await asyncio.to_thread(render_card, user.display_name, user.name, avatar,
                template='goodbye-template.jpg', heading='PUERTO RICO + LATINOAMÉRICA · HASTA PRONTO')

    async def member_remove(self, user, guild=None):
        guild = guild or getattr(user, 'guild', None)
        if guild is None or guild.id != GUILD_ID or user.bot:
            return
        self.validate_guild(guild)
        left = datetime.now(timezone.utc)
        await self.ready_event.wait()
        channel = self.channel(guild, 'goodbye')
        if (channel is None or channel.guild.id != GUILD_ID or
                channel.overwrites_for(guild.default_role).view_channel is not False):
            raise ValueError('El canal de despedidas debe ser privado para el equipo.')
        allowed_ids = {OWNER_ID, BOT_ID, self.store.get('role:founder'), self.store.get('role:admin')}
        for target, overwrite in channel.overwrites.items():
            if overwrite.view_channel is True and target.id not in allowed_ids:
                raise ValueError('Despedidas debe ser visible solo para los administradores.')
        joined = getattr(user, 'joined_at', None)
        joined_value = joined.isoformat() if isinstance(joined, datetime) else self.store.get('member_joined:' + str(user.id))
        # Membership generations distinguish a second departure after rejoining.
        # Uncached users without any known join get a fresh event, never a
        # permanent ID-only receipt that would suppress every future departure.
        key = f'goodbye:{user.id}:{joined_value or left.isoformat()}'
        marker = 'VIce District • ' + key
        async with self.goodbye_lock:
            existing = self.store.get(key)
            if existing:
                return existing
            async for message in channel.history(limit=100):
                if message.author.id == BOT_ID and any(e.footer.text == marker for e in message.embeds):
                    await self.call('put', key, message.id)
                    return message.id
            name = discord.utils.escape_markdown(clean_name(user.display_name))[:100]
            username = discord.utils.escape_markdown(clean_name(user.name))[:100]
            kind, reason, actor = await self.resolve_departure(guild, user, left)
            filename = 'vice-despedida-' + hashlib.sha256(key.encode()).hexdigest()[:16] + '.jpg'
            embed = self.embed('🚪 Hasta luego, ' + name,
                f'**{name}** salió del servidor.\n\n'
                f'**Usuario:** {username}\n**ID:** `{user.id}`\n'
                f'**Salida:** {discord.utils.format_dt(left, "F")}\n\n'
                'Registro privado para la administración del distrito.', CORAL)
            embed.add_field(name='Tipo de salida', value=kind, inline=False)
            embed.add_field(name='Razón', value=discord.utils.escape_markdown(reason)[:1024], inline=False)
            if actor:
                embed.add_field(name='Responsable',
                    value=f'{discord.utils.escape_markdown(str(actor))[:100]} · `{actor.id}`', inline=False)
            if joined_value:
                try:
                    joined_time = datetime.fromisoformat(joined_value)
                    embed.add_field(name='Se unió al distrito', value=discord.utils.format_dt(joined_time, 'F'))
                except ValueError:
                    pass
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_image(url='attachment://' + filename)
            embed.set_footer(text=marker)
            embed.timestamp = left
            async def snapshot():
                return dict(guild=GUILD_ID, channel=channel.id, member=user.id, message=self.store.get(key))
            async def send():
                card = await self.departure_card(user)
                message = await channel.send(embed=embed, file=discord.File(io.BytesIO(card), filename=filename),
                    allowed_mentions=discord.AllowedMentions.none())
                await self.call('put', key, message.id)
                log.info('VICE_GOODBYE_SENT guild=%s member=%s message=%s', GUILD_ID, user.id, message.id)
                return message.id
            return await self.track('GOODBYE', 'Registrar despedida privada del distrito', send, key, snapshot=snapshot)

    async def close(self):
        await self.audit.close()
        await self.voice.close()
        await self.welcome.close()

    def register_commands(self):
        group = app_commands.Group(name='vice', description='Tu comunidad GTA VI Latino')

        @group.command(name='evento', description='Programar un evento del corillo en hora de Puerto Rico')
        async def event(interaction: discord.Interaction):
            self.community.authorize_event(interaction)
            await interaction.response.send_modal(EventModal(self.community))

        @group.command(name='bienvenida', description='Ver tu tarjeta con nombre y avatar')
        async def welcome(interaction: discord.Interaction):
            await self.welcome.preview(interaction)

        @group.command(name='roles', description='Elegir plataformas, región y avisos')
        async def roles(interaction: discord.Interaction):
            self.authorize(interaction)
            await interaction.response.send_message('Personaliza tu perfil del distrito.', view=RolesPanel(self), ephemeral=True)

        @group.command(name='estado', description='Estado de la comunidad y las bienvenidas')
        async def status(interaction: discord.Interaction):
            self.authorize(interaction, staff=True)
            await interaction.response.send_message(f'🟢 **VIce District**\nConfigurado: {self.configured}\n'
                f'Bienvenidas con avatar: {bool(self.welcome.task and not self.welcome.task.done())}\n'
                f'Roles de personas: {sum(not r[0].endswith("separator") for r in ROLES) + 1}\n'
                f'Separadores visuales: 4\nDespedidas privadas: {bool(self.channel_id("goodbye"))}\n'
                f'Versión: {VERSION}\nEquipo: {STAFF_VERSION}', ephemeral=True)

        @group.command(name='publicar', description='Publicar un anuncio, una noticia o un evento')
        @app_commands.choices(destino=[app_commands.Choice(name=n, value=k) for k,n in
            [('announcements','Anuncios'),('news','Noticias'),('events','Eventos')]])
        async def publish(interaction: discord.Interaction, destino: app_commands.Choice[str], titulo: str,
                          texto: str, avisar: bool = False):
            self.authorize(interaction, staff=True)
            # Support can handle tickets; public announcements belong to owner/moderators.
            mod = self.role(interaction.guild, 'mod')
            if interaction.user.id != OWNER_ID and mod not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
                raise ValueError('Solo Fundador, Administrador o Moderación puede publicar anuncios.')
            if not 1 <= len(titulo) <= 256 or not 1 <= len(texto) <= 3800:
                raise ValueError('Título: hasta 256 caracteres. Texto: hasta 3800 caracteres.')
            await interaction.response.defer(ephemeral=True)
            channel = self.channel(interaction.guild, destino.value)
            role = self.role(interaction.guild, 'events' if destino.value == 'events' else 'news') if avisar else None
            async def apply():
                return await channel.send(content=role.mention if role else None, embed=self.embed(titulo, texto),
                    allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=[role] if role else []))
            message = await self.track('PUBLISH', 'Publicar contenido de la comunidad', apply, interaction.id)
            await interaction.followup.send('Publicado: ' + message.jump_url, ephemeral=True)

        self.bot.tree.add_command(group, guild=discord.Object(id=GUILD_ID))
