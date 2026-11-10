"""Read-only inspection of the rules channel explicitly supplied by the owner."""
import json
import logging

import discord

CHANNEL_ID=1528925322362228787
log=logging.getLogger('LaVenganzaRP.rules')


async def inspect_rules_source(bot,guild_id):
 if getattr(bot,'_rules_source_inspected',False):return
 source=await bot.fetch_channel(CHANNEL_ID)
 if source.guild.id!=guild_id:raise ValueError('El canal de normas no pertenece al servidor esperado.')
 log.info('RULES_SOURCE channel=%s',json.dumps(dict(id=source.id,name=source.name,type=str(source.type),topic=getattr(source,'topic',None)),ensure_ascii=False))
 locations=[source]
 if isinstance(source,discord.ForumChannel):
  active=[t for t in await source.guild.active_threads() if t.parent_id==source.id]
  archived=[t async for t in source.archived_threads(limit=50)]
  locations=list({t.id:t for t in [*active,*archived]}.values())[:50]
 for location in locations:
  if not isinstance(location,(discord.TextChannel,discord.Thread)):continue
  log.info('RULES_SOURCE location=%s',json.dumps(dict(id=location.id,name=location.name),ensure_ascii=False))
  async for message in location.history(limit=60,oldest_first=True):
   content=dict(id=message.id,channel=location.id,content=message.content,
     embeds=[dict(title=e.title,description=e.description,fields=[dict(name=f.name,value=f.value) for f in e.fields],url=e.url) for e in message.embeds],
     files=[dict(name=a.filename,type=a.content_type,size=a.size,url=a.url) for a in message.attachments])
   log.info('RULES_SOURCE message=%s',json.dumps(content,ensure_ascii=False))
 bot._rules_source_inspected=True
 log.info('RULES_SOURCE complete locations=%s discord_mutations=0',len(locations))
