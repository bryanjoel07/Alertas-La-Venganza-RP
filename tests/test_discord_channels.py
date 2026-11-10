import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,MagicMock
import discord
from change_log import server_snapshot
from discord_channels import fetch_channels,UnsupportedChannel

RAW=[
 {'id':'40','type':4,'name':'Tickets','position':2,'permission_overwrites':[]},
 {'id':'41','type':0,'name':'ticket-0008','position':3,'parent_id':'40','topic':'lv-ticket:8','permission_overwrites':[]},
 {'id':'42','type':20,'name':'Nuevo tipo','position':4,'parent_id':'40','permission_overwrites':[{'id':'10','type':0,'allow':'1024','deny':'2048'}],'extra_field':{'preserve':True}},
]
class ChannelInventoryTests(unittest.IsolatedAsyncioTestCase):
 def guild(self,data=None):
  http=NS(get_all_guild_channels=AsyncMock(return_value=copy.deepcopy(RAW if data is None else data)))
  return NS(id=10,_state=NS(http=http),fetch_channels=AsyncMock(side_effect=discord.InvalidData('Unknown channel type 20 for channel ID 42.')),fetch_roles=AsyncMock(return_value=[]))
 async def test_new_type_preserves_known_channels_and_unknown_metadata(self):
  guild=self.guild();channels=await fetch_channels(guild)
  self.assertIsInstance(channels[0],discord.CategoryChannel);self.assertIsInstance(channels[1],discord.TextChannel)
  unknown=channels[2];self.assertIsInstance(unknown,UnsupportedChannel)
  self.assertEqual(unknown.raw,RAW[2]);self.assertEqual(unknown.category_id,40)
  self.assertEqual([(o.id,o.type,o.allow,o.deny) for o in unknown._overwrites],[(10,0,1024,2048)])
  self.assertFalse(hasattr(unknown,'edit'));self.assertFalse(hasattr(unknown,'delete'))
  self.assertEqual(sum(c.category_id==40 for c in channels),2)
 async def test_snapshot_keeps_unsupported_channel_and_permissions(self):
  state=await server_snapshot(self.guild());row=next(c for c in state['channels'] if c['id']=='42')
  self.assertEqual(row['raw'],RAW[2]);self.assertEqual(row['overwrites'],[{'id':'10','type':0,'allow':'1024','deny':'2048'}])
 async def test_normal_sdk_path_does_not_use_internal_transport(self):
  guild=self.guild();guild.fetch_channels=AsyncMock(return_value=['normal'])
  self.assertEqual(await fetch_channels(guild),['normal']);guild._state.http.get_all_guild_channels.assert_not_awaited()
 async def test_network_errors_and_other_invalid_data_are_not_hidden(self):
  for error in (OSError('connection failed'),discord.InvalidData('Malformed channel data')):
   guild=self.guild();guild.fetch_channels.side_effect=error
   with self.assertRaises(type(error)):await fetch_channels(guild)
   guild._state.http.get_all_guild_channels.assert_not_awaited()
