"""Atomic community suggestions, votes and decisions in the existing SQLite backup."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import time
import unicodedata

STATES={'pendiente':('🕓','Pendiente'),'aceptada':('✅','Aceptada'),
        'proceso':('🛠️','En proceso'),'hecha':('🎉','Hecha'),'rechazada':('❌','Rechazada')}
CLOSED={'hecha','rechazada'}


class SuggestionStore:
 def __init__(self,path):self.path=Path(path)
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
  db.execute('PRAGMA foreign_keys=ON')
  try:
   db.execute('BEGIN IMMEDIATE');yield db;db.commit()
  except Exception:db.rollback();raise
  finally:db.close()
 def initialize(self):
  with self.db() as db:
   db.execute('''CREATE TABLE IF NOT EXISTS lv_suggestions(
     id INTEGER PRIMARY KEY,request TEXT NOT NULL UNIQUE,owner INTEGER NOT NULL,
     title TEXT NOT NULL,description TEXT NOT NULL,benefit TEXT NOT NULL,fingerprint TEXT NOT NULL,
     status TEXT NOT NULL DEFAULT 'pendiente',reason TEXT NOT NULL DEFAULT '',decided_by INTEGER,
     created INTEGER NOT NULL,updated INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 0,
     status_version INTEGER NOT NULL DEFAULT 0,rendered INTEGER NOT NULL DEFAULT -1,
     channel INTEGER,message INTEGER UNIQUE,publication TEXT NOT NULL DEFAULT 'pending',lease_until INTEGER NOT NULL DEFAULT 0)''')
   db.execute('''CREATE TABLE IF NOT EXISTS lv_suggestion_votes(
     suggestion INTEGER NOT NULL REFERENCES lv_suggestions(id),user INTEGER NOT NULL,
     value INTEGER NOT NULL CHECK(value IN (-1,1)),updated INTEGER NOT NULL,PRIMARY KEY(suggestion,user))''')
   db.execute('''CREATE TABLE IF NOT EXISTS lv_suggestion_events(
     id INTEGER PRIMARY KEY,suggestion INTEGER NOT NULL REFERENCES lv_suggestions(id),actor INTEGER NOT NULL,
     previous TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,created INTEGER NOT NULL)''')
   db.execute('CREATE TABLE IF NOT EXISTS lv_suggestion_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
   db.execute('CREATE INDEX IF NOT EXISTS lv_suggestion_owner ON lv_suggestions(owner,id DESC)')
 def config(self,key,value=None):
  with self.db() as db:
   if value is not None:db.execute('INSERT INTO lv_suggestion_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
   row=db.execute('SELECT value FROM lv_suggestion_config WHERE key=?',(key,)).fetchone()
   return row[0] if row else ''
 def create(self,request,owner,title,description,benefit='',now=None):
  title,description,benefit=(v.strip() for v in (title,description,benefit))
  if not 3<=len(title)<=100 or not 10<=len(description)<=2000 or len(benefit)>700:
   raise ValueError('Ponle un título y cuéntanos bien tu idea, bro.')
  stamp=int(time.time()) if now is None else now
  normalized=' '.join(unicodedata.normalize('NFKC',title+' '+description).casefold().split())
  fingerprint=hashlib.sha256(normalized.encode()).hexdigest()
  with self.db() as db:
   old=db.execute('SELECT id,owner FROM lv_suggestions WHERE request=?',(request,)).fetchone()
   if old:
    if old['owner']!=owner:raise ValueError('Esa solicitud pertenece a otro jugador.')
    return old['id']
   duplicate=db.execute("SELECT id FROM lv_suggestions WHERE owner=? AND fingerprint=? AND publication!='missing' AND status NOT IN ('hecha','rechazada')",(owner,fingerprint)).fetchone()
   if duplicate:raise ValueError(f"Ya enviaste esa idea, bro. Es la sugerencia #{duplicate['id']}.")
   recent=db.execute('SELECT MAX(created) FROM lv_suggestions WHERE owner=?',(owner,)).fetchone()[0]
   if recent is not None and stamp-recent<60:raise ValueError('Dale un minuto antes de enviar otra idea, bro.')
   return db.execute('INSERT INTO lv_suggestions(request,owner,title,description,benefit,fingerprint,created,updated) VALUES (?,?,?,?,?,?,?,?)',
     (request,owner,title,description,benefit,fingerprint,stamp,stamp)).lastrowid
 def get(self,rid):
  with self.db() as db:
   row=db.execute('''SELECT s.*,
     (SELECT COUNT(*) FROM lv_suggestion_votes WHERE suggestion=s.id AND value=1) AS up,
     (SELECT COUNT(*) FROM lv_suggestion_votes WHERE suggestion=s.id AND value=-1) AS down
     FROM lv_suggestions s WHERE s.id=?''',(rid,)).fetchone()
   return dict(row) if row else None
 def list(self,owner=None,limit=10,offset=0):
  with self.db() as db:
   where="publication!='missing'"+(' AND owner=?' if owner is not None else '')
   args=([owner] if owner is not None else [])+[limit,offset]
   return [dict(r) for r in db.execute('SELECT * FROM lv_suggestions WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',args)]
 def pending(self):
  with self.db() as db:
   return [r[0] for r in db.execute("SELECT id FROM lv_suggestions WHERE publication IN ('pending','publishing') OR (publication='published' AND revision!=rendered) ORDER BY id")]
 def acquire(self,rid,now=None):
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   return bool(db.execute("UPDATE lv_suggestions SET lease_until=?,publication='publishing' WHERE id=? AND publication IN ('pending','publishing') AND lease_until<=?",(stamp+180,rid,stamp)).rowcount)
 def bind(self,rid,channel,message):
  with self.db() as db:
   row=db.execute('SELECT publication,message FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row or row['publication']=='missing':raise ValueError('Esa sugerencia ya no está disponible.')
   if row['message'] and row['message']!=message:raise ValueError('La sugerencia ya tiene otra publicación. Se conservarán ambas para revisión.')
   db.execute("UPDATE lv_suggestions SET channel=?,message=?,publication='published',lease_until=0 WHERE id=?",(channel,message,rid))
 def acknowledge(self,rid,revision):
  with self.db() as db:
   return bool(db.execute("UPDATE lv_suggestions SET rendered=? WHERE id=? AND revision=? AND publication='published'",(revision,rid,revision)).rowcount)
 def vote(self,rid,user,value):
  if value not in (-1,0,1):raise ValueError('Elige un voto válido.')
  with self.db() as db:
   row=db.execute('SELECT status,publication FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row or row['publication']!='published':raise ValueError('Esa idea ya no está disponible para votar.')
   if row['status'] in CLOSED:raise ValueError('Esta idea ya tiene una decisión final y sus votos están cerrados.')
   old=db.execute('SELECT value FROM lv_suggestion_votes WHERE suggestion=? AND user=?',(rid,user)).fetchone()
   if (old[0] if old else 0)==value:return False
   if value:db.execute('INSERT INTO lv_suggestion_votes VALUES (?,?,?,?) ON CONFLICT(suggestion,user) DO UPDATE SET value=excluded.value,updated=excluded.updated',(rid,user,value,int(time.time())))
   else:db.execute('DELETE FROM lv_suggestion_votes WHERE suggestion=? AND user=?',(rid,user))
   db.execute('UPDATE lv_suggestions SET revision=revision+1,updated=? WHERE id=?',(int(time.time()),rid))
   return True
 def decide(self,rid,status,actor,reason,expected):
  reason=reason.strip()
  if status not in STATES or not 3<=len(reason)<=1000:raise ValueError('Elige el estado y deja una explicación breve.')
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row or row['publication']!='published':raise ValueError('Esa sugerencia ya no está disponible.')
   if row['status_version']!=expected:raise ValueError('Otra persona ya cambió el estado. Abre el botón Estado otra vez para ver cómo quedó.')
   if row['status']==status and row['reason']==reason:return False
   stamp=int(time.time())
   db.execute('INSERT INTO lv_suggestion_events(suggestion,actor,previous,status,reason,created) VALUES (?,?,?,?,?,?)',(rid,actor,row['status'],status,reason,stamp))
   db.execute('UPDATE lv_suggestions SET status=?,reason=?,decided_by=?,updated=?,revision=revision+1,status_version=status_version+1 WHERE id=?',(status,reason,actor,stamp,rid))
   return True
 def events(self,rid):
  with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM lv_suggestion_events WHERE suggestion=? ORDER BY id',(rid,))]
 def missing(self,channel,messages=None):
  with self.db() as db:
   if messages is None:db.execute("UPDATE lv_suggestions SET publication='missing' WHERE channel=?",(channel,))
   else:
    for message in messages:db.execute("UPDATE lv_suggestions SET publication='missing' WHERE channel=? AND message=?",(channel,message))
