import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

import discord
from link_spam import LinkSpamGuard, SpamStore, link_keys


class LinkSpamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = str(Path(temp.name) / "guard.db")
        self.store = SpamStore(self.path)
        self.store.initialize()

    def test_links_keep_distinct_destinations_and_normalize_invites(self):
        same = link_keys("discord.gg/AbC")
        self.assertTrue(same)
        self.assertEqual(same, link_keys("Mira <https://discord.com/invite/AbC>"))
        self.assertNotEqual(same, link_keys("discord.gg/abc"))
        self.assertNotEqual(link_keys("https://youtube.com/watch?v=1"), link_keys("https://youtube.com/watch?v=2"))
        self.assertFalse(link_keys("usuario@example.com hola mundo"))

    def test_window_channels_author_and_restarts(self):
        key = link_keys("https://example.com/sale")
        self.assertIsNone(self.store.record(1, 10, 100, 1000, key, 1000))
        self.assertIsNone(self.store.record(1, 10, 101, 1001, key, 1001))
        self.assertIsNone(self.store.record(2, 11, 102, 1002, key, 1002))
        self.assertIsNone(self.store.record(1, 12, 103, 1302, key, 1302))
        self.assertIsNone(self.store.record(1, 10, 104, 1303, key, 1303))
        case = SpamStore(self.path).record(1, 11, 105, 1304, key, 1304)
        self.assertEqual(set(case[1][next(iter(key))]), {(12,103),(10,104),(11,105)})
        self.assertIsNone(self.store.record(1, 11, 105, 1304, key, 1304))

    async def test_simultaneous_claims_produce_one_case(self):
        record = self.store.record
        key = link_keys("https://example.com")
        record(1, 1, 1, 1000, key, 1000)
        record(1, 2, 2, 1000, key, 1000)
        cases = await asyncio.gather(*(asyncio.to_thread(record, 1, i, i, 1000, key, 1000) for i in range(3, 7)))
        self.assertEqual(sum(bool(case) for case in cases), 1)

    async def test_gateway_three_channels_one_ban_selective_delete_and_private_notice(self):
        bot, guild, staff = Mock(), Mock(id=999), Mock()
        guild.ban = AsyncMock()
        guild.get_channel.return_value = staff
        staff.permissions_for.side_effect = lambda role: SimpleNamespace(view_channel=False, send_messages=True)
        staff.send = AsyncMock()
        member = SimpleNamespace(id=3,bot=False)
        guard = LinkSpamGuard(bot, self.path, guild.id)
        messages = {}
        async def fetch(mid):
            return messages[mid]
        bot.get_partial_messageable.return_value.fetch_message = AsyncMock(side_effect=fetch)
        def message(mid, cid, content):
            m = SimpleNamespace(guild=guild, author=member, webhook_id=None, channel=Mock(id=cid), id=mid,
                                content=content, created_at=datetime.now(timezone.utc), delete=AsyncMock(),
                                edited_at=None, attachments=[], stickers=[])
            messages[mid] = m
            return m
        await guard.observe(message(100,20,"discord.gg/AbC"))
        await guard.observe(message(101,21,"discord.gg/AbC"))
        messages[101].content = "Editado: otra cosa"
        await guard.observe(message(102,21,"https://otros.com"))
        guild.ban.assert_not_awaited()
        await guard.observe(message(103,22,"https://discord.com/invite/AbC"))
        guild.ban.assert_not_awaited()
        self.assertIn("Solo revisión", staff.send.call_args.args[0])
        messages[103].delete.assert_not_awaited()
        await guard.observe(message(104,23,"discord.gg/AbC"))
        guild.ban.assert_awaited_once()
        self.assertEqual(guild.ban.call_args.kwargs["delete_message_seconds"], 0)
        messages[100].delete.assert_not_awaited()
        messages[101].delete.assert_not_awaited()
        messages[102].delete.assert_not_awaited()
        messages[103].delete.assert_awaited_once()
        messages[104].delete.assert_awaited_once()
        self.assertEqual(staff.send.await_count,2)
        self.assertIn("Ban aplicado",staff.send.call_args.args[0])
        self.assertEqual(staff.send.call_args.kwargs['allowed_mentions'].to_dict()['parse'],[])

    async def test_hierarchy_and_missing_messages_reported_accurately(self):
        bot, guild = Mock(), Mock(id=999)
        guild.ban = AsyncMock(side_effect=discord.Forbidden(SimpleNamespace(status=403,reason="Forbidden"),""))
        bot.get_partial_messageable.return_value.fetch_message = AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404,reason="Not found"),""))
        guard = LinkSpamGuard(bot, self.path, guild.id)
        verified = [Mock(id=i, channel=Mock(id=i)) for i in (4,5,6)]
        result = await guard.enforce(guild, Mock(id=123), 1, "x", verified)
        self.assertIn("Ban pendiente",result)
        self.assertIn("Ya ausentes: 2",result)

    async def test_no_sanction_when_evidence_cannot_be_verified(self):
        guild = Mock(id=999)
        author = SimpleNamespace(id=321, bot=False)
        guard = LinkSpamGuard(Mock(), self.path, guild.id)
        key = next(iter(link_keys("discord.gg/Prueba")))
        for issue in ("deleted", "forbidden", "wrong_author", "old", "edited", "mixed", "same_channel", "different_link"):
            with self.subTest(issue=issue):
                messages = {i: SimpleNamespace(id=i, channel=Mock(id=i), guild=guild, author=author, webhook_id=None,
                    content="discord.gg/Prueba", created_at=datetime.now(timezone.utc), edited_at=None) for i in (1,2,3)}
                last = messages[3]
                if issue=="wrong_author": last.author = SimpleNamespace(id=999, bot=False)
                if issue=="old": last.created_at = datetime.fromtimestamp(1, timezone.utc)
                if issue=="edited": last.edited_at = datetime.now(timezone.utc)
                if issue=="mixed": last.content += " https://example.org"
                if issue=="same_channel": last.channel = Mock(id=2)
                if issue=="different_link": last.content = "discord.gg/Otro"
                async def fetch(mid):
                    if mid==3 and issue in ("deleted", "forbidden"):
                        error = discord.NotFound if issue=="deleted" else discord.Forbidden
                        raise error(SimpleNamespace(status=404 if issue=="deleted" else 403,reason=issue), "")
                    return messages[mid]
                guard.bot.get_partial_messageable.return_value.fetch_message = AsyncMock(side_effect=fetch)
                self.assertIsNone(await guard.verify(guild, author, {key: [(1,1),(2,2),(3,3)]}))
