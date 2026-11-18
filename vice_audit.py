"""Durable audit history and live activity for the district's private staff log."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re

import discord

from vice_design import GUILD_ID, BOT_ID, OWNER_ID, CYAN
from vice_audit_store import AuditStore
from vice_audit_format import format_audit_entry, compact_stored_embed

log = logging.getLogger('ViceDistrict.audit')
AUDIT_VERSION = 'vice-audit-compact-v2'
FORMAT_VERSION = 'vice-audit-compact-details-v3'
POLL_SECONDS = 60
TOPIC = 'Auditoría y actividad del distrito: miembros, voz y cambios administrativos. Registro privado del equipo.'


def utcnow():
    return datetime.now(timezone.utc)


def marker(key):
    return 'ref:' + hashlib.sha256(key.encode()).hexdigest()[:20]


def stamp_embed(embed, key, channel_id):
    copy = discord.Embed.from_dict(embed.to_dict())
    # URL metadata is retained by Discord without adding a visible footer row.
    copy.url = f'https://discord.com/channels/{GUILD_ID}/{channel_id}?ref={marker(key)[4:]}'
    return copy


def embed_marker(embed):
    found = re.fullmatch(r'https://discord\.com/channels/' + str(GUILD_ID)
                        + r'/\d+\?ref=([a-f0-9]{20})', str(embed.url or ''))
    if found:
        return 'ref:' + found.group(1)
    found = re.search(r'(ref:[a-f0-9]{20})$', str(embed.footer.text or ''))
    return found.group(1) if found else None


def semantic_embeds(embeds):
    """Ignore Discord's CDN proxy metadata when comparing delivered payloads."""
    result = []
    for embed in embeds:
        data = embed.to_dict()
        clean = {key: data[key] for key in ('title', 'description', 'url', 'color', 'timestamp')
                 if key in data}
        for part, keys in (('author', ('name', 'url', 'icon_url')),
                           ('footer', ('text', 'icon_url')),
                           ('image', ('url',)), ('thumbnail', ('url',))):
            if part in data:
                clean[part] = {key: data[part][key] for key in keys if key in data[part]}
        if data.get('fields'):
            clean['fields'] = [dict(name=field['name'], value=field['value'],
                                    inline=bool(field.get('inline', False)))
                               for field in data['fields']]
        result.append(clean)
    return result


def fit_batch(embeds, limit=5900):
    """Keep a merged historical batch sendable without losing its identity.

    Stored payloads remain complete. Only the rendered batch is abbreviated when
    later audit merging makes previously grouped records exceed Discord's limit.
    """
    result = [discord.Embed.from_dict(deepcopy(embed.to_dict())) for embed in embeds]
    if sum(len(embed) for embed in result) <= limit:
        return result
    essential = {'IDs', 'Responsable', 'Objeto afectado', 'Autor de los mensajes',
                 'Canal', 'Canal de destino', 'Cantidad acumulada', 'Permiso aplicado a'}
    note = 'Detalles abreviados para ajustar el lote; el registro completo se conserva.'
    for embed in result:
        embed.description = note
        for index, field in enumerate(embed.fields):
            if field.name not in essential and len(field.value) > 120:
                embed.set_field_at(index, name=field.name, value=field.value[:119] + '…',
                                   inline=field.inline)
    while sum(len(embed) for embed in result) > limit:
        candidates = [(len(field.name) + len(field.value), embed, index)
                      for embed in result for index, field in enumerate(embed.fields)
                      if field.name not in essential]
        if not candidates:
            break
        _, embed, index = max(candidates, key=lambda item: item[0])
        embed.remove_field(index)
    if sum(len(embed) for embed in result) > limit:
        # Very long display names are decoration. Preserve any snowflake mentions
        # and numeric IDs in identity fields while removing their verbose labels.
        for embed in result:
            author = embed.author
            if author.name and len(author.name) > 80:
                embed.set_author(name=author.name[:79] + '…',
                                 icon_url=author.icon_url, url=author.url)
            for index, field in enumerate(embed.fields):
                if field.name != 'IDs' and len(field.value) > 100:
                    ids = re.findall(r'<[@#][!&]?\d+>|`\d+`', field.value)
                    value = ' · '.join(dict.fromkeys(ids)) or field.value[:99] + '…'
                    embed.set_field_at(index, name=field.name, value=value, inline=field.inline)
    if sum(len(embed) for embed in result) > limit:
        raise ValueError('La identidad del lote excede el límite de Discord.')
    return result


