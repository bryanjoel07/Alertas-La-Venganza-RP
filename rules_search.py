"""Search exact official passages; aliases help retrieval and never generate policy text."""
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata

ALIASES={
 'ck':('ck','c k','character kill','characterkill','muerte definitiva'),
 'pk':('pk','p k','player kill','playerkill'),
 'pkt':('pkt','p k t','pk total','player kill total'),
 'mg':('mg','m g','metagaming','meta gaming'),
 'pg':('pg','p g','powergaming','power gaming'),
 'dm':('dm','d m','deathmatch','death match'),
 'vdm':('vdm','v d m','vehicle deathmatch','vehicle death match'),
 'rk':('rk','r k','revenge kill','revengekill'),
 'ooc':('ooc','o o c','fuera del personaje'),
 'ic':('ic','i c','in character','dentro del personaje'),
 'combat logging':('combat logging','combatlogging','desconectarse'),
 'policia':('policia','policias','policial','policiales'),
}
STOP={'regla','reglas','norma','normas','normativa','normativas','de','del','la','el','los','las','un','una','unos','unas','que','es','como','cual','sobre','para','por'}
HEADER=re.compile(r'^\s*(?:#{1,6}\s+(.+?)\s*#*|\*\*(.+?)\*\*)\s*$')


def normalize(value):
 value=unicodedata.normalize('NFKD',unicodedata.normalize('NFKC',str(value))).casefold()
 return ' '.join(''.join(c if c.isalnum() else ' ' for c in value if not unicodedata.combining(c)).split())


def fingerprint(message):
 payload=dict(content=message.content or '',embeds=[dict(title=e.title,description=e.description,
   fields=[dict(name=f.name,value=f.value) for f in e.fields]) for e in message.embeds])
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class RuleSection:
 message:int
 key:str
 heading:str
 body:str
 fingerprint:str


def split_sections(value,default):
 heading=default;body=[]
 for line in value.splitlines():
  found=HEADER.fullmatch(line)
  if found:
   if body and normalize(' '.join(body)):yield heading,'\n'.join(body).strip()
   heading=next(v for v in found.groups() if v).strip();body=[]
  else:body.append(line)
 if body and normalize(' '.join(body)):yield heading,'\n'.join(body).strip()


def sections(message):
 digest=fingerprint(message);result=[]
 content=re.sub(r'@(everyone|here)\b','',message.content or '')
 values=[('content',content,'Normas del servidor')]
 for n,embed in enumerate(message.embeds):
  if embed.description:values.append((f'embed:{n}',embed.description,embed.title or 'Normas del servidor'))
  for k,field in enumerate(embed.fields):values.append((f'embed:{n}:field:{k}',field.value,field.name))
 for source,value,title in values:
  for n,(heading,body) in enumerate(split_sections(value,title)):
   result.append(RuleSection(message.id,f'{source}:{n}',heading,body,digest))
 return result


def phrases(query):
 value=normalize(query)
 # Prefer a complete abbreviation such as PKT over a shorter alias contained in it.
 for key,aliases in sorted(ALIASES.items(),key=lambda item:max(len(v) for v in item[1]),reverse=True):
  if value in aliases:return [aliases]
 tokens=[t for t in value.split() if t not in STOP]
 if not tokens:return []
 groups=[]
 for token in tokens:
  aliases=next((a for a in ALIASES.values() if token in a),None)
  if aliases:groups.append(aliases)
  elif len(token)>=4:groups.append((token,token+'s',token[:-1] if token.endswith('s') else token))
  else:groups.append((token,))
 return groups


def search(rows,query):
 groups=phrases(query)
 if not groups:return []
 ranked=[]
 for section in rows:
  title=normalize(section.heading);body=normalize(section.body);score=0
  for group in groups:
   pattern=r'(?<!\w)(?:'+'|'.join(re.escape(v) for v in sorted(set(group),key=len,reverse=True))+r')(?!\w)'
   title_hits=list(re.finditer(pattern,title));body_hits=list(re.finditer(pattern,body))
   if not title_hits and not body_hits:break
   score+=30*len(title_hits)+min(10,len(body_hits))*4+(1/(1+body_hits[0].start()) if body_hits else 0)
  else:ranked.append((score,section))
 return [section for _,section in sorted(ranked,key=lambda item:(-item[0],item[1].message,item[1].key))]


def pages(body,limit=3300):
 result=[]
 while len(body)>limit:
  boundary=body.rfind('\n',0,limit+1)
  if boundary<limit//2:boundary=body.rfind(' ',0,limit+1)
  if boundary<limit//2:boundary=limit
  result.append(body[:boundary].strip());body=body[boundary:].strip()
 if body:result.append(body)
 return result or ['']
