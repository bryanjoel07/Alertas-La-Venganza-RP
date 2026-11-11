"""Allowlisted admin settings. No secrets, role edits or arbitrary SQL keys."""
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path

from sqlite_runtime import transaction

GUILD=1244988345327550565
TIMES=((86400,'24 horas'),(43200,'12 horas'),(21600,'6 horas'),(3600,'1 hora'),(900,'15 minutos'),(300,'5 minutos'),(0,'Al comenzar'))

@dataclass(frozen=True)
class Field:
    key:str
    label:str
    default:object
    kind:str='int'
    low:int=0
    high:int=1000000
    help:str=''
    table:str='settings'
    storage:str=''
    options:tuple=()

@dataclass(frozen=True)
class Form:
    key:str
    section:str
    title:str
    description:str
    fields:tuple

@dataclass(frozen=True)
class Section:
    key:str
    emoji:str
    title:str
    description:str
    commands:tuple=()
    channel:int|None=None

SECTIONS=(
 Section('server','📡','Servidor y avisos','Horario, mensajes, menciones y estado del servidor.',('estado-bot','mantenimiento','historial-caidas'),1567618156963430440),
 Section('tickets','🎫','Tickets','Entrada de casos, recordatorios, atención y archivos.',('ticket',),1513423707467415642),
 Section('economy','🛍️','Tienda y monedas','Precios, catálogo, premios y gestión de la economía.',('economia','tienda','comprar','regalar','inventario','equipar','quitar','trofeo','movimientos','deseos','saldo','retos','probar','perfil','sala')),
 Section('photos','📸','Fotos','Participación y premios del podio semanal.',('foto',),1513422142014754976),
 Section('games','🧩','Minijuegos','Turnos y modos de juego disponibles.',('minijuegos','jugar'),1513422089162330184),
 Section('feedback','⭐','Feedback','Opiniones sobre la atención del staff.',('feedback',),1539014594348064939),
 Section('suggestions','💡','Sugerencias','Ideas de los jugadores y votaciones.',('sugerencias',),1539013973947588759),
 Section('bugs','🐛','Reportes de errores','Entrada de reportes y seguimiento de fallos.',('errores',),1556488595131466000),
 Section('recruitment','👥','Solicitudes de staff','Abrir postulaciones y coordinar entrevistas.',('staff',),1567399097500041237),
 Section('streams','📺','Creadores y directos','Requisitos del rol y anuncios de los creadores.',('streamer',),1568403146219454586),
 Section('events','🏁','Eventos','Recordatorios y gestión de eventos.',('evento',),1545468565120098364),
 Section('meetings','📅','Reuniones','Avisos de reuniones de staff y comunidad.',('reunion',)),
 Section('security','🛡️','Seguridad','Palabras bloqueadas y enlaces repetidos.',()),
 Section('rules','📚','Normas y guía','Fuente de las normas y presentación de la guía.',('regla','guia'),1528925322362228787),
 Section('backups','💾','Respaldos','Horario de las copias y recuperación de prueba.',('respaldo',)),
 Section('activity','🧾','Historial y diagnóstico','Cambios, estado de las tareas y configuración guardada.',('cambios','estado-bot')),
)
BY_SECTION={s.key:s for s in SECTIONS}

def kv(key,label,default,table,low=0,high=1000000,kind='int',help=''):
 return Field(key,label,default,kind,low,high,help,table,key)

