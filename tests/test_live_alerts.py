import tempfile
import sqlite3
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch

from live_alerts import LiveAlerts
from streamers import Streamers


class LiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.streamers = Streamers(str(Path(temp.name) / "bot.db"))
        self.streamers.start()
        self.profile = "https://www.twitch.tv/creator"
        self.data = dict(owner="twitch:5", title="🚓 LA  VENGANZA RP | Patrulla", platform="Twitch",
                         session="123", link=self.profile)
        self.channel = NS(id=1513653533340073994, guild=NS(id=1, me=None, fetch_member=AsyncMock()),
                          permissions_for=lambda _:NS(view_channel=True,read_message_history=True,send_messages=True,embed_links=True),
                          send=AsyncMock(return_value=NS(id=89)))
        self.probe = AsyncMock(return_value=self.data)
        self.client = NS(get_channel=lambda _:self.channel,user=NS(id=9))
        with self.streamers.db() as db:
            db.execute("INSERT INTO streamer_requests(id,guild,member,code,issued,state,owner) VALUES(1,1,2,'code',1,'entregada','twitch:5')")
            db.execute("INSERT INTO streamer_profiles VALUES(1,'twitch:5',?,?)", (self.profile,self.profile))

    async def tick(self):
        monitor = LiveAlerts(self.client, self.streamers, 1, self.probe)
        monitor.init_db()
        await monitor.poll()

    async def test_restart_and_new_session(self):
        await self.tick()
        await self.tick()
        self.channel.send.assert_awaited_once()
        self.data["session"] = "124"
        await self.tick()
        self.assertEqual(self.channel.send.await_count,2)

    async def test_recover_unacknowledged_delivery(self):
        await self.tick()
        embed = self.channel.send.await_args.kwargs["embed"]
        async def history(**kwargs):
            yield NS(embeds=[embed],author=self.client.user,id=89)
        self.channel.history = history
        with self.streamers.db() as db:
            db.execute("UPDATE streamer_live_alerts SET message=NULL")
        await self.tick()
        self.channel.send.assert_awaited_once()
        with self.streamers.db() as db:
            self.assertEqual(db.execute("SELECT message FROM streamer_live_alerts").fetchone()[0],89)

    async def test_wrong_event_owner_or_offline(self):
        for update in ({"title":"Otro juego"},{"title":"La Venganza RPG"},{"title":"La Venganza RP","owner":"twitch:6"}):
            self.data.update(update)
            await self.tick()
        self.probe.return_value = None
        await self.tick()
        self.channel.send.assert_not_awaited()

    async def test_needs_approval_and_saved_link(self):
        with self.streamers.db() as db:
            db.execute("UPDATE streamer_requests SET state='pendiente'")
        await self.tick()
        with self.streamers.db() as db:
            db.execute("UPDATE streamer_requests SET state='verificada'")
            db.execute("UPDATE streamer_profiles SET saved_url=NULL")
        await self.tick()
        self.probe.assert_not_awaited()

    async def test_temporary_settings_failure_keeps_the_monitor_available_for_the_next_cycle(self):
        monitor=LiveAlerts(self.client,self.streamers,1,self.probe);monitor.init_db()
        with patch('live_alerts.setting',side_effect=[sqlite3.OperationalError('database is locked'),True,True]):
            with self.assertLogs('live_alerts',level='ERROR'):
                await monitor.poll()
            self.channel.send.assert_not_awaited()
            await monitor.poll();await monitor.poll()
        self.channel.send.assert_awaited_once()
