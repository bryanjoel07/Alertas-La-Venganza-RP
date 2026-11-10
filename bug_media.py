"""Serve confirmed report clips without Discord's smaller bot attachment ceiling.

The original stays in SQLite. Unpublished drafts have no public URL. Published
clips use a random capability URL and a disposable, verified playback cache.
"""
import asyncio
import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from urllib.parse import quote, urlsplit

from aiohttp import web

from bug_limits import MAX_CLIP_BYTES

log = logging.getLogger('LaVenganzaRP.bugs')
TYPES = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm'}


class ClipReader:
    def __init__(self, path, token):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, check_same_thread=False, timeout=10)
        self.blob = None
        try:
            self.db.execute('BEGIN')
            row = self.db.execute('''SELECT b.id,b.filename,b.sha256,length(b.video)
                FROM lv_bug_media m JOIN lv_bugs b ON b.id=m.report AND b.sha256=m.sha256
                WHERE m.token=? AND b.status IN ('publicando','pendiente','revision','proceso','solucionado','cerrado')
                AND b.video IS NOT NULL''', (token,)).fetchone()
            if not row:
                raise LookupError('Clip not published')
            self.rid, self.filename, self.sha256, self.size = row
            if Path(self.filename).suffix.lower() not in TYPES:
                raise LookupError('Unknown clip format')
            self.blob = self.db.blobopen('lv_bugs', 'video', self.rid, readonly=True)
        except BaseException:
            self.close()
            raise

    def read(self, offset, length):
        with self.lock:
            self.blob.seek(offset)
            return self.blob.read(length)

    def close(self):
        with self.lock:
            if self.blob is not None:
                self.blob.close()
            self.db.close()


class ReportMedia:
    def __init__(self, system):
        self.system = system
        self.base_url = os.getenv('BUG_CLIPS_BASE_URL', '').rstrip('/')
        self.runner = None
        self.slots = asyncio.Semaphore(4)
        self.cache = None

    def url(self, row):
        if not self.base_url or not row.get('media_token'):
            return ''
        suffix = Path(row['filename']).suffix.lower()
        return f"{self.base_url}/clips/{row['media_token']}/clip{suffix}"

    async def share(self, rid):
        if not self.base_url or self.runner is None:
            raise ValueError('El clip está guardado, pero falta conectar su publicación. No vuelvas a crear el reporte.')
        await self.system.call('media_token', rid)
        return await self.system.call('get', rid, include_video=False)

    def application(self):
        if self.cache is None:
            self.cache = tempfile.TemporaryDirectory(prefix='lv-report-clips-')
        app = web.Application(client_max_size=1024)
        app.router.add_get('/health', self.health)
        app.router.add_get(r'/clips/{token:[A-Za-z0-9_-]{43}}/{name}', self.clip)
        return app

    async def health(self, request):
        return web.json_response(dict(status='ok', max_clip_mb=MAX_CLIP_BYTES // (1024 * 1024),
            discord_connected=self.system.bot.is_ready(), release=os.getenv('RAILWAY_GIT_COMMIT_SHA', '')[:12]))

    async def clip(self, request):
        async with self.slots:
            try:
                path, filename, content_type = await asyncio.to_thread(self.prepare,
                    request.match_info['token'], request.match_info['name'])
            except LookupError:
                raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Type': content_type,
            'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600, no-transform',
            'Referrer-Policy': 'no-referrer',
            'Content-Disposition': "inline; filename*=UTF-8''" + quote(Path(filename).name, safe='')})

    def prepare(self, token, name):
        # Close the SQLite read transaction before streaming to a slow client.
        # The disposable cache is rebuilt from the persistent original on restart.
        reader = ClipReader(self.system.store.path, token)
        temporary = None
        try:
            suffix = Path(reader.filename).suffix.lower()
            if name != 'clip' + suffix:
                raise LookupError('Unknown clip')
            path = Path(self.cache.name) / (reader.sha256 + suffix)
            if not path.exists():
                digest = hashlib.sha256()
                with tempfile.NamedTemporaryFile(dir=self.cache.name, delete=False) as output:
                    temporary = Path(output.name)
                    offset = 0
                    while offset < reader.size:
                        chunk = reader.read(offset, min(256 * 1024, reader.size - offset))
                        if not chunk:
                            raise IOError('Incomplete stored clip')
                        output.write(chunk)
                        digest.update(chunk)
                        offset += len(chunk)
                if digest.hexdigest() != reader.sha256:
                    raise IOError('Stored clip checksum mismatch')
                os.replace(temporary, path)
                temporary = None
            return path, reader.filename, TYPES[suffix]
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            reader.close()

    async def start(self):
        if not self.base_url:
            return
        parsed = urlsplit(self.base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('BUG_CLIPS_BASE_URL must be an HTTPS origin')
        self.runner = web.AppRunner(self.application(), access_log=None)
        await self.runner.setup()
        port = int(os.getenv('PORT', '8080'))
        await web.TCPSite(self.runner, '0.0.0.0', port).start()
        log.info('BUGS media_ready port=%s max_clip_mb=60 streaming=True drafts_public=False', port)

    async def close(self):
        if self.runner is not None:
            await self.runner.cleanup()
            self.runner = None
        if self.cache is not None:
            await asyncio.to_thread(self.cache.cleanup)
            self.cache = None
