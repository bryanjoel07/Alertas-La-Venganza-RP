"""Guild-isolated GTA VI community, persistent panels and private support."""
import asyncio
from contextlib import closing
import io
import json
import logging
from pathlib import Path

import discord
from discord import app_commands

from esschino import StudioStore
from studio_journal import ChangeLog, server_snapshot
from vice_design import (GUILD_ID, BOT_ID, OWNER_ID, VERSION, PINK, CYAN, DESCRIPTION,
                         ROLES, GROUPS, SELF_ROLES, CATEGORIES, CHANNELS, panel_copy)
from vice_welcome import ViceWelcome, render_cover

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
        await interaction.followup.send('🌴 ¡Ya eres parte del distrito! Al unirte aceptas las normas. '
            f'Ahora personaliza tu perfil en <#{self.system.channel_id("roles")}>.', ephemeral=True)

    @discord.ui.button(label='Elegir mis roles', emoji='🎭', style=discord.ButtonStyle.secondary,
                       custom_id='vice:v1:roles', row=0)
    async def roles(self, interaction, button):
        await interaction.response.send_message('Elige tus plataformas, región e intereses. Cada grupo se guarda por separado.',
            view=RolesPanel(self.system), ephemeral=True)

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
        self.ready_lock = asyncio.Lock()
        self.roles_lock = asyncio.Lock()
        self.ticket_lock = asyncio.Lock()
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
        allowed = {self.store.get('role:mod'), self.store.get('role:support')}
        return member.id == OWNER_ID or member.guild_permissions.administrator or any(r.id in allowed for r in member.roles)

    def embed(self, title, description, color=PINK):
        return discord.Embed(title=title, description=description, color=color).set_footer(
            text='GTA VI Latino • VIce District • Comunidad de fans no oficial')

    async def track(self, kind, title, operation, request, snapshot=None):
        self.validate_guild(self.bot.get_guild(GUILD_ID))
        return await self.changes.tracked('VICE_' + kind, title, operation, request_id=str(request), snapshot=snapshot)

    async def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await self.call('initialize')
        await asyncio.to_thread(self.changes.journal.initialize)
        await self.welcome.start()
        for view in [WelcomePanel(self, links=False), RolesPanel(self), SupportPanel(self), CloseTicketPanel(self)]:
            self.bot.add_view(view)

    def overwrites(self, guild, policy, owner=None):
        self.validate_guild(guild)
        private = policy in {'staff', 'staffread', 'ticket', 'closed'}
        readonly = policy in {'read', 'staffread', 'closed'}
        rules = {guild.default_role: discord.PermissionOverwrite(view_channel=not private,
            read_message_history=not private, send_messages=not (private or readonly),
            send_messages_in_threads=not (private or readonly), create_public_threads=False,
            create_private_threads=False, mention_everyone=False)}
        rules[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
            send_messages=True, embed_links=True, attach_files=True, connect=True, speak=True,
            manage_channels=True, manage_messages=True, pin_messages=True)
        for key in ['founder', 'mod', 'support']:
            role = self.role(guild, key)
            if role:
                rules[role] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                    send_messages=policy not in {'closed', 'staffread'} and (key != 'support' or policy != 'read'),
                    send_messages_in_threads=policy not in {'closed', 'staffread', 'read'},
                    connect=True, speak=True, attach_files=True, embed_links=True)
        if owner:
            rules[owner] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                send_messages=policy != 'closed', attach_files=True, embed_links=True,
                send_messages_in_threads=False, create_public_threads=False, create_private_threads=False)
        return rules

    async def ready(self):
        async with self.ready_lock:
            if self.configured:
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
            self.configured = True
            self.ready_event.set()
            if self.welcome.task is None or self.welcome.task.done():
                self.welcome.task = asyncio.create_task(self.welcome.recover(), name='vice-welcome-recovery')
            log.info('VICE_READY guild=%s roles=%s channels=%s release=%s', GUILD_ID, len(ROLES) + 1, len(CHANNELS), VERSION)

    async def install(self, guild):
        roles = await guild.fetch_roles()
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
        if self.store.get('owner_example'):
            return
        member = await guild.fetch_member(OWNER_ID)
        filename = 'vice-bienvenida-muestra.jpg'
        channel = self.channel(guild, 'welcome')
        async for message in channel.history(limit=100):
            if message.author.id == BOT_ID and any(a.filename == filename for a in message.attachments):
                await self.call('put', 'owner_example', message.id)
                return
        card = await self.welcome.card(member)
        message = await channel.send(embed=self.welcome.embed(member, filename, example=True),
            file=discord.File(io.BytesIO(card), filename=filename), allowed_mentions=discord.AllowedMentions.none())
        await self.call('put', 'owner_example', message.id)

    async def role_snapshot(self, guild, user_id):
        member = await guild.fetch_member(user_id)
        return dict(guild=GUILD_ID, member=user_id, roles=[r.id for r in member.roles])

    async def join_community(self, interaction):
        self.authorize(interaction)
        role = self.role(interaction.guild, 'member')
        if role is None or role.permissions.value != 0:
            raise ValueError('El rol de Comunidad necesita revisión del equipo.')
        async with self.roles_lock:
            member = await interaction.guild.fetch_member(interaction.user.id)
            async def apply():
                await member.add_roles(role, reason='El miembro acepta las normas y se une a la comunidad')
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
                channel = await guild.create_text_channel('🎫・ticket-' + str(interaction.user.id)[-6:],
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
        row = await self.call('ticket', interaction.channel_id)
        if not row or (int(row['owner']) != interaction.user.id and not self.is_staff(interaction.user)):
            raise ValueError('Solo el autor del ticket o el equipo puede cerrarlo.')
        if row['state'] == 'closed':
            return
        async with self.ticket_lock:
            async def apply():
                guild = interaction.guild
                category = guild.get_channel(self.store.get('category:closed'))
                category = category or discord.utils.get(guild.categories, name='🔒 TICKETS ARCHIVADOS')
                if category is None:
                    category = await guild.create_category('🔒 TICKETS ARCHIVADOS', overwrites=self.overwrites(guild, 'staff'), reason=REASON)
                await self.call('put', 'category:closed', category.id)
                try:
                    owner = await guild.fetch_member(int(row['owner']))
                except discord.NotFound:
                    owner = discord.Object(id=int(row['owner']), type=discord.Member)
                await interaction.channel.edit(name='🔒・cerrado-' + str(row['owner'])[-6:], category=category,
                    topic='VIce ticket closed owner=' + str(row['owner']),
                    overwrites=self.overwrites(guild, 'closed', owner), reason=REASON)
                await interaction.channel.send(embed=self.embed('🔒 Conversación archivada',
                    'El ticket está cerrado. Su historial permanece privado para el autor y el equipo.'),
                    allowed_mentions=discord.AllowedMentions.none())
                await self.call('ticket_state', interaction.channel_id, 'closed')
            await self.track('TICKET_CLOSE', 'Cerrar ticket conservando su historial privado', apply, interaction.id)

    async def member_join(self, member):
        if member.guild.id != GUILD_ID or member.bot:
            return
        await self.ready_event.wait()
        current = await member.guild.fetch_member(member.id)
        await self.welcome.joined(current)

    async def close(self):
        await self.welcome.close()

    def register_commands(self):
        group = app_commands.Group(name='vice', description='Tu comunidad GTA VI Latino')

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
                f'Roles de comunidad: {len(ROLES) + 1}\nVersión: {VERSION}', ephemeral=True)

        @group.command(name='publicar', description='Publicar un anuncio, una noticia o un evento')
        @app_commands.choices(destino=[app_commands.Choice(name=n, value=k) for k,n in
            [('announcements','Anuncios'),('news','Noticias'),('events','Eventos')]])
        async def publish(interaction: discord.Interaction, destino: app_commands.Choice[str], titulo: str,
                          texto: str, avisar: bool = False):
            self.authorize(interaction, staff=True)
            # Support can handle tickets; public announcements belong to owner/moderators.
            mod = self.role(interaction.guild, 'mod')
            if interaction.user.id != OWNER_ID and mod not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
                raise ValueError('Solo Fundador o Moderación puede publicar anuncios.')
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
