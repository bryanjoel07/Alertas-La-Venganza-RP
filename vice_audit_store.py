"""Durable, guild-local audit outbox and catch-up cursor.

The caller supplies sanitized embed data. This store never accesses Discord and
never advances the historical cursor until the corresponding item is committed.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class AuditStore:
    def __init__(self, path):
        self.path = Path(path)

    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.db()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_outbox (
                key TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                sent_fingerprint TEXT,
                message_id TEXT,
                batch_key TEXT,
                attempted_at TEXT,
                event_time TEXT NOT NULL,
                event_type TEXT NOT NULL,
                source_id TEXT,
                historical INTEGER NOT NULL DEFAULT 0
            )''')
            db.execute('''CREATE INDEX IF NOT EXISTS vice_audit_outbox_order
                          ON vice_audit_outbox(event_time, key)''')
            db.execute('''CREATE INDEX IF NOT EXISTS vice_audit_outbox_batch
                          ON vice_audit_outbox(batch_key)''')
            db.execute('''CREATE INDEX IF NOT EXISTS vice_audit_outbox_message
                          ON vice_audit_outbox(message_id)''')
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_state (
                key TEXT PRIMARY KEY, value_json TEXT NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS vice_audit_replacements (
                version TEXT PRIMARY KEY,
                stage TEXT NOT NULL,
                originals_json TEXT NOT NULL,
                message_ids_json TEXT NOT NULL,
                deleted_ids_json TEXT NOT NULL DEFAULT '[]',
                reset_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )''')

    def get(self, key):
        with closing(self.db()) as db:
            row = db.execute('SELECT * FROM vice_audit_outbox WHERE key=?', (str(key),)).fetchone()
            return dict(row) if row else None

    def state(self, key, default=None):
        with closing(self.db()) as db:
            row = db.execute('SELECT value_json FROM vice_audit_state WHERE key=?',
                             (str(key),)).fetchone()
            return json.loads(row['value_json']) if row else default

    def set_state(self, key, value):
        payload = _json(value)
        with closing(self.db()) as db, db:
            db.execute('''INSERT INTO vice_audit_state(key,value_json) VALUES (?,?)
                          ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json''',
                       (str(key), payload))

    def enqueue(self, key, embed_dict, event_type, event_time, source_id=None,
                historical=False, cursor=None):
        payload = _json(embed_dict)
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        with closing(self.db()) as db, db:
            # The INSERT acquires the writer lock before reading/updating the cursor.
            # On conflict, the original history classification and send reservation
            # remain attached to this event, including while a merged count changes.
            db.execute('''INSERT INTO vice_audit_outbox
                (key,payload_json,fingerprint,event_time,event_type,source_id,historical)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    fingerprint=excluded.fingerprint,
                    event_time=excluded.event_time,
                    event_type=excluded.event_type,
                    source_id=COALESCE(vice_audit_outbox.source_id,excluded.source_id)''',
                (str(key), payload, digest, str(event_time), str(event_type),
                 str(source_id) if source_id is not None else None, int(bool(historical))))
            if cursor is not None:
                candidate = int(cursor)
                row = db.execute("SELECT value_json FROM vice_audit_state WHERE key='cursor'").fetchone()
                current = int(json.loads(row['value_json'])) if row else 0
                if candidate > current:
                    db.execute('''INSERT INTO vice_audit_state(key,value_json) VALUES ('cursor',?)
                        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json''',
                        (_json(candidate),))
            return dict(db.execute('SELECT * FROM vice_audit_outbox WHERE key=?',
                                   (str(key),)).fetchone())

    def pending(self, limit=20):
        with closing(self.db()) as db:
            return [dict(row) for row in db.execute('''SELECT * FROM vice_audit_outbox
                WHERE sent_fingerprint IS NULL OR sent_fingerprint != fingerprint
                ORDER BY event_time, key LIMIT ?''', (max(0, int(limit)),))]

    def reserve(self, keys, batch_key, attempted_at):
        if not batch_key or not attempted_at:
            raise ValueError('La reserva necesita identificador y hora del intento.')
        with closing(self.db()) as db, db:
            for key in keys:
                db.execute('''UPDATE vice_audit_outbox SET batch_key=?, attempted_at=?
                    WHERE key=? AND batch_key IS NULL''',
                    (str(batch_key), str(attempted_at), str(key)))
            return [dict(row) for row in db.execute('''SELECT * FROM vice_audit_outbox
                WHERE batch_key=? ORDER BY event_time,key''', (str(batch_key),))]

    def batch(self, batch_key):
        with closing(self.db()) as db:
            return [dict(row) for row in db.execute('''SELECT * FROM vice_audit_outbox
                WHERE batch_key=? ORDER BY event_time,key''', (str(batch_key),))]

    def for_message(self, message_id):
        with closing(self.db()) as db:
            return [dict(row) for row in db.execute('''SELECT * FROM vice_audit_outbox
                WHERE message_id=? ORDER BY event_time,key''', (str(message_id),))]

    def mark_sent(self, items, message_id):
        with closing(self.db()) as db, db:
            for key, expected_fingerprint in items:
                # A newer enqueue may race the Discord request. Record exactly the
                # version Discord received so the newer version remains pending.
                db.execute('''UPDATE vice_audit_outbox SET sent_fingerprint=?, message_id=?
                    WHERE key=?''',
                    (str(expected_fingerprint), str(message_id), str(key)))

    def stats(self):
        with closing(self.db()) as db:
            row = db.execute('''SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN sent_fingerprint IS NULL OR
                    sent_fingerprint != fingerprint THEN 1 ELSE 0 END),0) AS pending,
                COALESCE(SUM(CASE WHEN sent_fingerprint = fingerprint THEN 1 ELSE 0 END),0) AS sent,
                COALESCE(SUM(CASE WHEN message_id IS NOT NULL THEN 1 ELSE 0 END),0) AS published
                FROM vice_audit_outbox''').fetchone()
            return dict(row)

    @staticmethod
    def _replacement(row):
        if row is None:
            return None
        result = dict(version=row['version'], stage=row['stage'],
                      originals=json.loads(row['originals_json']),
                      message_ids=json.loads(row['message_ids_json']),
                      deleted_message_ids=json.loads(row['deleted_ids_json']),
                      recovered_messages={},
                      created_at=row['created_at'])
        result.update(json.loads(row['reset_json']))
        return result

    def replacement(self, version):
        with closing(self.db()) as db:
            return self._replacement(db.execute('''SELECT * FROM vice_audit_replacements
                WHERE version=?''', (str(version),)).fetchone())

    def prepare_replacement(self, version, keys=None):
        """Freeze only published/reserved records; retain an immutable full backup."""
        if not version:
            raise ValueError('La sustitución necesita una versión duradera.')
        selected = None if keys is None else {str(key) for key in keys}
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                  (str(version),)).fetchone()
            if existing:
                return self._replacement(existing)
            candidates = [dict(row) for row in db.execute('''SELECT * FROM vice_audit_outbox
                WHERE message_id IS NOT NULL OR batch_key IS NOT NULL
                ORDER BY event_time,key''')]
            rows = [row for row in candidates if selected is None or row['key'] in selected]
            if selected is not None:
                messages = {row['message_id'] for row in rows if row['message_id']}
                batches = {row['batch_key'] for row in rows if row['batch_key']}
                if any(row['key'] not in selected and
                       (row['message_id'] in messages or row['batch_key'] in batches)
                       for row in candidates):
                    raise ValueError('El filtro no puede dividir un mensaje o lote compartido.')
            message_ids = sorted({row['message_id'] for row in rows if row['message_id']})
            db.execute('''INSERT INTO vice_audit_replacements
                (version,stage,originals_json,message_ids_json,created_at)
                VALUES (?,'prepared',?,?,?)''',
                (str(version), _json(rows), _json(message_ids), datetime.now(timezone.utc).isoformat()))
            return self._replacement(db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                                (str(version),)).fetchone())

    def register_replacement_message(self, version, message_id, keys):
        """Register an externally verified orphan matching one complete frozen batch."""
        selected = {str(key) for key in keys}
        if not selected:
            raise ValueError('El mensaje recuperado necesita sus registros exactos.')
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                             (str(version),)).fetchone()
            if row is None or row['stage'] != 'prepared':
                raise ValueError('Sólo se registran mensajes durante la preparación.')
            originals = {item['key']: item for item in json.loads(row['originals_json'])}
            if not selected <= originals.keys():
                raise ValueError('El mensaje contiene registros fuera del conjunto congelado.')
            batches = {originals[key]['batch_key'] for key in selected}
            if len(batches) != 1 or None in batches:
                raise ValueError('Los registros no pertenecen a un único lote reservado.')
            batch = next(iter(batches))
            expected = {key for key, item in originals.items() if item['batch_key'] == batch}
            if selected != expected:
                raise ValueError('El mensaje recuperado debe representar el lote completo.')
            extra = json.loads(row['reset_json'])
            recovered = extra.setdefault('recovered_messages', {})
            existing = recovered.get(str(message_id))
            if existing is not None and set(existing) != selected:
                raise ValueError('El mensaje ya está asociado a otros registros.')
            recovered[str(message_id)] = sorted(selected)
            message_ids = set(json.loads(row['message_ids_json']))
            message_ids.add(str(message_id))
            db.execute('''UPDATE vice_audit_replacements SET message_ids_json=?,reset_json=?
                WHERE version=?''', (_json(sorted(message_ids)), _json(extra), str(version)))
            return self._replacement(db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                                (str(version),)).fetchone())

    def mark_replacement_deleted(self, version, message_id):
        """Persist cleanup acknowledgement; never expand the frozen deletion list."""
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                             (str(version),)).fetchone()
            if row is None:
                raise ValueError('La sustitución todavía no está preparada.')
            if str(message_id) not in json.loads(row['message_ids_json']):
                raise ValueError('El mensaje no pertenece al conjunto congelado.')
            deleted = set(json.loads(row['deleted_ids_json']))
            deleted.add(str(message_id))
            db.execute('UPDATE vice_audit_replacements SET deleted_ids_json=? WHERE version=?',
                       (_json(sorted(deleted)), str(version)))
            return self._replacement(db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                                (str(version),)).fetchone())

    def set_replacement_stage(self, version, stage):
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                             (str(version),)).fetchone()
            if row is None:
                raise ValueError('La sustitución todavía no está preparada.')
            current = row['stage']
            if current == stage:
                return self._replacement(row)
            if (current, stage) not in {('prepared', 'deletes_complete'), ('queue_ready', 'complete')}:
                raise ValueError('Transición de sustitución no válida.')
            if stage == 'deletes_complete':
                expected = set(json.loads(row['message_ids_json']))
                deleted = set(json.loads(row['deleted_ids_json']))
                if not expected <= deleted:
                    raise ValueError('Faltan mensajes del conjunto congelado por confirmar.')
            db.execute('UPDATE vice_audit_replacements SET stage=? WHERE version=?',
                       (str(stage), str(version)))
            return self._replacement(db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                                (str(version),)).fetchone())

    def reset_for_replacement(self, version, payloads_by_key):
        """Queue frozen records once; preserve newer merged payloads and new rows."""
        with closing(self.db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            replacement = db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                     (str(version),)).fetchone()
            if replacement is None:
                raise ValueError('La sustitución todavía no está preparada.')
            if replacement['stage'] in ('queue_ready', 'complete'):
                return self._replacement(replacement)
            if replacement['stage'] != 'deletes_complete':
                raise ValueError('Confirma primero la limpieza de los mensajes anteriores.')
            originals = json.loads(replacement['originals_json'])
            if any(row['key'] not in payloads_by_key for row in originals):
                raise ValueError('Faltan tarjetas compactas del conjunto congelado.')
            skipped = []
            for original in originals:
                key = original['key']
                current = db.execute('SELECT * FROM vice_audit_outbox WHERE key=?', (key,)).fetchone()
                if current is None:
                    raise ValueError('Falta una fila del conjunto congelado.')
                if current['fingerprint'] == original['fingerprint']:
                    payload = _json(payloads_by_key[key])
                    fingerprint = hashlib.sha256(payload.encode('utf-8')).hexdigest()
                else:
                    # An event merged while cleanup was running. Its latest payload
                    # was formatted by the new runtime; do not restore an older count.
                    payload, fingerprint = current['payload_json'], current['fingerprint']
                    skipped.append(key)
                db.execute('''UPDATE vice_audit_outbox SET payload_json=?,fingerprint=?,
                    sent_fingerprint=NULL,message_id=NULL,batch_key=NULL,attempted_at=NULL
                    WHERE key=?''', (payload, fingerprint, key))
            reset = json.loads(replacement['reset_json'])
            reset.update(reset_at=datetime.now(timezone.utc).isoformat(),
                         reset_count=len(originals), skipped_updated_keys=skipped)
            db.execute('''UPDATE vice_audit_replacements SET stage='queue_ready',reset_json=?
                WHERE version=?''', (_json(reset), str(version)))
            return self._replacement(db.execute('SELECT * FROM vice_audit_replacements WHERE version=?',
                                                (str(version),)).fetchone())