FORMS=(
 Form('announcements','server','Avisos y menciones','Los cambios se usan en los próximos avisos. Guardar no publica un mensaje.',(
  Field('daily_enabled','Aviso diario de Server Up',True,'bool'),Field('everyone','Mencionar a todos en los avisos',True,'bool'))),
 Form('ticket_attention','tickets','Atención de tickets','Se conservan los tickets abiertos, sus responsables y su privacidad.',(
  kv('max_open','Tickets abiertos por jugador',3,'lv_ticket_config',1,20),
  kv('remind_hours','Recordar sin responsable cada (horas)',6,'lv_ticket_config',1,168),
  kv('escalate_hours','Avisar al encargado después de (horas)',24,'lv_ticket_config',1,168),
  kv('inactive_hours','Esperar al jugador (horas)',72,'lv_ticket_config',1,720),
  kv('close_warning_hours','Aviso antes de archivar (horas)',24,'lv_ticket_config',1,168))),
 Form('ticket_notices','tickets','Horario y mensajes privados','Las horas son de Puerto Rico. Poner la misma hora en ambos campos elimina el horario de madrugada.',(
  Field('night_start','Inicio del horario de madrugada','00:00','time'),Field('night_end','Fin del horario de madrugada','08:00','time'),
  kv('dm_minutes','Pausa entre avisos privados (minutos)',15,'lv_ticket_config',1,1440),
  kv('dm_enabled','Avisos privados al jugador',True,'lv_ticket_config',kind='bool'))),
 Form('ticket_files','tickets','Archivos de tickets','Límites para respaldar nuevas pruebas. Los archivos guardados se conservan.',(
  kv('max_file_mb','Máximo por archivo (MB)',25,'lv_ticket_config',1,120),
  kv('max_case_mb','Máximo por ticket (MB)',100,'lv_ticket_config',1,2000),
  kv('max_total_mb','Máximo total de pruebas (MB)',500,'lv_ticket_config',1,2000))),
 Form('event_rewards','economy','Premios de eventos','Se usan en los próximos pagos. Los premios ya entregados no cambian.',(
  Field('first','Primer lugar',500,table='eco_rewards'),Field('second','Segundo lugar',350,table='eco_rewards'),
  Field('third','Tercer lugar',250,table='eco_rewards'),Field('participant','Participación confirmada',100,table='eco_rewards'))),
 Form('photo_entries','photos','Participación en Fotos','Pausar la entrada permite terminar de publicar las fotos ya recibidas. El podio sigue cerrando normalmente.',(
  kv('accepting','Recibir fotos nuevas',True,'lv_photo_config',kind='bool'),
  kv('weekly_limit','Fotos por jugador y semana',0,'lv_photo_config',0,100,help='0 significa sin límite.'))),
 Form('games','games','Turnos y modos de juego','Conserva aciertos, preguntas empezadas y monedas ganadas. El premio por acierto sigue siendo 25 monedas.',(
  kv('interval_hours','Tiempo entre respuestas (horas)',12,'lv_game_config',1,168),
  kv('foto_enabled','Adivinar lugares de GTA',True,'lv_game_config',kind='bool'),
  kv('roleplay_enabled','Preguntas de roleplay',True,'lv_game_config',kind='bool'),
  kv('acertijo_enabled','Acertijos',True,'lv_game_config',kind='bool'))),
 Form('feedback','feedback','Opiniones sobre la atención','Las valoraciones de tickets conservan su privacidad y su límite de una por caso.',(
  kv('outside_enabled','Valorar atención fuera de tickets',True,'lv_feedback_config',kind='bool'),
  kv('outside_hours','Tiempo entre opiniones externas (horas)',24,'lv_feedback_config',1,720))),
 Form('suggestions','suggestions','Ideas y votaciones','Pausar la entrada o los votos conserva las ideas y sus votos actuales.',(
  kv('accepting','Recibir ideas nuevas',True,'lv_suggestion_config',kind='bool'),
  kv('cooldown_minutes','Tiempo entre ideas (minutos)',1,'lv_suggestion_config',0,1440),
  kv('voting','Permitir votos',True,'lv_suggestion_config',kind='bool'))),
 Form('bugs','bugs','Entrada de reportes','Los borradores existentes pueden terminarse. Las pruebas siguen siendo obligatorias: hasta diez archivos de 120 MB cada uno.',(
  kv('accepting','Recibir reportes nuevos',True,'lv_bug_config',kind='bool'),
  kv('max_open','Reportes pendientes por jugador',3,'lv_bug_config',1,30),
  kv('cooldown_minutes','Tiempo entre reportes (minutos)',0,'lv_bug_config',0,1440))),
 Form('recruitment','recruitment','Postulaciones y entrevistas','Los casos existentes siguen disponibles. Administración conserva la asignación manual de roles.',(
  kv('open','Recibir solicitudes de staff',True,'lv_recruit_config',kind='bool'),
  kv('cooldown_minutes','Tiempo entre solicitudes (minutos)',5,'lv_recruit_config',0,1440),
  kv('interview_notice_minutes','Recordar entrevista con anticipación (min)',60,'lv_recruit_config',5,1440))),
 Form('streams','streams','Creadores y avisos de directos','Cambiar seguidores solo afecta verificaciones nuevas. Los directos siguen requiriendo La Venganza RP en el título.',(
  Field('minimum','Mínimo de seguidores',50,low=1,high=1000000,table='streamer_minimum'),
  Field('alerts_enabled','Anunciar directos',True,'bool'))),
 Form('event_notices','events','Recordatorios de eventos','Elige cuándo avisar. Los recordatorios ya enviados no se repiten.',(
  Field('times','Avisar antes del evento',[86400,43200,21600,3600,900,0],'multi',options=TIMES[:5]+TIMES[6:]),)),
 Form('meeting_notices','meetings','Recordatorios de reuniones','Se conservan las confirmaciones y la asistencia. Los avisos ya enviados no se repiten.',(
  Field('times','Cuándo recordar la reunión',[86400,43200,21600,3600,900,300,0],'multi',options=TIMES),
  Field('staff','Recordatorios de staff',True,'bool'),Field('general','Recordatorios de la comunidad',True,'bool'))),
 Form('security','security','Filtro de palabras','Se conserva la lista base y todas las exenciones actuales. Las palabras añadidas se suman al filtro.',(
  Field('enabled','Bloquear palabras obscenas',True,'bool'),
  Field('words','Palabras adicionales','',kind='words',high=1500,help='Una palabra o frase por línea. Máximo 50.'),
  Field('spam_channels','Mismo enlace en cuántos canales',3,low=3,high=20),
  Field('spam_minutes','Revisar enlaces durante (minutos)',5,low=1,high=60))),
 Form('rules','rules','Buscador de normas','Solo consulta el canal elegido. No modifica sus mensajes ni sus permisos.',(
  Field('source_channel','Canal oficial de normas',1528925322362228787,'channel'),
  Field('cache_minutes','Actualizar el índice cada (minutos)',5,low=1,high=60))),
 Form('guide','rules','Presentación de la guía','Los botones y enlaces de las funciones se conservan.',(
  Field('title','Título de la guía','📖 GUÍA DEL BOT | LA VENGANZA RP','text',high=150),
  Field('intro','Texto de bienvenida','Pulsa un botón para abrir el canal correspondiente.\nAllí encontrarás los comandos y paneles para usar cada función.','text',high=1800))),
 Form('backups','backups','Horario de respaldos','Usa la conexión de Drive ya configurada. No solicita ni muestra contraseñas o claves.',(
  Field('automatic','Respaldos automáticos',lambda:os.getenv('AUTO_BACKUP_ENABLED','0').lower() in ('1','true'),'bool'),
  Field('time','Hora de Puerto Rico',lambda:os.getenv('BACKUP_TIME_PR','03:00'),'time'))),
)
BY_FORM={f.key:f for f in FORMS}
TABLES={'settings','lv_ticket_config','eco_rewards','lv_photo_config','lv_game_config','lv_feedback_config','lv_suggestion_config','lv_bug_config','lv_recruit_config','streamer_minimum'}


