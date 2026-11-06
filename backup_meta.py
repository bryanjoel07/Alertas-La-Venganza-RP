"""Constancia local de respaldos verificados; nunca guarda autenticación de Drive."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile


def status_path(source):
    path = Path(os.environ['BACKUP_STATUS_PATH']) if os.getenv('BACKUP_STATUS_PATH') else Path(source).resolve().parent / 'backup-status.json'
    if not path.is_absolute():
        raise ValueError('BACKUP_STATUS_PATH debe ser una ruta absoluta.')
    if path.resolve() == Path(source).resolve():
        raise ValueError('El registro de respaldos no puede reemplazar la base activa.')
    return path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.backup-status-', suffix='.tmp', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_backup(source, manifest):
    fields = ('file', 'sha256', 'integrity', 'created_at', 'size_bytes', 'drive_state', 'drive_file_id', 'rows', 'restore_state', 'restore_checked_at')
    value = {key: manifest[key] for key in fields if key in manifest}
    value['source'] = str(Path(source).resolve())
    atomic_json(status_path(source), value)


def read_backup(source):
    try:
        path = status_path(source)
        if not path.is_file():
            return dict(known=False, reason='No hay respaldo verificado registrado.')
        if path.stat().st_size > 65536:
            raise ValueError('Registro inválido')
        data = json.loads(path.read_text())
        created = datetime.fromisoformat(data['created_at'])
        if created.tzinfo is None or Path(data['source']).resolve() != Path(source).resolve():
            raise ValueError('Origen o fecha no válidos')
        if data.get('integrity') != 'ok' or not re.fullmatch('[0-9a-f]{64}', data.get('sha256', '')):
            raise ValueError('No hay verificación de integridad')
        local_file = Path(data['file'])
        available = local_file.is_file() and local_file.stat().st_size == data['size_bytes']
        drive = data.get('drive_state', 'not_requested')
        if drive not in ('not_requested', 'pending', 'verified', 'failed'):
            raise ValueError('Estado inválido')
        restore = data.get('restore_state', 'not_tested')
        if restore not in ('not_tested', 'verified', 'failed'):
            restore = 'not_tested'
        checked_at = None
        if data.get('restore_checked_at'):
            parsed = datetime.fromisoformat(data['restore_checked_at'])
            if parsed.tzinfo is not None:
                checked_at = int(parsed.timestamp())
        if restore == 'verified' and checked_at is None:
            restore = 'not_tested'
        return dict(known=True, created_at=int(created.timestamp()), filename=local_file.name, local_available=available, drive_state=drive, restore_state=restore, restore_checked_at=checked_at)
    except (OSError, ValueError, KeyError, TypeError):
        return dict(known=False, reason='No se pudo validar el registro de respaldos de esta base.')
