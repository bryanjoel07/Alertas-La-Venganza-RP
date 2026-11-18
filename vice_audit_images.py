"""Durable before/after image reports for the district's evidenced guild changes."""
import asyncio
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit
import warnings

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont, ImageOps

from vice_design import GUILD_ID


VERSION = 'vice-audit-image-comparison-v1.1'
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 10_000_000
RETRY_SECONDS = 15 * 60
WIDTH, ROW_HEIGHT = 900, 312
FONT_DIR = Path(__file__).parent / 'assets' / 'esschino' / 'fonts'
SEED_DIR = Path(__file__).parent / 'assets' / 'vice-district' / 'audit-history'
# Verified originals from this session, before Discord removed their CDN copies.
# The provenance manifest accompanies these files; paths never come from an event.
SEEDS = {
    '2352b7002eea5e49591f494c92bb876d': 'c29b9af125c774dec1dbda144bfd8af53cac4a877e1cceb1440e6f5ad4cfb1e7',
    '1662ee4c26262cd955e7a7ab14362d59': '70ba88a73b44748e73e947e5e08aa33aa8c0cb7c06396983588a5867faee6b8c',
}
FIELDS = {'icon': ('Icono del servidor', 'icons'),
          'banner': ('Banner del servidor', 'banners'),
          'splash': ('Fondo de invitación', 'splashes')}
HASH = re.compile(r'(?:a_)?[a-f0-9]{32}\Z')
FILENAME = re.compile(r'vice-audit-(\d+)-([a-f0-9]{24})\.png\Z')


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _diff(value):
    if isinstance(value, dict):
        return value
    try:
        return dict(value) if value is not None else {}
    except (TypeError, ValueError):
        return vars(value) if hasattr(value, '__dict__') else {}


def _identifier(value):
    try:
        number = int(_get(value, 'id', value))
        return number if number > 0 and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


def attachment_filename(url):
    """Recognize only our attachment names and Discord's returned attachment URLs."""
    if not isinstance(url, str):
        return None
    if url.startswith('attachment://'):
        candidate = url[len('attachment://'):]
    else:
        try:
            parsed = urlsplit(url)
        except ValueError:
            return None
        if (parsed.scheme != 'https' or parsed.hostname not in
                ('cdn.discordapp.com', 'media.discordapp.net') or parsed.username or parsed.password):
            return None
        pieces = parsed.path.split('/')
        if len(pieces) != 5 or pieces[1] != 'attachments' or not all(p.isdigit() for p in pieces[2:4]):
            return None
        candidate = pieces[-1]
    return candidate if FILENAME.fullmatch(candidate) else None


def _asset(value, kind):
    if value is None:
        return None
    key = value if isinstance(value, str) else _get(value, 'key')
    if not isinstance(key, str) or not HASH.fullmatch(key):
        return 'unavailable'
    return f'https://cdn.discordapp.com/{FIELDS[kind][1]}/{GUILD_ID}/{key}.png?size=1024'


def image_plan(entry):
    """Take only image identities evidenced by an exact district audit event."""
    guild = _get(entry, 'guild')
    action = _get(entry, 'action')
    if _identifier(guild) != GUILD_ID or _get(action, 'value', action) != 1:
        return None
    target = _identifier(_get(entry, 'target')) or _identifier(_get(entry, '_target_id'))
    if target is not None and target != GUILD_ID:
        return None
    event_id = _identifier(entry)
    if not event_id:
        return None
    before, after = _diff(_get(entry, 'before')), _diff(_get(entry, 'after'))
    rows = []
    for kind in FIELDS:
        aliases = (kind, kind + '_hash')
        if not any(key in before or key in after for key in aliases):
            continue
        old = next((before[key] for key in aliases if key in before), None)
        new = next((after[key] for key in aliases if key in after), None)
        if old == new:
            continue
        rows.append(dict(kind=kind, before=_asset(old, kind), after=_asset(new, kind)))
    return dict(event_id=str(event_id), rows=rows) if rows else None


