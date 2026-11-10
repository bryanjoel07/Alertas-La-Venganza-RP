"""Staff feedback; ticket ownership and duplicate checks share one SQLite transaction."""
from contextlib import contextmanager
import json
import sqlite3
import time


class FeedbackStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS lv_feedback(
                    id INTEGER PRIMARY KEY, owner INTEGER NOT NULL, staff INTEGER,
                    ticket INTEGER UNIQUE, source TEXT NOT NULL, score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
                    comment TEXT NOT NULL, topic TEXT NOT NULL, visibility TEXT NOT NULL,
                    created INTEGER NOT NULL, hidden_at INTEGER, hidden_by INTEGER, hidden_reason TEXT,
                    response TEXT, response_by INTEGER, response_at INTEGER,
                    message INTEGER UNIQUE, publish_state TEXT NOT NULL DEFAULT 'pending');
                CREATE INDEX IF NOT EXISTS lv_feedback_owner ON lv_feedback(owner,created DESC);
                CREATE TABLE IF NOT EXISTS lv_feedback_events(
                    id INTEGER PRIMARY KEY, feedback INTEGER NOT NULL, actor INTEGER NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS lv_feedback_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            ''')
            # Prior ticket opinions were explicitly promised private. Never publish them.
            for row in db.execute('SELECT * FROM lv_tickets WHERE rating BETWEEN 1 AND 5').fetchall():
                if json.loads(row['form']).get('selftest'):
                    continue
                db.execute('''INSERT OR IGNORE INTO lv_feedback(owner,staff,ticket,source,score,comment,topic,visibility,created,publish_state)
                    VALUES (?,?,?,'ticket',?,?,'Atención en ticket','private',?,'private')''',
                    (row['owner'], row['assignee'], row['id'], row['rating'], row['rating_comment'] or '', row['closed'] or row['updated']))

    def config(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT INTO lv_feedback_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
            row = db.execute('SELECT value FROM lv_feedback_config WHERE key=?', (key,)).fetchone()
            return row[0] if row else ''

    @staticmethod
    def event(db, rid, actor, action, detail=''):
        db.execute('INSERT INTO lv_feedback_events(feedback,actor,action,detail,created) VALUES (?,?,?,?,?)',
                   (rid, actor, action, detail, int(time.time())))

    def get(self, rid):
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_feedback WHERE id=?', (rid,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def ticket_row(db, rid, owner, unrated=True):
        row = db.execute('SELECT * FROM lv_tickets WHERE id=?', (rid,)).fetchone()
        if not row or row['owner'] != owner or row['status'] != 'cerrado' or json.loads(row['form']).get('selftest'):
            raise ValueError('Solo puedes valorar tus tickets cuando estén cerrados.')
        if row['assignee'] == owner:
            raise ValueError('No puedes valorar un ticket que atendiste tú mismo, bro.')
        if unrated and (row['rating'] is not None or db.execute('SELECT 1 FROM lv_feedback WHERE ticket=?', (rid,)).fetchone()):
            raise ValueError('Ya dejaste tu opinión en este ticket. Gracias, bro.')
        return dict(row)

    def ticket(self, rid, owner):
        with self.db() as db:
            return self.ticket_row(db, rid, owner)

    def tickets(self, owner):
        with self.db() as db:
            rows = db.execute("SELECT * FROM lv_tickets WHERE owner=? AND status='cerrado' AND rating IS NULL ORDER BY closed DESC,id DESC", (owner,)).fetchall()
            return [dict(r) for r in rows if not json.loads(r['form']).get('selftest') and r['assignee'] != owner]

    def save(self, owner, score, comment, visibility, *, ticket=None, staff=None, topic='', now=None):
        stamp = int(time.time()) if now is None else now
        if type(score) is not int or score not in range(1, 6):
            raise ValueError('Elige de 1 a 5 estrellas, bro.')
        if visibility not in ('public', 'private'):
            raise ValueError('Elige dónde quieres que se vea tu opinión.')
        comment, topic = comment.strip(), topic.strip()
        if len(comment) > 1000 or len(topic) > 160:
            raise ValueError('Ese texto está demasiado largo.')
        with self.db() as db:
            if ticket is not None:
                row = self.ticket_row(db, ticket, owner)
                staff, topic = row['assignee'], 'Atención en ticket'
                if row['department'] == 'staff':
                    visibility = 'private'
            else:
                if not staff or staff == owner:
                    raise ValueError('Elige a quien te atendió; no puedes valorarte tú mismo.')
                if len(topic) < 3:
                    raise ValueError('Cuéntanos con qué te ayudaron.')
                recent = db.execute("SELECT MAX(created) FROM lv_feedback WHERE owner=? AND source='outside'", (owner,)).fetchone()[0]
                if recent is not None and stamp - recent < 86400:
                    raise ValueError(f'Ya dejaste una opinión fuera de tickets hoy. Puedes enviar otra <t:{recent + 86400}:R>.')
            cur = db.execute('''INSERT INTO lv_feedback(owner,staff,ticket,source,score,comment,topic,visibility,created,publish_state)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', (owner, staff, ticket, 'ticket' if ticket is not None else 'outside',
                score, comment, topic, visibility, stamp, 'pending' if visibility == 'public' else 'private'))
            rid = cur.lastrowid
            if ticket is not None:
                db.execute('UPDATE lv_tickets SET rating=?,rating_comment=? WHERE id=?', (score, comment, ticket))
                db.execute("INSERT INTO lv_ticket_events(ticket,actor,action,detail,created) VALUES (?,?,'valorar',?,?)", (ticket, owner, str(score), stamp))
            self.event(db, rid, owner, 'enviar', visibility)
            return rid

    def rows(self, *, owner=None, staff=None, public=False, days=None, pending=False, limit=25, offset=0):
        where, args = [], []
        for column, value in (('owner', owner), ('staff', staff)):
            if value is not None:
                where.append(column + '=?'); args.append(value)
        if owner is None or public or pending:
            where.append('hidden_at IS NULL')
        if public or pending:
            where.append("visibility='public'")
        if days is not None:
            where.append('created>=?'); args.append(int(time.time()) - days * 86400)
        if pending:
            where.append("publish_state IN ('pending','sending')")
        sql = 'SELECT * FROM lv_feedback' + (' WHERE ' + ' AND '.join(where) if where else '')
        with self.db() as db:
            return [dict(r) for r in db.execute(sql + ' ORDER BY created DESC,id DESC LIMIT ? OFFSET ?', (*args, limit, offset))]

    def summary(self, *, public=True, staff=None, days=None):
        where, args = ['hidden_at IS NULL'], []
        if public:
            where.append("visibility='public'")
        if staff is not None:
            where.append('staff=?'); args.append(staff)
        if days is not None:
            where.append('created>=?'); args.append(int(time.time()) - days * 86400)
        with self.db() as db:
            rows = db.execute('SELECT score,COUNT(*) AS n FROM lv_feedback WHERE ' + ' AND '.join(where) + ' GROUP BY score', args).fetchall()
            counts = {r['score']: r['n'] for r in rows}
            total = sum(counts.values())
            return dict(total=total, average=sum(s*n for s,n in counts.items())/total if total else 0, counts=counts)

    def respond(self, rid, actor, text, admin=False):
        text = text.strip()
        if not text or len(text) > 1000:
            raise ValueError('Escribe una respuesta de hasta 1000 letras.')
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_feedback WHERE id=?', (rid,)).fetchone()
            if not row or row['hidden_at'] or row['visibility'] != 'public' or actor == row['owner'] or not (admin or actor == row['staff']):
                raise ValueError('Solo quien atendió al jugador o administración puede responder una opinión pública.')
            if row['response']:
                raise ValueError('Esta opinión ya tiene una respuesta.')
            db.execute("UPDATE lv_feedback SET response=?,response_by=?,response_at=?,publish_state='pending' WHERE id=?", (text, actor, int(time.time()), rid))
            self.event(db, rid, actor, 'responder', text)

    def hide(self, rid, actor, reason, admin=False):
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_feedback WHERE id=?', (rid,)).fetchone()
            if not row or not (row['owner'] == actor or admin):
                raise ValueError('Solo puedes retirar tus propias opiniones.')
            if not reason.strip():
                raise ValueError('Indica por qué se retira la opinión.')
            if not row['hidden_at']:
                db.execute("UPDATE lv_feedback SET hidden_at=?,hidden_by=?,hidden_reason=?,publish_state=CASE WHEN message IS NULL THEN 'withdrawn' ELSE 'removing' END WHERE id=?", (int(time.time()), actor, reason[:1000], rid))
                self.event(db, rid, actor, 'retirar', reason[:1000])

    def removals(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM lv_feedback WHERE hidden_at IS NOT NULL AND publish_state='removing' ORDER BY id LIMIT 10")]

    def publication(self, rid, state, message=None):
        with self.db() as db:
            db.execute('UPDATE lv_feedback SET publish_state=?,message=COALESCE(?,message) WHERE id=?', (state, message, rid))

    def deleted(self, message):
        with self.db() as db:
            row = db.execute('SELECT id FROM lv_feedback WHERE message=? AND hidden_at IS NULL', (message,)).fetchone()
            if row:
                db.execute("UPDATE lv_feedback SET hidden_at=?,hidden_reason='Mensaje retirado en Discord',publish_state='withdrawn' WHERE id=?", (int(time.time()), row['id']))
                self.event(db, row['id'], 0, 'mensaje_retirado')
