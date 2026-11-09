"""Explicit one-shot cleanup of Registro Exclusive, with a verified private backup."""
import asyncio
from contextlib import closing
import hashlib
import json
import logging
import os
import re
import sqlite3
import time

import discord
from navigation import key

log=logging.getLogger('LaVenganzaRP.cleanup')
CHANNEL=1569084826324046028

class CleanupArchive:
 def __init__(self,path):self.path=path
 def initialize(self):
  with closing(sqlite3.connect(self.path)) as db,db:
   db.execute('CREATE TABLE IF NOT EXISTS bot_channel_cleanups(request TEXT PRIMARY KEY,channel TEXT NOT NULL,created INTEGER NOT NULL,completed INTEGER)')
   db.execute('CREATE TABLE IF NOT EXISTS bot_channel_cleanup_messages(request TEXT NOT NULL,message TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(request,message))')
   db.execute('CREATE TABLE IF NOT EXISTS bot_channel_cleanup_files(request TEXT NOT NULL,attachment TEXT NOT NULL,name TEXT NOT NULL,data BLOB NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(request,attachment))')
 def done(self,request):
  with closing(sqlite3.connect(self.path)) as db:
   row=db.execute('SELECT completed FROM bot_channel_cleanups WHERE request=?',(request,)).fetchone()
   return bool(row and row[0])
 def begin(self,request):
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT OR IGNORE INTO bot_channel_cleanups VALUES (?,?,?,NULL)',(request,str(CHANNEL),int(time.time())))
 def message(self,request,message):
  payload=dict(id=str(message.id),author=str(message.author.id),content=message.content,created=message.created_at.isoformat(),
    pinned=message.pinned,embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components],
    attachments=[dict(id=str(a.id),name=a.filename,url=a.url,size=a.size) for a in message.attachments])
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT OR REPLACE INTO bot_channel_cleanup_messages VALUES (?,?,?)',(request,str(message.id),json.dumps(payload,ensure_ascii=False)))
 def file(self,request,attachment,data):
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('INSERT OR REPLACE INTO bot_channel_cleanup_files VALUES (?,?,?,?,?)',(request,str(attachment.id),attachment.filename,data,hashlib.sha256(data).hexdigest()))
 def complete(self,request):
  with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE bot_channel_cleanups SET completed=? WHERE request=?',(int(time.time()),request))

async def clear_exclusive_log(bot,guild_id,path):
 request=os.getenv('CLEAR_EXCLUSIVE_LOG_REQUEST_ID','').strip()
 if not request:return
 if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):raise ValueError('Identificador de limpieza inválido')
 archive=CleanupArchive(path)
 await asyncio.to_thread(archive.initialize)
 if await asyncio.to_thread(archive.done,request):return
 channel=await bot.fetch_channel(CHANNEL)
 if not isinstance(channel,discord.TextChannel) or channel.guild.id!=guild_id or key(channel.name)!='registroexclusive':
  raise ValueError('No se confirmó el canal Registro Exclusive; no se borraron mensajes')
 bot._clearing_exclusive_log=True
 try:
  await asyncio.to_thread(archive.begin,request)
  total=0
  for _ in range(3):
   messages=[message async for message in channel.history(limit=None)]
   if not messages:break
   ids={message.id for message in messages}
   for message in messages:
    await asyncio.to_thread(archive.message,request,message)
    for attachment in message.attachments:
     try:data=await attachment.read()
     except discord.HTTPException:data=await attachment.read(use_cached=True)
     await asyncio.to_thread(archive.file,request,attachment,data)
   if not bot.backups.enabled:raise ValueError('No se vacía el canal hasta disponer de un respaldo externo verificado')
   backup=await bot.backups.execute()
   if backup.get('restore_state')!='verified':raise ValueError('El respaldo no pasó la verificación; los mensajes se conservan')
   # Delete only messages already copied and backed up; newly arriving messages get a new pass.
   removed=await channel.purge(limit=None,check=lambda message:message.id in ids,bulk=True,reason='Vaciar Registro Exclusive por solicitud expresa del propietario; copia privada verificada')
   total+=len(removed)
  remaining=[message async for message in channel.history(limit=1)]
  if remaining:raise ValueError('Llegaron mensajes nuevos durante la limpieza; se conservaron para una nueva revisión')
  await asyncio.to_thread(archive.complete,request)
  log.info('CHANNEL_CLEANUP verified channel=%s removed=%s remaining=0 backup_restore_verified=True request=%s',CHANNEL,total,request)
 finally:bot._clearing_exclusive_log=False
