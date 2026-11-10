import asyncio
import json
import sqlite3
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from change_log import ChangeLog
from citizen_cleanup import (BOT_ID, CITIZEN_ID, ENV, GUILD_ID, REQUEST,
                             keep_citizen_roles, resolve_targets)
from economy_store import EconomyStore


class Role:
    def __init__(self, rid, name, position, managed=False, permissions=None):
        self.id, self.name, self.position, self.managed = rid, name, position, managed
        self.permissions = permissions or discord.Permissions.none()

    def __lt__(self, other):
        return self.position < other.position


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "db.sqlite3"
        self.roles = {
            GUILD_ID: Role(GUILD_ID, "@everyone", 0),
            CITIZEN_ID: Role(CITIZEN_ID, "Ciudadanos", 1),
            1245008186440683530: Role(1245008186440683530, "Owner", 50),
            1300627506801541230: Role(1300627506801541230, "Programador", 40),
            9: Role(9, "Bot", 90, permissions=discord.Permissions(manage_roles=True)),
            10: Role(10, "Otro", 5),
        }
        self.members = {}
        self.events = []
        self.first = self.member(101, "esschino__", {1245008186440683530, 10})
        self.second = self.member(102, "esschino_", {CITIZEN_ID, 1300627506801541230})
        self.third = self.member(103, "esschino", {1245008186440683530, 10})
        self.member(BOT_ID, "bot", {9}, bot=True)
        self.guild = SimpleNamespace(id=GUILD_ID,
            fetch_roles=AsyncMock(side_effect=lambda: list(self.roles.values())),
            fetch_member=AsyncMock(side_effect=lambda uid: self.members[uid]))
        self.store = EconomyStore(path)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE events(id INTEGER PRIMARY KEY,status TEXT)")
        self.store.initialize()
        self.bot = SimpleNamespace(user=SimpleNamespace(id=BOT_ID),
            citizen_cleanup_lock=asyncio.Lock(), get_guild=lambda gid: self.guild,
            economy=SimpleNamespace(store=self.store, delivery=SimpleNamespace(lock=asyncio.Lock())))
        self.bot.changes = ChangeLog(self.bot, path, GUILD_ID)
        self.bot.changes.journal.initialize()
        self.directory = AsyncMock(side_effect=lambda guild, force: list(self.members.values()))
        self.env = patch.dict("os.environ", {ENV: REQUEST})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.loader = patch("citizen_cleanup.MemberDirectory.load", self.directory)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    def member(self, uid, username, roles, bot=False):
        member = SimpleNamespace(id=uid, name=username, bot=bot, _roles=set(roles))

        def assert_saved():
            row = self.bot.changes.journal.by_key(f"operation:{ENV}:{REQUEST}")
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row["before_json"])["plan"]["targets"][0]["user_id"], 101)

        async def add(role, **kwargs):
            assert_saved()
            self.events.append(("add", uid, role.id))
            member._roles.add(role.id)

        async def remove(role, **kwargs):
            assert_saved()
            self.assertIn(CITIZEN_ID, member._roles)
            self.events.append(("remove", uid, role.id))
            member._roles.remove(role.id)

        member.add_roles = AsyncMock(side_effect=add)
        member.remove_roles = AsyncMock(side_effect=remove)
        self.members[uid] = member
        return member

    async def test_exact_two_accounts_keep_citizen_and_other_members_are_untouched(self):
        result = await keep_citizen_roles(self.bot)
        self.assertTrue(all(r["only_citizen"] for r in result.values()))
        self.assertEqual(self.first._roles, {CITIZEN_ID})
        self.assertEqual(self.second._roles, {CITIZEN_ID})
        self.assertEqual(self.third._roles, {1245008186440683530, 10})
        self.assertEqual(self.events[0], ("add", 101, CITIZEN_ID))
        before = json.loads(self.bot.changes.journal.rows()[0]["before_json"])
        self.assertEqual({r["id"] for r in before["members"][0]["roles"]}, {1245008186440683530, 10})
        self.assertEqual(self.roles[1245008186440683530].position, 50)

    async def test_completed_request_does_not_remove_later_roles(self):
        await keep_citizen_roles(self.bot)
        count = len(self.events)
        self.first._roles.add(10)
        await keep_citizen_roles(self.bot)
        self.assertEqual(len(self.events), count)
        self.assertIn(10, self.first._roles)

    async def test_missing_or_ambiguous_exact_username_makes_no_changes(self):
        self.second.name = "esschino___"
        with self.assertRaisesRegex(ValueError, "esschino_"):
            await keep_citizen_roles(self.bot)
        self.assertFalse(self.events)
        self.assertFalse(self.bot.changes.journal.rows())
        impostor = SimpleNamespace(id=999, name="esschino__", bot=False)
        with self.assertRaises(ValueError):
            resolve_targets([self.first, self.first, impostor])

    async def test_managed_or_higher_roles_are_reported_without_role_edits(self):
        self.roles[10].managed = True
        self.roles[1300627506801541230].position = 100
        result = await keep_citizen_roles(self.bot)
        self.assertFalse(result["101"]["only_citizen"])
        self.assertEqual(result["101"]["blocked"][0]["reason"], "managed")
        self.assertEqual(result["102"]["blocked"][0]["reason"], "hierarchy_or_permission")
        self.assertEqual(self.first._roles, {CITIZEN_ID, 10})
        self.assertEqual(self.second._roles, {CITIZEN_ID, 1300627506801541230})

    async def test_no_removals_when_citizen_cannot_be_added(self):
        self.roles[CITIZEN_ID].position = 100
        with self.assertRaisesRegex(ValueError, "asignar Ciudadanos"):
            await keep_citizen_roles(self.bot)
        self.assertFalse(self.events)

    async def test_retry_uses_saved_ids_and_never_extends_original_role_plan(self):
        self.first.remove_roles.side_effect = RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            await keep_citizen_roles(self.bot)
        original = self.bot.changes.journal.rows()[0]["before_json"]
        self.first.name = "renamed_account"
        self.roles[11] = Role(11, "Nuevo", 6)
        self.first._roles.add(11)

        async def remove(role, **kwargs):
            self.first._roles.remove(role.id)

        self.first.remove_roles.side_effect = remove
        self.directory.reset_mock()
        result = await keep_citizen_roles(self.bot)
        self.directory.assert_not_awaited()
        self.assertEqual(self.first._roles, {CITIZEN_ID, 11})
        self.assertFalse(result["101"]["only_citizen"])
        self.assertEqual(self.bot.changes.journal.rows()[0]["before_json"], original)

    async def test_only_role_cosmetics_are_unequipped_and_saved(self):
        for uid in (101, 102, 103):
            for slot in ("color", "titulo", "banner"):
                self.store.rows("INSERT INTO eco_equipped VALUES (?,?,?,?)", (uid, slot, "purchase", "value"))
        await keep_citizen_roles(self.bot)
        self.assertEqual([r["slot"] for r in self.store.rows("SELECT * FROM eco_equipped WHERE user_id=101")], ["banner"])
        self.assertEqual(len(self.store.rows("SELECT * FROM eco_equipped WHERE user_id=103")), 3)
        before = json.loads(self.bot.changes.journal.rows()[0]["before_json"])
        self.assertEqual({r["slot"] for r in before["plan"]["targets"][0]["equipped"]}, {"color", "titulo"})

    async def test_disabled_or_wrong_bot_cannot_mutate(self):
        with patch.dict("os.environ", {ENV: ""}):
            await keep_citizen_roles(self.bot)
        self.directory.assert_not_awaited()
        self.bot.user.id = 99
        with self.assertRaises(ValueError):
            await keep_citizen_roles(self.bot)
        self.assertFalse(self.events)
