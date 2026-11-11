"""Validated settings and receipts in the bot's existing SQLite database."""
from sqlite_runtime import transaction
from contextlib import contextmanager
from datetime import datetime,timedelta
import json
from pathlib import Path
import re
from string import Formatter
import time
from settings_catalog import BY_FORM,read_form,validate as validate_system,write_form,exists
from zoneinfo import ZoneInfo

PR=ZoneInfo('America/Puerto_Rico')
DEFAULT_PHOTO_REWARDS=(500,300,150)
DEFAULTS={
    'daily_server_up_time':'18:30',
    'daily_server_up_title':'🔴 SERVER UP | LA VENGANZA RP 🔥',
    'daily_server_up_body':('🌴 ¡Mi gente, la ciudad los espera!\n'
        '🚗 Preparen sus máquinas, reúnan al corillo y entren a disfrutar del mejor roleplay.\n\n'
        '🎮 **CONÉCTATE AQUÍ:**\n{enlace}\n\n'
        '🔴 **LA VENGANZA RP**\n*La ciudad más real · El rol más duro*'),
    'daily_server_up_footer':'La Venganza RP | Aviso diario · {hora} Puerto Rico',
}
TEXT_KEYS=('daily_server_up_title','daily_server_up_body','daily_server_up_footer')


def photo_week(now=None,offset=0):
    local=datetime.fromtimestamp(time.time() if now is None else now,PR)
    return (local.date()-timedelta(days=local.weekday())+timedelta(weeks=offset)).isoformat()