def default(field):return field.default() if callable(field.default) else field.default

def exists(db,table):
 return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() is not None


def read_value(db,form_id,key,fallback_override=...):
 field=next(f for f in BY_FORM[form_id].fields if f.key==key)
 fallback=default(field) if fallback_override is ... else fallback_override;table=field.table
 if table=='eco_rewards':
  row=db.execute("SELECT value FROM eco_config WHERE key='rewards'").fetchone() if exists(db,'eco_config') else None
  raw=json.loads(row[0]).get(key,fallback) if row else fallback
 elif table=='streamer_minimum':
  row=db.execute('SELECT minimum FROM streamer_config WHERE guild=?',(GUILD,)).fetchone() if exists(db,'streamer_config') else None
  raw=row[0] if row else fallback
 else:
  assert table in TABLES
  storage=field.storage or f'panel.{form_id}.{key}'
  row=db.execute(f'SELECT value FROM {table} WHERE key=?',(storage,)).fetchone() if exists(db,table) else None
  raw=row[0] if row else fallback
 if field.kind=='bool':return raw in (True,1,'1','true','True')
 if field.kind in ('int','channel'):return int(raw)
 if field.kind=='multi':return list(raw) if isinstance(raw,(list,tuple)) else json.loads(raw)
 return str(raw)


def read_form(db,key):return {f.key:read_value(db,key,f.key) for f in BY_FORM[key].fields}


