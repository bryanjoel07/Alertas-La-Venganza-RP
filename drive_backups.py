"""Drive autenticado y prueba de recuperación aislada, sin tocar la base activa."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from urllib.parse import urlparse


class BackupFailure(RuntimeError):
    def __init__(self, stage, message):
        self.stage = stage
        super().__init__(message)


class DriveBackupClient:
    def __init__(self):
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            scopes = ['https://www.googleapis.com/auth/drive.file']
            secret = os.getenv('GOOGLE_DRIVE_CREDENTIALS_JSON')
            if secret:
                info = json.loads(secret)
                if info.get('type') == 'authorized_user':
                    from google.oauth2.credentials import Credentials
                    credentials = Credentials.from_authorized_user_info(info, scopes=scopes)
                elif info.get('type') == 'service_account':
                    from google.oauth2.service_account import Credentials
                    credentials = Credentials.from_service_account_info(info, scopes=scopes)
                else:
                    raise ValueError('Unsupported credentials')
            else:
                credentials, _ = google.auth.default(scopes=scopes)
            self.service_account = hasattr(credentials, 'service_account_email')
            self.session = AuthorizedSession(credentials)
        except Exception:
            raise BackupFailure('authentication', 'No se pudo cargar la autenticación de Google. Revisa las variables privadas de Railway.') from None

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, **kwargs)
            if response.status_code >= 400:
                response.close()
                raise BackupFailure('drive', f'Google Drive rechazó la operación (HTTP {response.status_code}).')
            return response
        except BackupFailure:
            raise
        except Exception:
            # Nunca propagar una excepción de HTTP que pueda contener URL de sesión o tokens.
            raise BackupFailure('drive', 'No se pudo completar la conexión con Google Drive.') from None

    def folder(self, folder_id=None):
        if folder_id:
            if not re.fullmatch(r'[A-Za-z0-9_-]+', folder_id):
                raise BackupFailure('configuration', 'El ID de la carpeta de Drive no es válido.')
            with self.request('GET', f'https://www.googleapis.com/drive/v3/files/{folder_id}', params={'fields': 'id,mimeType,trashed,capabilities(canAddChildren)', 'supportsAllDrives': 'true'}, timeout=(10, 30)) as response:
                data = response.json()
            if data.get('trashed') or data.get('mimeType') != 'application/vnd.google-apps.folder' or not data.get('capabilities', {}).get('canAddChildren', False):
                raise BackupFailure('configuration', 'La identidad de Google no puede guardar archivos en la carpeta elegida.')
            return folder_id
        if self.service_account:
            raise BackupFailure('configuration', 'Una cuenta de servicio necesita una carpeta de una unidad compartida. Para Gmail personal usa OAuth de usuario.')
        with self.request('POST', 'https://www.googleapis.com/drive/v3/files', params={'fields': 'id'}, json={'name': 'LA VENGANZA RP - Respaldos', 'mimeType': 'application/vnd.google-apps.folder'}, timeout=(10, 30)) as response:
            return response.json()['id']

    def upload(self, path, folder_id):
        path = Path(path)
        try:
            with self.request('POST', 'https://www.googleapis.com/upload/drive/v3/files', params={'uploadType': 'resumable', 'fields': 'id,size,md5Checksum', 'supportsAllDrives': 'true'}, json={'name': path.name, 'parents': [folder_id]}, headers={'X-Upload-Content-Type': 'application/vnd.sqlite3', 'X-Upload-Content-Length': str(path.stat().st_size)}, timeout=(10, 30)) as response:
                location = response.headers['Location']
            target = urlparse(location)
            if target.scheme != 'https' or target.hostname not in ('www.googleapis.com', 'content.googleapis.com'):
                raise BackupFailure('drive', 'Drive devolvió una dirección de subida no válida.')
            with path.open('rb') as data:
                with self.request('PUT', location, data=data, headers={'Content-Type': 'application/vnd.sqlite3', 'Content-Length': str(path.stat().st_size)}, timeout=(10, 180)) as response:
                    result = response.json()
            digest = hashlib.md5()
            with path.open('rb') as data:
                for chunk in iter(lambda: data.read(1024 * 1024), b''):
                    digest.update(chunk)
            if int(result.get('size', -1)) != path.stat().st_size or result.get('md5Checksum') != digest.hexdigest():
                raise BackupFailure('upload', 'Drive no confirmó tamaño y checksum del archivo subido.')
            file_id = result['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', file_id):
                raise BackupFailure('upload', 'Drive no devolvió un identificador válido del respaldo.')
            return file_id
        except BackupFailure:
            raise
        except Exception:
            raise BackupFailure('upload', 'No se pudo verificar la subida del respaldo.') from None

    def download(self, file_id, output, manifest):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', str(file_id)):
            raise BackupFailure('recovery', 'El identificador del respaldo no es válido.')
        output = Path(output)
        digest, total = hashlib.sha256(), 0
        deadline = time.monotonic() + 240
        try:
            fd = os.open(str(output), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as file:
                with self.request('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}', params={'alt': 'media', 'supportsAllDrives': 'true'}, stream=True, timeout=(10, 60)) as response:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if time.monotonic() > deadline:
                            raise BackupFailure('recovery', 'La descarga de prueba excedió su tiempo máximo.')
                        total += len(chunk)
                        if total > manifest['size_bytes']:
                            raise BackupFailure('recovery', 'El respaldo descargado supera el tamaño esperado.')
                        digest.update(chunk)
                        file.write(chunk)
            if total != manifest['size_bytes'] or digest.hexdigest() != manifest['sha256']:
                raise BackupFailure('recovery', 'El respaldo descargado no coincide con el SHA-256 o tamaño originales.')
        except BackupFailure:
            raise
        except Exception:
            raise BackupFailure('recovery', 'No se pudo descargar y verificar el respaldo de Drive.') from None


def _database_info(db):
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise BackupFailure('recovery', 'La base recuperada no pasó la comprobación de integridad.')
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}
    return schema, counts


def recovery_probe(downloaded, manifest, workspace):
    """Restaura únicamente en un directorio temporal NUEVO, nunca en source/DB_PATH."""
    downloaded = Path(downloaded).resolve()
    if str(downloaded) == str(Path(manifest['source']).resolve()):
        raise BackupFailure('recovery', 'La prueba no puede usar la base activa como archivo de recuperación.')
    digest = hashlib.sha256()
    with downloaded.open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != manifest['sha256'] or downloaded.stat().st_size != manifest['size_bytes']:
        raise BackupFailure('recovery', 'La copia de prueba no coincide con el respaldo verificado.')
    deadline = time.monotonic() + 120
    def progress(*args):
        if time.monotonic() > deadline:
            raise BackupFailure('recovery', 'La restauración de prueba excedió su tiempo máximo.')
    with tempfile.TemporaryDirectory(prefix='restore-', dir=workspace) as folder:
        restored = Path(folder) / 'restaurada.sqlite3'
        fd = os.open(str(restored), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        with closing(sqlite3.connect(downloaded.as_uri() + '?mode=ro', uri=True, timeout=5)) as source:
            expected_schema, expected_counts = _database_info(source)
            if manifest.get('rows') is not None and expected_counts != manifest['rows']:
                raise BackupFailure('recovery', 'Las tablas o conteos no coinciden con el manifiesto original.')
            with closing(sqlite3.connect(restored, timeout=5)) as target:
                source.backup(target, pages=256, sleep=0.05, progress=progress)
                target.execute('PRAGMA query_only=ON')
                actual_schema, actual_counts = _database_info(target)
                if actual_schema != expected_schema or actual_counts != expected_counts:
                    raise BackupFailure('recovery', 'La restauración no conservó el esquema y los conteos del respaldo.')
    return True
