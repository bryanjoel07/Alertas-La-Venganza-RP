import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from stream_proof import supported_url
from streamer_panel import ApplicationButtons
from streamers import Streamers, decision


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.system = Streamers(str(Path(self.tmp.name) / "test.db"))
        self.system.start()
        self.role = MagicMock(name="role", id=45, permissions=discord.Permissions.none())
        self.role.name = "Streamer"
        self.member = MagicMock(id=100, roles=[], add_roles=AsyncMock())
        self.guild = MagicMock(id=23, roles=[self.role], fetch_member=AsyncMock(return_value=self.member))
        self.guild.me.guild_permissions = discord.Permissions(manage_roles=True)
        self.interaction = SimpleNamespace(guild=self.guild, guild_id=23, user=self.member,
                                           response=AsyncMock(), followup=AsyncMock())
        self.interaction.response.is_done = MagicMock(return_value=False)

    async def invoke(self, name, *args):
        await self.system.get_command(name).callback(self.system, self.interaction, *args)

    async def test_admin_registration_preserves_profile_urls_and_does_not_fabricate_followers(self):
        member = MagicMock(id=201,bot=False,add_roles=AsyncMock())
        for url in ('https://www.twitch.tv/example','https://www.youtube.com/@example','https://www.tiktok.com/@example'):
            await self.invoke('registrar',member,url)
            row = self.system.request(23,201)
            self.assertEqual(row['state'],'manual')
            self.assertIsNone(row['followers'])
            with self.system.db() as db:
                profile = db.execute('SELECT * FROM streamer_profiles').fetchone()
            self.assertFalse(profile['saved_url'].endswith('/live'))
            self.assertIsNotNone(__import__('stream_proof').live_target(profile['saved_url']))
            self.assertEqual(profile['saved_url'],profile['verified_url'])

    async def test_admin_registration_rejects_non_platform_links(self):
        member = MagicMock(id=201,bot=False,add_roles=AsyncMock())
        await self.invoke('registrar',member,'https://example.com/profile')
        member.add_roles.assert_not_awaited()
        self.assertIsNone(self.system.request(23,201))

    def row(self):
        return self.system.request(23, self.interaction.user.id)

    async def test_profile_link_only_after_approval(self):
        panel = ApplicationButtons(self.system)
        self.assertTrue(panel.is_persistent())
        self.assertEqual([b.label for b in panel.children], ["Solicitar rol", "Ver mi estado"])
        await self.invoke("solicitar")
        proof_buttons = self.interaction.followup.send.await_args.kwargs["view"]
        self.assertEqual([b.label for b in proof_buttons.children], ["Verificar requisitos"])
        link = "https://www.twitch.tv/example"
        await self.system.save_profile(self.interaction, link)
        with self.system.db() as db:
            self.assertFalse(db.execute("SELECT 1 FROM streamer_profiles").fetchone())
        data = {"owner": "twitch:111", "profile": link, "followers": 55,
                "title": f"La Venganza RP {self.row()['code']}"}
        with patch("streamers.inspect_stream", AsyncMock(return_value=data)):
            await self.invoke("verificar", link)
        controls = self.interaction.followup.send.await_args.kwargs["view"]
        self.assertEqual(controls.children[0].label, "Enviar enlace")
        await self.system.save_profile(self.interaction, "https://www.twitch.tv/another")
        with self.system.db() as db:
            self.assertIsNone(db.execute("SELECT saved_url FROM streamer_profiles").fetchone()[0])
        await self.system.save_profile(self.interaction, link)
        with self.system.db() as db:
            self.assertEqual(db.execute("SELECT saved_url FROM streamer_profiles").fetchone()[0], link)

    def test_evidence(self):
        data = {"owner": "youtube:123", "followers": 50, "title": "La Venganza RP LVRP-ABC"}
        self.assertEqual(decision(data, "LVRP-ABC", 50), "verificada")
        self.assertEqual(decision(data, "LVRP-XYZ", 50), "falta_titulo")
        self.assertEqual(decision(data, "LVRP-ABC", 51), "faltan_seguidores")
        self.assertEqual(decision(None, "LVRP-ABC", 50), "pendiente")
        self.assertIsNone(supported_url("https://youtube.com.evil.example/watch?v=12345678901"))
        self.assertIsNone(supported_url("https://twitch.tv/creator/clip/trending"))

    async def test_grant_retry_and_duplicate_owner(self):
        await self.invoke("solicitar")
        code = self.row()["code"]
        proof = {"owner": "youtube:123", "followers": 50, "title": f"La Venganza RP {code}"}
        self.guild.me.guild_permissions = discord.Permissions.none()
        with patch("streamers.inspect_stream", AsyncMock(return_value=proof)):
            await self.invoke("verificar", "https://youtu.be/12345678901")
        self.assertEqual(self.row()["state"], "verificada")
        self.member.add_roles.assert_not_awaited()
        self.guild.me.guild_permissions = discord.Permissions(manage_roles=True)
        await self.invoke("estado")
        await self.invoke("estado")
        self.member.add_roles.assert_awaited_once()
        self.assertEqual(self.row()["state"], "entregada")
        self.interaction.user = SimpleNamespace(id=101)
        await self.invoke("solicitar")
        proof["title"] = f"La Venganza RP {self.row()['code']}"
        with patch("streamers.inspect_stream", AsyncMock(return_value=proof)):
            await self.invoke("verificar", "https://youtu.be/12345678901")
        self.assertEqual(self.row()["state"], "canal_en_uso")

    async def test_unknown_platform_requires_independent_review(self):
        await self.invoke("solicitar")
        with patch("streamers.inspect_stream", AsyncMock()) as inspect:
            await self.invoke("verificar", "https://another.example/creator/live")
            inspect.assert_not_awaited()
        row = self.row()
        review = f"{row['id']}-{row['checked']}"
        await self.invoke("revisar", review, True, 50, "https://another.example/creator")
        self.member.add_roles.assert_not_awaited()
        self.interaction.user = SimpleNamespace(id=200)
        await self.invoke("revisar", review, True, 49, "https://another.example/creator")
        self.member.add_roles.assert_not_awaited()
        await self.invoke("revisar", review, True, 50, "https://another.example/creator")
        self.member.add_roles.assert_awaited_once()
