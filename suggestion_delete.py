"""Confirmed hard deletion: private before-state, Discord read-back, then atomic purge."""
import logging
import sqlite3
import time

import discord

log=logging.getLogger('LaVenganzaRP.suggestions')


async def locate(system,row):
 if row['message']:
  try:found=await system.card(row,allow_deleting=True)
  except discord.NotFound:return None
 else:
  try:found=await system.find_idea(row)
  except discord.NotFound:return None
 if found and isinstance(found[0],discord.Thread) and found[0].id==found[1].id:
  base=await system.target()
  if not isinstance(base,discord.ForumChannel) or found[0].parent_id!=base.id or found[0].owner_id!=system.bot.user.id:
   raise ValueError('Esa publicación no es un hilo propio del sistema de sugerencias.')
 return found


async def snapshot(system,rid):
 row=system.store.get(rid)
 value=dict(suggestion=row,votes=system.store.votes(rid),decisions=system.store.events(rid),deletion=system.store.deletion(rid))
 if row:
  found=await locate(system,row)
  value['discord_missing']=found is None
  if found:
   channel,message=found
   value['message']=dict(id=message.id,channel=channel.id,author=message.author.id,content=message.content,
     embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components])
   if isinstance(channel,discord.Thread) and channel.id==message.id:
    value['discussion']=[dict(id=m.id,author=m.author.id,content=m.content,embeds=[e.to_dict() for e in m.embeds],
      attachments=[dict(id=a.id,filename=a.filename,size=a.size,url=a.url) for a in m.attachments])
      async for m in channel.history(limit=None,oldest_first=True)]
 return value


async def finish(system,rid):
 row=system.store.get(rid)
 if not row:return True
 job=system.store.deletion(rid)
 if row['publication']!='deleting' or not job or job['request']!=row['request']:
  raise ValueError('Esta idea no tiene una eliminación confirmada.')
 if job['not_before']>time.time():return False
 found=await locate(system,row)
 if found:
  channel,message=found
  if row['channel']!=channel.id or row['message']!=message.id:
   await system.call('deletion_target',rid,channel.id,message.id)
  forum_post=isinstance(channel,discord.Thread) and channel.id==message.id
  if forum_post:
   base=await system.target()
   if not isinstance(base,discord.ForumChannel) or channel.parent_id!=base.id or channel.owner_id!=system.bot.user.id:
    raise ValueError('No se eliminará un hilo que no sea la publicación propia de esta idea.')
  try:
   if forum_post:await channel.delete(reason=f'Eliminar sugerencia #{rid}, confirmado por administrador {job["actor"]}')
   else:await message.delete()
  except discord.NotFound:pass
  try:
   if forum_post:await system.bot.fetch_channel(channel.id)
   else:await channel.fetch_message(message.id)
  except discord.NotFound:pass
  else:raise RuntimeError('Discord todavía no confirmó que la publicación desapareció.')
 await system.call('purge',rid,job['request'])
 log.info('SUGGESTIONS deletion_verified id=%s actor=%s discord_absent=True suggestion_purged=True votes_purged=True decisions_purged=True',rid,job['actor'])
 return True


async def delete(system,i,expected):
 admin=await system.member(i,admin=True)
 rid=expected['id']
 async with system.lock(rid):
  current=system.store.get(rid)
  if not current:return True
  # Validate the exact idea again before creating the private audit snapshot.
  if any(current[key]!=expected[key] for key in ('request','channel','message','status_version')):
   raise ValueError('La idea cambió desde que abriste la confirmación. Revísala y vuelve a pulsar Eliminar.')
  async def remove():
   await system.call('queue_deletion',rid,admin.id,expected)
   return await finish(system,rid)
  try:
   return await system.bot.changes.tracked('SUGGESTION_DELETE',f'Eliminar sugerencia #{rid}',remove,
     request_id=f'{current["request"]}:{admin.id}:{time.time_ns()}',snapshot=lambda:snapshot(system,rid))
  except (discord.HTTPException,RuntimeError,TimeoutError,sqlite3.Error):
   remaining=system.store.get(rid)
   if not remaining or remaining['publication']!='deleting':raise
   log.exception('SUGGESTIONS deletion_pending id=%s; active rows retained until Discord confirms',rid)
   return False


async def recover(system):
 for rid in await system.call('pending_deletions'):
  try:
   async with system.lock(rid):
    job=system.store.deletion(rid)
    if job and job['not_before']>time.time():continue
    async def remove():return await finish(system,rid)
    await system.bot.changes.tracked('SUGGESTION_DELETE_RETRY',f'Completar eliminación de sugerencia #{rid}',remove,
      request_id=f'{rid}:{time.time_ns()}',snapshot=lambda:snapshot(system,rid))
  except Exception:log.exception('SUGGESTIONS deletion_retry_pending id=%s; continuing other ideas',rid)
