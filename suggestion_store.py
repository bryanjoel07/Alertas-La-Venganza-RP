"""Atomic community suggestions, votes and decisions in the existing SQLite backup."""
from settings_catalog import read_value
from sqlite_runtime import transaction
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time
import unicodedata

STATES={'pendiente':('🕓','Pendiente'),'aceptada':('✅','Aceptada'),
        'proceso':('🛠️','En proceso'),'hecha':('🎉','Hecha'),'rechazada':('❌','Rechazada')}
CLOSED={'hecha','rechazada'}


class SuggestionStore:
 def __init__(self,path):self.path=Path(path)
 @contextmanager
 def db(self, *, readonly=False):
     with transaction(self.path, readonly=readonly, foreign_keys=True, timeout=10) as db:
         yield db
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
   last=db.execute('SELECT COALESCE(MAX(id),0) FROM lv_suggestions').fetchone()[0]
   db.execute("INSERT INTO lv_suggestion_config VALUES ('last_id',?) ON CONFLICT(key) DO UPDATE SET value=CAST(MAX(CAST(value AS INTEGER),CAST(excluded.value AS INTEGER)) AS TEXT)",(str(last),))
 def config(self,key,value=None):
  with self.db(readonly=value is None) as db:
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
   if not read_value(db,'suggestions','accepting'):raise ValueError('Ahora mismo no estamos recibiendo ideas nuevas. Las anteriores siguen disponibles.')
   duplicate=db.execute("SELECT id FROM lv_suggestions WHERE owner=? AND fingerprint=? AND publication!='missing' AND status NOT IN ('hecha','rechazada')",(owner,fingerprint)).fetchone()
   if duplicate:raise ValueError(f"Ya enviaste esa idea, bro. Es la sugerencia #{duplicate['id']}.")
   recent=db.execute('SELECT MAX(created) FROM lv_suggestions WHERE owner=?',(owner,)).fetchone()[0]
   wait=read_value(db,'suggestions','cooldown_minutes')*60
   if recent is not None and stamp-recent<wait:raise ValueError(f'Espera {wait//60} minuto'+('s' if wait!=60 else '')+f' entre ideas, bro. Puedes enviar otra <t:{recent+wait}:R>.')
   counter=db.execute("SELECT value FROM lv_suggestion_config WHERE key='last_id'").fetchone()
   rid=max(int(counter[0]) if counter else 0,db.execute('SELECT COALESCE(MAX(id),0) FROM lv_suggestions').fetchone()[0])+1
   db.execute('INSERT INTO lv_suggestions(id,request,owner,title,description,benefit,fingerprint,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
     (rid,request,owner,title,description,benefit,fingerprint,stamp,stamp))
   db.execute("INSERT INTO lv_suggestion_config VALUES ('last_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(rid),))
   return rid
 def get(self,rid):
  with self.db(readonly=True) as db:
   row=db.execute('''SELECT s.*,
     (SELECT COUNT(*) FROM lv_suggestion_votes WHERE suggestion=s.id AND value=1) AS up,
     (SELECT COUNT(*) FROM lv_suggestion_votes WHERE suggestion=s.id AND value=-1) AS down
     FROM lv_suggestions s WHERE s.id=?''',(rid,)).fetchone()
   return dict(row) if row else None
 def list(self,owner=None,limit=10,offset=0):
  with self.db(readonly=True) as db:
   where="publication NOT IN ('missing','deleting')"+(' AND owner=?' if owner is not None else '')
   args=([owner] if owner is not None else [])+[limit,offset]
   return [dict(r) for r in db.execute('SELECT * FROM lv_suggestions WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?',args)]
 def pending(self):
  with self.db(readonly=True) as db:
   return [r[0] for r in db.execute("SELECT id FROM lv_suggestions WHERE publication IN ('pending','publishing') OR (publication='published' AND revision!=rendered) ORDER BY id")]
 def acquire(self,rid,now=None):
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   return bool(db.execute("UPDATE lv_suggestions SET lease_until=?,publication='publishing' WHERE id=? AND publication IN ('pending','publishing') AND lease_until<=?",(stamp+180,rid,stamp)).rowcount)
 def bind(self,rid,channel,message):
  with self.db() as db:
   row=db.execute('SELECT publication,message FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row or row['publication'] in ('missing','deleting'):raise ValueError('Esa sugerencia ya no está disponible.')
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
   if value and not read_value(db,'suggestions','voting'):raise ValueError('Las votaciones están pausadas. Puedes quitar un voto que ya habías dejado.')
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
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute('SELECT * FROM lv_suggestion_events WHERE suggestion=? ORDER BY id',(rid,))]
 def votes(self,rid):
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute('SELECT * FROM lv_suggestion_votes WHERE suggestion=? ORDER BY user',(rid,))]
 def published(self):
  with self.db(readonly=True) as db:return [r[0] for r in db.execute("SELECT id FROM lv_suggestions WHERE publication='published' ORDER BY id")]
 def pending_deletions(self):
  with self.db(readonly=True) as db:return [r[0] for r in db.execute("SELECT id FROM lv_suggestions WHERE publication='deleting' ORDER BY id")]
 def deletion(self,rid):
  value=self.config(f'deletion:{rid}')
  return json.loads(value) if value else None
 def queue_deletion(self,rid,actor,expected):
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row:return False
   keys=('request','channel','message','status_version')
   if any(row[key]!=expected[key] for key in keys):raise ValueError('La idea cambió desde que abriste la confirmación. Revisa la idea y vuelve a pulsar Eliminar.')
   if row['publication']=='deleting':return True
   job=dict(actor=actor,request=row['request'],not_before=row['lease_until'] if row['publication']=='publishing' and not row['message'] else 0)
   db.execute('INSERT INTO lv_suggestion_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(f'deletion:{rid}',json.dumps(job)))
   db.execute("UPDATE lv_suggestions SET publication='deleting',lease_until=0 WHERE id=?",(rid,))
   return True
 def deletion_target(self,rid,channel,message):
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row or row['publication']!='deleting' or row['message'] not in (None,message):raise ValueError('Cambió la publicación de esa idea; no se eliminará otra.')
   db.execute('UPDATE lv_suggestions SET channel=?,message=? WHERE id=?',(channel,message,rid))
 def purge(self,rid,request):
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_suggestions WHERE id=?',(rid,)).fetchone()
   if not row:return False
   if row['request']!=request or row['publication']!='deleting':raise ValueError('La idea no tiene una eliminación confirmada.')
   db.execute('DELETE FROM lv_suggestion_votes WHERE suggestion=?',(rid,))
   db.execute('DELETE FROM lv_suggestion_events WHERE suggestion=?',(rid,))
   db.execute('DELETE FROM lv_suggestions WHERE id=?',(rid,))
   db.execute('DELETE FROM lv_suggestion_config WHERE key=?',(f'deletion:{rid}',))
   return True
 def missing(self,channel,messages=None):
  with self.db() as db:
   if messages is None:db.execute("UPDATE lv_suggestions SET publication='missing' WHERE channel=? AND publication!='deleting'",(channel,))
   else:
    for message in messages:db.execute("UPDATE lv_suggestions SET publication='missing' WHERE channel=? AND message=? AND publication!='deleting'",(channel,message))