def value(path,form,key,fallback_override=...):
 if not Path(path).is_file():
  field=next(f for f in BY_FORM[form].fields if f.key==key)
  return default(field) if fallback_override is ... else fallback_override
 with transaction(path,readonly=True) as db:return read_value(db,form,key,fallback_override)


def validate(form_id,values):
 if form_id not in BY_FORM:raise ValueError('Ese grupo de ajustes no existe.')
 form=BY_FORM[form_id]
 if not isinstance(values,dict) or set(values)!={f.key for f in form.fields}:raise ValueError('Revisa todos los campos del formulario.')
 result={}
 for field in form.fields:
  raw=values[field.key]
  if field.kind=='bool':
   if type(raw) is not bool:raise ValueError(f'Revisa «{field.label}».')
   result[field.key]=raw
  elif field.kind in ('int','channel'):
   text=str(raw).strip()
   if field.kind=='int' and re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',text):text=text.replace(',','').replace('.','')
   if isinstance(raw,bool) or not text.isdecimal():raise ValueError(f'«{field.label}» necesita un número entero.')
   n=int(text)
   low,high=(1,2**64-1) if field.kind=='channel' else (field.low,field.high)
   if not low<=n<=high:raise ValueError(f'«{field.label}» debe estar entre {low:,} y {high:,}.')
   result[field.key]=n
  elif field.kind=='multi':
   allowed={v for v,_ in field.options}
   if isinstance(raw,(tuple,list)) and any(isinstance(v,bool) for v in raw):raise ValueError('Elige los horarios de la lista.')
   try:chosen=[int(v) for v in raw] if isinstance(raw,(tuple,list)) else []
   except (ValueError,TypeError):raise ValueError('Elige los horarios de la lista.') from None
   if not isinstance(raw,(tuple,list)) or len(chosen)!=len(set(chosen)) or not set(chosen)<=allowed:raise ValueError('Elige los horarios de la lista.')
   result[field.key]=[v for v,_ in field.options if v in chosen]
  elif field.kind=='time':
   from bot_settings import parse_hour
   result[field.key]=parse_hour(raw)
  else:
   if not isinstance(raw,str):raise ValueError(f'Revisa «{field.label}».')
   text=raw.strip()
   if len(text)>field.high or (not text and field.kind!='words'):raise ValueError(f'Revisa «{field.label}»: hasta {field.high} letras.')
   if field.kind=='words':
    words=list(dict.fromkeys(w.strip().casefold() for w in text.splitlines() if w.strip()))
    if len(words)>50 or any(len(w)>60 or not all(c.isalnum() or c==' ' for c in w) for w in words):raise ValueError('Pon hasta 50 palabras o frases, una por línea, sin símbolos especiales.')
    text='\n'.join(words)
   result[field.key]=text
 if form_id=='ticket_files' and not result['max_file_mb']<=result['max_case_mb']<=result['max_total_mb']:
  raise ValueError('El límite total debe cubrir el de un ticket, y el del ticket debe cubrir un archivo.')
 if form_id=='event_rewards' and not result['first']>=result['second']>=result['third']:
  raise ValueError('El primer premio debe ser igual o mayor que el segundo, y el segundo que el tercero.')
 return result


def write_form(db,form_id,values):
 for field in BY_FORM[form_id].fields:
  raw=values[field.key]
  if field.table=='eco_rewards':continue
  if field.table=='streamer_minimum':
   if not db.execute('UPDATE streamer_config SET minimum=? WHERE guild=?',(raw,GUILD)).rowcount:raise ValueError('Primero hay que configurar el rol de creadores en el servidor.')
   continue
  table=field.table
  if not exists(db,table):raise ValueError('Ese sistema todavía no está preparado. Vuelve a intentarlo cuando termine de iniciar.')
  encoded=('1' if raw else '0') if field.kind=='bool' else json.dumps(raw) if field.kind=='multi' else str(raw)
  db.execute(f'INSERT INTO {table}(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(field.storage or f'panel.{form_id}.{field.key}',encoded))
 if form_id=='event_rewards':
  row=db.execute("SELECT value FROM eco_config WHERE key='rewards'").fetchone()
  rewards=json.loads(row[0]) if row else {};rewards.update(values)
  db.execute("INSERT INTO eco_config VALUES ('rewards',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(rewards),))
