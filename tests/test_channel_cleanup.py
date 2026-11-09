from datetime import datetime,timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,AsyncMock,patch
import discord
from channel_cleanup import CHANNEL,CleanupArchive,clear_exclusive_log

class CleanupTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
  self.path=Path(temp.name)/'db.sqlite3'
  self.bot=MagicMock();self.bot.backups.enabled=True
  self.channel=MagicMock(spec=discord.TextChannel)
  self.channel.id=CHANNEL;self.channel.guild.id=10;self.channel.name='🛡️┊𝐑𝐞𝐠𝐢𝐬𝐭𝐫𝐨-𝐄𝐱𝐜𝐥𝐮𝐬𝐢𝐯𝐞'
  self.message=SimpleNamespace(id=1,author=SimpleNamespace(id=5),content='Contenido anterior',created_at=datetime.now(timezone.utc),pinned=False,embeds=[],components=[],attachments=[])
  self.messages=[self.message]
  async def history(limit=None):
   for message in self.messages[:limit]:yield message
  self.channel.history=history
  self.bot.fetch_channel=AsyncMock(return_value=self.channel)
 async def test_backup_precedes_delete_and_completion_prevents_repeated_purges(self):
  order=[]
  async def backup():
   archive=CleanupArchive(self.path)
   import sqlite3
   with sqlite3.connect(self.path) as db:
    self.assertEqual(db.execute('SELECT COUNT(*) FROM bot_channel_cleanup_messages').fetchone()[0],1)
   order.append('backup');return {'restore_state':'verified'}
  async def purge(**kwargs):
   self.assertTrue(kwargs['check'](self.message))
   self.assertFalse(kwargs['check'](SimpleNamespace(id=99)))
   order.append('purge');self.messages=[];return [self.message]
  self.bot.backups.execute=AsyncMock(side_effect=backup);self.channel.purge=AsyncMock(side_effect=purge)
  with patch.dict('os.environ',CLEAR_EXCLUSIVE_LOG_REQUEST_ID='test'):
   await clear_exclusive_log(self.bot,10,self.path)
   await clear_exclusive_log(self.bot,10,self.path)
  self.assertEqual(order,['backup','purge']);self.assertFalse(self.bot._clearing_exclusive_log)
 async def test_unverified_backup_or_wrong_channel_never_deletes(self):
  self.bot.backups.execute=AsyncMock(return_value={'restore_state':'failed'})
  self.channel.purge=AsyncMock()
  with patch.dict('os.environ',CLEAR_EXCLUSIVE_LOG_REQUEST_ID='test'):
   with self.assertRaisesRegex(ValueError,'respaldo'):await clear_exclusive_log(self.bot,10,self.path)
   self.channel.name='Otro canal'
   with self.assertRaisesRegex(ValueError,'canal'):await clear_exclusive_log(self.bot,10,self.path)
  self.channel.purge.assert_not_awaited()