def _image(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Imagen fuera de los límites permitidos.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP', 'GIF') or not 0 < source.width * source.height <= MAX_PIXELS:
                raise ValueError('Formato o tamaño de imagen no permitido.')
            source.seek(0)
            source.load()
            return source.convert('RGBA')


def _seed(url):
    for image_hash, digest in SEEDS.items():
        if url != f'https://cdn.discordapp.com/splashes/{GUILD_ID}/{image_hash}.png?size=1024':
            continue
        try:
            data = (SEED_DIR / (image_hash + '.jpg')).read_bytes()
            if hashlib.sha256(data).hexdigest() != digest:
                return None
            _image(data)
            return data
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            return None
    return None


def render_comparison(plan, assets):
    """Render a labeled report with original pixels, fitting both sides without crop."""
    rows = plan['rows']
    if not 1 <= len(rows) <= 3:
        raise ValueError('La comparación requiere entre una y tres imágenes cambiadas.')
    canvas = Image.new('RGB', (WIDTH, ROW_HEIGHT * len(rows)), '#202127')
    draw = ImageDraw.Draw(canvas)
    bold = ImageFont.truetype(str(FONT_DIR / 'NotoSans-Bold.ttf'), 28)
    label_font = ImageFont.truetype(str(FONT_DIR / 'NotoSans-Bold.ttf'), 24)
    empty_font = ImageFont.truetype(str(FONT_DIR / 'NotoSans-Regular.ttf'), 26)
    for index, row in enumerate(rows):
        top = index * ROW_HEIGHT
        draw.text((22, top + 10), FIELDS[row['kind']][0], font=bold, fill='#FFFFFF')
        for side, x, label, accent in (('before', 22, 'ANTES', '#C8CBD4'),
                                       ('after', 462, 'DESPUÉS', '#55E1CB')):
            draw.text((x, top + 50), label, font=label_font, fill=accent)
            box = (x, top + 80, x + 416, top + 294)
            draw.rounded_rectangle(box, radius=10, fill='#14151A')
            url = row[side]
            data = assets.get(url) if url and url != 'unavailable' else None
            if data:
                image = _image(data)
                contained = ImageOps.contain(image, (412, 210), Image.Resampling.LANCZOS)
                offset = (x + (416 - contained.width) // 2,
                          top + 80 + (214 - contained.height) // 2)
                canvas.paste(contained, offset, contained)
            else:
                message = ('Imagen no disponible' if url is not None else
                           ('Imagen retirada' if side == 'after' and row['before'] is not None else 'Sin imagen'))
                draw.text((x + 208, top + 187), message, font=empty_font,
                          fill='#B8BDC8', anchor='mm')
        if index:
            draw.line((22, top, 878, top), fill='#393C45', width=1)
    output = io.BytesIO()
    canvas.save(output, format='PNG', optimize=True)
    data = output.getvalue()
    if len(data) > MAX_BYTES:
        raise ValueError('La comparación supera el tamaño permitido.')
    return data


class AuditVisuals:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = asyncio.Lock()
        self.download_slots = asyncio.Semaphore(3)

    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.db()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_visual_assets (
                url TEXT PRIMARY KEY, payload BLOB NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_visual_files (
                filename TEXT PRIMARY KEY, event_key TEXT NOT NULL, payload BLOB NOT NULL,
                sha256 TEXT NOT NULL, created REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_visual_latest (
                event_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, filename TEXT NOT NULL,
                complete INTEGER NOT NULL, rendered_at REAL NOT NULL)''')

    async def start(self):
        await asyncio.to_thread(self._initialize)

    def _one(self, query, params):
        with closing(self.db()) as db:
            row = db.execute(query, params).fetchone()
            return dict(row) if row else None

    def _save_asset(self, url, data):
        with closing(self.db()) as db, db:
            db.execute('INSERT OR IGNORE INTO vice_audit_visual_assets(url,payload) VALUES (?,?)', (url, data))

    async def _download(self, url):
        # URLs are constructed solely from the exact guild, known paths and hashes.
        async with self.download_slots:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                    async with session.get(url, allow_redirects=False) as response:
                        if response.status != 200 or not response.headers.get('Content-Type', '').lower().startswith('image/'):
                            return None
                        if response.content_length is not None and response.content_length > MAX_BYTES:
                            return None
                        data = bytearray()
                        async for chunk in response.content.iter_chunked(64 * 1024):
                            data.extend(chunk)
                            if len(data) > MAX_BYTES:
                                return None
                        result = bytes(data)
                        await asyncio.to_thread(_image, result)
                        return result
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError,
                    Image.DecompressionBombError, Image.DecompressionBombWarning):
                return None

    async def _asset_bytes(self, url):
        existing = await asyncio.to_thread(self._one,
            'SELECT payload FROM vice_audit_visual_assets WHERE url=?', (url,))
        if existing:
            return existing['payload']
        data = await asyncio.to_thread(_seed, url)
        if data is None:
            data = await self._download(url)
        if data:
            await asyncio.to_thread(self._save_asset, url, data)
        return data

    def _save_report(self, event_key, fingerprint, data, complete):
        digest = hashlib.sha256(data).hexdigest()
        filename = f'vice-audit-{event_key.split(":", 1)[1]}-{digest[:24]}.png'
        now = time.time()
        with closing(self.db()) as db, db:
            db.execute('''INSERT OR IGNORE INTO vice_audit_visual_files
                (filename,event_key,payload,sha256,created) VALUES (?,?,?,?,?)''',
                (filename, event_key, data, digest, now))
            db.execute('''INSERT INTO vice_audit_visual_latest
                (event_key,fingerprint,filename,complete,rendered_at) VALUES (?,?,?,?,?)
                ON CONFLICT(event_key) DO UPDATE SET fingerprint=excluded.fingerprint,
                filename=excluded.filename,complete=excluded.complete,rendered_at=excluded.rendered_at''',
                (event_key, fingerprint, filename, int(complete), now))
        return filename

    async def render(self, entry):
        plan = image_plan(entry)
        if plan is None:
            return None
        event_key = 'audit:' + plan['event_id']
        fingerprint = hashlib.sha256(json.dumps(dict(version=VERSION, **plan), sort_keys=True).encode()).hexdigest()
        async with self.lock:
            latest = await asyncio.to_thread(self._one,
                'SELECT * FROM vice_audit_visual_latest WHERE event_key=?', (event_key,))
            if (latest and latest['fingerprint'] == fingerprint and
                    (latest['complete'] or time.time() - latest['rendered_at'] < RETRY_SECONDS)):
                return latest['filename']
            urls = sorted({row[side] for row in plan['rows'] for side in ('before', 'after')
                           if row[side] not in (None, 'unavailable')})
            values = await asyncio.gather(*(self._asset_bytes(url) for url in urls))
            assets = dict(zip(urls, values))
            complete = all(assets.values()) and not any(
                row[side] == 'unavailable' for row in plan['rows'] for side in ('before', 'after'))
            data = await asyncio.to_thread(render_comparison, plan, assets)
            return await asyncio.to_thread(self._save_report, event_key, fingerprint, data, complete)

    async def files_for(self, embeds):
        names = []
        for embed in embeds:
            name = attachment_filename(_get(_get(embed, 'image'), 'url'))
            if name and name not in names:
                names.append(name)
        files = []
        for name in names:
            row = await asyncio.to_thread(self._one,
                'SELECT * FROM vice_audit_visual_files WHERE filename=?', (name,))
            if row is None or hashlib.sha256(row['payload']).hexdigest() != row['sha256']:
                raise ValueError('Falta la copia registrada de una comparación de auditoría.')
            files.append(discord.File(io.BytesIO(row['payload']), filename=name,
                                      description='Comparación de imagen anterior y nueva'))
        return files

    async def validate_attachments(self, attachments, rows):
        keys = set()
        for row in rows:
            key = str(row['key'])
            if not key.startswith('audit:'):
                continue
            source_id = _get(row, 'source_id')
            if source_id is not None and str(source_id) != key.split(':', 1)[1]:
                return False
            keys.add(key)
        seen = set()
        for attachment in attachments:
            name = _get(attachment, 'filename')
            if not isinstance(name, str) or not FILENAME.fullmatch(name) or name in seen:
                return False
            seen.add(name)
            saved = await asyncio.to_thread(self._one,
                'SELECT event_key,payload,sha256 FROM vice_audit_visual_files WHERE filename=?', (name,))
            if saved is None or saved['event_key'] not in keys:
                return False
            size = _get(attachment, 'size')
            if size is not None and size != len(saved['payload']):
                return False
            if hashlib.sha256(saved['payload']).hexdigest() != saved['sha256']:
                return False
        return True
