"""Durable staff applications, decisions and notification receipts."""
from settings_catalog import read_value
from interview_reminders import START_GRACE_SECONDS, interview_text, notice_details, notice_key, reminder_phase
from sqlite_runtime import transaction
from contextlib import contextmanager
import json
from pathlib import Path
import time

ACTIVE={'borrador','enviada','revision','esperando','entrevista'}
FINAL={'aceptada','rechazada','retirada'}
LABELS={'borrador':'Sin enviar','enviada':'Por revisar','revision':'En revisión','esperando':'Esperando tu respuesta',
        'entrevista':'Entrevista','aceptada':'Aceptada','rechazada':'No aceptada','retirada':'Retirada'}
QUESTIONS=(
 ('nombre','¿Cómo te llamas en el servidor?',100,'Tu nombre de personaje o el que usas aquí.',False),
 ('edad','¿Qué edad tienes?',30,'Solo tu edad. No hace falta tu fecha de nacimiento.',False),
 ('horario','¿Qué días y a qué hora puedes ayudar?',400,'Dinos también de qué país eres para cuadrar la hora.',True),
 ('experiencia','¿Has sido staff antes?',600,'Si sí, cuéntanos dónde y qué hacías. Si no, dilo tranquilo.',True),
 ('motivo','¿Por qué quieres ser staff aquí?',700,'Cuéntanos con tus palabras.',True),
 ('normas','¿Conoces las reglas del servidor?',500,'¿Qué regla te parece más importante y por qué?',True),
 ('caso','Se están insultando. ¿Cómo lo manejas?',900,'Dos jugadores se están insultando. ¿Qué haces?',True),
 ('amigo','Un amigo tuyo rompe las reglas. ¿Qué haces?',700,'Queremos saber cómo lo resolverías.',True),
 ('extra','¿Algo más que quieras contarnos?',700,'Esto es opcional.',True),
)

