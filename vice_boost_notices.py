"""A dedicated native boost channel and verified copies of its old notices.

Only the four Discord boost message types in the exact old welcome channel may
be removed, after a complete durable source record and a verified replacement.
The native system-message flags and the bot's own welcome destination are never
edited. A lost creation/publication response is recovered, never blindly retried.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import uuid

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID, PINK
from vice_readonly import WRITE_FLAGS
from vice_booster_club import benefits_copy
from vice_channel_style import stylize, format_name

log = logging.getLogger('ViceDistrict.boost_notices')
VERSION = 'vice-boost-notices-v1'
SOURCE_CHANNEL_ID = 1572462547058032804
BOOST_TYPES = frozenset({8, 9, 10, 11})
DESTINATION_KEY = 'boost_notices:destination'
MIGRATION_KEY = 'boost_notices:history:' + VERSION
ROUTE_KEY = 'boost_notices:route:' + VERSION
PANEL_KEY = 'boost_notices:panel:' + VERSION
NAME = '├・💎│mejoras-del-servidor'
TOPIC = 'Mejoras y niveles de VIce District. Gracias al corillo que impulsa el servidor. Solo lectura.'
REASON = 'Notificaciones de mejoras en su propio canal, solicitadas por el propietario'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def channel_state(channel):
    return dict(id=str(channel.id), guild=str(channel.guild.id), name=channel.name,
                category=str(channel.category_id), topic=channel.topic,
                position=channel.position, overwrites=[dict(id=str(target.id),
                allow=str(overwrite.pair()[0].value), deny=str(overwrite.pair()[1].value))
                for target, overwrite in channel.overwrites.items()])


def embed_projection(embed):
    """Discord enriches image URLs; compare every field we actually published."""
    data = embed.to_dict() if hasattr(embed, 'to_dict') else embed
    return dict(title=data.get('title'), description=data.get('description'),
                timestamp=data.get('timestamp'), color=data.get('color'),
                author={k: data.get('author', {}).get(k) for k in ('name', 'icon_url')},
                footer=data.get('footer', {}).get('text'),
                fields=data.get('fields', []))


class BoostNotices:
    def __init__(self, system):
        self.system = system
        self.lock = asyncio.Lock()

    async def context(self):
        if getattr(self.system.bot.user, 'id', None) != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        guild = await self.system.bot.fetch_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
            raise ValueError('No coincide el servidor o su propietario.')
        if int(self.system.channel_id('welcome') or 0) != SOURCE_CHANNEL_ID:
            raise ValueError('El canal de bienvenida registrado cambió; no se moverá su historial.')
        roles = {role.id: role for role in await guild.fetch_roles()}
        member = await guild.fetch_member(BOT_ID)
        if member.id != BOT_ID or member.guild.id != GUILD_ID or GUILD_ID not in roles:
            raise ValueError('No se confirmó el miembro del bot.')
        role_ids = set(member._roles) | {GUILD_ID}
        bits = 0
        for rid in role_ids:
            if rid in roles:
                bits |= roles[rid].permissions.value
        permissions = discord.Permissions(bits)
        if not (permissions.administrator or all(getattr(permissions, flag) for flag in
                ('manage_guild', 'manage_channels', 'manage_roles', 'view_audit_log'))):
            raise ValueError('Faltan permisos para configurar el canal de mejoras.')
        return dict(guild=guild, roles=roles, member=member, role_ids=role_ids,
                    permissions=permissions)

    @staticmethod
    def permissions(context, channel):
        base = discord.Permissions(context['permissions'].value)
        if base.administrator:
            return discord.Permissions.all()
        rules = {target.id: overwrite.pair() for target, overwrite in channel.overwrites.items()}
        allow, deny = rules.get(GUILD_ID, (discord.Permissions.none(), discord.Permissions.none()))
        base.handle_overwrite(allow.value, deny.value)
        allows = denies = 0
        for rid in context['role_ids'] - {GUILD_ID}:
            allow, deny = rules.get(rid, (discord.Permissions.none(), discord.Permissions.none()))
            allows |= allow.value
            denies |= deny.value
        base.handle_overwrite(allows, denies)
        allow, deny = rules.get(BOT_ID, (discord.Permissions.none(), discord.Permissions.none()))
        base.handle_overwrite(allow.value, deny.value)
        return base

    def require_permissions(self, context, channel, *flags):
        permissions = self.permissions(context, channel)
        if not permissions.view_channel or any(not getattr(permissions, flag) for flag in flags):
            raise ValueError('Faltan permisos en el canal; se conserva el mensaje original.')

    def overwrites(self, context):
        readonly = dict(view_channel=True, read_message_history=True)
        readonly.update({flag: False for flag in WRITE_FLAGS})
        return {context['roles'][GUILD_ID]: discord.PermissionOverwrite(**readonly),
                context['member']: discord.PermissionOverwrite(view_channel=True,
                    read_message_history=True, send_messages=True, embed_links=True,
                    attach_files=True, manage_messages=True)}

    def validate_destination(self, channel, record):
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID
                or record.get('guild') != GUILD_ID or channel.id != int(record.get('channel') or 0)
                or channel.id == SOURCE_CHANNEL_ID
                or channel.category_id != int(self.system.store.get('category:community') or 0)
                or channel.name not in {NAME, stylize(NAME), stylize(NAME.removeprefix('├・')),
                                       stylize(NAME).replace('│', '╎'), format_name(NAME)}
                or channel.topic != TOPIC):
            raise ValueError('El canal de mejoras registrado necesita revisión.')
        rules = {target.id: overwrite for target, overwrite in channel.overwrites.items()}
        if set(rules) != {GUILD_ID, BOT_ID}:
            raise ValueError('Cambió la política de publicación del canal de mejoras.')
        if (rules[GUILD_ID].view_channel is not True or rules[GUILD_ID].read_message_history is not True
                or any(getattr(rules[GUILD_ID], flag) is not False for flag in WRITE_FLAGS)
                or any(getattr(rules[BOT_ID], flag) is not True for flag in
                       ('view_channel', 'read_message_history', 'send_messages', 'embed_links', 'manage_messages'))):
            raise ValueError('El canal de mejoras no tiene los permisos de solo lectura previstos.')
        return channel

    async def source_channel(self, context):
        source = await context['guild'].fetch_channel(SOURCE_CHANNEL_ID)
        if not isinstance(source, discord.TextChannel) or source.guild.id != GUILD_ID or source.id != SOURCE_CHANNEL_ID:
            raise ValueError('No se confirmó el canal de bienvenida autorizado.')
        self.require_permissions(context, source, 'read_message_history', 'manage_messages')
        return source

    async def destination(self, context=None):
        context = context or await self.context()
        record = await self.system.call('get', DESTINATION_KEY) or {}
        if not record.get('channel'):
            raise ValueError('El canal de mejoras no está registrado.')
        channel = await context['guild'].fetch_channel(int(record['channel']))
        self.validate_destination(channel, record)
        self.require_permissions(context, channel, 'read_message_history', 'send_messages', 'embed_links')
        return channel

    async def ensure_destination(self):
        context = await self.context()
        guild = context['guild']
        await self.source_channel(context)
        record = await self.system.call('get', DESTINATION_KEY) or {}
        if record.get('channel'):
            destination = await self.destination(context)
            await self.system.call('put', 'channel:boost_notices', destination.id)
            return destination
        category_id = int(self.system.store.get('category:community') or 0)
        if not category_id:
            raise ValueError('No está registrada la categoría del corillo.')
        category = await guild.fetch_channel(category_id)
        if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
            raise ValueError('No se confirmó la categoría del corillo.')
        if not record:
            record = dict(guild=GUILD_ID, nonce=uuid.uuid4().hex,
                          started_at=datetime.now(timezone.utc).isoformat(), attempted=False)
            await self.system.call('put', DESTINATION_KEY, record)
        if record.get('guild') != GUILD_ID or not record.get('nonce'):
            raise ValueError('El registro del canal de mejoras es inválido.')
        reason = REASON + ' • ' + record['nonce']
        if record.get('attempted'):
            found = []
            after = datetime.fromisoformat(record['started_at']) - timedelta(seconds=5)
            async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.channel_create, after=after):
                if getattr(entry.user, 'id', None) == BOT_ID and entry.reason == reason:
                    candidate = await guild.fetch_channel(entry.target.id)
                    self.validate_destination(candidate, dict(record, channel=candidate.id))
                    found.append(candidate)
            if len(found) != 1:
                raise ValueError('La creación previa no se confirmó de forma única; no se duplicará el canal.')
            destination = found[0]
        else:
            async def snapshot():
                current = await self.context()
                return dict(guild=GUILD_ID, owner=OWNER_ID, bot=BOT_ID,
                    record=await self.system.call('get', DESTINATION_KEY),
                    channels=[dict(id=str(c.id), name=c.name, parent=str(c.category_id))
                              for c in await current['guild'].fetch_channels()])

            async def create():
                fresh = await self.context()
                current_category = await fresh['guild'].fetch_channel(category_id)
                if not isinstance(current_category, discord.CategoryChannel) or current_category.guild.id != GUILD_ID:
                    raise ValueError('La categoría cambió antes de crear el canal.')
                rules = self.overwrites(fresh)
                existing = await fresh['guild'].fetch_channels()
                last = next((channel for channel in existing
                             if channel.id == self.system.channel_id('suggestions')
                             and channel.category_id == category_id), None)
                position = dict(position=last.position) if last else {}
                record['attempted'] = True
                await self.system.call('put', DESTINATION_KEY, record)
                try:
                    return await fresh['guild'].create_text_channel(format_name(NAME), category=current_category,
                        topic=TOPIC, overwrites=rules, reason=reason, **position)
                except discord.HTTPException as error:
                    if 400 <= error.status < 500 and error.status != 429:
                        record['attempted'] = False
                        await self.system.call('put', DESTINATION_KEY, record)
                    raise
            destination = await self.system.track('BOOST_CHANNEL', 'Crear canal de mejoras de solo lectura',
                create, VERSION, snapshot=snapshot)
        self.validate_destination(destination, dict(record, channel=destination.id))
        record['channel'] = destination.id
        await self.system.call('put', DESTINATION_KEY, record)
        await self.system.call('put', 'channel:boost_notices', destination.id)
        log.info('VICE_BOOST_CHANNEL_READY guild=%s channel=%s', GUILD_ID, destination.id)
        return destination

    async def route_system_channel(self, destination):
        async def snapshot():
            context = await self.context()
            guild = context['guild']
            return dict(guild=GUILD_ID, owner=OWNER_ID, system_channel=guild._system_channel_id,
                        system_flags=guild.system_channel_flags.value,
                        bot_welcome_channel=self.system.channel_id('welcome'),
                        route=await self.system.call('get', ROUTE_KEY))
        state = await snapshot()
        record = state['route']
        if record and record.get('complete'):
            if state['system_channel'] != destination.id:
                raise ValueError('El propietario cambió el canal del sistema; no se sobrescribirá.')
            return
        if state['system_channel'] not in {SOURCE_CHANNEL_ID, destination.id}:
            raise ValueError('El canal del sistema no coincide con el traslado autorizado.')
        if not record:
            record = dict(before=state, destination=destination.id, complete=False)
            await self.system.call('put', ROUTE_KEY, record)
        if record.get('destination') != destination.id:
            raise ValueError('El destino del sistema cambió durante el traslado.')

        async def route():
            context = await self.context()
            guild = context['guild']
            current = await self.destination(context)
            if guild._system_channel_id not in {SOURCE_CHANNEL_ID, current.id}:
                raise ValueError('El canal del sistema cambió; se requiere revisión.')
            flags = guild.system_channel_flags.value
            if guild._system_channel_id != current.id:
                # Omitting this separate API field preserves all native flags.
                await guild.edit(system_channel=current, reason=REASON)
            verified = (await self.context())['guild']
            if verified._system_channel_id != current.id or verified.system_channel_flags.value != flags:
                raise ValueError('No se confirmó el destino conservando las opciones del sistema.')
            record.update(complete=True, system_flags=flags)
            await self.system.call('put', ROUTE_KEY, record)
        await self.system.track('BOOST_ROUTE', 'Dirigir las notificaciones nativas al canal de mejoras',
                                route, VERSION, snapshot=snapshot)

    @staticmethod
    def source_key(message_id):
        return 'boost_notices:source:' + str(message_id)

    @staticmethod
    def receipt_key(message_id):
        return 'boost_notices:receipt:' + str(message_id)

    @staticmethod
    def validate_raw(raw, message_id):
        if (str(raw.get('id')) != str(message_id) or str(raw.get('channel_id')) != str(SOURCE_CHANNEL_ID)
                or int(raw.get('type', -1)) not in BOOST_TYPES
                or raw.get('guild_id') not in (None, str(GUILD_ID), GUILD_ID)
                or raw.get('webhook_id') or not raw.get('author', {}).get('id')
                or not raw.get('timestamp')):
            raise ValueError('El mensaje no es una notificación nativa de mejoras autorizada.')
        # Native boosts do not need media; an unexpected payload is retained for review.
        if raw.get('attachments') or raw.get('embeds') or raw.get('components'):
            raise ValueError('La notificación contiene material adicional; no se eliminará.')
        count = str(raw.get('content') or '').strip()
        if count and (not count.isdecimal() or len(count) > 8 or int(count) <= 0):
            raise ValueError('El contenido de la notificación requiere revisión; se conserva el original.')
        return raw

    async def raw_source(self, message_id):
        raw = await self.system.bot.http.get_message(SOURCE_CHANNEL_ID, int(message_id))
        return self.validate_raw(raw, message_id)

    async def freeze_history(self, source):
        manifest = await self.system.call('get', MIGRATION_KEY)
        if manifest:
            if manifest.get('guild') != GUILD_ID or manifest.get('source') != SOURCE_CHANNEL_ID:
                raise ValueError('El historial no pertenece al canal autorizado.')
            return manifest
        context = await self.context()
        fresh = await self.source_channel(context)
        if source.id != fresh.id:
            raise ValueError('El origen del historial no coincide.')
        ids = [str(message.id) async for message in fresh.history(limit=None, oldest_first=True)
               if message.type.value in BOOST_TYPES]
        manifest = dict(guild=GUILD_ID, source=SOURCE_CHANNEL_ID, messages=ids,
                        frozen_at=datetime.now(timezone.utc).isoformat(), complete=False)
        await self.system.call('put', MIGRATION_KEY, manifest)
        return manifest

    @staticmethod
    def historical_embed(raw):
        author = raw['author']
        name = author.get('global_name') or author.get('username') or author['id']
        display = discord.utils.escape_markdown(name)
        level = int(raw['type']) - 8
        description = f'**{display}** impulsó el servidor. 💎'
        count = str(raw.get('content') or '').strip()
        if count.isdecimal() and int(count) > 0:
            description += f' **{int(count)} mejora' + ('s**' if int(count) != 1 else '**') + '.'
        if level:
            description += f'\nEl servidor alcanzó el **nivel {level}** en ese momento.'
        timestamp = datetime.fromisoformat(raw['timestamp'].replace('Z', '+00:00'))
        embed = discord.Embed(title='💎 Historial de mejoras', description=description,
                              color=PINK, timestamp=timestamp)
        avatar = author.get('avatar')
        if avatar:
            embed.set_author(name=name[:256], icon_url=f'https://cdn.discordapp.com/avatars/{author["id"]}/{avatar}.png')
        else:
            embed.set_author(name=name[:256])
        embed.add_field(name='Fecha original', value=f'<t:{int(timestamp.timestamp())}:F>', inline=False)
        embed.set_footer(text=f'VIce District • Historial • boost:{raw["id"]}')
        return embed

    def verify_copy(self, message, destination, embed):
        if (message.author.id != BOT_ID or message.channel.id != destination.id
                or message.guild.id != GUILD_ID or message.content or len(message.embeds) != 1
                or getattr(message, 'attachments', []) or getattr(message, 'components', [])
                or embed_projection(message.embeds[0]) != embed_projection(embed)):
            raise ValueError('La copia no coincide íntegramente; se conserva la notificación original.')
        return message

    async def recover_copy(self, destination, receipt, embed):
        marker = embed.footer.text
        after = datetime.fromisoformat(receipt['started_at']) - timedelta(seconds=5)
        found = []
        async for message in destination.history(limit=None, after=after, oldest_first=True):
            if (message.author.id == BOT_ID and any(e.footer.text == marker for e in message.embeds)):
                found.append(self.verify_copy(message, destination, embed))
        if len(found) != 1:
            raise ValueError('No se confirmó una única copia previa; se conserva el original.')
        return found[0]

    async def benefits_panel(self, destination):
        lounge_id = int(self.system.channel_id('booster_lounge') or 0)
        terrace_id = int(self.system.channel_id('booster_terrace') or 0)
        category_id = int(self.system.store.get('category:booster_club') or 0)
        if not all((lounge_id, terrace_id, category_id)):
            return False
        context = await self.context()
        for cid, expected_type in ((lounge_id, discord.TextChannel), (terrace_id, discord.VoiceChannel)):
            channel = await context['guild'].fetch_channel(cid)
            if (not isinstance(channel, expected_type) or channel.guild.id != GUILD_ID
                    or channel.category_id != category_id
                    or channel.overwrites_for(context['roles'][GUILD_ID]).view_channel is not False):
                raise ValueError('No se confirmaron los espacios privados antes de anunciar sus beneficios.')
        record = await self.system.call('get', PANEL_KEY)
        if not record:
            body = ('Gracias al corillo que impulsa **VIce District**. Aquí aparecen las mejoras '
                    'y los niveles que alcanza nuestro servidor.\n\n'
                    + benefits_copy(lounge_id, terrace_id,
                        high_quality=int(self.system.store.get('channel:booster_terrace_bitrate') or 0) >= 256000))
            embed = discord.Embed(title='💎 EL CORILLO QUE NOS IMPULSA', description=body, color=PINK)
            embed.set_footer(text='VIce District • panel:boost_notices')
            record = dict(destination=destination.id, embed=embed.to_dict(), attempted=False,
                          started_at=datetime.now(timezone.utc).isoformat())
            await self.system.call('put', PANEL_KEY, record)
        if record.get('destination') != destination.id:
            raise ValueError('El panel de mejoras tiene otro destino registrado.')
        embed = discord.Embed.from_dict(record['embed'])
        if record.get('message'):
            message = await destination.fetch_message(int(record['message']))
        elif record.get('attempted'):
            message = await self.recover_copy(destination, record, embed)
        else:
            async def snapshot():
                return dict(guild=GUILD_ID, destination=channel_state(await self.destination()),
                            panel=await self.system.call('get', PANEL_KEY))

            async def publish():
                target = await self.destination()
                record['attempted'] = True
                await self.system.call('put', PANEL_KEY, record)
                try:
                    return await target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                             nonce='vice-boost-info-v1', silent=True)
                except discord.HTTPException as error:
                    if 400 <= error.status < 500 and error.status != 429:
                        record['attempted'] = False
                        await self.system.call('put', PANEL_KEY, record)
                    raise
            message = await self.system.track('BOOST_PANEL', 'Explicar los beneficios del Club Booster',
                publish, VERSION, snapshot=snapshot)
        message = await destination.fetch_message(message.id)
        self.verify_copy(message, destination, embed)
        record.update(message=str(message.id), complete=True)
        await self.system.call('put', PANEL_KEY, record)
        return True

    async def migrate_message(self, source_id, destination):
        manifest = await self.system.call('get', MIGRATION_KEY) or {}
        if (manifest.get('guild') != GUILD_ID or manifest.get('source') != SOURCE_CHANNEL_ID
                or str(source_id) not in manifest.get('messages', [])):
            raise ValueError('El mensaje no está en el historial autorizado y congelado.')
        context = await self.context()
        source = await self.source_channel(context)
        current_destination = await self.destination(context)
        if destination.id != current_destination.id:
            raise ValueError('El destino cambió durante la copia.')
        receipt = await self.system.call('get', self.receipt_key(source_id)) or {}
        if receipt.get('deleted'):
            return 'completed'
        saved = await self.system.call('get', self.source_key(source_id))
        if not saved:
            try:
                raw = await self.raw_source(source_id)
            except discord.NotFound:
                return 'absent'
            saved = dict(guild=GUILD_ID, source=SOURCE_CHANNEL_ID, raw=raw, sha256=digest(raw))
            await self.system.call('put', self.source_key(source_id), saved)
        if (saved.get('guild') != GUILD_ID or saved.get('source') != SOURCE_CHANNEL_ID
                or digest(saved['raw']) != saved.get('sha256')):
            raise ValueError('La copia duradera de origen no es válida.')
        raw = self.validate_raw(saved['raw'], source_id)
        embed = self.historical_embed(raw)
        if receipt and (receipt.get('destination') != destination.id or receipt.get('source_sha256') != saved['sha256']):
            raise ValueError('El comprobante no corresponde a la fuente y destino autorizados.')
        if not receipt:
            receipt = dict(destination=destination.id, source_sha256=saved['sha256'],
                started_at=datetime.now(timezone.utc).isoformat(), attempted=False, deleted=False)
            await self.system.call('put', self.receipt_key(source_id), receipt)

        async def snapshot():
            return dict(guild=GUILD_ID, source=SOURCE_CHANNEL_ID, message=str(source_id),
                source_record=await self.system.call('get', self.source_key(source_id)),
                receipt=await self.system.call('get', self.receipt_key(source_id)))

        if receipt.get('message'):
            copy = await destination.fetch_message(int(receipt['message']))
            self.verify_copy(copy, destination, embed)
        elif receipt.get('attempted'):
            copy = await self.recover_copy(destination, receipt, embed)
        else:
            async def publish():
                fresh = await self.context()
                target = await self.destination(fresh)
                await self.source_channel(fresh)
                live_raw = await self.raw_source(source_id)
                if self.identity(live_raw) != self.identity(raw):
                    raise ValueError('La notificación cambió; se conserva el original.')
                receipt['attempted'] = True
                await self.system.call('put', self.receipt_key(source_id), receipt)
                try:
                    return await target.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                             nonce='boost:' + str(source_id), silent=True)
                except discord.HTTPException as error:
                    if 400 <= error.status < 500 and error.status != 429:
                        receipt['attempted'] = False
                        await self.system.call('put', self.receipt_key(source_id), receipt)
                    raise
            copy = await self.system.track('BOOST_HISTORY_COPY', 'Copiar una mejora histórica con su fecha original',
                publish, f'{VERSION}:{source_id}', snapshot=snapshot)
        # Fetch, rather than trusting the send response, before durable verification.
        copy = await destination.fetch_message(copy.id)
        self.verify_copy(copy, destination, embed)
        receipt.update(message=str(copy.id), verified=True, embed_sha256=digest(embed_projection(embed)))
        await self.system.call('put', self.receipt_key(source_id), receipt)

        async def delete_snapshot():
            state = await snapshot()
            try:
                state['current_source'] = await self.raw_source(source_id)
            except discord.NotFound:
                state['current_source'] = None
            return state

        async def remove_source():
            fresh = await self.context()
            current_source = await self.source_channel(fresh)
            target = await self.destination(fresh)
            confirmed = await target.fetch_message(int(receipt['message']))
            self.verify_copy(confirmed, target, embed)
            persisted = await self.system.call('get', self.receipt_key(source_id))
            if persisted != receipt or not persisted.get('verified'):
                raise ValueError('No se conservó el comprobante de copia; no se elimina el original.')
            try:
                current_raw = await self.raw_source(source_id)
                if self.identity(current_raw) != self.identity(raw):
                    raise ValueError('La fuente cambió; no se eliminará.')
                # Retain the final complete payload too (including any later reactions).
                saved['before_delete_raw'] = current_raw
                await self.system.call('put', self.source_key(source_id), saved)
                message = await current_source.fetch_message(int(source_id))
                if message.type.value not in BOOST_TYPES or message.channel.id != SOURCE_CHANNEL_ID:
                    raise ValueError('El mensaje dejó de coincidir con el alcance autorizado.')
                await self.system.bot.http.delete_message(SOURCE_CHANNEL_ID, int(source_id), reason=REASON)
            except discord.NotFound:
                pass
            receipt['deleted'] = True
            await self.system.call('put', self.receipt_key(source_id), receipt)
        await self.system.track('BOOST_HISTORY_REMOVE', 'Retirar la mejora original después de verificar su copia',
            remove_source, f'{VERSION}:{source_id}', snapshot=delete_snapshot)
        return 'moved'

    @staticmethod
    def identity(raw):
        return {key: raw.get(key) for key in ('id', 'channel_id', 'type', 'author', 'content',
                                             'timestamp', 'attachments', 'embeds', 'components')}

    async def ready(self):
        async with self.lock:
            destination = await self.ensure_destination()
            await self.route_system_channel(destination)
            await self.benefits_panel(destination)
            context = await self.context()
            source = await self.source_channel(context)
            manifest = await self.freeze_history(source)
            summary = dict(total=len(manifest['messages']), moved=0, completed=0, absent=0, failed=0)
            if not manifest.get('complete'):
                for source_id in manifest['messages']:
                    try:
                        result = await self.migrate_message(source_id, destination)
                        summary[result] += 1
                    except Exception:
                        summary['failed'] += 1
                        log.exception('VICE_BOOST_HISTORY_FAILED message=%s', source_id)
                manifest.update(complete=summary['failed'] == 0, summary=summary)
                await self.system.call('put', MIGRATION_KEY, manifest)
            else:
                summary = manifest.get('summary', summary)
            log.info('VICE_BOOST_NOTICES_READY guild=%s channel=%s total=%s moved=%s completed=%s absent=%s failed=%s',
                     GUILD_ID, destination.id, *[summary[k] for k in ('total', 'moved', 'completed', 'absent', 'failed')])
            return summary
