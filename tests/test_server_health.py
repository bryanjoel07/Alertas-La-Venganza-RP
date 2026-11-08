import time
import unittest
import discord
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server_health import KEY, ServerHealthPanel, health_embed


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_finds_and_edits_the_existing_panel(self):
        settings = {}
        posts = []
        author = SimpleNamespace(id=7)
        async def history(**kwargs):
            for message in posts:
                yield message
        async def send(**kwargs):
            message = SimpleNamespace(id=99,author=author,embeds=[kwargs['embed']],edit=AsyncMock())
            posts.append(message)
            return message
        channel = SimpleNamespace(history=history,send=send,fetch_message=AsyncMock(side_effect=lambda _:posts[0]))
        bot = SimpleNamespace(user=author,get_channel=lambda _:channel)
        now = int(time.time())
        def new():
            return ServerHealthPanel(bot,3,'https://cfx.re',lambda k:settings.get(k,''),lambda k,v:settings.update({k:str(v)}))
        panel = new()
        panel.sample = ('down','down',('unreachable','stale'),False,now)
        await panel.refresh()
        self.assertIn('fuera de servicio',posts[0].embeds[0].description)
        self.assertEqual(settings[f'{KEY}_3'],'99')
        for saved in (True,False):
            if not saved: settings.clear()
            other = new()
            other.sample=('up','up',('up','stale'),False,now)
            await other.refresh()
            self.assertIn('en línea',posts[0].edit.await_args.kwargs['embed'].description)
            self.assertEqual(len(posts),1)

    def test_checking_down_maintenance_and_stale_read(self):
        sample=('down','up',('unreachable','stale'),False,1000)
        self.assertIn('posible caída',health_embed(sample,1010,'').description)
        self.assertIn('sin confirmar',health_embed(sample,1200,'').description)
        self.assertIn('mantenimiento',health_embed((*sample[:3],True,1000),1010,'').description)

    async def test_removed_panel_is_not_republished(self):
        channel=SimpleNamespace(fetch_message=AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404,reason='Not Found'),'Unknown Message')),send=AsyncMock())
        panel=ServerHealthPanel(SimpleNamespace(get_channel=lambda _:channel),3,'',lambda k:'99',lambda k,v:None)
        panel.sample=('down','down',('unreachable','stale'),False,int(time.time()))
        await panel.refresh()
        await panel.refresh()
        channel.fetch_message.assert_awaited_once()
        channel.send.assert_not_awaited()
