"""Private, verified ticket transcripts that must complete before deletion."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit, urlunsplit
import uuid
import zipfile

import aiohttp
import discord

from vice_design import GUILD_ID, BOT_ID, OWNER_ID
from vice_tickets import KINDS

log = logging.getLogger('ViceDistrict.ticket_archive')
DESTINATION_KEY = 'ticket_archive:destination'
TOPIC = 'Copias privadas de tickets cerrados. Acceso exclusivo del equipo.'
TITLE = '📁 Copia privada de ticket'
MAX_MESSAGES = 10000
MAX_ATTACHMENT = 25 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_TRANSCRIPT = 20 * 1024 * 1024
MAX_ATTACHMENTS = 200
CDN_HOSTS = {'cdn.discordapp.com', 'media.discordapp.net'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha_file(path):
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(128 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def stable_url(value):
    if not value:
        return value
    parts = urlsplit(str(value))
    return urlunsplit(parts._replace(query='', fragment='')) if parts.hostname in CDN_HOSTS else str(value)


def stable(value):
    if isinstance(value, dict):
        return {key: stable_url(item) if key in ('url', 'proxy_url', 'proxy_icon_url')
                and isinstance(item, str) else stable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stable(item) for item in value]
    return value


def iso(value):
    return value.isoformat() if value else None


def safe_attachment_name(message_id, attachment):
    basename = str(attachment.filename).replace('\\', '/').rsplit('/', 1)[-1]
    basename = re.sub(r'[^\w. -]', '_', basename, flags=re.UNICODE).strip(' .')[:100] or 'archivo'
    return f'attachments/{int(message_id)}-{int(attachment.id)}-{basename}'


def render_html(snapshot):
    escape = lambda value: html.escape(str(value or ''), quote=True)
    rows = []
    for message in snapshot['messages']:
        attachments = ''.join(f'<li>{escape(a["filename"])} — {a["size"]} bytes '
                              f'(<code>{escape(a["archive_path"])}</code>)</li>' for a in message['attachments'])
        embeds = ''.join('<pre>' + escape(json.dumps(embed, ensure_ascii=False, indent=2)) + '</pre>'
                         for embed in message['embeds'])
        rows.append(f'<article><h2>{escape(message["author"]["display_name"])} '
                    f'<small>({message["author"]["id"]})</small></h2>'
                    f'<p>{escape(message["created_at"])} · ID {message["id"]}</p>'
                    f'<p>Editado: {escape(message["edited_at"]) or "—"}</p>'
                    f'<pre>{escape(message["content"])}</pre>{embeds}<ul>{attachments}</ul></article>')
    return ('<!doctype html><html lang="es"><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>Copia privada de ticket</title><style>body{font:16px system-ui;background:#161320;'
            'color:#eee;max-width:1000px;margin:40px auto;padding:20px}article{padding:20px;margin:20px 0;'
            'background:#242033;border-left:4px solid #ff168a}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
            'small{font-size:12px}h2{font-size:18px}</style><h1>VIce District · Ticket cerrado</h1>'
            f'<p>#{escape(snapshot["channel"]["name"])} · {snapshot["channel"]["id"]}</p>'
            f'<p>Tipo: {escape(snapshot["ticket"]["kind"])} · Equipo asignado: '
            f'{escape((snapshot.get("assignment") or {}).get("staff_id")) or "Sin asignación"}</p>'
            + ''.join(rows) + '</html>')


class TicketArchive:
    def __init__(self, system):
        self.system = system
        self.root = Path(system.path).parent / 'vice-ticket-archives'
        self.lock = asyncio.Lock()

    async def start(self):
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True, mode=0o700)

    def guild(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.bot.user.id != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        return guild

    def staff_roles(self, guild):
        roles = [guild.get_role(int(self.system.store.get('role:' + key) or 0))
                 for key in ('admin', 'mod', 'support')]
        if any(role is None for role in roles):
            raise ValueError('Faltan roles del equipo; el ticket se conserva.')
        return roles

    def overwrites(self, guild):
        readonly = dict(view_channel=True, read_message_history=True, send_messages=False,
            send_messages_in_threads=False, add_reactions=False, create_public_threads=False,
            create_private_threads=False, send_voice_messages=False, send_polls=False)
        # Member caching is intentionally disabled by this bot. The guild's
        # owner ID was validated above; an overwrite needs only its typed ID.
        self.system.validate_guild(guild)
        owner = discord.Object(id=OWNER_ID, type=discord.Member)
        if guild.me is None or guild.me.id != BOT_ID:
            raise ValueError('No se pudo verificar el equipo del archivo privado.')
        result = {guild.default_role: discord.PermissionOverwrite(**dict(readonly, view_channel=False,
                                                                        read_message_history=False))}
        for target in [owner, *self.staff_roles(guild)]:
            result[target] = discord.PermissionOverwrite(**readonly)
        result[guild.me] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
            send_messages=True, embed_links=True, attach_files=True, manage_messages=True)
        return result

    def validate_destination(self, channel, record):
        guild = self.guild()
        if (not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID
                or int(record.get('channel') or 0) != channel.id
                or channel.category_id != int(self.system.store.get('category:team') or 0)
                or channel.topic != TOPIC):
            raise ValueError('El archivo privado necesita revisión; el ticket se conserva.')
        expected = self.overwrites(guild)
        actual = {target.id: overwrite for target, overwrite in channel.overwrites.items()}
        if set(actual) != {target.id for target in expected}:
            raise ValueError('El archivo no tiene los accesos privados esperados; el ticket se conserva.')
        for target, required in expected.items():
            overwrite = actual[target.id]
            for permission, value in required:
                if value is not None and getattr(overwrite, permission) is not value:
                    raise ValueError('Los permisos del archivo cambiaron; el ticket se conserva.')
        return channel

    async def destination(self):
        record = await self.system.call('get', DESTINATION_KEY) or {}
        if not record.get('channel'):
            raise ValueError('El archivo privado aún no está listo; el ticket se conserva.')
        channel = await self.guild().fetch_channel(int(record['channel']))
        return self.validate_destination(channel, record)

    @staticmethod
    def known_pre_dispatch_failure(record):
        """Only the logged owner-cache failure, never an unknown API attempt."""
        if set(record) != {'guild', 'nonce', 'started_at', 'attempted_at'}:
            return False
        start = datetime(2026, 11, 18, 18, 4, 52, tzinfo=timezone.utc)
        end = datetime(2026, 11, 18, 18, 4, 54, tzinfo=timezone.utc)
        try:
            timestamps = [datetime.fromisoformat(record[key]) for key in ('started_at', 'attempted_at')]
            return all(stamp.tzinfo is not None and start <= stamp <= end for stamp in timestamps)
        except (TypeError, ValueError):
            return False

    async def ready(self):
        async with self.lock:
            guild = self.guild()
            record = await self.system.call('get', DESTINATION_KEY) or {}
            if record.get('channel'):
                return await self.destination()
            category = await guild.fetch_channel(int(self.system.store.get('category:team') or 0))
            if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
                raise ValueError('No se encontró la categoría privada del equipo.')
            if not record:
                record = dict(guild=GUILD_ID, nonce=uuid.uuid4().hex,
                              started_at=datetime.now(timezone.utc).isoformat())
                await self.system.call('put', DESTINATION_KEY, record)
            if record.get('guild') != GUILD_ID or not record.get('nonce'):
                raise ValueError('El registro del archivo necesita revisión.')
            reason = 'VIce ticket archive ' + record['nonce']
            matches = []
            after = datetime.fromisoformat(record['started_at']) - timedelta(seconds=5)
            async for entry in guild.audit_logs(limit=None, action=discord.AuditLogAction.channel_create, after=after):
                if (getattr(entry.user, 'id', None) == BOT_ID and entry.reason == reason
                        and getattr(entry.target, 'id', None)):
                    candidate = await guild.fetch_channel(entry.target.id)
                    candidate_record = dict(record, channel=candidate.id)
                    self.validate_destination(candidate, candidate_record)
                    matches.append(candidate)
            if len(matches) > 1:
                raise ValueError('Hay más de un archivo registrado; se requiere revisión del equipo.')
            if not matches and record.get('attempted_at'):
                if not self.known_pre_dispatch_failure(record):
                    raise ValueError('La creación anterior del archivo aún no se pudo verificar. No se creará otro.')
                existing = await guild.fetch_channels()
                if any(getattr(item, 'topic', None) == TOPIC and item.category_id == category.id
                       for item in existing):
                    raise ValueError('Existe un posible archivo previo; no se creará otro.')
                # Live traceback proved this exact attempt raised while
                # evaluating overwrites, before create_text_channel dispatch.
                # Audit and channel checks above independently rule out a copy.
                original = dict(record)
                async def recovery_snapshot():
                    return dict(destination=await self.system.call('get', DESTINATION_KEY),
                                original=original)
                async def recover_pre_dispatch():
                    if await self.system.call('get', DESTINATION_KEY) != original:
                        raise ValueError('El registro del archivo cambió; se conserva para revisión.')
                    record.pop('attempted_at')
                    record['recovered_pre_dispatch_bug_v1'] = dict(
                        at=datetime.now(timezone.utc).isoformat(), original=original)
                    await self.system.call('put', DESTINATION_KEY, record)
                await self.system.track('TICKET_ARCHIVE_RECOVERY', 'Recuperar preparación del archivo privado',
                    recover_pre_dispatch, record['nonce'] + ':owner-cache-fix-v1', snapshot=recovery_snapshot)
            async def snapshot():
                return dict(destination=await self.system.call('get', DESTINATION_KEY))
            async def create():
                if matches:
                    channel = matches[0]
                else:
                    channels = await guild.fetch_channels()
                    voices = [item for item in channels if isinstance(item, discord.VoiceChannel)
                              and item.category_id == category.id]
                    position = min((item.position for item in voices), default=category.position + 1)
                    expected_overwrites = self.overwrites(guild)
                    record['attempted_at'] = datetime.now(timezone.utc).isoformat()
                    await self.system.call('put', DESTINATION_KEY, record)
                    channel = await guild.create_text_channel('├・📁│archivo-tickets',
                        category=category, position=position, topic=TOPIC,
                        overwrites=expected_overwrites, reason=reason)
                record['channel'] = channel.id
                self.validate_destination(channel, record)
                await self.system.call('put', DESTINATION_KEY, record)
                await self.system.call('put', 'channel:ticket_archive', channel.id)
                return channel
            result = await self.system.track('TICKET_ARCHIVE_SETUP', 'Preparar archivo privado de tickets',
                create, record['nonce'], snapshot=snapshot)
            log.info('VICE_TICKET_ARCHIVE_READY channel=%s', result.id)
            return result

    def valid_ticket(self, channel, row):
        self.guild()
        if (not row or row.get('state') != 'closed' or not isinstance(channel, discord.TextChannel)
                or channel.guild.id != GUILD_ID or str(channel.id) != str(row['channel'])
                or channel.category_id != int(self.system.store.get('category:closed') or 0)
                or channel.topic != 'VIce ticket closed owner=' + str(row['owner'])):
            raise ValueError('Solo se archivan tickets cerrados y registrados del distrito.')

    async def capture(self, channel, row):
        current = await self.system.call('ticket', channel.id)
        self.valid_ticket(channel, current)
        if str(current['owner']) != str(row['owner']):
            raise ValueError('El ticket cambió; se conserva para revisión.')
        if channel.threads or any(thread.parent_id == channel.id for thread in await self.guild().active_threads()):
            raise ValueError('Este ticket contiene hilos; consérvalo hasta archivarlos por completo.')
        for private in (False, True):
            async for unused in channel.archived_threads(limit=1, private=private):
                raise ValueError('Este ticket contiene hilos archivados; se conserva para revisión.')
        messages, downloads, total = [], [], 0
        async for message in channel.history(limit=MAX_MESSAGES + 1, oldest_first=True):
            if len(messages) >= MAX_MESSAGES:
                raise ValueError('El ticket supera 10.000 mensajes; se conserva sin eliminar.')
            attachments = []
            for attachment in message.attachments:
                if attachment.size > MAX_ATTACHMENT or attachment.size < 0:
                    raise ValueError('Un adjunto supera 25 MiB; el ticket se conserva sin eliminar.')
                total += attachment.size
                if total > MAX_TOTAL:
                    raise ValueError('Los adjuntos superan 100 MiB; el ticket se conserva sin eliminar.')
                name = safe_attachment_name(message.id, attachment)
                attachments.append(dict(id=str(attachment.id), filename=attachment.filename,
                    size=attachment.size, content_type=attachment.content_type,
                    url=stable_url(attachment.url), archive_path=name,
                    width=attachment.width, height=attachment.height))
                downloads.append((attachment.url, name, attachment.size))
                if len(downloads) > MAX_ATTACHMENTS:
                    raise ValueError('El ticket supera 200 adjuntos; se conserva sin eliminar.')
            avatar = getattr(message.author, 'display_avatar', None)
            messages.append(dict(id=str(message.id), content=message.content,
                author=dict(id=str(message.author.id), name=message.author.name,
                    display_name=message.author.display_name, bot=message.author.bot,
                    avatar_url=str(avatar.url) if avatar else None),
                created_at=iso(message.created_at), edited_at=iso(message.edited_at),
                type=message.type.value, pinned=message.pinned, flags=message.flags.value,
                reference=message.reference.to_dict() if message.reference else None,
                embeds=[stable(embed.to_dict()) for embed in message.embeds], attachments=attachments,
                components=[component.to_dict() for component in message.components],
                stickers=[dict(id=str(sticker.id), name=sticker.name, url=str(sticker.url))
                          for sticker in message.stickers]))
        snapshot = dict(guild=str(GUILD_ID), channel=dict(id=str(channel.id), name=channel.name,
            category=str(channel.category_id), topic=channel.topic), ticket=dict(current),
            assignment=await self.system.call('get', 'ticket_assignment:' + str(channel.id)), messages=messages)
        if len(canonical(snapshot)) > MAX_TRANSCRIPT:
            raise ValueError('La transcripción es demasiado grande; el ticket se conserva.')
        return snapshot, downloads

    async def download(self, url, path, expected, maximum):
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.hostname not in CDN_HOSTS or parts.username or parts.password
                or parts.port not in (None, 443)
                or not parts.path.startswith(('/attachments/', '/ephemeral-attachments/'))):
            raise ValueError('No se pudo verificar un adjunto de Discord; el ticket se conserva.')
        size = 0
        timeout = aiohttp.ClientTimeout(total=90, connect=15, sock_read=30)
        async with aiohttp.ClientSession(timeout=timeout, auto_decompress=False) as session:
            async with session.get(url, allow_redirects=False, headers={'Accept-Encoding': 'identity'}) as response:
                if response.status != 200:
                    raise ValueError('No se pudo descargar un adjunto completo; el ticket se conserva.')
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('wb') as stream:
                    async for block in response.content.iter_chunked(128 * 1024):
                        size += len(block)
                        if size > maximum or size > expected:
                            raise ValueError('Un adjunto excede el tamaño esperado; el ticket se conserva.')
                        stream.write(block)
        if size != expected:
            raise ValueError('La copia de un adjunto está incompleta; el ticket se conserva.')
        return await asyncio.to_thread(sha_file, path)

    def write_zip(self, target, directory, snapshot, attachment_hashes):
        manifest = dict(snapshot, attachment_sha256=attachment_hashes)
        def entry(name):
            result = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            result.compress_type = zipfile.ZIP_DEFLATED
            result.external_attr = 0o600 << 16
            return result
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(entry('transcript.json'), canonical(manifest))
            archive.writestr(entry('transcript.html'), render_html(snapshot).encode('utf-8'))
            for relative in attachment_hashes:
                with (directory / relative).open('rb') as source, archive.open(entry(relative), 'w') as output:
                    shutil.copyfileobj(source, output, 128 * 1024)
        target.chmod(0o600)

    def marker(self, channel_id, fingerprint):
        return f'https://discord.com/channels/{GUILD_ID}/{channel_id}?archive={fingerprint}'

    def matching_message(self, message, receipt):
        return (message.author.id == BOT_ID and not message.content and len(message.embeds) == 1
            and message.embeds[0].title == TITLE
            and message.embeds[0].url == self.marker(receipt['channel'], receipt['fingerprint'])
            and len(message.attachments) == 1
            and message.attachments[0].filename == receipt['filename']
            and message.attachments[0].size == receipt['size'])

    async def verify_message(self, destination, message, receipt):
        current = await destination.fetch_message(message.id)
        if not self.matching_message(current, receipt):
            raise ValueError('No se pudo verificar la copia privada; el ticket se conserva.')
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            value = await self.download(current.attachments[0].url, Path(folder) / 'verify.zip',
                                        receipt['size'], receipt['size'])
        if value != receipt['sha256']:
            raise ValueError('La copia privada no coincide con el original; el ticket se conserva.')
        return current

    async def backup(self, channel, row, actor_id):
        try:
            async with asyncio.timeout(300):
                return await self._backup(channel, row, actor_id)
        except TimeoutError as error:
            raise ValueError('La copia tardó demasiado. El ticket se conserva; vuelve a intentarlo.') from error

    async def _backup(self, channel, row, actor_id):
        async with self.lock:
            await self.start()
            self.valid_ticket(channel, row)
            if not self.system.bot.intents.message_content:
                raise ValueError('Falta acceso al contenido completo de mensajes. El ticket se conserva sin eliminar.')
            destination = await self.destination()
            snapshot, downloads = await self.capture(channel, row)
            fingerprint = digest(snapshot)
            key = f'ticket_archive:receipt:{channel.id}:{fingerprint}'
            receipt = await self.system.call('get', key) or {}
            filename = f'ticket-{channel.id}-{fingerprint[:16]}.zip'
            path = self.root / filename
            valid_local = (receipt.get('sha256') and path.is_file()
                and await asyncio.to_thread(sha_file, path) == receipt['sha256'])
            if not valid_local:
                with tempfile.TemporaryDirectory(dir=self.root) as folder:
                    directory = Path(folder)
                    hashes = {}
                    for url, name, size in downloads:
                        hashes[name] = await self.download(url, directory / name, size, MAX_ATTACHMENT)
                    temporary = directory / 'archive.zip'
                    await asyncio.to_thread(self.write_zip, temporary, directory, snapshot, hashes)
                    await asyncio.to_thread(temporary.replace, path)
                local_hash = await asyncio.to_thread(sha_file, path)
                if receipt.get('sha256') and local_hash != receipt['sha256']:
                    raise ValueError('La copia reconstruida no coincide con la anterior; el ticket se conserva.')
                receipt = dict(receipt, guild=GUILD_ID, channel=channel.id, owner=str(row['owner']),
                    actor=int(actor_id), fingerprint=fingerprint, sha256=local_hash,
                    size=path.stat().st_size, filename=filename, message_count=len(snapshot['messages']),
                    attachment_count=len(downloads), created_at=receipt.get('created_at') or
                    datetime.now(timezone.utc).isoformat(), state='local')
                await self.system.call('put', key, receipt)
            limit = int(self.guild().filesize_limit) - 64 * 1024
            if receipt['size'] > limit:
                raise ValueError('La copia supera el límite de archivos de Discord. El ticket se conserva sin eliminar.')
            message = None
            if receipt.get('message_id'):
                try:
                    message = await destination.fetch_message(int(receipt['message_id']))
                except discord.NotFound as error:
                    if error.code != 10008:
                        raise
            if message is None and receipt.get('attempted_at'):
                after = datetime.fromisoformat(receipt['attempted_at']) - timedelta(seconds=5)
                async for candidate in destination.history(limit=None, after=after, oldest_first=True):
                    if self.matching_message(candidate, receipt):
                        message = candidate
                        break
            async def archive_state():
                return dict(ticket=dict(row), receipt=await self.system.call('get', key), destination=destination.id)
            async def publish():
                nonlocal message, destination
                destination = await self.destination()
                if message is None:
                    receipt['attempted_at'] = datetime.now(timezone.utc).isoformat()
                    await self.system.call('put', key, receipt)
                    embed = discord.Embed(title=TITLE,
                        description=f'Ticket **{channel.name}** · {len(snapshot["messages"])} mensajes.\n'
                                    'Incluye transcripción HTML/JSON y los adjuntos originales.', color=0x00D9E8,
                        url=self.marker(channel.id, fingerprint))
                    assignment = snapshot.get('assignment') or {}
                    staff_name = assignment.get('staff_name')
                    responsible = (discord.utils.escape_markdown(staff_name) if staff_name else
                        f'<@{int(assignment["staff_id"])}>' if assignment.get('staff_id') else 'Sin asignar')
                    embed.add_field(name='Categoría', value=KINDS.get(row['kind'], KINDS['general']))
                    embed.add_field(name='Autor', value=f'<@{int(row["owner"])}>')
                    embed.add_field(name='Responsable', value=responsible[:1024])
                    embed.set_footer(text='VIce District • Archivo privado')
                    with closing(discord.File(path, filename=filename)) as upload:
                        message = await destination.send(embed=embed, file=upload,
                            nonce=str(int(fingerprint[:16], 16)), allowed_mentions=discord.AllowedMentions.none())
                message = await self.verify_message(destination, message, receipt)
                receipt.update(message_id=message.id, destination=destination.id, state='verified',
                               verified_at=datetime.now(timezone.utc).isoformat())
                await self.system.call('put', key, receipt)
            await self.system.track('TICKET_ARCHIVE_BACKUP', 'Guardar copia privada completa del ticket',
                publish, f'{channel.id}:{fingerprint}', snapshot=archive_state)
            await self.verify_current(channel, row, receipt)
            log.info('VICE_TICKET_ARCHIVE_VERIFIED channel=%s destination=%s message=%s messages=%s '
                     'attachments=%s sha256=%s size=%s', channel.id, receipt['destination'], receipt['message_id'],
                     receipt['message_count'], receipt['attachment_count'], receipt['sha256'], receipt['size'])
            return receipt

    async def verify_current(self, channel, row, receipt):
        fresh = await self.guild().fetch_channel(channel.id)
        snapshot, unused = await self.capture(fresh, row)
        if receipt.get('state') != 'verified' or digest(snapshot) != receipt.get('fingerprint'):
            raise ValueError('El ticket cambió durante la copia. Se conserva; vuelve a intentarlo.')
        destination = await self.destination()
        if receipt.get('destination') != destination.id or not receipt.get('message_id'):
            raise ValueError('No se pudo verificar el destino de la copia; el ticket se conserva.')
        message = await destination.fetch_message(int(receipt['message_id']))
        if not self.matching_message(message, receipt):
            raise ValueError('La copia privada cambió; el ticket se conserva.')
        return fresh
