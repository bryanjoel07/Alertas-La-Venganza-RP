"""Fresh channel inventories that preserve unsupported channel metadata read-only.

The SDK rejects the entire list when Discord adds a channel type. Known channels
still use the SDK's normal constructors; unknown ones expose only inventory data.
"""
import copy
import logging
import re
from types import SimpleNamespace

import discord
from discord.channel import _guild_channel_factory

log=logging.getLogger('LaVenganzaRP.channels')
_reported=set()

class UnsupportedChannel:
 __slots__=('id','guild','name','position','category_id','topic','type','_overwrites','raw')
 def __init__(self,guild,data):
  self.raw=copy.deepcopy(data);self.guild=guild;self.id=int(data['id'])
  self.name=data.get('name','');self.position=int(data.get('position',0))
  self.category_id=int(data['parent_id']) if data.get('parent_id') else None
  self.topic=data.get('topic');self.type=f"unsupported:{data['type']}"
  self._overwrites=tuple(SimpleNamespace(id=int(o['id']),type=int(o['type']),allow=int(o['allow']),deny=int(o['deny']))
   for o in data.get('permission_overwrites',[]))

async def fetch_channels(guild):
 try:return await guild.fetch_channels()
 except discord.InvalidData as error:
  if not re.fullmatch(r'Unknown channel type \d+ for channel ID \d+\.',str(error)):raise
 data=await guild._state.http.get_all_guild_channels(guild.id)
 channels=[];unknown=[]
 for record in data:
  factory,_=_guild_channel_factory(record['type'])
  if factory is None:
   channels.append(UnsupportedChannel(guild,record));unknown.append((int(record['id']),int(record['type'])))
  else:channels.append(factory(guild=guild,state=guild._state,data=record))
 signature=(guild.id,tuple(sorted(unknown)))
 if unknown and signature not in _reported:
  log.warning('CHANNEL_INVENTORY compatible guild=%s known=%s unsupported=%s retained_read_only=True',guild.id,len(channels)-len(unknown),unknown)
  _reported.add(signature)
 return channels
