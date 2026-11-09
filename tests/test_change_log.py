import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock,patch
import discord
from discord import app_commands
from change_log import Journal,ChangeLog,change_embed

class JournalTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'db.sqlite3'
        self.journal=Journal(self.path);self.journal.initialize()

    def test_retry_preserves_original_and_survives_restart(self):
        rid=self.journal.begin('same','Prueba','Qué cambió','Cómo restaurar',{'roles':[1]})
        self.assertEqual(rid,self.journal.begin('same','Otra','Cambio','Restaurar',{'roles':[99]}))
        self.journal.finish(rid,'completado',{'roles':[2]})
        fresh=Journal(self.path);fresh.initialize()
        row=fresh.get(rid)
        self.assertEqual(json.loads(row['before_json']),{'roles':[1]})
        self.assertEqual(json.loads(row['after_json']),{'roles':[2]})
        self.assertEqual(len(fresh.rows(pending=True)),1)
        fresh.mark_sent(rid,123)
        self.assertFalse(fresh.rows(pending=True))
        self.assertLess(len(change_embed(row)),6000)

    def test_authorization_checks_actual_permissions_and_guild(self):
        service=object.__new__(ChangeLog);service.guild_id=10
        i=SimpleNamespace(guild_id=10,user=SimpleNamespace(guild_permissions=discord.Permissions.none()))
        with self.assertRaises(app_commands.CheckFailure):service.authorize(i)
        i.user.guild_permissions=discord.Permissions(administrator=True)
        service.authorize(i)
        i.guild_id=20
        with self.assertRaises(app_commands.CheckFailure):service.authorize(i)

class TrackingTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_records_before_and_partial_state_without_masking_error(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        service=ChangeLog(MagicMock(),Path(temp.name)/'db.sqlite3',10)
        service.journal.initialize()
        operation=AsyncMock(side_effect=ValueError('falló'))
        with patch.dict('os.environ',TRACK_TEST='request'),patch('change_log.server_snapshot',AsyncMock(side_effect=[{'before':1},{'partial':2}])):
            with self.assertRaises(ValueError):await service.tracked('TRACK_TEST','Prueba',operation)
        row=service.journal.rows()[0]
        self.assertEqual(row['status'],'fallido')
        self.assertEqual(json.loads(row['before_json']),{'before':1})
        self.assertEqual(json.loads(row['after_json'])['state'],{'partial':2})
        operation.assert_awaited_once()

    async def test_publish_refuses_public_channel_without_editing_permissions(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        bot=MagicMock();channel=MagicMock();channel.guild.id=10
        channel.permissions_for.return_value.view_channel=True
        bot.fetch_channel=AsyncMock(return_value=channel)
        service=ChangeLog(bot,Path(temp.name)/'db.sqlite3',10)
        with self.assertRaises(ValueError):await service.publish(MagicMock())
        channel.send.assert_not_called();channel.set_permissions.assert_not_called()
