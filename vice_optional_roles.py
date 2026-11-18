"""Additive, journaled optional-role migration for the Latino community only."""
import asyncio
import logging
import uuid

import discord

from studio_journal import server_snapshot
from vice_design import BOT_ID, GUILD_ID
from vice_role_catalog import CATALOG_VERSION, OPTIONAL_ROLES

log = logging.getLogger('ViceDistrict.optional_roles')
RELEASE_KEY = 'optional_roles_release'
ROLES_TOPIC = ('Personaliza tu perfil: país o territorio, regiones, plataformas y avisos. '
               'Todo es opcional y puedes cambiarlo cuando quieras.')
REASON = 'Países, regiones y plataformas solicitados por el propietario'


class OptionalRoles:
    def __init__(self, system):
        self.system = system
        self.lock = asyncio.Lock()

    def validate(self, guild):
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID or guild.me is None or guild.me.id != BOT_ID:
            raise ValueError('Se requiere EssChino Studio Bot para organizar los roles.')

    def validate_role(self, guild, role, bot_role, protected_ids):
        if (role.guild.id != GUILD_ID or role.id in protected_ids or role.managed
                or role.is_default() or role.permissions.value != 0 or not role < bot_role):
            raise ValueError('Un rol opcional registrado necesita revisión antes de modificarlo.')

    async def snapshot(self, guild):
        state = await server_snapshot(guild)
        state['catalog_release'] = self.system.store.get(RELEASE_KEY)
        state['role_registry'] = {key: self.system.store.get('role:' + key) for key, *_ in OPTIONAL_ROLES}
        channel = await guild.fetch_channel(self.system.channel_id('roles'))
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError('No se confirmó el canal de roles registrado.')
        message = await self.system.find_panel(channel, 'roles')
        state['roles_panel'] = None if message is None else dict(
            id=str(message.id), channel=str(channel.id), content=message.content,
            embeds=[embed.to_dict() for embed in message.embeds],
            components=[component.to_dict() for component in message.components], pinned=message.pinned)
        return state

    async def recover_creation(self, guild, state, roles):
        """A name is never ownership evidence after an interrupted create."""
        reason = REASON + ' • nonce:' + state['nonce']
        matches = []
        async for entry in guild.audit_logs(limit=1000, action=discord.AuditLogAction.role_create,
                                             user=discord.Object(id=BOT_ID)):
            if (getattr(entry.user, 'id', None) == BOT_ID and entry.reason == reason
                    and getattr(entry.target, 'id', None) in roles):
                matches.append(roles[entry.target.id])
        if len(matches) != 1:
            raise ValueError('Una creación de rol quedó pendiente; espera a que Discord confirme su auditoría.')
        return matches[0]

    async def ensure_role(self, guild, spec, roles, bot_role, protected_ids):
        key, name, color, permissions, hoist, _old = spec
        if permissions or hoist:
            raise ValueError('El catálogo opcional solo admite roles cosméticos.')
        stored_id = self.system.store.get('role:' + key)
        role = roles.get(int(stored_id)) if stored_id else None
        if stored_id and role is None:
            raise ValueError('Falta un rol registrado; no se reemplazará sin revisar: ' + key)
        if role is None:
            receipt_key = 'optional_roles:create:' + key
            state = self.system.store.get(receipt_key)
            if state and state.get('attempted'):
                role = await self.recover_creation(guild, state, roles)
            else:
                state = state or dict(nonce=uuid.uuid4().hex, attempted=False)
                await self.system.call('put', receipt_key, state)
                state = dict(state, attempted=True)
                await self.system.call('put', receipt_key, state)
                try:
                    role = await guild.create_role(name=name, colour=discord.Colour(color),
                        permissions=discord.Permissions.none(), hoist=False, mentionable=False,
                        reason=REASON + ' • nonce:' + state['nonce'])
                except discord.HTTPException as error:
                    # A definitive rejection did not create an object. Ambiguous
                    # network/server outcomes must be recovered through audit.
                    if 400 <= error.status < 500 and error.status != 429:
                        await self.system.call('put', receipt_key, dict(state, attempted=False))
                    raise
                roles[role.id] = role
            self.validate_role(guild, role, bot_role, protected_ids)
            await self.system.call('put', 'role:' + key, role.id)
        self.validate_role(guild, role, bot_role, protected_ids)
        if (role.name != name or role.colour.value != color or role.hoist or role.mentionable):
            role = await role.edit(name=name, colour=discord.Colour(color),
                permissions=discord.Permissions.none(), hoist=False, mentionable=False, reason=REASON)
            roles[role.id] = role
        self.system.role_cache[key] = role
        return role

    async def migrate(self, guild, refresh_panel):
        self.validate(guild)
        roles = {role.id: role for role in await guild.fetch_roles()}
        bot_ids = {role.id for role in guild.me.roles}
        bot_role = max(role for role in roles.values() if role.id in bot_ids)
        protected_keys = ('founder', 'admin', 'mod', 'support', 'creator', 'team_separator',
                          'community_separator', 'legend', 'veteran', 'citizen', 'crew',
                          'entry_separator', 'member')
        protected_ids = {int(value) for key in protected_keys
                         if (value := self.system.store.get('role:' + key))}
        entry = roles.get(self.system.store.get('role:entry_separator'))
        member = roles.get(self.system.store.get('role:member'))
        crew = roles.get(self.system.store.get('role:crew'))
        if not entry or not member or not crew or not member < entry < crew < bot_role:
            raise ValueError('No se confirmó la jerarquía de comunidad y recién llegados.')
        registered = [self.system.store.get('role:' + key) for key, *_ in OPTIONAL_ROLES]
        existing_ids = [int(value) for value in registered if value]
        if len(existing_ids) != len(set(existing_ids)):
            raise ValueError('Dos roles opcionales apuntan al mismo registro.')
        if len(roles) + sum(not value for value in registered) > 250:
            raise ValueError('El servidor no tiene espacio para completar el catálogo de roles.')
        # Preflight the whole existing block before the first Discord mutation.
        for rid in existing_ids:
            if rid not in roles:
                raise ValueError('Falta un rol opcional registrado.')
            self.validate_role(guild, roles[rid], bot_role, protected_ids)
        channel = await guild.fetch_channel(self.system.channel_id('roles'))
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError('No se confirmó el canal de roles registrado.')
        ordered_ids = []
        for spec in OPTIONAL_ROLES:
            role = await self.ensure_role(guild, spec, roles, bot_role, protected_ids)
            ordered_ids.append(role.id)
        # Insert the cosmetic block immediately above the entry divider. Only
        # optional roles are sent to Discord's position endpoint; all remaining
        # roles keep their relative order and their permissions/assignments.
        fresh = sorted(await guild.fetch_roles())
        optional_ids = set(ordered_ids)
        current = {role.id: role for role in fresh}
        fresh_bot = max(role for role in fresh if role.id in bot_ids)
        if not current[member.id] < current[entry.id] < current[crew.id] < fresh_bot:
            raise ValueError('La jerarquía cambió durante la organización de roles.')
        for rid in ordered_ids:
            if rid not in current:
                raise ValueError('Un rol opcional desapareció durante la organización.')
            self.validate_role(guild, current[rid], fresh_bot, protected_ids)
        remaining = [role for role in fresh if role.id not in optional_ids]
        base = next(index for index, role in enumerate(remaining) if role.id == entry.id) + 1
        by_id = {role.id: role for role in fresh}
        desired = remaining[:base] + [by_id[rid] for rid in reversed(ordered_ids)] + remaining[base:]
        if [role.id for role in fresh] != [role.id for role in desired]:
            await guild.edit_role_positions(positions={by_id[rid]: base + offset
                for offset, rid in enumerate(reversed(ordered_ids))}, reason=REASON)
        final = sorted(await guild.fetch_roles())
        if [role.id for role in final] != [role.id for role in desired]:
            raise ValueError('Discord no confirmó el orden esperado de los roles.')
        for key, *_ in OPTIONAL_ROLES:
            rid = self.system.store.get('role:' + key)
            self.system.role_cache[key] = next(role for role in final if role.id == rid)
        if channel.topic != ROLES_TOPIC:
            await channel.edit(topic=ROLES_TOPIC, reason=REASON)
        await refresh_panel()
        await self.system.call('put', RELEASE_KEY, CATALOG_VERSION)
        log.info('VICE_OPTIONAL_ROLES_READY guild=%s roles=%s release=%s',
                 GUILD_ID, len(ordered_ids), CATALOG_VERSION)

    async def ready(self, refresh_panel):
        async with self.lock:
            guild = self.system.bot.get_guild(GUILD_ID)
            self.validate(guild)
            if self.system.store.get(RELEASE_KEY) == CATALOG_VERSION:
                return
            async with self.system.roles_lock:
                await self.system.track('OPTIONAL_ROLE_CATALOG', 'Organizar países, regiones y plataformas',
                    lambda: self.migrate(guild, refresh_panel), CATALOG_VERSION,
                    snapshot=lambda: self.snapshot(guild))
