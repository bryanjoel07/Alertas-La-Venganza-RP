"""Additive, journaled optional-role migration for the Latino community only."""
import asyncio
import logging
import uuid

import discord

from studio_journal import server_snapshot
from vice_design import BOT_ID, GUILD_ID
from vice_role_catalog import (CATALOG_VERSION, OPTIONAL_ROLES, COUNTRY_KEYS,
                               REGION_KEYS, PLATFORM_KEYS, INTEREST_ROLES, RETIRED_KEYS)

log = logging.getLogger('ViceDistrict.optional_roles')
RELEASE_KEY = 'optional_roles_release'
ROLES_TOPIC = ('Personaliza tu perfil: país o territorio, regiones, plataformas y avisos. '
               'Todo es opcional y puedes cambiarlo cuando quieras.')
REASON = 'Países, regiones y plataformas solicitados por el propietario'
# The owner-authorized removal set belongs to v2 permanently. Cosmetic catalog
# revisions must reuse its receipts rather than freezing/deleting those IDs anew.
RETIREMENT_KEY = 'optional_roles:retirement:vice-optional-role-catalog-v2-hispano'


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
        state['retired_role_registry'] = {key: self.system.store.get('role:' + key) for key in sorted(RETIRED_KEYS)}
        state['retirement_plan'] = self.system.store.get(RETIREMENT_KEY)
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

    async def retire_unused(self, guild, protected_ids):
        """Retire only the frozen, registered out-of-scope roles, never members."""
        active_keys = {spec[0] for spec in OPTIONAL_ROLES}
        if active_keys & set(RETIRED_KEYS):
            raise ValueError('El catálogo activo coincide con un rol marcado para retirar.')
        active_ids = {int(value) for key in active_keys if (value := self.system.store.get('role:' + key))}
        plan = self.system.store.get(RETIREMENT_KEY)
        if plan is None:
            plan = [dict(key=key, id=int(value), state='pending') for key in sorted(RETIRED_KEYS)
                    if (value := self.system.store.get('role:' + key))]
            await self.system.call('put', RETIREMENT_KEY, plan)
        ids = [row['id'] for row in plan]
        if len(ids) != len(set(ids)) or set(ids) & (active_ids | protected_ids):
            raise ValueError('El plan de retirada contiene roles duplicados o protegidos.')
        for row in plan:
            if (row['key'] not in RETIRED_KEYS or
                    self.system.store.get('role:' + row['key']) != row['id']):
                raise ValueError('Un registro de retirada cambió; no se eliminará ese rol.')
        pending = [row for row in plan if row['state'] == 'pending']
        if not pending:
            return
        for row in pending:
            self.validate(guild)
            roles = {role.id: role for role in await guild.fetch_roles()}
            role = roles.get(row['id'])
            if role is None:
                row['state'] = 'deleted_or_absent'
                await self.system.call('put', RETIREMENT_KEY, plan)
                continue
            bot_ids = {role.id for role in guild.me.roles}
            bot_role = max(role for role in roles.values() if role.id in bot_ids)
            self.validate_role(guild, role, bot_role, protected_ids | active_ids)
            if self.system.store.get('role:' + row['key']) != role.id:
                raise ValueError('Cambió el rol registrado antes de retirarlo.')
            # Refresh REST membership immediately before each individual delete.
            # _roles is Discord's raw SnowflakeList; Member.roles can hide IDs
            # missing from the gateway cache.
            assigned = 0
            async for member in guild.fetch_members(limit=None):
                if member.guild.id != GUILD_ID:
                    raise ValueError('La comprobación de miembros salió del servidor autorizado.')
                assigned += role.id in member._roles
            if assigned:
                row.update(state='kept_assigned', member_count=assigned)
                await self.system.call('put', RETIREMENT_KEY, plan)
                log.warning('VICE_OPTIONAL_ROLE_RETAINED key=%s members=%s', row['key'], assigned)
                continue
            row['before'] = dict(name=role.name, position=role.position, color=role.colour.value,
                                 permissions=role.permissions.value, members=0)
            await self.system.call('put', RETIREMENT_KEY, plan)
            try:
                await role.delete(reason='Catálogo hispanoamericano solicitado por el propietario')
            except discord.NotFound:
                pass
            row['state'] = 'deleted'
            self.system.role_cache.pop(row['key'], None)
            await self.system.call('put', RETIREMENT_KEY, plan)
        log.info('VICE_OPTIONAL_ROLES_RETIRED deleted=%s retained=%s',
                 sum(row['state'] in {'deleted', 'deleted_or_absent'} for row in plan),
                 sum(row['state'] == 'kept_assigned' for row in plan))

    def bucket_positions(self, roles, crew, entry):
        """Bounded sections preserve old Mexico's ID and country alphabetization."""
        country_keys = tuple(key for key in COUNTRY_KEYS if key != 'pr')
        mexico_index = country_keys.index('mexico')
        groups = [('country_separator',), ('pr',), country_keys[:mexico_index],
                  ('mexico',), country_keys[mexico_index + 1:],
                  ('region_separator',), REGION_KEYS, ('preferences_separator',), PLATFORM_KEYS,
                  ('interests_separator',), tuple(role[0] for role in INTEREST_ROLES)]
        top = crew.position - 1
        if top - len(groups) + 1 <= entry.position:
            raise ValueError('No hay espacio entre Comunidad y Recién llegados para ordenar las secciones.')
        by_key = {key: roles[self.system.store.get('role:' + key)] for key, *_ in OPTIONAL_ROLES}
        positions = {by_key[key]: top - index for index, keys in enumerate(groups) for key in keys}
        if set(positions) != set(by_key.values()):
            raise ValueError('Las secciones no cubren exactamente el catálogo activo.')
        return positions

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
        await self.retire_unused(guild, protected_ids)
        roles = {role.id: role for role in await guild.fetch_roles()}
        bot_role = max(role for role in roles.values() if role.id in bot_ids)
        ordered_ids = []
        for spec in OPTIONAL_ROLES:
            role = await self.ensure_role(guild, spec, roles, bot_role, protected_ids)
            ordered_ids.append(role.id)
        # Equal positions are supported by Discord, ordered by snowflake ID.
        # Group the cosmetic sections into bounded slots below Crew. Menus stay
        # alphabetical; section peers have Discord's deterministic ID order.
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
        positions = self.bucket_positions(current, current[crew.id], current[entry.id])
        if max(positions.values()) >= fresh_bot.position:
            raise ValueError('La jerarquía del bot no permite ordenar las secciones opcionales.')
        desired = sorted(fresh, key=lambda role: (positions.get(role, role.position), -role.id))
        optional_indices = [index for index, role in enumerate(desired) if role.id in optional_ids]
        if optional_indices[-1] - optional_indices[0] + 1 != len(optional_indices):
            raise ValueError('Un rol ajeno ocupa el espacio reservado para las secciones opcionales.')
        if any(role.position != position for role, position in positions.items()):
            await guild.edit_role_positions(positions=positions, reason=REASON)
        final = sorted(await guild.fetch_roles())
        if [role.id for role in final] != [role.id for role in desired]:
            raise ValueError('Discord no confirmó el orden esperado de los roles.')
        if [role.id for role in final if role.id not in optional_ids] != [role.id for role in remaining]:
            raise ValueError('Cambió el orden relativo de un rol ajeno al catálogo.')
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
