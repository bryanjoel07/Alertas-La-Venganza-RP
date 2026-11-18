"""Durable, guild-local audit outbox and catch-up cursor.

The caller supplies sanitized embed data. This store never accesses Discord and
never advances the historical cursor until the corresponding item is committed.
"""
from contextlib import closing
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