def ensure_settings_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS lv_photo_reward_rates(
        effective_week TEXT PRIMARY KEY,first_coins INTEGER NOT NULL CHECK(first_coins>0),
        second_coins INTEGER NOT NULL CHECK(second_coins>0),third_coins INTEGER NOT NULL CHECK(third_coins>0),
        actor INTEGER NOT NULL,updated INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS bot_setting_ops(
        op TEXT PRIMARY KEY,actor INTEGER NOT NULL,kind TEXT NOT NULL,target TEXT,
        values_json TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,created INTEGER NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS bot_setting_jobs(op TEXT PRIMARY KEY,state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL,error_type TEXT)''')
    db.execute('CREATE INDEX IF NOT EXISTS bot_setting_jobs_state ON bot_setting_jobs(state)')
    db.execute('CREATE INDEX IF NOT EXISTS bot_setting_ops_created ON bot_setting_ops(created)')


def photo_rewards_in(db,week):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lv_photo_reward_rates'").fetchone():
        return DEFAULT_PHOTO_REWARDS
    row=db.execute('''SELECT first_coins,second_coins,third_coins FROM lv_photo_reward_rates
        WHERE effective_week<=? ORDER BY effective_week DESC LIMIT 1''',(week,)).fetchone()
    return tuple(row) if row else DEFAULT_PHOTO_REWARDS


def parse_hour(value):
    if not isinstance(value,str):raise ValueError('Escribe una hora como 18:30 o 6:30 p. m.')
    value=value.casefold().replace(' ','').replace('.','')
    match=re.fullmatch(r'(\d{1,2}):(\d{2})(am|pm)?',value)
    if not match:raise ValueError('Escribe una hora como 18:30 o 6:30 p. m.')
    hour,minute=int(match[1]),int(match[2]);suffix=match[3]
    if minute>59 or (suffix and not 1<=hour<=12) or (not suffix and hour>23):
        raise ValueError('Esa hora no es válida. Ejemplo: 18:30 o 6:30 p. m.')
    if suffix:hour=hour%12+(12 if suffix=='pm' else 0)
    return f'{hour:02}:{minute:02}'


def friendly_hour(value):
    hour,minute=map(int,parse_hour(value).split(':'))
    return f"{hour%12 or 12}:{minute:02} {'p. m.' if hour>=12 else 'a. m.'}"


def validate_template(value,limit,label):
    if not isinstance(value,str):raise ValueError(f'{label} debe ser texto.')
    value=value.strip()
    if not value or len(value)>limit:raise ValueError(f'{label} debe tener entre 1 y {limit} caracteres.')
    try:
        for _,field,spec,conversion in Formatter().parse(value):
            if field is not None and (field not in {'enlace','servidor','hora'} or spec or conversion):
                raise ValueError()
    except ValueError:
        raise ValueError('En los textos solo puedes usar {enlace}, {servidor} y {hora}. Revisa las llaves.') from None
    return value


def validate_values(kind,values):
    if kind=='rewards':
        try:
            if not isinstance(values,(list,tuple)):raise ValueError()
            coins=[]
            for value in values:
                if isinstance(value,bool):raise ValueError()
                text=str(value).strip()
                if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',text):text=text.replace(',','').replace('.','')
                if not re.fullmatch(r'\d+',text):raise ValueError()
                coins.append(int(text))
            if len(coins)!=3 or not all(1<=n<=1_000_000 for n in coins) or coins!=sorted(coins,reverse=True):raise ValueError()
        except (ValueError,TypeError):
            raise ValueError('Pon tres premios enteros entre 1 y 1,000,000 monedas. El primero debe ser igual o mayor que el segundo, y el segundo que el tercero.') from None
        return coins
    if kind=='schedule':return parse_hour(values)
    if kind=='text':
        if not isinstance(values,dict) or set(values)!=set(TEXT_KEYS):raise ValueError('Revisa los tres textos del Server Up.')
        result={key:validate_template(values[key],limit,label) for key,limit,label in zip(TEXT_KEYS,(150,3000,150),('El título','El mensaje','El pie del mensaje'))}
        if not any(field=='enlace' for _,field,_,_ in Formatter().parse(result['daily_server_up_body'])):
            raise ValueError('Deja {enlace} en el mensaje para que los jugadores puedan conectarse al servidor.')
        sample=dict(enlace='https://cfx.re/join/57vjg7',servidor='La Venganza RP',hora='12:59 p. m.')
        sizes=[len(result[key].format_map(sample)) for key in TEXT_KEYS]
        if any(size>limit for size,limit in zip(sizes,(256,4096,2048))) or sum(sizes)>5000:
            raise ValueError('El mensaje queda demasiado largo al añadir el enlace. Hazlo más corto.')
        return result
    raise ValueError('Ese ajuste no está disponible.')


class SettingsStore:
    def __init__(self,path):self.path=Path(path)

    @contextmanager
    def db(self, *, readonly=False):
        with transaction(self.path, readonly=readonly, foreign_keys=False, timeout=10) as db:
            yield db

    def initialize(self):
        with self.db() as db:ensure_settings_schema(db)

    @staticmethod
    def get_in(db,key,default=''):
        row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return row[0] if row else default

    def snapshot_in(self,db,now):
        week=photo_week(now);next_week=photo_week(now,1)
        return dict(revision=int(self.get_in(db,'admin_settings_revision','0')),
            values={key:self.get_in(db,key,value) for key,value in DEFAULTS.items()},
            week=week,next_week=next_week,rewards=list(photo_rewards_in(db,week)),next_rewards=list(photo_rewards_in(db,next_week)),
            daily_slot=self.get_in(db,'daily_server_up_slot',''),
            systems={key:read_form(db,key) for key in BY_FORM})

    def snapshot(self,now=None):
        with self.db(readonly=True) as db:return self.snapshot_in(db,int(time.time()) if now is None else now)

    def receipt(self,op):
        with self.db(readonly=True) as db:
            row=db.execute('SELECT * FROM bot_setting_ops WHERE op=?',(op,)).fetchone()
            return dict(row) if row else None

    def apply(self,kind,values,expected_revision,actor,op,target=None,now=None,expected_fields=None):
        if kind=='system':values=validate_system(target,values)
        elif kind=='product':
            if not isinstance(values,dict) or set(values)!={'price','active'} or type(values['active']) is not bool:
                raise ValueError('Revisa el precio y la disponibilidad del producto.')
            text=str(values['price']).strip()
            if not text.isdecimal() or not 0<=int(text)<=1000000:raise ValueError('El precio debe ser un entero entre 0 y 1,000,000 monedas.')
            values=dict(price=int(text),active=values['active'])
        else:values=validate_values(kind,values)
        now=int(time.time()) if now is None else now
        encoded=json.dumps(values,ensure_ascii=False,sort_keys=True)
        with self.db() as db:
            previous=db.execute('SELECT * FROM bot_setting_ops WHERE op=?',(op,)).fetchone()
            if previous:
                if (previous['actor'],previous['kind'],previous['target'],previous['values_json'])!=(actor,kind,target,encoded):
                    raise ValueError('Esta confirmación pertenece a otro cambio.')
                return json.loads(previous['after_json'])
            before=self.snapshot_in(db,now)
            if before['revision']!=expected_revision:
                raise ValueError('Alguien cambió los ajustes mientras tenías el panel abierto. Abre /ajustes panel otra vez para revisarlos.')
            if kind=='system':
                if expected_fields is not None and before['systems'][target]!=expected_fields:
                    raise ValueError('Estos ajustes cambiaron desde otro comando. Abre el formulario otra vez.')
                if target=='ticket_files' and exists(db,'lv_ticket_blobs'):
                    used=db.execute('SELECT COALESCE(SUM(length(data)),0) FROM lv_ticket_blobs').fetchone()[0]
                    if used>values['max_total_mb']*1048576:raise ValueError('Ese límite queda por debajo de las pruebas ya guardadas. Se conservan todos los archivos.')
                write_form(db,target,values)
            elif kind=='product':
                row=db.execute('SELECT sku,name,price,active,revision FROM eco_products WHERE sku=?',(target,)).fetchone()
                if not row:raise ValueError('Ese producto ya no está en el catálogo.')
                before['product']=dict(row)
                if expected_fields is not None and dict(row)!=expected_fields:raise ValueError('El producto cambió. Abre su formulario otra vez.')
                db.execute('UPDATE eco_products SET price=?,active=?,revision=revision+1 WHERE sku=?',(values['price'],int(values['active']),target))
            elif kind=='rewards':
                if target not in (before['week'],before['next_week']):raise ValueError('Esa semana ya pasó. Abre el panel otra vez.')
                if target==before['week'] and db.execute("SELECT 1 FROM sqlite_master WHERE name='lv_photo_weeks'").fetchone():
                    current=db.execute('SELECT state,ends,podium_closed FROM lv_photo_weeks WHERE week=?',(target,)).fetchone()
                    if current and (current['state']!='open' or current['ends']<=now or current['podium_closed'] is not None):
                        raise ValueError('Esa semana ya está cerrada. Cambia los premios desde la próxima.')
                db.execute('''INSERT INTO lv_photo_reward_rates VALUES (?,?,?,?,?,?) ON CONFLICT(effective_week) DO UPDATE SET
                    first_coins=excluded.first_coins,second_coins=excluded.second_coins,third_coins=excluded.third_coins,
                    actor=excluded.actor,updated=excluded.updated''',(target,*values,actor,now))
            else:
                updates={'daily_server_up_time':values} if kind=='schedule' else values
                for key,value in updates.items():db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,value))
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('admin_settings_revision',str(expected_revision+1)))
            after=self.snapshot_in(db,now)
            if kind=='product':after['product']=dict(db.execute('SELECT sku,name,price,active,revision FROM eco_products WHERE sku=?',(target,)).fetchone())
            db.execute('INSERT INTO bot_setting_ops VALUES (?,?,?,?,?,?,?,?)',
                (op,actor,kind,target,encoded,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),now))
            db.execute('INSERT INTO bot_setting_jobs(op,updated) VALUES (?,?)',(op,now))
            return after

    def history(self,limit=8,offset=0):
        with self.db(readonly=True) as db:
            return [dict(r) for r in db.execute('SELECT o.*,j.state AS sync_state,j.error_type FROM bot_setting_ops o LEFT JOIN bot_setting_jobs j ON j.op=o.op ORDER BY o.created DESC,o.rowid DESC LIMIT ? OFFSET ?',(limit,offset))]

    def pending(self):
        with self.db(readonly=True) as db:
            return [dict(r) for r in db.execute("SELECT o.* FROM bot_setting_jobs j JOIN bot_setting_ops o ON o.op=j.op WHERE j.state='pending' ORDER BY o.created LIMIT 8")]

    def job_status(self,op):
        with self.db(readonly=True) as db:
            row=db.execute('SELECT state FROM bot_setting_jobs WHERE op=?',(op,)).fetchone()
            return row['state'] if row else None

    def synced(self,op,error=None):
        with self.db() as db:
            db.execute('UPDATE bot_setting_jobs SET state=?,attempts=attempts+1,updated=?,error_type=? WHERE op=?',
                ('pending' if error else 'done',int(time.time()),error,op))

    def catalog(self):
        with self.db(readonly=True) as db:
            if not exists(db,'eco_products'):return []
            return [dict(r) for r in db.execute('SELECT sku,name,price,active,revision,kind FROM eco_products ORDER BY active DESC,price,name')]
