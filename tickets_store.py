"""Transactional ticket state. Independent tables; never edits roles or economy balances."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time

STATES={'nuevo','en_atencion','esperando_jugador','resuelto','cerrado'}
DEPARTMENTS={
 'soporte':('🛠️','Soporte técnico','Algo no funciona o necesitas una mano.'),
 'jugador':('🚨','Reportar jugador','Cuéntanos qué pasó con otro jugador.'),
 'tienda':('🛍️','Problema con tienda','¿Compraste algo y tienes un problema?'),
 'donacion':('💳','Donaciones','Cuéntanos qué quieres donar y cómo.'),
 'apelacion':('⚖️','Apelar sanción','¿Te pusieron un castigo y quieres hablarlo?'),
 'faccion':('🥷','Gangas y negocios','Lo que necesites para tu ganga o negocio.'),
 'staff':('🔒','Reportar al staff','Cuéntanos qué pasó. Lo ven los administradores.'),
}
PROTECTED={1245008186440683530,1300627506801541230,1300619682486947931,1245010156576833536}
NORMAL_STAFF={1300627732954349619,1300631163362218054,1567253212937846935}
ALL_STAFF=NORMAL_STAFF|PROTECTED
DEFAULTS={'max_open':3,'remind_hours':6,'inactive_hours':72,'close_warning_hours':24,
          'closed_category':'','active_category':'','panel_message':'','staff_channel':'','panel_channel':'1513423707467415642','max_file_mb':25,'max_case_mb':100,'max_total_mb':500}

class TicketStore:
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
   for sql in [
    '''CREATE TABLE IF NOT EXISTS lv_tickets(id INTEGER PRIMARY KEY,owner INTEGER NOT NULL,department TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'creando',
       channel INTEGER UNIQUE,control_message INTEGER,assignee INTEGER,priority TEXT NOT NULL DEFAULT 'normal',subject TEXT NOT NULL,form TEXT NOT NULL,
       created INTEGER NOT NULL,updated INTEGER NOT NULL,last_user INTEGER NOT NULL,last_staff INTEGER,first_response INTEGER,closed INTEGER,
       resolution TEXT,warning_at INTEGER,reminded_at INTEGER,rating INTEGER,rating_comment TEXT,transcript TEXT,archive_state TEXT,
       excluded INTEGER,purchase_id TEXT)''',
    "CREATE UNIQUE INDEX IF NOT EXISTS lv_ticket_duplicate ON lv_tickets(owner,department) WHERE status NOT IN ('cerrado','fallido')",
    '''CREATE TABLE IF NOT EXISTS lv_ticket_events(id INTEGER PRIMARY KEY,ticket INTEGER NOT NULL REFERENCES lv_tickets(id),actor INTEGER NOT NULL,
       action TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_people(ticket INTEGER NOT NULL REFERENCES lv_tickets(id),user INTEGER NOT NULL,
       PRIMARY KEY(ticket,user))''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_notes(id INTEGER PRIMARY KEY,ticket INTEGER NOT NULL REFERENCES lv_tickets(id),actor INTEGER NOT NULL,
       text TEXT NOT NULL,created INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_files(ticket INTEGER NOT NULL REFERENCES lv_tickets(id),message INTEGER NOT NULL,attachment INTEGER NOT NULL,
       filename TEXT NOT NULL,source TEXT NOT NULL,path TEXT,state TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT,
       PRIMARY KEY(ticket,attachment))''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_blobs(ticket INTEGER NOT NULL,attachment INTEGER NOT NULL,data BLOB NOT NULL,PRIMARY KEY(ticket,attachment))''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_messages(ticket INTEGER NOT NULL,message INTEGER NOT NULL,author INTEGER NOT NULL,name TEXT NOT NULL,
       content TEXT NOT NULL,embeds TEXT NOT NULL,created TEXT NOT NULL,edited TEXT,deleted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(ticket,message))''',
    '''CREATE TABLE IF NOT EXISTS lv_ticket_message_versions(id INTEGER PRIMARY KEY,ticket INTEGER NOT NULL,message INTEGER NOT NULL,saved TEXT NOT NULL)''',
    'CREATE TABLE IF NOT EXISTS lv_ticket_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)']:
    db.execute(sql)
   columns={r[1] for r in db.execute('PRAGMA table_info(lv_tickets)')}
   for column in ('deleted_at','deletion_requested','deletion_actor'):
    if column not in columns:db.execute(f'ALTER TABLE lv_tickets ADD COLUMN {column} INTEGER')
   for key,value in DEFAULTS.items():db.execute('INSERT OR IGNORE INTO lv_ticket_config VALUES (?,?)',(key,str(value)))
 def config(self,key,value=None):
  with self.db() as db:
   if value is not None:db.execute('INSERT INTO lv_ticket_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
   r=db.execute('SELECT value FROM lv_ticket_config WHERE key=?',(key,)).fetchone()
   return r[0] if r else ''
 def event(self,db,rid,actor,action,detail=''):
  db.execute('INSERT INTO lv_ticket_events(ticket,actor,action,detail,created) VALUES (?,?,?,?,?)',(rid,actor,action,detail,int(time.time())))
 def create(self,user,department,subject,form,excluded=None,purchase=None,now=None):
  if department not in DEPARTMENTS:raise ValueError('Departamento no válido.')
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   old=db.execute("SELECT id,channel FROM lv_tickets WHERE owner=? AND department=? AND status NOT IN ('cerrado','fallido')",(user,department)).fetchone()
   if old:raise ValueError(f"Ya tienes el ticket #{old['id']} de ese tema"+(f" en <#{old['channel']}>." if old['channel'] else '; su creación está pendiente.'))
   limit=int(db.execute("SELECT value FROM lv_ticket_config WHERE key='max_open'").fetchone()[0])
   if db.execute("SELECT COUNT(*) FROM lv_tickets WHERE owner=? AND status NOT IN ('cerrado','fallido')",(user,)).fetchone()[0]>=limit:raise ValueError(f'Puedes tener hasta {limit} tickets abiertos.')
   recent=db.execute('SELECT MAX(created) FROM lv_tickets WHERE owner=?',(user,)).fetchone()[0]
   if recent and stamp-recent<60:raise ValueError('Espera un minuto antes de abrir otro ticket.')
   rid=db.execute('INSERT INTO lv_tickets(owner,department,subject,form,created,updated,last_user,excluded,purchase_id) VALUES (?,?,?,?,?,?,?,?,?)',
      (user,department,subject,json.dumps(form,ensure_ascii=False),stamp,stamp,stamp,excluded,purchase)).lastrowid
   self.event(db,rid,user,'crear',department)
   return rid
 def get(self,rid=None,channel=None):
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_tickets WHERE '+('id=?' if rid is not None else 'channel=?'),(rid if rid is not None else channel,)).fetchone()
   return dict(row) if row else None
 def list(self,owner=None,status=None,limit=25,offset=0):
  clauses=[];args=[]
  if owner is not None:clauses.append('owner=?');args.append(owner)
  if status is not None:clauses.append('status=?');args.append(status)
  with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM lv_tickets'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY id DESC LIMIT ? OFFSET ?',(*args,limit,offset))]
 def update(self,rid,**fields):
  allowed={'channel','control_message','status','assignee','priority','resolution','warning_at','reminded_at','closed','transcript','archive_state','department','deletion_requested','deletion_actor'}
  if not fields or not set(fields)<=allowed:raise ValueError('Actualización no válida')
  with self.db() as db:db.execute('UPDATE lv_tickets SET '+','.join(k+'=?' for k in fields)+',updated=? WHERE id=?',(*fields.values(),int(time.time()),rid))
 def claim(self,rid,actor):
  with self.db() as db:
   r=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not r or r['status'] in ('cerrado','creando','fallido'):raise ValueError('Ese ticket no está disponible.')
   if r['assignee'] and r['assignee']!=actor:raise ValueError('Otro responsable ya reclamó este ticket. Usa transferir.')
   db.execute("UPDATE lv_tickets SET assignee=?,status='en_atencion',updated=? WHERE id=?",(actor,int(time.time()),rid))
   self.event(db,rid,actor,'reclamar')
 def transition(self,rid,status,actor,detail):
  if status not in STATES:raise ValueError('Estado no válido.')
  if not detail.strip():raise ValueError('Indica un motivo o resolución.')
  stamp=int(time.time())
  with self.db() as db:
   r=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not r:raise ValueError('Ticket no encontrado.')
   if r['deleted_at']:raise ValueError('El canal fue eliminado y ya no figura en las listas de tickets.')
   if status=='cerrado' and r['status']=='cerrado':raise ValueError('El ticket ya está cerrado.')
   if r['status']=='cerrado' and status!='en_atencion':raise ValueError('Primero reabre el ticket.')
   if r['status'] in ('creando','fallido'):raise ValueError('La creación de este ticket no ha terminado.')
   if r['status']=='cerrado':
    duplicate=db.execute("SELECT id FROM lv_tickets WHERE owner=? AND department=? AND id!=? AND status NOT IN ('cerrado','fallido')",(r['owner'],r['department'],rid)).fetchone()
    if duplicate:raise ValueError(f"Ya hay otro ticket activo del mismo tema: #{duplicate['id']}.")
    limit=int(db.execute("SELECT value FROM lv_ticket_config WHERE key='max_open'").fetchone()[0])
    if db.execute("SELECT COUNT(*) FROM lv_tickets WHERE owner=? AND status NOT IN ('cerrado','fallido')",(r['owner'],)).fetchone()[0]>=limit:raise ValueError('El jugador ya alcanzó el límite de tickets abiertos.')
   db.execute('UPDATE lv_tickets SET status=?,updated=?,closed=?,resolution=?,warning_at=NULL,reminded_at=NULL WHERE id=?',
     (status,stamp,stamp if status=='cerrado' else None,detail if status in ('cerrado','resuelto') else r['resolution'],rid))
   self.event(db,rid,actor,status,detail)
 def transfer(self,rid,department,actor,reason,assignee=None):
  if department not in DEPARTMENTS:raise ValueError('Departamento no válido.')
  with self.db() as db:
   r=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not r or r['status'] in ('cerrado','creando','fallido'):raise ValueError('Ticket no activo.')
   if r['department']=='staff' and department!='staff':raise ValueError('Un reporte reservado no puede transferirse a un departamento público de staff.')
   duplicate=db.execute("SELECT id FROM lv_tickets WHERE owner=? AND department=? AND id!=? AND status NOT IN ('cerrado','fallido')",(r['owner'],department,rid)).fetchone()
   if duplicate:raise ValueError('El jugador ya tiene otro ticket en ese departamento.')
   db.execute("UPDATE lv_tickets SET department=?,assignee=?,status='en_atencion',updated=? WHERE id=?",(department,assignee,int(time.time()),rid))
   self.event(db,rid,actor,'transferir',json.dumps(dict(from_department=r['department'],to_department=department,reason=reason,assignee=assignee),ensure_ascii=False))
 def activity(self,rid,user,staff,now=None):
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   r=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not r or r['status'] in ('cerrado','creando','fallido'):return
   if staff:
    db.execute('UPDATE lv_tickets SET last_staff=?,first_response=COALESCE(first_response,?),reminded_at=NULL WHERE id=?',(stamp,stamp,rid))
   else:
    db.execute("UPDATE lv_tickets SET last_user=?,warning_at=NULL,reminded_at=NULL,status=CASE WHEN status='esperando_jugador' THEN 'en_atencion' ELSE status END WHERE id=?",(stamp,rid))
 def people(self,rid):
  with self.db() as db:return [r[0] for r in db.execute('SELECT user FROM lv_ticket_people WHERE ticket=?',(rid,))]
 def participant(self,rid,user,actor,add=True):
  with self.db() as db:
   if add:db.execute('INSERT OR IGNORE INTO lv_ticket_people VALUES (?,?)',(rid,user))
   else:db.execute('DELETE FROM lv_ticket_people WHERE ticket=? AND user=?',(rid,user))
   self.event(db,rid,actor,'añadir' if add else 'retirar',str(user))
 def note(self,rid,actor,text):
  with self.db() as db:
   db.execute('INSERT INTO lv_ticket_notes(ticket,actor,text,created) VALUES (?,?,?,?)',(rid,actor,text,int(time.time())))
   self.event(db,rid,actor,'nota_interna','Nota privada guardada')
 def events(self,rid,notes=False):
  with self.db() as db:return [dict(r) for r in db.execute(('SELECT * FROM lv_ticket_notes' if notes else 'SELECT * FROM lv_ticket_events')+' WHERE ticket=? ORDER BY id',(rid,))]
 def rate(self,rid,user,score,comment):
  if score not in range(1,6):raise ValueError('Elige una valoración de 1 a 5.')
  with self.db() as db:
   r=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not r or r['owner']!=user or r['status']!='cerrado':raise ValueError('Solo el autor puede valorar un ticket cerrado.')
   if r['rating'] is not None:raise ValueError('Ya valoraste este ticket.')
   db.execute('UPDATE lv_tickets SET rating=?,rating_comment=? WHERE id=?',(score,comment[:1000],rid))
   self.event(db,rid,user,'valorar',str(score))
 def files(self,rid):
  with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM lv_ticket_files WHERE ticket=?',(rid,))]
 def file(self,rid,message,attachment,name,url,size,path=None,state='pendiente',sha=None):
  with self.db() as db:db.execute('''INSERT INTO lv_ticket_files VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT(ticket,attachment) DO UPDATE SET path=COALESCE(excluded.path,lv_ticket_files.path),state=CASE WHEN lv_ticket_files.state='guardado' THEN 'guardado' ELSE excluded.state END,sha256=COALESCE(excluded.sha256,lv_ticket_files.sha256)''',
    (rid,message,attachment,name,url,path,state,size,sha))
 def stats(self):
  with self.db() as db:
   return dict(states=dict(db.execute('SELECT status,COUNT(*) FROM lv_tickets GROUP BY status')),
     unclaimed=db.execute("SELECT COUNT(*) FROM lv_tickets WHERE assignee IS NULL AND status NOT IN ('cerrado','fallido','creando')").fetchone()[0],
     response_seconds=db.execute('SELECT AVG(first_response-created) FROM lv_tickets WHERE first_response IS NOT NULL').fetchone()[0],
     rating=db.execute('SELECT AVG(rating) FROM lv_tickets WHERE rating IS NOT NULL').fetchone()[0],
     reopened=db.execute("SELECT COUNT(*) FROM lv_ticket_events WHERE action='en_atencion' AND detail LIKE 'Reapertura:%'").fetchone()[0])

 def message(self,rid,message):
  import json
  with self.db() as db:
   previous=db.execute('SELECT * FROM lv_ticket_messages WHERE ticket=? AND message=?',(rid,message.id)).fetchone()
   new_embeds=json.dumps([e.to_dict() for e in message.embeds],ensure_ascii=False,sort_keys=True)
   if previous and (previous['content']!=message.content or previous['embeds']!=new_embeds):
    db.execute('INSERT INTO lv_ticket_message_versions(ticket,message,saved) VALUES (?,?,?)',(rid,message.id,json.dumps(dict(previous),ensure_ascii=False)))
   db.execute("""INSERT INTO lv_ticket_messages(ticket,message,author,name,content,embeds,created,edited) VALUES (?,?,?,?,?,?,?,?)
      ON CONFLICT(ticket,message) DO UPDATE SET content=excluded.content,embeds=excluded.embeds,edited=excluded.edited""",
      (rid,message.id,message.author.id,message.author.display_name,message.content,
       json.dumps([e.to_dict() for e in message.embeds],ensure_ascii=False,sort_keys=True),message.created_at.isoformat(),
       message.edited_at.isoformat() if message.edited_at else None))
 def deleted(self,channel,message):
  with self.db() as db:db.execute('UPDATE lv_ticket_messages SET deleted=1 WHERE message=? AND ticket IN (SELECT id FROM lv_tickets WHERE channel=?)',(message,channel))
 def messages(self,rid):
  with self.db() as db:
   current=[dict(r) for r in db.execute('SELECT * FROM lv_ticket_messages WHERE ticket=? ORDER BY message',(rid,))]
   deleted={r['message']:r['deleted'] for r in current}
   versions=[]
   for row in db.execute('SELECT saved FROM lv_ticket_message_versions WHERE ticket=? ORDER BY id',(rid,)):
    item=json.loads(row[0]);item['name']+=' [versión anterior]';item['deleted']=deleted.get(item['message'],item['deleted']);versions.append(item)
   return sorted(versions+current,key=lambda r:r['message'])
 def save_blob(self,rid,attachment,data):
  import hashlib
  with self.db() as db:
   previous=db.execute('SELECT 1 FROM lv_ticket_blobs WHERE ticket=? AND attachment=?',(rid,attachment)).fetchone()
   if previous:return
   case=db.execute('SELECT COALESCE(SUM(LENGTH(data)),0) FROM lv_ticket_blobs WHERE ticket=?',(rid,)).fetchone()[0]
   total=db.execute('SELECT COALESCE(SUM(LENGTH(data)),0) FROM lv_ticket_blobs').fetchone()[0]
   limits=dict(db.execute("SELECT key,value FROM lv_ticket_config WHERE key IN ('max_file_mb','max_case_mb','max_total_mb')"))
   if len(data)>int(limits['max_file_mb'])*1048576 or case+len(data)>int(limits['max_case_mb'])*1048576 or total+len(data)>int(limits['max_total_mb'])*1048576:
    raise ValueError('Límite de respaldo de pruebas alcanzado; el archivo no quedó respaldado. Staff debe revisar /ticket configuracion.')
   import shutil
   if shutil.disk_usage(self.path.parent).free < (total+len(data))*3+32*1048576:
    raise ValueError('No hay espacio suficiente para conservar esta prueba y sus respaldos; avisa a administración.')
   db.execute('INSERT INTO lv_ticket_blobs VALUES (?,?,?)',(rid,attachment,data))
   db.execute("UPDATE lv_ticket_files SET state='guardado',sha256=? WHERE ticket=? AND attachment=?",(hashlib.sha256(data).hexdigest(),rid,attachment))
 def blob(self,rid,attachment):
  with self.db() as db:
   r=db.execute('SELECT data FROM lv_ticket_blobs WHERE ticket=? AND attachment=?',(rid,attachment)).fetchone()
   return r[0] if r else None

 def mark_deleted(self,rid,actor):
  stamp=int(time.time())
  with self.db() as db:
   row=db.execute('SELECT * FROM lv_tickets WHERE id=?',(rid,)).fetchone()
   if not row or row['status']!='cerrado':raise ValueError('Solo se pueden eliminar canales de tickets cerrados.')
   if row['deleted_at']:return False
   db.execute('UPDATE lv_tickets SET deleted_at=?,deletion_actor=?,deletion_requested=NULL,updated=? WHERE id=?',(stamp,actor,stamp,rid))
   self.event(db,rid,actor,'eliminar_canal','Canal eliminado por confirmación; transcripción y pruebas conservadas')
   return True