class ViceAudit:
    def __init__(self, system):
        self.system = system
        self.store = AuditStore(system.path)
        self.task = None
        self.wakeup = asyncio.Event()
        self.flush_lock = asyncio.Lock()

    async def db(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, method), *args, **kwargs)

    async def start(self):
        await self.db('initialize')
        if not await self.db('state', 'started_at'):
            await self.db('set_state', 'started_at', utcnow().isoformat())

    def guild(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID:
            raise ValueError('El registro requiere el bot autorizado del distrito.')
        return guild

    def destination(self):
        guild = self.guild()
        channel = self.system.channel(guild, 'log')
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID
                or channel.id != self.system.channel_id('log')):
            raise ValueError('Falta el canal de registro del distrito.')
        if channel.overwrites_for(guild.default_role).view_channel is not False:
            raise ValueError('El registro debe permanecer privado para el equipo.')
        allowed = {OWNER_ID, BOT_ID}
        allowed.update(self.system.store.get('role:' + key)
                       for key in ('founder', 'admin', 'mod', 'support'))
        for target, overwrite in channel.overwrites.items():
            if overwrite.view_channel is True and target.id not in allowed:
                raise ValueError('El registro tiene acceso de una persona o rol ajeno al equipo.')
        if getattr(guild.me, 'id', None) != BOT_ID:
            raise ValueError('El bot autorizado debe ser miembro del distrito.')
        permissions = channel.permissions_for(guild.me)
        if not all(getattr(permissions, name) for name in
                   ('view_channel', 'send_messages', 'embed_links', 'read_message_history')):
            raise ValueError('El bot necesita leer y publicar inserciones en registro-staff.')
        return channel

    async def publish(self, key, embed, *, event_type, event_time, source_id=None,
                      historical=False, cursor=None):
        self.guild()
        # Each persisted payload carries an exact recovery marker; it is never a ping.
        copy = stamp_embed(embed, key, self.system.channel_id('log'))
        if len(copy) > 5900 or len(copy.fields) > 25:
            raise ValueError('El registro excede el límite de Discord.')
        await self.db('enqueue', key, copy.to_dict(), event_type,
                      event_time.isoformat(), source_id=source_id,
                      historical=historical, cursor=cursor)
        self.wakeup.set()

    async def ingest(self, entry, *, historical=False, cursor=None):
        if getattr(getattr(entry, 'guild', None), 'id', None) != GUILD_ID:
            return
        self.system.validate_guild(entry.guild)
        key = 'audit:' + str(entry.id)
        old = await self.db('get', key)
        if old:
            historical = bool(old['historical'])
        embed = format_audit_entry(entry, historical=historical)
        await self.publish(key, embed, event_type='audit', event_time=entry.created_at,
                           source_id=str(entry.id), historical=historical, cursor=cursor)

    async def entry_create(self, entry):
        # Gateway entries do not move the polling cursor: older events may still be missing.
        await self.ingest(entry)

    async def scan(self, *, full=False):
        guild = self.guild()
        if not guild.me.guild_permissions.view_audit_log:
            raise ValueError('El bot necesita Ver registro de auditoría.')
        cursor = int(await self.db('state', 'cursor', '0'))
        after = 0 if full else max(0, cursor - (60 * 60 * 1000 << 22))
        started = datetime.fromisoformat(await self.db('state', 'started_at'))
        count = 0
        # Explicit after=0 + oldest_first pages all available history, not just 100 entries.
        async for entry in guild.audit_logs(limit=None, after=discord.Object(id=after), oldest_first=True):
            await self.ingest(entry, historical=entry.created_at < started, cursor=str(entry.id))
            count += 1
        await self.db('set_state', 'last_scan', utcnow().isoformat())
        if full:
            await self.db('set_state', 'last_full_scan', utcnow().isoformat())
            await self.db('set_state', 'format_version', FORMAT_VERSION)
            log.info('VICE_AUDIT_FORMAT_REFRESH version=%s entries=%s', FORMAT_VERSION, count)
        return count

    async def install_panel(self, *, finished=False):
        guild, channel = self.guild(), self.destination()
        stats = await self.db('stats')
        body = ('🟢 Entradas · 🟠 Cambios · 🔴 Salidas\n'
                'Auditoría, miembros y voz en tarjetas breves.\n'
                '🕒 Puerto Rico · AST (UTC−4)\n'
                '🔒 Motivos de expulsión y baneo: solo en despedidas.')
        version = AUDIT_VERSION + (':complete' if finished else ':install')
        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, topic=channel.topic,
                        panel=self.system.store.get('panel:log'), status=stats)
        async def apply():
            if channel.topic != TOPIC:
                await channel.edit(topic=TOPIC, reason='Activar auditoría privada solicitada por el propietario')
            await self.system.panel(guild, 'log', ('📋 AUDITORÍA Y ACTIVIDAD DEL DISTRITO', body, CYAN), None)
            await self.db('set_state', 'panel_release', version)
        await self.system.track('AUDIT_PANEL', 'Configurar registro privado de auditoría', apply,
                                version, snapshot=snapshot)

    async def ready(self):
        self.destination()
        if self.task and not self.task.done():
            return
        if not await self.db('state', 'panel_release'):
            await self.install_panel()
        self.task = asyncio.create_task(self.run(), name='vice-audit-history-and-activity')
        log.info('VICE_AUDIT_READY guild=%s channel=%s', GUILD_ID, self.system.channel_id('log'))

    @staticmethod
    def embeds(rows):
        return [discord.Embed.from_dict(json.loads(row['payload_json'])) for row in rows]

    async def recover(self, channel, rows):
        earliest = min(row['attempted_at'] for row in rows)
        since = datetime.fromisoformat(earliest) - timedelta(seconds=10)
        wanted = {marker(row['key']) for row in rows}
        async for message in channel.history(limit=None, after=since, oldest_first=True):
            if message.author.id != BOT_ID:
                continue
            found = {embed_marker(e) for e in message.embeds}
            if wanted == found and len(message.embeds) == len(wanted):
                return message
        return None

    async def replace_long_records(self):
        """Owner-requested replacement of exact persisted bot cards; restart safe."""
        async with self.flush_lock:
            channel = self.destination()
            manifest = await self.db('prepare_replacement', AUDIT_VERSION)
            if manifest['stage'] in ('queue_ready', 'complete'):
                return
            panel_key = 'replacement_panel:' + AUDIT_VERSION
            panel = await self.db('state', panel_key)
            if panel is None:
                panel = {'message_id': self.system.store.get('panel:log'), 'deleted': False}
                await self.db('set_state', panel_key, panel)
            originals = manifest['originals']
            payloads = {row['key']: stamp_embed(
                compact_stored_embed(json.loads(row['payload_json']), event_type=row['event_type']),
                row['key'], channel.id).to_dict() for row in originals}
            if manifest['stage'] == 'prepared':
                # Refresh available audit entries from their source after preserving
                # the complete old cards. Concurrent new events remain independent.
                await self.scan(full=True)
                batches = {row['batch_key'] for row in originals
                           if row['batch_key'] and not row['message_id']}
                for batch in batches:
                    rows = [row for row in originals if row['batch_key'] == batch]
                    message = await self.recover(channel, rows)
                    if message:
                        manifest = await self.db('register_replacement_message', AUDIT_VERSION,
                                                 str(message.id), [r['key'] for r in rows])
                for message_id in manifest['message_ids']:
                    if message_id in manifest['deleted_message_ids']:
                        continue
                    self.destination()
                    keys = {row['key'] for row in originals if row['message_id'] == message_id}
                    keys.update(manifest.get('recovered_messages', {}).get(message_id, []))
                    try:
                        message = await channel.fetch_message(int(message_id))
                    except discord.NotFound:
                        await self.db('mark_replacement_deleted', AUDIT_VERSION, message_id)
                        continue
                    expected = {marker(key) for key in keys}
                    if (message.author.id != BOT_ID or not expected or
                            {embed_marker(e) for e in message.embeds} != expected or
                            len(message.embeds) != len(expected) or message.content
                            or message.attachments or message.components):
                        raise ValueError('El mensaje antiguo no coincide con el registro congelado.')
                    await self.delete_registered_card(channel, message, keys)
                    await self.db('mark_replacement_deleted', AUDIT_VERSION, message_id)
                if panel['message_id'] and not panel['deleted']:
                    try:
                        message = await channel.fetch_message(int(panel['message_id']))
                    except discord.NotFound:
                        pass
                    else:
                        if (message.author.id != BOT_ID or len(message.embeds) != 1
                                or message.embeds[0].footer.text != 'VIce District • panel:log'
                                or message.content or message.attachments or message.components):
                            raise ValueError('El panel anterior no pertenece al registro autorizado.')
                        await self.delete_registered_card(channel, message, {'panel:log'})
                    panel['deleted'] = True
                    await self.db('set_state', panel_key, panel)
                manifest = await self.db('set_replacement_stage', AUDIT_VERSION, 'deletes_complete')
                log.info('VICE_AUDIT_COMPACT_DELETED messages=%s records=%s',
                         len(manifest['message_ids']), len(originals))
            await self.db('reset_for_replacement', AUDIT_VERSION, payloads)
            await self.install_panel()
            log.info('VICE_AUDIT_COMPACT_QUEUED records=%s', len(originals))

    async def delete_registered_card(self, channel, message, keys):
        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, message=message.id,
                        author=message.author.id, content=message.content,
                        embeds=[e.to_dict() for e in message.embeds], keys=sorted(keys),
                        replacement=AUDIT_VERSION)
        await self.system.track('AUDIT_COMPACT_REPLACE',
            'Reemplazar tarjeta larga por formato compacto solicitado por el propietario',
            message.delete, AUDIT_VERSION + ':' + str(message.id), snapshot=snapshot)

    async def flush_once(self):
        async with self.flush_lock:
            channel = self.destination()
            pending = await self.db('pending', 20)
            if not pending:
                return False
            first = pending[0]
            message = None
            recovery = False
            if first['message_id']:
                rows = await self.db('for_message', first['message_id'])
                try:
                    message = await channel.fetch_message(int(first['message_id']))
                except discord.NotFound:
                    # A removed record may be recreated from its persisted payload.
                    pass
                if message and message.author.id != BOT_ID:
                    raise ValueError('El mensaje de auditoría no pertenece al bot.')
            elif first['batch_key']:
                rows = await self.db('batch', first['batch_key'])
                recovery = True
            else:
                rows, total = [], 0
                for row in pending:
                    if row['message_id'] or row['batch_key']:
                        break
                    if rows and (not first['historical'] or not row['historical']):
                        break
                    size = len(self.embeds([row])[0])
                    if rows and (len(rows) >= 5 or total + size > 5500):
                        break
                    rows.append(row)
                    total += size
                batch = hashlib.sha256((AUDIT_VERSION + '|' + '|'.join(
                    row['key'] for row in rows)).encode()).hexdigest()[:24]
                await self.db('reserve', [row['key'] for row in rows], batch, utcnow().isoformat())
                rows = await self.db('batch', batch)
            if recovery:
                message = await self.recover(channel, rows)
            expected = [(row['key'], row['fingerprint']) for row in rows]
            embeds = fit_batch(self.embeds(rows))
            async def snapshot():
                return dict(guild=GUILD_ID, channel=channel.id,
                    records=[dict(key=r['key'], fingerprint=r['fingerprint'], message=r['message_id']) for r in rows])
            async def send():
                nonlocal message
                if message:
                    message = await message.edit(embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
                else:
                    message = await channel.send(embeds=embeds,
                        nonce=rows[0]['batch_key'], silent=True,
                        allowed_mentions=discord.AllowedMentions.none())
                    # Discord may return a previously accepted nonce after a lost
                    # response. Its body can predate a concurrent merged update.
                    if semantic_embeds(message.embeds) != semantic_embeds(embeds):
                        message = await message.edit(embeds=embeds,
                                                     allowed_mentions=discord.AllowedMentions.none())
                wanted = {marker(row['key']) for row in rows}
                if {embed_marker(e) for e in message.embeds} != wanted:
                    # Defensive fallback if Discord ever strips titleless URL metadata.
                    for embed, row in zip(embeds, rows):
                        embed.set_footer(text=str(embed.footer.text or '') + ' • ' + marker(row['key']))
                    message = await message.edit(embeds=embeds,
                                                 allowed_mentions=discord.AllowedMentions.none())
                if ({embed_marker(e) for e in message.embeds} != wanted
                        or len(message.embeds) != len(rows)):
                    raise ValueError('Discord no conservó la identidad de las tarjetas publicadas.')
                await self.db('mark_sent', expected, str(message.id))
            request = hashlib.sha256(json.dumps(expected).encode()).hexdigest()
            await self.system.track('AUDIT_RECORD', 'Publicar registro privado de actividad',
                                    send, request, snapshot=snapshot)
            return True

    async def run(self):
        next_poll = 0.0
        while True:
            try:
                self.destination()
                await self.replace_long_records()
                if not await self.db('state', 'initial_scan_done'):
                    count = await self.scan(full=True)
                    await self.db('set_state', 'initial_history_count', str(count))
                    await self.db('set_state', 'initial_scan_done', 'yes')
                    log.info('VICE_AUDIT_HISTORY_QUEUED entries=%s', count)
                now = asyncio.get_running_loop().time()
                if now >= next_poll:
                    full_at = await self.db('state', 'last_full_scan')
                    full = (await self.db('state', 'format_version') != FORMAT_VERSION or not full_at
                            or utcnow() - datetime.fromisoformat(full_at) > timedelta(days=1))
                    await self.scan(full=full)
                    next_poll = now + POLL_SECONDS
                for _ in range(20):
                    if not await self.flush_once():
                        break
                    await asyncio.sleep(0.35)
                stats = await self.db('stats')
                if stats['pending']:
                    log.info('VICE_AUDIT_PROGRESS total=%s pending=%s sent=%s',
                             stats['total'], stats['pending'], stats['sent'])
                if not stats['pending'] and await self.db('state', 'panel_release') != AUDIT_VERSION + ':complete':
                    await self.install_panel(finished=True)
                    log.info('VICE_AUDIT_HISTORY_COMPLETE total=%s', stats['total'])
                if not stats['pending']:
                    await self.db('set_replacement_stage', AUDIT_VERSION, 'complete')
                self.wakeup.clear()
                try:
                    await asyncio.wait_for(self.wakeup.wait(), timeout=1 if stats['pending'] else 5)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('VICE_AUDIT_RETRY pending records remain durable')
                await asyncio.sleep(30)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
