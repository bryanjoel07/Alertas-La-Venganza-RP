"""Weekly photo entries and votes, kept in the bot's existing SQLite backups."""
from settings_catalog import read_value
from sqlite_runtime import transaction
from contextlib import contextmanager
import json
from pathlib import Path
import time

from economy_store import SLOTS, EconomyStore
from weekly_challenges import week_bounds
from bot_settings import DEFAULT_PHOTO_REWARDS,ensure_settings_schema,photo_rewards_in,photo_week

COIN_REWARDS=DEFAULT_PHOTO_REWARDS


class PhotoStore:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def db(self, *, readonly=False):
        with transaction(self.path, readonly=readonly, foreign_keys=True, timeout=10) as db:
            yield db

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
                '''CREATE TABLE IF NOT EXISTS lv_photo_podium(
                    week TEXT NOT NULL REFERENCES lv_photo_weeks(week),place INTEGER NOT NULL CHECK(place BETWEEN 1 AND 3),
                    entry INTEGER NOT NULL REFERENCES lv_photo_entries(id),author INTEGER NOT NULL,
                    votes INTEGER NOT NULL CHECK(votes>0),coins INTEGER NOT NULL CHECK(coins>0),ledger_op TEXT UNIQUE NOT NULL,
                    PRIMARY KEY(week,place),UNIQUE(week,author),UNIQUE(week,entry))''',
            ]
            for statement in statements:
                db.execute(statement)
            ensure_settings_schema(db)
            columns = {r[1] for r in db.execute('PRAGMA table_info(lv_photo_entries)')}
            additions = {'post_mode': "TEXT NOT NULL DEFAULT 'reply'", 'caption': "TEXT NOT NULL DEFAULT ''",
                'media': 'BLOB', 'upload_key': 'TEXT', 'post_started': 'INTEGER', 'retired_control': 'INTEGER',
                'mentions': "TEXT NOT NULL DEFAULT '[]'"}
            for column, definition in additions.items():
                if column not in columns:
                    db.execute(f'ALTER TABLE lv_photo_entries ADD COLUMN {column} {definition}')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS lv_photo_upload_key ON lv_photo_entries(upload_key)')
            week_columns={r[1] for r in db.execute('PRAGMA table_info(lv_photo_weeks)')}
            if 'podium_closed' not in week_columns:
                db.execute('ALTER TABLE lv_photo_weeks ADD COLUMN podium_closed INTEGER')
            db.execute('INSERT OR IGNORE INTO lv_photo_config VALUES (?,?)', ('since', str(week_bounds(now)[1])))
            db.execute('INSERT OR IGNORE INTO lv_photo_config VALUES (?,?)', ('coins_since', str(week_bounds(now)[1])))

    def config(self, key, value=None):
        with self.db(readonly=value is None) as db:
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

    def rebind_post_image(self,entry,message,attachment,url,now=None):
        """Repair the upload-form ID mistakenly kept when Discord hid an inline file."""
        now=int(time.time()) if now is None else now
        with self.db() as db:
            row=db.execute('''SELECT e.*,w.state,w.ends FROM lv_photo_entries e
                JOIN lv_photo_weeks w ON w.week=e.week WHERE e.id=?''',(entry,)).fetchone()
            if not row or row['post_mode']!='post' or not row['upload_key'] or row['source']!=message or row['control']!=message:
                raise ValueError('La imagen no corresponde a una subida de este bot.')
            if row['attachment']==attachment:return False
            form_attachment=int(row['upload_key'].rsplit(':',1)[1])
            if row['attachment']!=form_attachment:
                raise ValueError('El archivo guardado no coincide con el fallo de subida conocido.')
            restore=False
            if not row['active'] and row['state']=='open' and row['ends']>now:
                journal=db.execute("SELECT 1 FROM sqlite_master WHERE name='bot_changes'").fetchone()
                if journal:
                    withdrawals=db.execute("SELECT before_json FROM bot_changes WHERE change_key LIKE 'operation:PHOTO_WITHDRAW:%'")
                    restore=not any(json.loads(r[0]).get('entry')==entry for r in withdrawals)
            db.execute('''UPDATE lv_photo_entries SET attachment=?,url=?,active=CASE WHEN ? THEN 1 ELSE active END,
                rendered_count=-1,rendered_closed=-1 WHERE id=?''',(attachment,url,restore,entry))
            return restore

    def upload(self, key, attachment, author, filename, url, data, caption='', now=None, mentions=()):
        now = int(time.time()) if now is None else now
        upload_key = f'{key}:{attachment}'
        with self.db() as db:
            previous = db.execute('SELECT id FROM lv_photo_entries WHERE upload_key=?', (upload_key,)).fetchone()
            if previous:
                return previous[0]
            if not read_value(db,'photo_entries','accepting'):raise ValueError('Ahora mismo no estamos recibiendo fotos nuevas, bro. La votación de las que ya están sigue abierta.')
            current_week=week_bounds(now)[0]
            limit=read_value(db,'photo_entries','weekly_limit')
            if limit and db.execute('SELECT COUNT(*) FROM lv_photo_entries WHERE author=? AND week=? AND active=1',(author,current_week)).fetchone()[0]>=limit:
                raise ValueError(f'Ya llegaste al límite de {limit} fotos de esta semana, bro.')
            if db.execute("SELECT COUNT(*) FROM lv_photo_entries WHERE author=? AND post_mode='pending'", (author,)).fetchone()[0] >= 3:
                raise ValueError('Tienes fotos pendientes de publicar. Espera un momento, bro.')
            total = db.execute('SELECT COALESCE(SUM(LENGTH(media)),0) FROM lv_photo_entries').fetchone()[0]
            if total + len(data) > 100*1024*1024:
                raise ValueError('Hay varias fotos pendientes. Inténtalo de nuevo en un momento.')
            week, _, _ = self.ensure_in(db, now)
            return db.execute('''INSERT INTO lv_photo_entries(week,source,attachment,author,filename,url,created,post_mode,media,upload_key,caption,mentions)
                VALUES (?,?,?,?,?,?,?,'pending',?,?,?,?)''', (week,key,attachment,author,filename,url,now,data,upload_key,caption,json.dumps(list(dict.fromkeys(mentions))))).lastrowid

    def stage_post(self, entry, data):
        with self.db() as db:
            db.execute("""UPDATE lv_photo_entries SET post_mode='pending',media=?,retired_control=COALESCE(retired_control,control),control=NULL
                WHERE id=? AND post_mode='reply'""", (data,entry))

    def posting(self, entry, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            row = db.execute('SELECT e.*,w.ends FROM lv_photo_entries e JOIN lv_photo_weeks w ON w.week=e.week WHERE e.id=?', (entry,)).fetchone()
            if row['upload_key'] and row['ends'] <= now:
                week, _, _ = self.ensure_in(db, now)
                db.execute('UPDATE lv_photo_entries SET week=?,created=? WHERE id=?', (week,now,entry))
            db.execute('UPDATE lv_photo_entries SET post_started=COALESCE(post_started,?) WHERE id=?', (now,entry))

    def posted(self, entry, message, attachment, url):
        with self.db() as db:
            db.execute("""UPDATE lv_photo_entries SET post_mode='post',control=?,media=NULL,url=?,
                source=CASE WHEN upload_key IS NULL THEN source ELSE ? END,
                attachment=CASE WHEN upload_key IS NULL THEN attachment ELSE ? END,
                rendered_count=-1,rendered_closed=-1 WHERE id=?""", (message,url,message,attachment,entry))

    def retired(self, entry):
        with self.db() as db:
            db.execute('UPDATE lv_photo_entries SET retired_control=NULL WHERE id=?', (entry,))

    def pending_posts(self):
        with self.db(readonly=True) as db:
            return [r[0] for r in db.execute("SELECT id FROM lv_photo_entries WHERE (post_mode='pending' AND active=1) OR retired_control IS NOT NULL")]

    @staticmethod
    def query():
        return '''SELECT e.*,w.ends,w.state AS week_state,COUNT(v.user) AS votes FROM lv_photo_entries e
            JOIN lv_photo_weeks w ON w.week=e.week LEFT JOIN lv_photo_votes v ON v.entry=e.id'''

    def entry(self, entry):
        with self.db(readonly=True) as db:
            row = db.execute(self.query() + ' WHERE e.id=? GROUP BY e.id', (entry,)).fetchone()
            return dict(row) if row else None

    def entries(self, week=None):
        with self.db(readonly=True) as db:
            query = self.query() + (' WHERE e.week=?' if week is not None else '') + ' GROUP BY e.id ORDER BY votes DESC,e.created,e.attachment,e.id'
            return [dict(r) for r in db.execute(query, (week,) if week is not None else ())]

    @classmethod
    def leaders_in(cls,db,week):
        rows=db.execute(cls.query()+''' WHERE e.week=? AND e.active=1
            GROUP BY e.id HAVING COUNT(v.user)>0 ORDER BY votes DESC,e.created,e.attachment,e.id''',(week,))
        leaders=[];authors=set()
        for row in rows:
            if row['author'] in authors:continue
            authors.add(row['author']);leaders.append(dict(row))
            if len(leaders)==3:break
        return leaders

    @staticmethod
    def podium_in(db,week):
        return [dict(r) for r in db.execute('''SELECT e.*,w.ends,w.state AS week_state,
            p.place,p.votes,p.coins,p.ledger_op FROM lv_photo_podium p
            JOIN lv_photo_entries e ON e.id=p.entry JOIN lv_photo_weeks w ON w.week=p.week
            WHERE p.week=? ORDER BY p.place''',(week,))]

    @staticmethod
    def coin_week_in(db,week):
        since=db.execute("SELECT value FROM lv_photo_config WHERE key='coins_since'").fetchone()
        return bool(since and week['starts']>=int(since[0]))

    def ranking(self,week):
        with self.db(readonly=True) as db:
            current=db.execute('SELECT * FROM lv_photo_weeks WHERE week=?',(week,)).fetchone()
            if not current:return []
            if current['podium_closed'] is not None:return self.podium_in(db,week)
            rates=photo_rewards_in(db,week)
            return [dict(row,place=n,coins=rates[n-1] if self.coin_week_in(db,current) else 0,ledger_op=None)
                for n,row in enumerate(self.leaders_in(db,week),1)]

    def reward_rates(self,week):
        with self.db(readonly=True) as db:return photo_rewards_in(db,week)

    def reward_podium(self,week,bot_id,expected=None,now=None,media=None):
        """Commit the final podium and all shop credits in one SQLite transaction."""
        now=int(time.time()) if now is None else now
        with self.db() as db:
            current=db.execute('SELECT * FROM lv_photo_weeks WHERE week=?',(week,)).fetchone()
            if not current:return []
            if current['podium_closed'] is not None:return self.podium_in(db,week)
            if current['ends']>now or current['state']=='published' or not self.coin_week_in(db,current):return []
            leaders=self.leaders_in(db,week)
            actual=[(r['id'],r['author'],r['votes']) for r in leaders]
            if expected is not None and actual!=expected:
                raise ValueError('Las fotos cambiaron mientras cerraba la semana. Se revisarán otra vez.')
            receipts=[]
            rates=photo_rewards_in(db,week)
            for place,row in enumerate(leaders,1):
                coins=rates[place-1];op=f"photo-coins:{week}:{row['author']}"
                if not EconomyStore.credit(db,row['author'],coins,op,
                    f'Fotos de la semana · Puesto {place} · {week}',bot_id):
                    previous=db.execute('SELECT user_id,amount FROM eco_ledger WHERE op=?',(op,)).fetchone()
                    if (previous['user_id'],previous['amount'])!=(row['author'],coins):
                        raise ValueError('El premio no coincide con su movimiento de monedas. Requiere revisión.')
                db.execute('INSERT INTO lv_photo_podium(week,place,entry,author,votes,coins,ledger_op) VALUES (?,?,?,?,?,?,?)',
                    (week,place,row['id'],row['author'],row['votes'],coins,op))
                receipts.append(dict(place=place,entry=row['id'],author=row['author'],votes=row['votes'],coins=coins,op=op))
            winner=leaders[0] if leaders else None
            if current['winner']!=(winner['id'] if winner else None):
                db.execute('UPDATE lv_photo_weeks SET image=NULL,filename=NULL,image_url=NULL WHERE week=?',(week,))
            db.execute("UPDATE lv_photo_weeks SET state='closed',podium_closed=?,winner=?,winning_votes=? WHERE week=?",
                (now,winner['id'] if winner else None,winner['votes'] if winner else 0,week))
            if winner and media is not None:
                db.execute('UPDATE lv_photo_weeks SET image=?,filename=?,image_url=? WHERE week=?',(*media,week))
            db.execute('INSERT INTO lv_photo_actions(week,actor,action,detail,created) VALUES (?,?,?,?,?)',
                (week,bot_id,'podio_monedas',json.dumps(receipts),now))
            if receipts:
                EconomyStore.audit(db,bot_id,f'Fotos de la semana {week}: '+', '.join(f"{r['place']}º {r['author']} +{r['coins']} monedas" for r in receipts))
            return self.podium_in(db,week)

    def reward_status(self):
        with self.db(readonly=True) as db:
            invalid=db.execute('''SELECT COUNT(*) FROM lv_photo_podium p LEFT JOIN eco_ledger l ON l.op=p.ledger_op
                WHERE l.id IS NULL OR l.user_id!=p.author OR l.amount!=p.coins''').fetchone()[0]
            if invalid:raise RuntimeError('Hay premios de Fotos que no coinciden con sus movimientos de monedas.')
            return dict(rewards=photo_rewards_in(db,photo_week()),since=int(db.execute("SELECT value FROM lv_photo_config WHERE key='coins_since'").fetchone()[0]),
                paid_positions=db.execute('SELECT COUNT(*) FROM lv_photo_podium').fetchone()[0])

    def refresh_entries(self, now):
        with self.db(readonly=True) as db:
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
            db.execute("""UPDATE lv_photo_entries SET active=0,rendered_closed=1,
                rendered_count=(SELECT COUNT(*) FROM lv_photo_votes WHERE entry=lv_photo_entries.id)
                WHERE control=? AND post_mode='post'""", (message,))
            db.execute("UPDATE lv_photo_entries SET control=NULL,rendered_count=-1 WHERE control=? AND post_mode='reply'", (message,))

    def due(self, now=None):
        now = int(time.time()) if now is None else now
        with self.db(readonly=True) as db:
            return [dict(r) for r in db.execute("SELECT * FROM lv_photo_weeks WHERE ends<=? AND state!='published' ORDER BY starts", (now,))]

    def freeze(self, week, now=None):
        now = int(time.time()) if now is None else now
        with self.db() as db:
            current = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            if not current or current['ends'] > now or current['state'] == 'published' or current['podium_closed'] is not None:
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
        with self.db(readonly=True) as db:
            row = db.execute('SELECT * FROM lv_photo_weeks WHERE week=?', (week,)).fetchone()
            return dict(row) if row else None

    def announced_winner(self, message):
        with self.db(readonly=True) as db:
            row = db.execute("SELECT * FROM lv_photo_weeks WHERE announcement=? AND state='published' AND winner IS NOT NULL", (message,)).fetchone()
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
        with self.db(readonly=True) as db:
            return [dict(r) for r in db.execute("SELECT * FROM lv_photo_weeks WHERE state='published' AND winner IS NOT NULL AND prize_sku IS NOT NULL AND prize_receipt IS NULL")]
