import asyncio
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord

from backup import snapshot
from drive_backups import recovery_probe
from economy import Confirm, Economy, Panel, shop_embed
from economy_delivery import Delivery
from economy_store import CATEGORY_ID, PR, EconomyStore, week_slot


class EconomyTests(unittest.TestCase):
    def test_gift_requires_both_confirmations_and_is_private(self):
        async def scenario():
            system = object.__new__(Economy)
            system.store = self.store
            system.delivery = Delivery(self.store)
            self.store.adjust(1, 10000, "premio", 90, "gift")
            item = next(
                p for p in self.store.rotation()["products"] if p["kind"] == "limited"
            )
            sender = MagicMock()
            sender.user.id = 1
            sender.response.is_done.return_value = False
            sender.response.send_message = AsyncMock()
            recipient = MagicMock(id=2, bot=False, display_name="Jugador")
            recipient.send = AsyncMock()
            sender.guild.fetch_member = AsyncMock(return_value=recipient)
            await system.preview(sender, item["sku"], recipient)
            msg = sender.response.send_message.call_args.kwargs
            self.assertTrue(msg["ephemeral"])
            await msg["view"].action(sender)
            self.assertEqual(self.store.account(1)["balance"], 10000)
            recipient_view = recipient.send.call_args.kwargs["view"]
            self.assertEqual(recipient_view.user, 2)
            await recipient_view.action(recipient)
            await recipient_view.action(recipient)
            self.assertEqual(self.store.account(1)["balance"], 10000 - item["price"])
            receipt = self.store.inventory(2)[0]
            system.delivery.equip(recipient, receipt["id"], "")
            embed = discord.Embed()
            system.ready = True
            system.decorate(embed, 2)
            self.assertIn("Aniversario", embed.fields[0].value)
            self.store.refund(receipt["id"], 90, "prueba")
            self.assertFalse(self.store.equipped(2))

        asyncio.run(scenario())

    def test_future_campaign_and_admin_restriction(self):
        now = int(datetime(2026, 11, 9, 20, tzinfo=PR).timestamp())
        self.store.save_product(
            90,
            "edicion",
            "Edición",
            "limited",
            "limited",
            5000,
            2,
            0,
            True,
            {"label": "Insignia"},
            now + 3 * 86400,
            now + 86400,
        )
        self.assertNotIn(
            "edicion", [p["sku"] for p in self.store.rotation(now)["products"]]
        )
        with self.assertRaises(ValueError):
            self.store.quote(1, 2, "edicion", now)
        system = object.__new__(Economy)
        system.store = self.store
        system.guild = discord.Object(id=3)
        i = MagicMock(guild_id=3)
        i.user.guild_permissions = discord.Permissions.none()
        i.user.roles = []
        with self.assertRaises(ValueError):
            system.authorized(i)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "active.db"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE events(id INTEGER PRIMARY KEY,status TEXT,winner1 TEXT,winner2 TEXT,winner3 TEXT)"
            )
            db.execute("CREATE TABLE registrations(event_id INTEGER,user_id INTEGER)")
            db.execute("INSERT INTO events VALUES (1,'finished','1','2','3')")
            db.execute("INSERT INTO events VALUES (2,'open',NULL,NULL,NULL)")
        self.store = EconomyStore(self.path)
        self.store.initialize()

    def test_event_finalization_is_atomic_and_idempotent(self):
        self.store.participant(2, 8, True, 90)
        self.store.participant(2, 2, True, 90)
        with self.store.db() as db:
            db.execute("INSERT INTO registrations VALUES(2,9)")
            db.execute(
                "UPDATE events SET status='finished',winner1='1',winner2='2',winner3='3' WHERE id=2"
            )
            self.store.reconcile_in(db, 2, 90)
        self.store.initialize()
        with self.store.db() as db:
            self.assertFalse(self.store.reconcile_in(db, 2, 90))
            self.assertFalse(self.store.reconcile_in(db, 1, 90))
        self.assertEqual(
            [self.store.account(u)["balance"] for u in (1, 2, 3, 8, 9)],
            [500, 350, 250, 100, 0],
        )
        preview = self.store.correct(2, [2, 1, 3], 90)
        self.assertEqual(preview[1], {1: -150, 2: 150})
        self.assertEqual(self.store.account(2)["balance"], 350)
        self.store.correct(2, [2, 1, 3], 90, preview)
        with self.assertRaises(ValueError):
            self.store.correct(2, [2, 1, 3], 90, preview)
        self.store.adjust(2, -500, "prueba", 90, "spend")
        with self.assertRaises(ValueError):
            self.store.correct(2, [1, 2, 3], 90)
        self.assertEqual(
            self.store.rows("SELECT winner1 FROM events WHERE id=2")[0]["winner1"], "2"
        )
        with self.assertRaises(ValueError):
            self.store.participant(1, 9, True, 90)

    def test_rotation_restart_and_pr_cutover(self):
        cut = int(datetime(2026, 11, 9, 18, 30, tzinfo=PR).timestamp())
        self.assertNotEqual(week_slot(cut - 1)[0], week_slot(cut)[0])
        first = self.store.rotation(cut)
        self.assertEqual(first, EconomyStore(self.path).rotation(cut + 400))
        self.assertEqual(sum(p["kind"] == "bundle" for p in first["products"]), 1)
        self.assertEqual(sum(p["tier"] == "cheap" for p in first["products"]), 2)
        self.assertLess(len(shop_embed(first)), 6000)

    def test_simultaneous_stock_gifts_and_repeat_confirmations(self):
        now = int(datetime(2026, 11, 9, 20, tzinfo=PR).timestamp())
        sku = "aniversario-2026"
        self.store.rows("UPDATE eco_products SET stock=1 WHERE sku=?", (sku,))
        self.store.adjust(1, 5000, "premio", 90, "fund1")
        quotes = [self.store.quote(1, user, sku, now) for user in (5, 6)]

        def attempt(q):
            try:
                return self.store.buy(q["id"], 1, now)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, quotes))
        receipt = next(r for r in outcomes if r)
        self.assertEqual(sum(bool(r) for r in outcomes), 1)
        self.assertEqual(self.store.account(1)["balance"], 0)
        self.assertEqual(self.store.buy(receipt["quote"], 1, now)["id"], receipt["id"])
        self.assertEqual(self.store.inventory(receipt["recipient"])[0]["edition"], 1)
        self.assertEqual(self.store.account(receipt["recipient"])["balance"], 0)
        self.store.refund(receipt["id"], 90, "prueba")
        self.store.refund(receipt["id"], 90, "reintento")
        self.assertEqual(self.store.account(1)["balance"], 5000)
        self.assertFalse(self.store.inventory(receipt["recipient"]))

    def test_price_change_and_concurrent_balance(self):
        r = self.store.rotation()
        choices = [p for p in r["products"] if p["tier"] == "cheap"]
        funds = max(p["price"] for p in choices)
        self.store.adjust(1, funds, "premio", 90, "fund2")
        quotes = [self.store.quote(1, 1, p["sku"]) for p in choices]

        def attempt(q):
            try:
                return self.store.buy(q["id"], 1)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(bool(v) for v in pool.map(attempt, quotes)), 1)
        q = self.store.quote(3, 3, choices[0]["sku"])
        self.store.rows(
            "UPDATE eco_products SET revision=revision+1,price=10 WHERE sku=?",
            (q["sku"],),
        )
        with self.assertRaisesRegex(ValueError, "oferta"):
            self.store.buy(q["id"], 3)

    def test_backup_restores_ledger_and_existing_tables(self):
        self.store.adjust(1, 300, "premio", 90, "fund3")
        copies = list((self.path.parent / "backups").glob("*.sqlite3"))
        self.assertEqual(len(copies), 1)
        with closing(sqlite3.connect(copies[0])) as db:
            self.assertFalse(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='eco_accounts'"
                ).fetchone()
            )
        target = self.path.with_name("snapshot.db")
        manifest = snapshot(self.path, target)
        self.assertEqual(manifest["rows"]["eco_ledger"], 1)
        self.assertEqual(manifest["rows"]["events"], 2)
        self.assertTrue(recovery_probe(target, manifest, self.path.parent))

    def test_voice_recovers_existing_marker_and_expires_when_empty(self):
        async def scenario():
            d = Delivery(self.store)
            guild = MagicMock()
            category = MagicMock(spec=discord.CategoryChannel)
            category.id = CATEGORY_ID
            guild.id = 12
            guild.get_channel.return_value = category
            owner = MagicMock()
            owner.guild = guild
            owner.display_name = "Jugador"
            owner.send = AsyncMock()
            guild.fetch_member = AsyncMock(return_value=owner)
            room = MagicMock(spec=discord.VoiceChannel)
            room.id = 150
            room.category_id = category.id
            room.guild = guild
            room.edit = AsyncMock()
            room.delete = AsyncMock()
            guild.create_voice_channel = AsyncMock()
            guild.fetch_channels = AsyncMock(return_value=[room])
            with self.store.db() as db:
                db.execute(
                    "INSERT INTO eco_purchases(id,quote,buyer,recipient,sku,price,name,kind,payload,duration,edition,status,created) VALUES('abc','q',1,1,'sala-voz',4000,'Sala','voice','{}',604800,1,'pending',123)"
                )
            room.name = "exclusive-abc"
            await d.voice(guild, self.store.purchase("abc"))
            receipt = self.store.purchase("abc")
            self.assertEqual(receipt["resource_id"], room.id)
            self.assertEqual(receipt["status"], "delivered")
            guild.create_voice_channel.assert_not_awaited()
            guild.get_channel.side_effect = lambda ident: (
                category if ident == CATEGORY_ID else room
            )
            self.store.rows("UPDATE eco_purchases SET expires=1")
            room.members = [owner]
            room.voice_states = {1: owner}
            await d.recover(guild)
            room.delete.assert_not_awaited()
            owner.send.assert_awaited_once()
            room.members = []
            room.voice_states = {}
            await d.recover(guild)
            room.delete.assert_awaited_once()
            self.assertEqual(self.store.purchase("abc")["status"], "expired")

        asyncio.run(scenario())

    def test_panel_reconnect_and_private_permissions(self):
        async def scenario():
            system = object.__new__(Economy)
            system.store = self.store
            system.delivery = Delivery(self.store)
            system.signature = None
            guild = MagicMock()
            category = MagicMock(spec=discord.CategoryChannel)
            category.id = CATEGORY_ID
            channel = MagicMock(spec=discord.TextChannel)
            channel.id = 12345
            channel.category_id = category.id
            channel.topic = "La Venganza Exclusive · shop_channel"
            guild.get_channel.side_effect = lambda ident: {
                CATEGORY_ID: category,
                12345: channel,
            }.get(ident)
            guild.fetch_channels = AsyncMock(return_value=[])
            guild.create_text_channel = AsyncMock(return_value=channel)
            message = MagicMock()
            message.id = 54321
            message.edit = AsyncMock()
            channel.send = AsyncMock(return_value=message)
            channel.fetch_message = AsyncMock(return_value=message)

            async def history(limit=None):
                if False:
                    yield None

            channel.history = history
            await system.panel(guild)
            system.signature = None
            await system.panel(guild)
            guild.create_text_channel.assert_awaited_once()
            self.assertEqual(
                guild.create_text_channel.call_args.kwargs["category"], category
            )
            channel.send.assert_awaited_once()
            message.edit.assert_awaited_once()
            self.assertTrue(Panel(system).is_persistent())
            channel.overwrites_for.return_value = discord.PermissionOverwrite()
            with self.assertRaises(ValueError):
                system.check_private(channel)
            i = MagicMock()
            i.user.id = 2
            i.response.is_done.return_value = False
            i.response.send_message = AsyncMock()
            self.assertFalse(await Confirm(1, AsyncMock()).interaction_check(i))
            self.assertTrue(i.response.send_message.call_args.kwargs["ephemeral"])

        asyncio.run(scenario())