class RecruitmentStore:
 def __init__(self,path):self.path=Path(path)
 @contextmanager
 def db(self, *, readonly=False):
     with transaction(self.path, readonly=readonly, foreign_keys=False, timeout=10) as db:
         yield db
 def initialize(self):
  with self.db() as db:
   db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_cases(id INTEGER PRIMARY KEY,owner INTEGER NOT NULL,
    status TEXT NOT NULL,answers TEXT NOT NULL DEFAULT '{}',step INTEGER NOT NULL DEFAULT 0,
    assignee INTEGER,created INTEGER NOT NULL,updated INTEGER NOT NULL,submitted INTEGER,revision INTEGER NOT NULL DEFAULT 0,
    review_message INTEGER,review_revision INTEGER NOT NULL DEFAULT -1,interview_at INTEGER,
    interviewer INTEGER,interview_done INTEGER NOT NULL DEFAULT 0,interview_message INTEGER,
    interview_revision INTEGER NOT NULL DEFAULT -1,result TEXT,decided_by INTEGER,decided_at INTEGER)''')
   db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lv_recruit_one_active ON lv_recruit_cases(owner) WHERE status IN ('borrador','enviada','revision','esperando','entrevista')")
   db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_events(id INTEGER PRIMARY KEY,application INTEGER NOT NULL,
    actor INTEGER NOT NULL,action TEXT NOT NULL,text TEXT NOT NULL,private INTEGER NOT NULL DEFAULT 0,created INTEGER NOT NULL)''')
   db.execute('CREATE INDEX IF NOT EXISTS lv_recruit_interview_events ON lv_recruit_events(application,action,id)')
   db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_notices(id INTEGER PRIMARY KEY,application INTEGER NOT NULL,
    user INTEGER NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
    created INTEGER NOT NULL,message INTEGER,UNIQUE(application,user,kind))''')
   db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)''')
   db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_voice(application INTEGER PRIMARY KEY,user INTEGER NOT NULL,
    before_json TEXT NOT NULL,after_json TEXT NOT NULL,expires INTEGER NOT NULL,state TEXT NOT NULL)''')
   db.execute("INSERT OR IGNORE INTO lv_recruit_config VALUES ('open','1')")
 def config(self,key,value=None):
  with self.db(readonly=value is None) as db:
   if value is not None:db.execute('INSERT INTO lv_recruit_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
   row=db.execute('SELECT value FROM lv_recruit_config WHERE key=?',(key,)).fetchone();return row[0] if row else ''
 def _event(self,db,row,actor,action,text='',private=False):
  eid=db.execute('INSERT INTO lv_recruit_events(application,actor,action,text,private,created) VALUES (?,?,?,?,?,?)',
    (row['id'],actor,action,text,int(private),int(time.time()))).lastrowid
  return eid
 def _notice(self,db,row,kind,text,user=None,state='pending'):
  db.execute('INSERT OR IGNORE INTO lv_recruit_notices(application,user,kind,text,state,created) VALUES (?,?,?,?,?,?)',
    (row['id'],user or row['owner'],kind,text,state,int(time.time())))
 def _appointment(self,db,rid):
  return db.execute("SELECT id,created,text FROM lv_recruit_events WHERE application=? AND action='entrevista' ORDER BY id DESC LIMIT 1",(rid,)).fetchone()
 def _cancel_interview_notices(self,db,rid):
  db.execute("UPDATE lv_recruit_notices SET state='cancelled' WHERE application=? AND state='pending' AND (kind LIKE 'entrevista:%' OR kind LIKE 'recordatorio:%')",(rid,))
 def _row(self,db,rid,revision=None):
  row=db.execute('SELECT * FROM lv_recruit_cases WHERE id=?',(rid,)).fetchone()
  if not row:raise ValueError('No encuentro esa solicitud.')
  if revision is not None and row['revision']!=revision:raise ValueError('La solicitud cambió. Ábrela otra vez antes de seguir.')
  return row
 def _touch(self,db,rid,**fields):
  db.execute('UPDATE lv_recruit_cases SET '+','.join(k+'=?' for k in fields)+',updated=?,revision=revision+1 WHERE id=?',(*fields.values(),int(time.time()),rid))
 def get(self,rid):
  with self.db(readonly=True) as db:return dict(self._row(db,rid))
 def rows(self,owner=None,active=False,limit=25,offset=0,submitted=False):
  terms=[];args=[]
  if owner is not None:terms.append('owner=?');args.append(owner)
  if submitted:terms.append('submitted IS NOT NULL')
  if active:terms.append("status IN ('enviada','revision','esperando','entrevista')")
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute('SELECT * FROM lv_recruit_cases'+(' WHERE '+' AND '.join(terms) if terms else '')+' ORDER BY id DESC LIMIT ? OFFSET ?',(*args,limit,offset))]
 def begin(self,owner):
  with self.db() as db:
   row=db.execute("SELECT * FROM lv_recruit_cases WHERE owner=? AND status IN ('borrador','enviada','revision','esperando','entrevista')",(owner,)).fetchone()
   if row:return dict(row)
   if db.execute("SELECT value FROM lv_recruit_config WHERE key='open'").fetchone()[0]!='1':raise ValueError('Ahora mismo no estamos recibiendo solicitudes. Puedes consultar una que ya hayas enviado.')
   recent=db.execute('SELECT MAX(created) FROM lv_recruit_cases WHERE owner=?',(owner,)).fetchone()[0]
   wait=read_value(db,'recruitment','cooldown_minutes')*60
   if recent and int(time.time())-recent<wait:raise ValueError('Espera unos minutos antes de empezar otra solicitud.')
   stamp=int(time.time());rid=db.execute("INSERT INTO lv_recruit_cases(owner,status,created,updated) VALUES (?,'borrador',?,?)",(owner,stamp,stamp)).lastrowid
   return dict(self._row(db,rid))
 def save_step(self,rid,owner,step,values,revision):
  questions=QUESTIONS[:5] if step==0 else QUESTIONS[5:]
  cleaned={k:str(values.get(k,'')).strip() for k,_,_,_,_ in questions}
  for k,_,limit,_,_ in questions:
   if (not cleaned[k] and k!='extra') or len(cleaned[k])>limit:raise ValueError('Revisa las respuestas; falta una o es demasiado larga.')
  with self.db() as db:
   row=self._row(db,rid,revision)
   if row['owner']!=owner or row['status']!='borrador':raise ValueError('Solo puedes editar tu solicitud antes de enviarla.')
   if step!=row['step']:raise ValueError('Este paso ya está guardado. Abre «Mi solicitud» para seguir.')
   answers=json.loads(row['answers']);answers.update(cleaned)
   self._touch(db,rid,answers=json.dumps(answers,ensure_ascii=False),step=step+1)
 def submit(self,rid,owner,revision):
  with self.db() as db:
   row=self._row(db,rid,revision)
   if row['owner']!=owner or row['status']!='borrador' or row['step']!=2:raise ValueError('Termina el formulario antes de enviarlo.')
   if db.execute("SELECT value FROM lv_recruit_config WHERE key='open'").fetchone()[0]!='1':raise ValueError('Se cerraron las solicitudes. Tu borrador sigue guardado.')
   self._touch(db,rid,status='enviada',submitted=int(time.time()));self._event(db,row,owner,'enviada')
   self._notice(db,row,'enviada','Recibimos tu solicitud para el staff. El equipo la revisará y te avisaremos por aquí. Puedes ver cómo va en «Mi solicitud».')
 def restart(self,rid,owner,revision):
  with self.db() as db:
   row=self._row(db,rid,revision)
   if row['owner']!=owner or row['status']!='borrador':raise ValueError('Solo puedes cambiar el formulario antes de enviarlo.')
   self._touch(db,rid,step=0)
 def claim(self,rid,actor,revision):
  with self.db() as db:
   row=self._row(db,rid,revision);self._staff(row,actor)
   if row['assignee'] and row['assignee']!=actor:raise ValueError('Ya hay alguien encargado de esta solicitud.')
   self._touch(db,rid,assignee=actor,status='revision' if row['status']=='enviada' else row['status'])
   self._event(db,row,actor,'reclamar')
   self._notice(db,row,'revision','Ya están revisando tu solicitud para el staff. Te avisaremos si necesitamos algo más.')
 def _staff(self,row,actor):
  if row['owner']==actor:raise ValueError('No puedes revisar ni decidir tu propia solicitud.')
  if row['status'] not in ACTIVE-{'borrador'}:raise ValueError('Esta solicitud ya terminó o todavía no se ha enviado.')
 def staff_text(self,rid,actor,kind,text,revision):
  if kind not in {'mensaje','pregunta','nota'} or not text.strip() or len(text)>1500:raise ValueError('Escribe el mensaje para poder guardarlo.')
  with self.db() as db:
   row=self._row(db,rid,revision);self._staff(row,actor)
   self._touch(db,rid,**({'status':'esperando'} if kind=='pregunta' else {'status':row['status']}))
   eid=self._event(db,row,actor,kind,text.strip(),kind=='nota')
   if kind!='nota':self._notice(db,row,f'mensaje:{eid}',('El equipo te pregunta:\n' if kind=='pregunta' else 'El equipo te dejó un mensaje:\n')+text.strip())
 def answer(self,rid,owner,text,revision):
  if not text.strip() or len(text)>1500:raise ValueError('Escribe lo que quieres decirle al equipo.')
  with self.db() as db:
   row=self._row(db,rid,revision)
   if row['owner']!=owner or row['status'] not in ACTIVE-{'borrador'}:raise ValueError('Esta solicitud no permite más respuestas.')
   self._touch(db,rid,status='revision' if row['status']=='esperando' else row['status'])
   self._event(db,row,owner,'respuesta',text.strip())
 def schedule(self,rid,actor,at,interviewer,text,revision,now=None):
  stamp=int(time.time()) if now is None else now
  if at<stamp+60 or at>stamp+90*86400:raise ValueError('Pon una fecha futura dentro de los próximos 90 días.')
  with self.db() as db:
   row=self._row(db,rid,revision);self._staff(row,actor)
   self._cancel_interview_notices(db,rid)
   self._touch(db,rid,status='entrevista',interview_at=at,interviewer=interviewer,interview_done=0)
   generation=self._event(db,row,actor,'entrevista',text)
   row=dict(self._row(db,rid));phase=reminder_phase(at,stamp,read_value(db,'recruitment','interview_notice_minutes'))
   for user in {row['owner'],interviewer}:
    self._notice(db,row,notice_key(at,generation),interview_text(row,user,instructions=text),user)
    # Booking inside a reminder window already informs both recipients.
    if phase:self._notice(db,row,notice_key(at,generation,phase),interview_text(row,user,phase),user,state='covered')
 def interviewed(self,rid,actor,text,revision):
  if not text.strip():raise ValueError('Cuéntanos cómo fue la entrevista.')
  with self.db() as db:
   row=self._row(db,rid,revision);self._staff(row,actor)
   if not row['interview_at']:raise ValueError('Primero hay que agendar la entrevista.')
   self._cancel_interview_notices(db,rid)
   self._touch(db,rid,interview_done=1);self._event(db,row,actor,'entrevista_realizada',text.strip(),True)
 def decide(self,rid,actor,accepted,text,revision):
  if not text.strip() or len(text)>1500:raise ValueError('Escribe una respuesta para el candidato.')
  with self.db() as db:
   row=self._row(db,rid,revision);self._staff(row,actor)
   if accepted and not row['interview_done']:raise ValueError('Hay que hacer la entrevista y marcarla como realizada antes de aceptar.')
   status='aceptada' if accepted else 'rechazada'
   self._cancel_interview_notices(db,rid)
   self._touch(db,rid,status=status,result=text.strip(),decided_by=actor,decided_at=int(time.time()))
   self._event(db,row,actor,status,text.strip());self._notice(db,row,'resultado',('¡Te aceptaron en el staff! 🎉\n' if accepted else 'Ya revisamos tu solicitud. Esta vez no fuiste seleccionado.\n')+text.strip())
 def withdraw(self,rid,owner,revision):
  with self.db() as db:
   row=self._row(db,rid,revision)
   if row['owner']!=owner or row['status'] not in ACTIVE:raise ValueError('Solo puedes retirar una solicitud tuya que siga abierta.')
   self._cancel_interview_notices(db,rid)
   self._touch(db,rid,status='retirada');self._event(db,row,owner,'retirada')
 def events(self,rid,private=False):
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute('SELECT * FROM lv_recruit_events WHERE application=?'+('' if private else ' AND private=0')+' ORDER BY id',(rid,))]
 def receipt(self,rid,field,message,revision):
  if field not in {'review','interview'}:raise ValueError('Recibo incorrecto.')
  with self.db() as db:db.execute(f'UPDATE lv_recruit_cases SET {field}_message=?,{field}_revision=? WHERE id=?',(message,revision,rid))
 def pending(self):
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute("SELECT * FROM lv_recruit_notices WHERE state='pending' ORDER BY CASE WHEN kind LIKE 'recordatorio:%' THEN 0 WHEN kind LIKE 'entrevista:%' THEN 1 ELSE 2 END,id LIMIT 30")]
 def notice_done(self,nid,state,message=None):
  if state not in {'sent','blocked','cancelled'}:raise ValueError('Recibo incorrecto.')
  with self.db() as db:db.execute("UPDATE lv_recruit_notices SET state=?,message=? WHERE id=? AND state='pending'",(state,message,nid))
 def notice_snapshot(self,nid):
  with self.db(readonly=True) as db:
   notice=db.execute('SELECT * FROM lv_recruit_notices WHERE id=?',(nid,)).fetchone()
   return dict(notice) if notice else {}
 def interview_reminder_settings(self):
  with self.db(readonly=True) as db:
   minutes=read_value(db,'recruitment','interview_notice_minutes')
   scheduled=db.execute("SELECT COUNT(*) FROM lv_recruit_cases WHERE status IN ('enviada','revision','esperando','entrevista') AND interview_done=0 AND interview_at>=?",(int(time.time())-START_GRACE_SECONDS,)).fetchone()[0]
   return dict(advance_minutes=minutes,second_minutes=15 if minutes>15 else None,scheduled=scheduled)
 def notice_ready(self,nid,now=None):
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   notice=db.execute("SELECT * FROM lv_recruit_notices WHERE id=? AND state='pending'",(nid,)).fetchone()
   if not notice:return None
   notice=dict(notice)
   try:details=notice_details(notice['kind'])
   except ValueError:details={}
   if details is None:return notice
   row=db.execute('SELECT * FROM lv_recruit_cases WHERE id=?',(notice['application'],)).fetchone()
   event=self._appointment(db,notice['application']) if row else None
   valid=bool(details and row and row['status'] in ACTIVE-{'borrador'} and not row['interview_done']
    and row['interview_at']==details['at'] and stamp<=details['at']+START_GRACE_SECONDS
    and (details['generation'] is None or (event['id'] if event else 0)==details['generation'])
    and notice['user'] in {row['owner'],row['interviewer']})
   if valid and details['phase'] in {'previo','pronto','hora'}:
    valid=reminder_phase(details['at'],stamp,read_value(db,'recruitment','interview_notice_minutes'))==details['phase']
   if valid and details['phase']=='confirmada':
    phase=reminder_phase(details['at'],stamp,read_value(db,'recruitment','interview_notice_minutes'))
    if phase:
     key=notice_key(details['at'],event['id'] if event else 0,phase)
     legacy=f'recordatorio:{details["at"]}' if details['generation'] is None else key
     # A current reminder replaces a booking confirmation delayed by downtime.
     newer=db.execute("SELECT 1 FROM lv_recruit_notices WHERE application=? AND user=? AND kind IN (?,?) AND state IN ('pending','sent','blocked')",(row['id'],notice['user'],key,legacy)).fetchone()
     if newer:valid=False
   if not valid:
    db.execute("UPDATE lv_recruit_notices SET state='cancelled' WHERE id=?",(nid,));return None
   notice.update(audience='candidate' if notice['user']==row['owner'] else 'interviewer',
    interview_at=row['interview_at'],interview_event=event['id'] if event else 0,owner=row['owner'])
   return notice
 def notice_blocked(self,nid):
  with self.db() as db:
   notice=db.execute("SELECT * FROM lv_recruit_notices WHERE id=? AND state='pending'",(nid,)).fetchone()
   if not notice:return
   db.execute("UPDATE lv_recruit_notices SET state='blocked' WHERE id=?",(nid,))
   details=notice_details(notice['kind'])
   if not details:return
   row=self._row(db,notice['application']);event=self._appointment(db,row['id'])
   if (notice['user']!=row['owner'] or not row['interviewer'] or row['status'] not in ACTIVE-{'borrador'}
    or row['interview_done'] or row['interview_at']!=details['at']
    or details['generation'] is not None and (not event or event['id']!=details['generation'])):return
   text=f'No pude avisarle por privado a <@{row["owner"]}> sobre su entrevista de <t:{row["interview_at"]}:F>.\nSus mensajes privados no están disponibles. Avísale por otro medio; también puede consultar la fecha en «Mi solicitud».'
   self._notice(db,row,notice_key(row['interview_at'],event['id'] if event else 0,'dm_cerrado'),text,row['interviewer'])
 def remind(self,now=None):
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   minutes=read_value(db,'recruitment','interview_notice_minutes')
   for row in db.execute("SELECT * FROM lv_recruit_cases WHERE status IN ('enviada','revision','esperando','entrevista') AND interview_done=0 AND interview_at BETWEEN ? AND ?",(stamp-START_GRACE_SECONDS,stamp+minutes*60)).fetchall():
    phase=reminder_phase(row['interview_at'],stamp,minutes);event=self._appointment(db,row['id'])
    if phase is None:continue
    generation=event['id'] if event else 0
    current_booking=db.execute('SELECT 1 FROM lv_recruit_notices WHERE application=? AND kind=?',(row['id'],notice_key(row['interview_at'],generation))).fetchone()
    for user in {row['owner'],row['interviewer']} - {None}:
     # Honor the previous version's receipt for the first reminder.
     legacy=db.execute("SELECT 1 FROM lv_recruit_notices WHERE application=? AND user=? AND kind=? AND state!='cancelled'",(row['id'],user,f'recordatorio:{row["interview_at"]}')).fetchone()
     if phase=='previo' and legacy and not current_booking:continue
     self._notice(db,row,notice_key(row['interview_at'],generation,phase),interview_text(row,user,phase,instructions=event['text'] if event else ''),user)
 def voice(self,rid=None):
  with self.db(readonly=True) as db:
   rows=db.execute('SELECT * FROM lv_recruit_voice'+(' WHERE application=?' if rid is not None else ''),(rid,) if rid is not None else ()).fetchall()
   return [dict(r) for r in rows]
 def voice_save(self,rid,user,before,after,expires):
  with self.db() as db:
   db.execute('INSERT INTO lv_recruit_voice VALUES (?,?,?,?,?,?) ON CONFLICT(application) DO UPDATE SET before_json=excluded.before_json,after_json=excluded.after_json,expires=excluded.expires,state=excluded.state',
    (rid,user,json.dumps(before),json.dumps(after),expires,'pending'))
 def voice_state(self,rid,state):
  with self.db() as db:db.execute('UPDATE lv_recruit_voice SET state=? WHERE application=?',(state,rid))
