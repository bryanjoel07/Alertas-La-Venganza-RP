"""One-time, guild-scoped VIP styling and private rooms for Discord boosters."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_role_icons import role_state
from vice_channel_style import format_name

log = logging.getLogger('ViceDistrict.booster_club')
VERSION = 'vice-booster-club-v1'
BOOSTER_ID = 1572695862809853982
SUPPORT_ID = 1572473452848226364
CREATOR_ID = 1572465800231788685
COMMUNITY_CATEGORY_ID = 1572463586222149632
STAFF_IDS = (1572465087304700047, 1572581938798272642,
             1572465389877858415, SUPPORT_ID)
ROLE_NAME, ROLE_COLOR = '💎 VIP del Distrito', 0xFF4FD8
CATEGORY_NAME = '━━ 💎 CLUB BOOSTER ━━'
LOUNGE_NAME, TERRACE_NAME = '╭・💬│lounge-vip', '╰・🔊│terraza-vip'
LOUNGE_TOPIC = 'Club privado de quienes mantienen una mejora activa: charla y comunidad VIP.'
RELEASE_KEY = 'booster_club:release'
ROLE_RECEIPT = 'booster_club:role:' + VERSION
PANEL_RECEIPT = 'booster_club:panel:' + VERSION
FOOTER = 'VIce District • panel:booster_club'
REASON = 'Club Booster solicitado por el propietario'


def benefits_copy(lounge_id, terrace_id, high_quality=False):
    """Exact benefits, reusable by the public boosts information panel."""
    voice = 'audio de hasta 256 kbps' if high_quality else 'voz privada'
    return ('💎 **Rol VIP del Distrito:** color rosa y lugar destacado bajo el equipo.\n'
            f'💬 **Lounge privado:** comparte con otros boosters en <#{lounge_id}>.\n'
            f'🔊 **Terraza VIP:** {voice} para reunirte en <#{terrace_id}>.\n\n'
            'Discord asigna y retira el rol automáticamente según las mejoras activas. '
            'El acceso al club acompaña al rol; el equipo también puede entrar para ayudar.')


class BoosterClub:
    def __init__(self, system):
        self.system = system
        self.lock = asyncio.Lock()

    async def context(self):
        if getattr(self.system.bot.user, 'id', None) != BOT_ID:
            raise ValueError('El Club Booster requiere el bot autorizado.')
        guild = await self.system.bot.fetch_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('El Club Booster pertenece únicamente al distrito autorizado.')
        roles = {role.id: role for role in await guild.fetch_roles()}
        member = await guild.fetch_member(BOT_ID)
        if member.id != BOT_ID or member.guild.id != GUILD_ID:
            raise ValueError('No se confirmó la identidad del bot.')
        bot_ids = set(member._roles) | {GUILD_ID}
        bot_roles = [role for role in roles.values() if role.id in bot_ids]
        permissions = discord.Permissions(0)
        for role in bot_roles:
            permissions.value |= role.permissions.value
        if not bot_roles or not (permissions.administrator or
                (permissions.manage_channels and permissions.manage_roles)):
            raise ValueError('El bot necesita administrar los canales y el rol VIP.')
        required = {GUILD_ID, BOOSTER_ID, CREATOR_ID, *STAFF_IDS}
        if not required <= roles.keys():
            raise ValueError('Faltan roles registrados del Club Booster o del equipo.')
        booster = roles[BOOSTER_ID]
        if (booster.guild.id != GUILD_ID or not booster.is_premium_subscriber()
                or not booster < max(bot_roles)):
            raise ValueError('El rol indicado no es el Booster cosmético administrable de Discord.')
        if not roles[CREATOR_ID] < roles[SUPPORT_ID] < max(bot_roles):
            raise ValueError('La jerarquía del equipo necesita revisión.')
        registered = self.system.store.get('role:booster')
        if registered is not None and int(registered) != BOOSTER_ID:
            raise ValueError('El registro Booster apunta a otro rol.')
        return dict(guild=guild, roles=roles, bot_member=member, booster=booster,
                    top_role=max(bot_roles))

    @staticmethod
    def overwrites(context):
        roles = context['roles']
        result = {roles[GUILD_ID]: discord.PermissionOverwrite(
            view_channel=False, read_message_history=False, send_messages=False, connect=False)}
        access = dict(view_channel=True, read_message_history=True, send_messages=True,
                      embed_links=True, attach_files=True, add_reactions=True,
                      connect=True, speak=True, stream=True, use_voice_activation=True)
        for rid in (BOOSTER_ID, *STAFF_IDS):
            result[roles[rid]] = discord.PermissionOverwrite(**access)
        result[discord.Object(id=OWNER_ID, type=discord.Member)] = discord.PermissionOverwrite(**access)
        result[context['bot_member']] = discord.PermissionOverwrite(**access)
        return result

    @staticmethod
    def overwrite_state(overwrites):
        return {str(target.id): dict(allow=str(value.pair()[0].value), deny=str(value.pair()[1].value))
                for target, value in overwrites.items()}

    def validate_channel(self, channel, context, kind, category_id=None):
        expected_type = {'category': discord.CategoryChannel, 'lounge': discord.TextChannel,
                         'terrace': discord.VoiceChannel}[kind]
        if not isinstance(channel, expected_type) or channel.guild.id != GUILD_ID:
            raise ValueError('El destino del club no es un canal del tipo y servidor esperados.')
        if kind != 'category' and channel.category_id != category_id:
            raise ValueError('El canal VIP no pertenece a la categoría privada registrada.')
        if self.overwrite_state(channel.overwrites) != self.overwrite_state(self.overwrites(context)):
            raise ValueError('Los permisos del Club Booster necesitan revisión; no se publicará contenido.')
        return channel

    async def style_role(self):
        receipt = self.system.store.get(ROLE_RECEIPT)
        if receipt and receipt.get('state') in {'complete', 'owner_ui_required'}:
            return receipt['state']
        latest = None
        async def snapshot():
            nonlocal latest
            latest = await self.context()
            return dict(guild=str(GUILD_ID), owner=str(OWNER_ID), role=role_state(latest['booster']),
                        hierarchy=[dict(id=str(role.id), position=role.position)
                                   for role in sorted(latest['roles'].values())],
                        receipt=self.system.store.get(ROLE_RECEIPT))
        async def apply():
            context = latest
            role = context['booster']
            before = role_state(role)
            state = self.system.store.get(ROLE_RECEIPT) or dict(state='pending', before=before)
            await self.system.call('put', ROLE_RECEIPT, state)
            def check_preserved(candidate):
                after = role_state(candidate)
                if any(after[key] != before[key] for key in
                       ('permissions', 'icon_hash', 'unicode_emoji', 'mentionable', 'managed')):
                    raise ValueError('Los permisos o el icono existentes del rol VIP cambiaron; se requiere revisión.')
            try:
                if (role.name != ROLE_NAME or role.colour.value != ROLE_COLOR or not role.hoist
                        or role.secondary_colour is not None or role.tertiary_colour is not None):
                    # Omitted permissions/display_icon retain the existing access
                    # and owner's freshly installed image, including on retries.
                    await role.edit(name=ROLE_NAME, colour=discord.Colour(ROLE_COLOR),
                                    secondary_color=None, tertiary_color=None,
                                    hoist=True, reason=REASON)
                context = await self.context()
                check_preserved(context['booster'])
                current = sorted(context['roles'].values())
                role = context['booster']
                remaining = [item for item in current if item.id != BOOSTER_ID]
                target = remaining.index(context['roles'][SUPPORT_ID])
                desired = remaining[:target] + [role] + remaining[target:]
                if [item.id for item in current] != [item.id for item in desired]:
                    support = context['roles'][SUPPORT_ID]
                    # Discord supports shared raw positions, sorted by ID. Find
                    # a slot that moves only VIP and preserves every other role.
                    candidates = range(max(1, support.position - 1), support.position + 1)
                    position = next((candidate for candidate in candidates if
                        [item.id for item in sorted(current, key=lambda item:
                            (candidate if item.id == BOOSTER_ID else item.position, -item.id))]
                        == [item.id for item in desired]), None)
                    if position is None:
                        raise ValueError('No hay una posición aislada para VIP debajo de Soporte.')
                    await context['guild'].edit_role_positions(positions={role: position}, reason=REASON)
                final = await self.context()
                check_preserved(final['booster'])
                ordered = sorted(final['roles'].values())
                vip_index = next(i for i, item in enumerate(ordered) if item.id == BOOSTER_ID)
                if (vip_index + 1 >= len(ordered) or ordered[vip_index + 1].id != SUPPORT_ID
                        or not final['roles'][CREATOR_ID] < final['booster']):
                    raise ValueError('Discord no confirmó el lugar de VIP bajo Soporte.')
                if [item.id for item in ordered if item.id != BOOSTER_ID] != [item.id for item in remaining]:
                    raise ValueError('Cambió el orden relativo de otro rol durante el ajuste VIP.')
                if (final['booster'].name != ROLE_NAME or final['booster'].colour.value != ROLE_COLOR
                        or not final['booster'].hoist or final['booster'].secondary_colour is not None
                        or final['booster'].tertiary_colour is not None):
                    raise ValueError('Discord no confirmó el diseño del rol VIP.')
            except discord.Forbidden:
                await self.system.call('put', ROLE_RECEIPT, dict(state, state='owner_ui_required'))
                log.warning('VICE_BOOSTER_ROLE_OWNER_UI_REQUIRED role=%s', BOOSTER_ID)
                return 'owner_ui_required'
            await self.system.call('put', 'role:booster', BOOSTER_ID)
            await self.system.call('put', ROLE_RECEIPT, dict(state, state='complete', after=role_state(final['booster'])))
            return 'complete'
        return await self.system.track('BOOSTER_ROLE', 'Destacar el rol VIP del Distrito',
            apply, VERSION + ':role', snapshot=snapshot)

    async def recover_channel(self, context, record, kind, category_id):
        guild = context['guild']
        matches = []
        after = datetime.fromisoformat(record['started_at']) - timedelta(seconds=5)
        async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.channel_create,
                                            after=after, user=discord.Object(id=BOT_ID)):
            if (getattr(entry.user, 'id', None) == BOT_ID
                    and entry.reason == record['reason'] and getattr(entry.target, 'id', None)):
                channel = await guild.fetch_channel(entry.target.id)
                matches.append(self.validate_channel(channel, context, kind, category_id))
        if len(matches) != 1:
            raise ValueError('Creación del club pendiente de auditoría; no se duplicará el canal.')
        return matches[0]

    async def ensure_channel(self, kind, category=None):
        key = {'category': 'booster_club', 'lounge': 'booster_lounge', 'terrace': 'booster_terrace'}[kind]
        registry = ('category:' if kind == 'category' else 'channel:') + key
        receipt_key = 'booster_club:create:' + key
        context = await self.context()
        category_id = getattr(category, 'id', None)
        registered = self.system.store.get(registry)
        if registered:
            return self.validate_channel(await context['guild'].fetch_channel(int(registered)),
                                         context, kind, category_id)
        latest = None
        async def snapshot():
            nonlocal latest
            latest = await self.context()
            return dict(guild=str(GUILD_ID), owner=str(OWNER_ID), registry=registry,
                        registered=self.system.store.get(registry), category=category_id,
                        expected_overwrites=self.overwrite_state(self.overwrites(latest)),
                        creation=self.system.store.get(receipt_key))
        async def create():
            context = latest
            guild = context['guild']
            record = self.system.store.get(receipt_key)
            if record and (record.get('guild') != GUILD_ID or record.get('kind') != kind):
                raise ValueError('El registro de creación del club no coincide.')
            if record and record.get('attempted'):
                channel = await self.recover_channel(context, record, kind, category_id)
            else:
                if kind != 'category':
                    fresh_category = await guild.fetch_channel(category_id)
                    self.validate_channel(fresh_category, context, 'category')
                else:
                    community = await guild.fetch_channel(COMMUNITY_CATEGORY_ID)
                    if not isinstance(community, discord.CategoryChannel) or community.guild.id != GUILD_ID:
                        raise ValueError('No se confirmó la categoría Corillo Latino.')
                if record is None:
                    nonce = uuid.uuid4().hex
                    record = dict(guild=GUILD_ID, kind=kind, started_at=datetime.now(timezone.utc).isoformat(),
                                  reason=REASON + ' • ' + key + ':' + nonce, nonce=nonce, attempted=False)
                    await self.system.call('put', receipt_key, record)
                overwrites = self.overwrites(context)
                record = dict(record, attempted=True)
                await self.system.call('put', receipt_key, record)
                try:
                    if kind == 'category':
                        channel = await guild.create_category(format_name(CATEGORY_NAME, category=True), position=community.position + 1,
                                                             overwrites=overwrites, reason=record['reason'])
                    elif kind == 'lounge':
                        channel = await guild.create_text_channel(format_name(LOUNGE_NAME), category=fresh_category,
                            position=0, topic=LOUNGE_TOPIC, overwrites=overwrites, reason=record['reason'])
                    else:
                        channel = await guild.create_voice_channel(format_name(TERRACE_NAME), category=fresh_category,
                            position=1, user_limit=0, bitrate=min(int(guild.bitrate_limit), 256000),
                            overwrites=overwrites, reason=record['reason'])
                except discord.HTTPException as error:
                    if 400 <= error.status < 500 and error.status != 429:
                        await self.system.call('put', receipt_key, dict(record, attempted=False))
                    raise
                self.validate_channel(channel, context, kind, category_id)
            await self.system.call('put', registry, channel.id)
            if kind == 'terrace':
                await self.system.call('put', 'channel:booster_terrace_bitrate', channel.bitrate)
            await self.system.call('put', receipt_key, dict(record, id=channel.id, complete=True))
            return channel
        return await self.system.track('BOOSTER_CHANNEL', 'Preparar espacio privado del Club Booster',
                                       create, VERSION + ':' + key, snapshot=snapshot)

    async def private_destinations(self):
        context = await self.context()
        guild = context['guild']
        category_id = self.system.store.get('category:booster_club')
        lounge_id = self.system.store.get('channel:booster_lounge')
        terrace_id = self.system.store.get('channel:booster_terrace')
        if not all((category_id, lounge_id, terrace_id)):
            raise ValueError('Faltan destinos privados del Club Booster.')
        category = self.validate_channel(await guild.fetch_channel(int(category_id)), context, 'category')
        lounge = self.validate_channel(await guild.fetch_channel(int(lounge_id)), context, 'lounge', category.id)
        terrace = self.validate_channel(await guild.fetch_channel(int(terrace_id)), context, 'terrace', category.id)
        return context, lounge, terrace

    async def ensure_panel(self):
        record = self.system.store.get(PANEL_RECEIPT)
        if record and record.get('complete'):
            return
        latest = None
        async def snapshot():
            nonlocal latest
            latest = await self.private_destinations()
            return dict(guild=str(GUILD_ID), lounge=str(latest[1].id), terrace=str(latest[2].id),
                        receipt=self.system.store.get(PANEL_RECEIPT))
        async def publish():
            _, lounge, terrace = latest
            record = self.system.store.get(PANEL_RECEIPT)
            if record is None:
                record = dict(guild=GUILD_ID, channel=lounge.id, nonce=uuid.uuid4().hex,
                              attempted=False, complete=False)
                await self.system.call('put', PANEL_RECEIPT, record)
            if record.get('guild') != GUILD_ID or record.get('channel') != lounge.id:
                raise ValueError('El registro del panel VIP apunta a otro destino.')
            marker = f'https://discord.com/channels/{GUILD_ID}/{lounge.id}?booster={record["nonce"]}'
            message = None
            if record.get('attempted'):
                matches = []
                async for candidate in lounge.history(limit=100):
                    if (candidate.author.id == BOT_ID and len(candidate.embeds) == 1
                            and candidate.embeds[0].footer.text == FOOTER and candidate.embeds[0].url == marker):
                        matches.append(candidate)
                if len(matches) != 1:
                    raise ValueError('El panel VIP quedó pendiente; no se publicará un duplicado.')
                message = matches[0]
            if message is None:
                embed = discord.Embed(title='💎 CLUB VIP DEL DISTRITO',
                    description='Gracias por apoyar al corillo. Estos son tus beneficios:\n\n' +
                                benefits_copy(lounge.id, terrace.id, terrace.bitrate >= 256000),
                    colour=ROLE_COLOR, url=marker)
                embed.set_footer(text=FOOTER)
                await self.system.call('put', PANEL_RECEIPT, dict(record, attempted=True))
                try:
                    message = await lounge.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                                 nonce=int(record['nonce'][:16], 16))
                except discord.HTTPException as error:
                    if 400 <= error.status < 500 and error.status != 429:
                        await self.system.call('put', PANEL_RECEIPT, dict(record, attempted=False))
                    raise
            await self.system.call('put', 'panel:booster_club', message.id)
            await self.system.call('put', PANEL_RECEIPT, dict(record, attempted=True, complete=True, message=message.id))
        await self.system.track('BOOSTER_PANEL', 'Publicar beneficios privados del Club Booster',
                                publish, VERSION + ':panel', snapshot=snapshot)

    async def ready(self):
        async with self.lock:
            if self.system.store.get(RELEASE_KEY) == VERSION:
                return
            async with self.system.roles_lock:
                role_status = await self.style_role()
            category = await self.ensure_channel('category')
            await self.ensure_channel('lounge', category)
            await self.ensure_channel('terrace', category)
            await self.ensure_panel()
            await self.system.call('put', RELEASE_KEY, VERSION)
            log.info('VICE_BOOSTER_CLUB_READY guild=%s role_status=%s lounge=%s terrace=%s',
                     GUILD_ID, role_status, self.system.store.get('channel:booster_lounge'),
                     self.system.store.get('channel:booster_terrace'))
