"""Weekly photo entries and votes, kept in the bot's existing SQLite backups."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

from economy_store import SLOTS
from weekly_challenges import week_bounds


class PhotoStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            statements = [
                'CREATE TABLE IF NOT EXISTS lv_photo_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)',
                '''CREATE TABLE IF NOT EXISTS lv_photo_weeks(
                    week TEXT PRIMARY KEY,starts INTEGER NOT NULL,ends INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'open',
                    winner INTEGER,winning_votes INTEGER NOT NULL DEFAULT 0,announcement INTEGER,publishing INTEGER,
                    image BLOB,filename TEXT,image_url TEXT,prize_sku TEXT,prize_name TEXT,prize_actor INTEGER,
                    prize_receipt TEXT,prize_error TEXT)''',
                '''CREATE TABLE IF NOT EXISTS lv_photo_entries(
                    id INTEGER PRIMARY KEY,week TEXT NOT NULL REFERENCES lv_photo_weeks(week),source INTEGER NOT NULL,
                    attachment INTEGER NOT NULL,author INTEGER NOT NULL,filename TEXT NOT NULL,url TEXT NOT NULL,
                    created INTEGER NOT NULL,active INTEGER NOT NULL DEFAULT 1,control INTEGER UNIQUE,notice_started INTEGER,
                    rendered_count INTEGER NOT NULL DEFAULT -1,rendered_closed INTEGER NOT NULL DEFAULT -1,
                    UNIQUE(source,attachment))''',
                'CREATE INDEX IF NOT EXISTS lv_photo_week_entries ON lv_photo_entries(week,active,created,id)',
                '''CREATE TABLE IF NOT EXISTS lv_photo_votes(
                    entry INTEGER NOT NULL REFERENCES lv_photo_entries(id),user INTEGER NOT NULL,created INTEGER NOT NULL,
                    PRIMARY KEY(entry,user))''',
                '''CREATE TABLE IF NOT EXISTS lv_photo_actions(
                    id INTEGER PRIMARY KEY,week TEXT NOT NULL,actor INTEGER NOT NULL,action TEXT NOT NULL,
                    detail TEXT NOT NULL,created INTEGER NOT NULL)''',
            ]
            for statement in statements:
                db.execute(statement)
            db.execute('INSERT OR IGNORE INTO lv_photo_config VALUES (?,?)', ('since', str(week_bounds(now)[1])))

    def config(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT INTO lv_photo_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
            row = db.execute('SELECT value FROM lv_photo_config WHERE key=?', (key,)).fetchone()
            return row[0] if row else ''

    @staticmethod
    def ensure_in(db, stamp):
        week, start, end = week_bounds(stamp)
        db.execute('INSERT OR IGNORE INTO lv_photo_weeks(week,starts,ends) VALUES (?,?,?)', (week, start, end))
        return week, start, end

    def current(self, now=None):
        with self.db() as db:
            week, _, _ = self.ensure_in(db, int(time.time()) if now is None else now)
            return dict(db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone())

    def register(self, source, attachment, author, filename, url, created, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            since = int(db.execute("SELECT value FROM lv_photo_config WHERE key='since'").fetchone()[0])
            if created < since or created > now + 5:
                return None
            week, _, end = self.ensure_in(db, created)
            state = db.execute('SELECT state FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()[0]
            if now >= end or state != 'open':
                return None
            db.execute('''INSERT OR IGNORE INTO lv_photo_entries(week,source,attachment,author,filename,url,created)
                VALUES (?,?,?,?,?,?,?)''', (week, source, attachment, author, filename, url, created))
            db.execute('UPDATE lv_photo_entries SET url=? WHERE source=? AND attachment=?', (url, source, attachment))
            return db.execute('SELECT id FROM lv_photo_entries WHERE source=? AND attachment=?', (source, attachment)).fetchone()[0]

    def image_url(self, entry, url):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET url=? WHERE id=?', (url, entry))

    @staticmethod
    def query():
        return '''SELECT e.*,w.ends,w.state AS week_state,COUNT(v.user) AS votes FROM lv_photo_entries e
            JOIN lv_photo_weeks w ON w.week=e.week LEFT JOIN lv_photo_votes v ON v.entry=e.id'''

    def entry(self, entry):
        with self.db() as db:
            row = db.execute(self.query() + ' WHERE e.id=? GROUP BY e.id', (entry,)).fetchone()
            return dict(row) if row else None

    def entries(self, week=None):
        with self.db() as db:
            query = self.query() + (' WHERE e.week=?' if week is not None else '') + ' GROUP BY e.id ORDER BY votes DESC,e.created,e.attachment,e.id'
            return [dict(r) for r in db.execute(query, (week,) if week is not None else ())]

    def refresh_entries(self, now):
        with self.db() as db:
            return [dict(r) for r in db.execute(self.query() + " WHERE (w.state='open' AND w.ends>?) OR e.rendered_closed!=1 GROUP BY e.id", (now,))]

    def control_started(self, entry, now):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET notice_started=COALESCE(notice_started,?) WHERE id=?', (now, entry))

    def control(self, entry, message):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET control=? WHERE id=?', (message, entry))

    def rendered(self, entry, count, closed):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET rendered_count=?,rendered_closed=? WHERE id=?', (count, int(closed), entry))

    def vote(self, entry, user, add=True, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            row = db.execute('''SELECT e.*,w.state,w.ends FROM lv_photo_entries e
                JOIN lv_photo_weeks w ON w.week=e.week WHERE e.id=?''', (entry,)).fetchone()
            if not row or not row['active']:
                raise ValueError('Esta foto ya no participa.')
            if row['state'] != 'open' or now >= row['ends']:
                raise ValueError('La votación de esta semana ya terminó.')
            if row['author'] == user:
                raise ValueError('Vota por las fotos de los demás, bro. Tu propia foto no cuenta.')
            if add:
                changed = db.execute('INSERT OR IGNORE INTO lv_photo_votes VALUES (?,?,?)', (entry, user, now)).rowcount
            else:
                changed = db.execute('DELETE FROM lv_photo_votes WHERE entry=? AND user=?', (entry, user)).rowcount
            return bool(changed)

    def sync_source(self, source, attachment_ids):
        with self.db() as db:
            for row in db.execute('SELECT id,attachment FROM lv_photo_entries WHERE source=? AND active=1', (source,)):
                if row['attachment'] not in attachment_ids:
                    db.execute('UPDATE lv_photo_entries SET active=0 WHERE id=?', (row['id'],))

    def deleted(self, message):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET active=0 WHERE source=?', (message,))
            db.execute('UPDATE lv_photo_entries SET control=NULL,rendered_count=-1 WHERE control=?', (message,))

    def due(self, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM lv_photo_weeks WHERE ends<=? AND state!='published' ORDER BY starts", (now,))]

    def freeze(self, week, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            current = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            if not current or current['ends'] > now or current['state'] == 'published':
                return dict(current) if current else None
            winner = db.execute('''SELECT e.id,COUNT(v.user) AS votes FROM lv_photo_entries e
                JOIN lv_photo_votes v ON v.entry=e.id WHERE e.week=? AND e.active=1
                GROUP BY e.id ORDER BY votes DESC,e.created,e.attachment,e.id LIMIT 1''', (week,)).fetchone()
            if current['winner'] != (winner['id'] if winner else None):
                db.execute('UPDATE lv_photo_weeks SET image=NULL,filename=NULL,image_url=NULL WHERE week=?', (week,))
            db.execute("UPDATE lv_photo_weeks SET state='closed',winner=?,winning_votes=? WHERE week=?",
                (winner['id'] if winner else None, winner['votes'] if winner else 0, week))
            return dict(db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone())

    def stage(self, week, image, filename, url):
        with self.db() as db:
            db.execute('UPDATE lv_photo_weeks SET image=?,filename=?,image_url=? WHERE week=?', (image, filename, url, week))

    def publishing(self, week, now):
        with self.db() as db:
            db.execute('UPDATE lv_photo_weeks SET publishing=COALESCE(publishing,?) WHERE week=?', (now, week))

    def published(self, week, message, url=None):
        with self.db() as db:
            db.execute("UPDATE lv_photo_weeks SET state='published',announcement=?,image=NULL,image_url=COALESCE(?,image_url) WHERE week=?", (message, url, week))

    def week(self, week):
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            return dict(row) if row else None

    def prize(self, week, sku, actor, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            if not row or row['prize_receipt']:
                raise ValueError('Esa semana no existe o el premio ya se entregó.')
            item = db.execute('SELECT * FROM eco_products WHERE sku=? AND active=1', (sku,)).fetchone() if sku else None
            if sku and (not item or item['kind'] not in SLOTS):
                raise ValueError('Elige un artículo de perfil que esté activo en la tienda.')
            db.execute('UPDATE lv_photo_weeks SET prize_sku=?,prize_name=?,prize_actor=?,prize_error=NULL WHERE week=?',
                (sku, item['name'] if item else None, actor, week))
            db.execute('INSERT INTO lv_photo_actions(week,actor,action,detail,created) VALUES (?,?,?,?,?)',
                (week, actor, 'premio', json.dumps({'before': row['prize_sku'], 'after': sku}), now))

    def award(self, week, bot_id, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            row = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            if not row or not row['winner'] or not row['prize_sku'] or row['state'] != 'published' or row['prize_receipt']:
                return row['prize_receipt'] if row else None
            owner = db.execute('SELECT author FROM lv_photo_entries WHERE id=?', (row['winner'],)).fetchone()[0]
            item = db.execute('SELECT * FROM eco_products WHERE sku=? AND active=1', (row['prize_sku'],)).fetchone()
            if not item or item['kind'] not in SLOTS or (item['stock'] is not None and item['stock'] <= 0):
                raise ValueError('El premio ya no está disponible. El staff puede elegir otro.')
            if db.execute("SELECT 1 FROM eco_purchases WHERE recipient=? AND sku=? AND status!='refunded' AND (expires IS NULL OR expires>?)", (owner, item['sku'], now)).fetchone():
                raise ValueError('El ganador ya tiene ese artículo. El staff puede elegir otro premio.')
            receipt = f"photo:{week}:{owner}"
            db.execute('UPDATE eco_products SET serial=serial+1,stock=CASE WHEN stock IS NULL THEN NULL ELSE stock-1 END WHERE sku=?', (item['sku'],))
            db.execute('''INSERT INTO eco_purchases(id,quote,buyer,recipient,sku,price,name,kind,payload,duration,edition,status,created)
                VALUES (?,?,?,?,?,0,?,?,?,?,?,'delivered',?)''',
                (receipt, receipt, bot_id, owner, item['sku'], item['name'], item['kind'], item['payload'], item['duration'], item['serial']+1, now))
            db.execute('UPDATE lv_photo_weeks SET prize_receipt=?,prize_error=NULL WHERE week=?', (receipt, week))
            db.execute('INSERT INTO lv_photo_actions(week,actor,action,detail,created) VALUES (?,?,?,?,?)',
                (week, row['prize_actor'], 'entregar_premio', receipt, now))
            return receipt

    def prize_error(self, week, error):
        with self.db() as db:
            db.execute('UPDATE lv_photo_weeks SET prize_error=? WHERE week=?', (str(error), week))

    def pending_prizes(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM lv_photo_weeks WHERE state='published' AND winner IS NOT NULL AND prize_sku IS NOT NULL AND prize_receipt IS NULL")]
