"""Durable bug reports, evidence and audit trail in the bot's existing SQLite."""
from contextlib import contextmanager
import hashlib
import json
import sqlite3
import time
from urllib.parse import urlsplit

STATES = {'pendiente':'🔴 Pendiente','revision':'🟠 En revisión','proceso':'🔵 En proceso','solucionado':'🟢 Solucionado','cerrado':'⚫ Cerrado'}

def clip_url(value):
    value=value.strip()
    if value:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or len(value)>1000:
            raise ValueError('El enlace del clip debe empezar con https://.')
    return value

class BugStore:
    def __init__(self,path):self.path=path
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
    def initialize(self):
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS lv_bugs(id INTEGER PRIMARY KEY,owner INTEGER NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',step INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'borrador',
                thread INTEGER UNIQUE,message INTEGER,assignee INTEGER,created INTEGER NOT NULL,updated INTEGER NOT NULL,
                filename TEXT,video BLOB,sha256 TEXT,pending TEXT,revision INTEGER NOT NULL DEFAULT 0)''')
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS lv_bug_draft ON lv_bugs(owner) WHERE status='borrador'")
            db.execute('''CREATE TABLE IF NOT EXISTS lv_bug_events(id INTEGER PRIMARY KEY,report INTEGER NOT NULL,
                actor INTEGER NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL,created INTEGER NOT NULL)''')
            db.execute('CREATE TABLE IF NOT EXISTS lv_bug_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    def config(self,key,value=None):
        with self.db() as db:
            if value is not None:db.execute('INSERT INTO lv_bug_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
            row=db.execute('SELECT value FROM lv_bug_config WHERE key=?',(key,)).fetchone();return row[0] if row else ''
    def get(self,rid):
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            return dict(row) if row else None
    def begin(self,owner):
        with self.db() as db:
            row=db.execute("SELECT id FROM lv_bugs WHERE owner=? AND status='borrador'",(owner,)).fetchone()
            if row:return row[0]
            if db.execute("SELECT COUNT(*) FROM lv_bugs WHERE owner=? AND status NOT IN ('solucionado','cerrado')",(owner,)).fetchone()[0]>=3:
                raise ValueError('Ya tienes 3 reportes pendientes. Continúa en esos, bro.')
            now=int(time.time());return db.execute('INSERT INTO lv_bugs(owner,created,updated) VALUES (?,?,?)',(owner,now,now)).lastrowid
    def by_thread(self,thread):
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE thread=?',(thread,)).fetchone()
            return dict(row) if row else None
    def save(self,rid,owner,step,values,revision,filename=None,video=None):
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['owner']!=owner or row['status']!='borrador' or row['revision']!=revision:
                raise ValueError('El formulario cambió. Abre tu borrador otra vez.')
            data=json.loads(row['data'])
            if step==1:
                for key in ('player_id','title','description','steps','system'):
                    if not values.get(key,'').strip():raise ValueError('Completa todos los campos, bro.')
                data.update({key:values[key].strip() for key in ('player_id','title','description','steps','system')})
            elif step==2:
                if row['step']<1:raise ValueError('Completa primero los datos del error.')
                if values.get('frequency') not in ('Siempre','A veces','Una sola vez'):raise ValueError('Elige con qué frecuencia pasa.')
                data.update(frequency=values['frequency'],clip=clip_url(values.get('clip','')))
                if not data['clip'] and not video and not row['video']:raise ValueError('Falta el clip, bro. Adjunta el video o pega su enlace.')
                if video is not None and (not video or len(video)>25*1024*1024):raise ValueError('El video debe pesar hasta 25 MB.')
                if video and db.execute('SELECT COALESCE(SUM(length(video)),0) FROM lv_bugs WHERE id!=?',(rid,)).fetchone()[0]+len(video)>200*1024*1024:
                    raise ValueError('No queda espacio para más videos adjuntos ahora. Pega el enlace del clip.')
            else:raise ValueError('Paso desconocido.')
            db.execute('''UPDATE lv_bugs SET data=?,step=?,updated=?,revision=revision+1,
                filename=COALESCE(?,filename),video=COALESCE(?,video),sha256=COALESCE(?,sha256) WHERE id=?''',
                (json.dumps(data,ensure_ascii=False),step,int(time.time()),filename,video,hashlib.sha256(video).hexdigest() if video else None,rid))
    def reserve(self,rid,owner):
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['owner']!=owner:raise ValueError('Ese reporte no es tuyo.')
            if row['thread']:return
            if row['status']=='publicando':raise ValueError('Ese reporte ya se está publicando. Lo recuperaré si Discord tarda.')
            if row['step']!=2:raise ValueError('Completa el formulario primero.')
            data=json.loads(row['data'])
            if not data.get('clip') and not row['video']:raise ValueError('Falta el clip del error.')
            db.execute("UPDATE lv_bugs SET status='publicando' WHERE id=?",(rid,))
    def save_full(self,rid,owner,values,revision,filename=None,video=None):
        limits={'player_id':30,'title':100,'details':2500}
        for key,limit in limits.items():
            if not values.get(key,'').strip() or len(values[key])>limit:raise ValueError('Completa el ID, el título y los detalles del problema.')
        clip=clip_url(values.get('clip',''))
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['owner']!=owner or row['status']!='borrador' or row['revision']!=revision:
                raise ValueError('El formulario cambió. Abre tu borrador otra vez.')
            if not clip and not video and not row['video']:raise ValueError('El clip es obligatorio, bro. Adjunta el video o pega su enlace; el reporte no se envió.')
            if video is not None:
                if not video or len(video)>25*1024*1024 or not filename:raise ValueError('Adjunta un video válido de hasta 25 MB.')
                if db.execute('SELECT COALESCE(SUM(length(video)),0) FROM lv_bugs WHERE id!=?',(rid,)).fetchone()[0]+len(video)>200*1024*1024:
                    raise ValueError('No queda espacio para más archivos ahora. Pega el enlace del clip.')
            data=json.loads(row['data']);data.update({key:values[key].strip() for key in limits});data['clip']=clip
            db.execute('''UPDATE lv_bugs SET data=?,step=2,updated=?,revision=revision+1,
                filename=COALESCE(?,filename),video=COALESCE(?,video),sha256=COALESCE(?,sha256) WHERE id=?''',
                (json.dumps(data,ensure_ascii=False),int(time.time()),filename,video,hashlib.sha256(video).hexdigest() if video else None,rid))
    def published(self,rid,thread,message):
        with self.db() as db:
            db.execute("UPDATE lv_bugs SET thread=?,message=?,status='pendiente',updated=? WHERE id=?",(thread,message,int(time.time()),rid))
    def adopt(self,thread,owner,title,content,clip=''):
        with self.db() as db:
            existing=db.execute('SELECT id FROM lv_bugs WHERE thread=?',(thread,)).fetchone()
            if existing:return existing[0]
            now=int(time.time());data=dict(title=title,description=content[:1200],steps='Ver publicación original',player_id='Ver publicación original',system='Por revisar',frequency='Por revisar',clip=clip,manual=True)
            return db.execute("INSERT INTO lv_bugs(owner,data,status,thread,created,updated) VALUES (?,?,'pendiente',?,?,?)",(owner,json.dumps(data),thread,now,now)).lastrowid
    def manual_clip(self,rid,owner,url):
        url=clip_url(url)
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['owner']!=owner:return
            data=json.loads(row['data']);data['clip']=url
            db.execute('UPDATE lv_bugs SET data=? WHERE id=?',(json.dumps(data),rid))
    def controls(self,rid,message):
        with self.db() as db:db.execute('UPDATE lv_bugs SET message=? WHERE id=?',(message,rid))
    def rows(self,owner=None,recovery=False):
        with self.db() as db:
            if recovery:sql="SELECT * FROM lv_bugs WHERE status='publicando' OR pending IS NOT NULL OR (thread IS NOT NULL AND message IS NULL)";args=()
            else:sql='SELECT * FROM lv_bugs'+(' WHERE owner=?' if owner is not None else '')+' ORDER BY id DESC LIMIT 25';args=(owner,) if owner is not None else ()
            return [dict(r) for r in db.execute(sql,args)]
    def claim(self,rid,actor):
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or not row['thread']:raise ValueError('El reporte todavía no está publicado.')
            if row['assignee'] and row['assignee']!=actor:raise ValueError('Este reporte ya tiene responsable.')
            db.execute('UPDATE lv_bugs SET assignee=? WHERE id=?',(actor,rid));self.event(db,rid,actor,'tomar','')
    def intent(self,rid,actor,state,reason):
        if state not in STATES or not reason.strip():raise ValueError('Elige un estado y explica el cambio.')
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or not row['thread']:raise ValueError('Reporte no encontrado.')
            if state!='cerrado' and not json.loads(row['data']).get('clip') and not row['video']:
                raise ValueError('Falta el clip del error. El jugador debe adjuntarlo antes de continuar.')
            if row['pending']:raise ValueError('Ese reporte está terminando otro cambio. Espera un momento.')
            db.execute('UPDATE lv_bugs SET pending=? WHERE id=?',(json.dumps(dict(actor=actor,state=state,reason=reason[:1500])),rid))
    @staticmethod
    def event(db,rid,actor,action,detail):
        db.execute('INSERT INTO lv_bug_events(report,actor,action,detail,created) VALUES (?,?,?,?,?)',(rid,actor,action,detail,int(time.time())))
    def finish(self,rid):
        with self.db() as db:
            row=db.execute('SELECT pending FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or not row['pending']:return
            pending=json.loads(row['pending']);self.event(db,rid,pending['actor'],pending['state'],pending['reason'])
            db.execute('UPDATE lv_bugs SET status=?,pending=NULL,updated=? WHERE id=?',(pending['state'],int(time.time()),rid))
    def events(self,rid):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM lv_bug_events WHERE report=? ORDER BY id',(rid,))]
    def external_state(self,rid,state):
        if state not in STATES:return False
        with self.db() as db:
            row=db.execute('SELECT * FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['pending'] or row['status']==state:return False
            db.execute('UPDATE lv_bugs SET status=?,updated=? WHERE id=?',(state,int(time.time()),rid))
            self.event(db,rid,0,state,'Etiqueta modificada directamente en Discord; autor no atribuido al bot.');return True
