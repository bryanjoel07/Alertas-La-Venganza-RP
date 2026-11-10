"""Short, explicit SQLite transactions; readers never reserve the writer lock."""
from contextlib import closing, contextmanager
import logging
from pathlib import Path
import sqlite3
import time

log = logging.getLogger('LaVenganzaRP.storage')


@contextmanager
def transaction(path, *, readonly=False, foreign_keys=False, timeout=10):
    target = Path(path).resolve()
    with closing(sqlite3.connect(target.as_uri() + '?mode=ro' if readonly else target,
                                uri=readonly, timeout=timeout)) as db:
        db.row_factory = sqlite3.Row
        if foreign_keys:
            db.execute('PRAGMA foreign_keys=ON')
        if readonly:
            db.execute('PRAGMA query_only=ON')
        try:
            db.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def configure_database(path):
    """Enable concurrent readers after making a verified, non-overwriting backup.

    Keep SQLite's FULL durability. Existing backup jobs use the SQLite backup API,
    which also includes committed changes still present in the WAL file.
    """
    target = Path(path).resolve()
    with closing(sqlite3.connect(target, timeout=10)) as db:
        before = db.execute('PRAGMA journal_mode').fetchone()[0].lower()
        populated = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    backup = None
    if before != 'wal' and populated:
        from backup import snapshot
        from backup_meta import atomic_json
        backup = snapshot(target, target.parent / 'backups' / f'before-wal-{time.time_ns()}.sqlite3')
        atomic_json(Path(backup['file'] + '.manifest.json'), backup)
        log.info('STORAGE before_wal_backup_verified integrity=%s bytes=%s sha256=%s',
                 backup['integrity'], backup['size_bytes'], backup['sha256'])
    with closing(sqlite3.connect(target, timeout=10)) as db:
        mode = db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()
        if mode != 'wal':
            raise RuntimeError('SQLite no confirmó WAL; no se iniciarán los sistemas.')
        synchronous = db.execute('PRAGMA synchronous').fetchone()[0]
        if synchronous != 2:
            raise RuntimeError('SQLite no confirmó durabilidad FULL; no se iniciarán los sistemas.')
    log.info('STORAGE ready journal_mode=%s synchronous=FULL migrated=%s backup_verified=%s',
             mode, before != mode, backup is not None)
    return {'journal_mode': mode, 'synchronous': synchronous, 'backup': backup}
