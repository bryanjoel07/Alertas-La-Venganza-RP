import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

import discord

from change_log import ChangeLog
from tickets import TicketSystem
from ticket_bot_permission import BOT,GUILD,MARKER,ensure_bot_delete_permission
from tickets_store import PROTECTED


class BotPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'bot.sqlite'
        self.role=NS(id=700,name='Alertas La Venganza RP',managed=True,tags=NS(bot_id=BOT),permissions=discord.Permissions(send_messages=True))
        self.other=NS(id=701,name='Otra integración',managed=True,tags=NS(bot_id=123),permissions=discord.Permissions.none(),edit=AsyncMock())
        self.everyone=NS(id=GUILD,name='@everyone',managed=False,tags=None,permissions=discord.Permissions(view_channel=True),edit=AsyncMock())
        self.member=NS(id=BOT,roles=[self.everyone,self.role])
        self.guild=NS(id=GUILD,fetch_roles=AsyncMock(side_effect=lambda:[self.everyone,self.role,self.other]),fetch_member=AsyncMock(return_value=self.member))
        self.bot=NS(user=NS(id=BOT),get_guild=lambda gid:self.guild)
        self.system=TicketSystem(self.bot,self.path,GUILD);self.system.store.initialize()
        self.bot.changes=ChangeLog(self.bot,self.path,GUILD);self.bot.changes.journal.initialize()
        async def edit(**kwargs):
            before=json.loads(self.bot.changes.journal.rows()[0]['before_json'])
            self.assertEqual(before['role'],self.role.id)
            self.assertEqual(before['permissions'],self.role.permissions.value)
            self.assertFalse(before['role_manage_channels'])
            self.assertEqual(set(kwargs),{'permissions','reason'})
            self.role.permissions=kwargs['permissions'];return self.role
        self.role.edit=AsyncMock(side_effect=edit)

    async def test_grants_only_manage_channels_on_the_verified_bot_role_after_durable_copy(self):
        original=self.role.permissions.value
        state=await ensure_bot_delete_permission(self.system)
        self.assertTrue(state['verified']);self.assertTrue(self.role.permissions.manage_channels)
        self.assertEqual(self.role.permissions.value,original|discord.Permissions(manage_channels=True).value)
        self.role.edit.assert_awaited_once();self.other.edit.assert_not_awaited();self.everyone.edit.assert_not_awaited()
        self.assertEqual(self.system.store.config(MARKER),'verified')
        await ensure_bot_delete_permission(self.system);self.role.edit.assert_awaited_once()

    async def test_administrator_already_includes_delete_permission_without_role_edits(self):
        self.role.permissions=discord.Permissions(administrator=True)
        result=await ensure_bot_delete_permission(self.system)
        self.assertTrue(result['verified']);self.role.edit.assert_not_awaited()

    async def test_effective_manage_channels_does_not_require_editing_the_highest_bot_role(self):
        self.other.managed=False;self.other.tags=None
        self.other.permissions=discord.Permissions(manage_channels=True)
        self.member.roles.append(self.other)
        result=await ensure_bot_delete_permission(self.system)
        self.assertTrue(result['verified']);self.role.edit.assert_not_awaited();self.other.edit.assert_not_awaited()

    async def test_completed_request_does_not_overwrite_a_later_manual_revocation(self):
        await ensure_bot_delete_permission(self.system)
        self.role.permissions=discord.Permissions(send_messages=True)
        result=await ensure_bot_delete_permission(self.system)
        self.assertFalse(result['verified']);self.role.edit.assert_awaited_once()

    async def test_protected_or_unassigned_roles_cannot_be_used_as_a_grant_target(self):
        self.role.id=next(iter(PROTECTED))
        with self.assertRaises(ValueError):await ensure_bot_delete_permission(self.system)
        self.role.edit.assert_not_awaited()
        self.role.id=700;self.member.roles=[self.everyone]
        with self.assertRaises(ValueError):await ensure_bot_delete_permission(self.system)
        self.role.edit.assert_not_awaited();self.everyone.edit.assert_not_awaited()

    async def test_discord_rejection_does_not_claim_permission_or_modify_another_role(self):
        self.role.edit.side_effect=discord.Forbidden(NS(status=403,reason='Forbidden'),'Missing permissions')
        state=await ensure_bot_delete_permission(self.system)
        self.assertFalse(state['verified']);self.assertFalse(self.role.permissions.manage_channels)
        self.assertNotEqual(self.system.store.config(MARKER),'verified')
        self.other.edit.assert_not_awaited();self.everyone.edit.assert_not_awaited()
