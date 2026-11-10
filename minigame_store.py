"""Atomic minigame answers and 25-coin payments in the existing economy."""
from sqlite_runtime import transaction
from contextlib import contextmanager
import json
from pathlib import Path
import secrets
import time
import unicodedata

from economy_store import EconomyStore
from minigame_catalog import KINDS

REWARD=25
ANSWER_INTERVAL=12*60*60

class AnswerWait(ValueError):
 def __init__(self,next_at):
  self.next_at=next_at
  super().__init__(f'⏳ Ya usaste tu turno, bro. Puedes responder otra vez <t:{next_at}:R>\nPróximo turno: <t:{next_at}:F>.')

def normalize(text):
 text=unicodedata.normalize('NFKD',str(text)).casefold()
 text=''.join(c for c in text if unicodedata.category(c) not in {'Mn','Cf'})
 words=''.join(c if c.isalnum() else ' ' for c in text).split()
 prefixes=('la respuesta es','creo que es','creo que','es','el','la','los','las','un','una','tu','mi')
 while words:
  found=False
  for prefix in prefixes:
   tokens=prefix.split()
   if words[:len(tokens)]==tokens:words=words[len(tokens):];found=True;break
  if not found:break
 return ' '.join(words)

class MinigameStore:
 def __init__(self,path):self.path=Path(path)
 @contextmanager
 def db(self, *, readonly=False):
     with transaction(self.path, readonly=readonly, foreign_keys=False, timeout=10) as db:
         yield db
 def initialize(self,questions):
  with self.db() as db:
   statements=[
    '''CREATE TABLE IF NOT EXISTS lv_game_questions(id TEXT PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1)''',
    '''CREATE TABLE IF NOT EXISTS lv_game_sessions(id TEXT PRIMARY KEY,user INTEGER NOT NULL,question TEXT NOT NULL,payload TEXT NOT NULL,
     status TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL)''',
    "CREATE UNIQUE INDEX IF NOT EXISTS lv_game_one_active ON lv_game_sessions(user) WHERE status='active'",
    '''CREATE TABLE IF NOT EXISTS lv_game_wins(user INTEGER NOT NULL,question TEXT NOT NULL,session TEXT NOT NULL UNIQUE,
     coins INTEGER NOT NULL CHECK(coins=25),ledger_op TEXT NOT NULL UNIQUE,created INTEGER NOT NULL,PRIMARY KEY(user,question))''',
    '''CREATE TABLE IF NOT EXISTS lv_game_attempts(op TEXT PRIMARY KEY,user INTEGER NOT NULL,session TEXT NOT NULL,
     result TEXT NOT NULL,created INTEGER NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS lv_game_config(key TEXT PRIMARY KEY,value TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS lv_game_turns(user INTEGER PRIMARY KEY,last_answer INTEGER NOT NULL)''',
   ]
   for sql in statements:db.execute(sql)
   # Carry actual answers forward from the previous release, including wrong guesses.
   # Replays of completed/skipped sessions never start or extend the waiting period.
   latest={}
   for row in db.execute('SELECT user,created,result FROM lv_game_attempts'):
    if json.loads(row['result']).get('state') in {'correct','wrong'}:
     latest[row['user']]=max(latest.get(row['user'],row['created']),row['created'])
   for user,stamp in latest.items():
    db.execute('INSERT INTO lv_game_turns VALUES (?,?) ON CONFLICT(user) DO UPDATE SET last_answer=MAX(last_answer,excluded.last_answer)',(user,stamp))
   db.execute('UPDATE lv_game_questions SET enabled=0')
   for q in questions:
    if q['kind'] not in KINDS or not q['id'] or not q['aliases'] or not all(normalize(a) for a in q['aliases']):raise ValueError('Pregunta incompleta.')
    db.execute('INSERT INTO lv_game_questions VALUES (?,?,?,1) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,payload=excluded.payload,enabled=1',
     (q['id'],q['kind'],json.dumps(q,ensure_ascii=False)))
 def config(self,key,value=None):
  with self.db(readonly=value is None) as db:
   if value is not None:db.execute('INSERT INTO lv_game_config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))
   row=db.execute('SELECT value FROM lv_game_config WHERE key=?',(key,)).fetchone();return row[0] if row else ''
 @staticmethod
 def _session(db,token,user):
  row=db.execute('SELECT * FROM lv_game_sessions WHERE id=? AND user=?',(token,user)).fetchone()
  if not row:raise ValueError('Esa pregunta no es tuya. Abre tu propio minijuego en General.')
  return dict(row)
 def get(self,token,user):
  with self.db(readonly=True) as db:return self._session(db,token,user)
 @staticmethod
 def _availability(db,user,stamp):
  row=db.execute('SELECT last_answer FROM lv_game_turns WHERE user=?',(user,)).fetchone()
  next_at=row['last_answer']+ANSWER_INTERVAL if row else None
  return {'available':next_at is None or stamp>=next_at,'next_at':next_at,
   'last_answer':row['last_answer'] if row else None}
 def availability(self,user,now=None):
  with self.db(readonly=True) as db:return self._availability(db,user,int(time.time()) if now is None else now)
 def open(self,user,kind,previous=None,skip=False,now=None):
  if kind not in KINDS:raise ValueError('Elige fotos, roleplay o acertijos.')
  stamp=int(time.time()) if now is None else now
  with self.db() as db:
   if previous:self._session(db,previous,user)
   active=db.execute("SELECT * FROM lv_game_sessions WHERE user=? AND status='active'",(user,)).fetchone()
   if active:
    payload=json.loads(active['payload'])
    if (payload['kind']==kind and not (skip and active['id']==previous)) or (previous and active['id']!=previous):return dict(active)
    db.execute("UPDATE lv_game_sessions SET status='skipped',updated=? WHERE id=?",(stamp,active['id']))
   eligible=db.execute('''SELECT q.id,q.payload FROM lv_game_questions q WHERE q.kind=? AND q.enabled=1
    AND NOT EXISTS (SELECT 1 FROM lv_game_wins w WHERE w.user=? AND w.question=q.id)''',(kind,user)).fetchall()
   if not eligible:return None
   if skip and len(eligible)>1:eligible=[q for q in eligible if q['id']!=self._session(db,previous,user)['question']]
   selected=secrets.choice(eligible);token=secrets.token_hex(12)
   db.execute("INSERT INTO lv_game_sessions VALUES (?,?,?,?,'active',?,?)",(token,user,selected['id'],selected['payload'],stamp,stamp))
   return self._session(db,token,user)
 def answer(self,user,token,text,op,bot_id,now=None):
  stamp=int(time.time()) if now is None else now
  if not str(text).strip() or len(str(text))>150:raise ValueError('Escribe una respuesta corta, de hasta 150 caracteres.')
  with self.db() as db:
   receipt=db.execute('SELECT * FROM lv_game_attempts WHERE op=?',(op,)).fetchone()
   if receipt:
    if receipt['user']!=user or receipt['session']!=token:raise ValueError('Ese intento pertenece a otra pregunta.')
    result=json.loads(receipt['result']);result['replayed']=True
    if result['state'] in {'correct','wrong'}:result.setdefault('next_at',receipt['created']+ANSWER_INTERVAL)
    return result
   session=self._session(db,token,user);question=json.loads(session['payload'])
   balance=db.execute('SELECT balance FROM eco_accounts WHERE user_id=?',(user,)).fetchone();balance=balance[0] if balance else 0
   result={'state':'already' if session['status']=='correct' else 'skipped','coins':0,'balance':balance,'question':session['question']}
   if session['status']=='active':
    turn=self._availability(db,user,stamp)
    if not turn['available']:raise AnswerWait(turn['next_at'])
    correct=normalize(text) in {normalize(a) for a in question['aliases']}
    result['state']='correct' if correct else 'wrong'
    if correct:
     ledger_op=f'minigame:{session["question"]}:{user}'
     previous=db.execute('SELECT * FROM lv_game_wins WHERE user=? AND question=?',(user,session['question'])).fetchone()
     if previous:
      result['state']='already'
     else:
      paid=EconomyStore.credit(db,user,REWARD,ledger_op,f'Minijuego · {session["question"]}',bot_id)
      if not paid:raise ValueError('Ese premio ya tiene un recibo. El staff debe revisar el saldo antes de repetirlo.')
      db.execute('INSERT INTO lv_game_wins VALUES (?,?,?,?,?,?)',(user,session['question'],token,REWARD,ledger_op,stamp))
      result['coins']=REWARD;result['balance']=balance+REWARD
     db.execute("UPDATE lv_game_sessions SET status='correct',updated=? WHERE id=?",(stamp,token))
    db.execute('INSERT INTO lv_game_turns VALUES (?,?) ON CONFLICT(user) DO UPDATE SET last_answer=excluded.last_answer',(user,stamp))
    result['next_at']=stamp+ANSWER_INTERVAL
   db.execute('INSERT INTO lv_game_attempts VALUES (?,?,?,?,?)',(op,user,token,json.dumps(result),stamp))
   return result
 def progress(self,user):
  with self.db(readonly=True) as db:
   kinds=[]
   for kind in KINDS:
    total=db.execute('SELECT COUNT(*) FROM lv_game_questions WHERE kind=? AND enabled=1',(kind,)).fetchone()[0]
    won=db.execute('SELECT COUNT(*) FROM lv_game_wins w JOIN lv_game_questions q ON q.id=w.question WHERE w.user=? AND q.kind=? AND q.enabled=1',(user,kind)).fetchone()[0]
    kinds.append({'kind':kind,'total':total,'won':won})
   coins=db.execute('SELECT COALESCE(SUM(coins),0) FROM lv_game_wins WHERE user=?',(user,)).fetchone()[0]
   balance=db.execute('SELECT balance FROM eco_accounts WHERE user_id=?',(user,)).fetchone()
   return {'kinds':kinds,'coins':coins,'balance':balance[0] if balance else 0,
    'turn':self._availability(db,user,int(time.time()))}
 def ranking(self):
  with self.db(readonly=True) as db:return [dict(r) for r in db.execute('SELECT user,COUNT(*) AS correct,SUM(coins) AS coins FROM lv_game_wins GROUP BY user ORDER BY correct DESC,MIN(created),user LIMIT 10')]
 def audit(self):
  with self.db(readonly=True) as db:
   invalid=db.execute('''SELECT COUNT(*) FROM lv_game_wins w LEFT JOIN eco_ledger l ON l.op=w.ledger_op
    WHERE l.op IS NULL OR l.user_id!=w.user OR l.amount!=w.coins''').fetchone()[0]
   return {'questions':dict(db.execute('SELECT kind,COUNT(*) FROM lv_game_questions WHERE enabled=1 GROUP BY kind').fetchall()),
    'wins':db.execute('SELECT COUNT(*) FROM lv_game_wins').fetchone()[0],'invalid_rewards':invalid}
