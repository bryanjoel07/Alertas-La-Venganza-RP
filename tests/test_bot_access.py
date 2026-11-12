import importlib
from copy import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import discord

from bot_access import (ADMIN_DISCOVERY, ADMIN_ROLES, STAFF_ROLES, GUILD_ID,
    command_access, command_level, install_command_access, is_bot_admin)
from feedback import is_staff
from recruitment import can_review
from tickets import is_staff_role

CITIZENS = 1245009164070158409
SUPPORT = 1300627732954349619
MODERATOR = 1300631163362218054
ADMIN = 1300619682486947931
SUPER_ADMIN = 1245010156576833536
CUSTOM_ADMIN = 800000000000000001
SPOOF = 800000000000000002
DELEGATE = 800000000000000003
TIMEOUT_ONLY = 800000000000000004


class BotAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, dict(DISCORD_BOT_TOKEN='offline-placeholder',
            DISCORD_WEBHOOK_URL='https://example.invalid',
            DB_PATH=str(Path(self.temp.name) / 'access.db'), ALLOW_EMPTY_DB='1'))
        env.start()
        self.addCleanup(env.stop)
        self.module = importlib.import_module('bot')
        self.app = self.module.LaVenganzaBot()
        self.addAsyncCleanup(self.app.close)
        self.config = {}
        self.app.economy.store = SimpleNamespace(config=lambda key:self.config.get(key, ''))
        self.app.tickets.store = SimpleNamespace(config=lambda key:self.config.get(key, ''))
        # The original event/alert decorators register on the module's client;
        # include those roots as well as the systems created by the constructor.
        for root in self.module.client.tree.get_commands(guild=self.module.GUILD):
            if self.app.tree.get_command(root.name, guild=self.module.GUILD) is None:
                self.app.tree.add_command(copy(root), guild=self.module.GUILD)
        self.inventory = install_command_access(self.app.tree, self.module.GUILD)
        roles = []
        for position, rid in enumerate([GUILD_ID, CITIZENS, *sorted(STAFF_ROLES),
            CUSTOM_ADMIN, SPOOF, DELEGATE, TIMEOUT_ONLY]):
            permissions = discord.Permissions(view_channel=True, read_message_history=True,
                send_messages=True, use_application_commands=True)
            if rid in ADMIN_ROLES or rid == TIMEOUT_ONLY:
                permissions.moderate_members = True
            if rid == CUSTOM_ADMIN:
                permissions.administrator = True
            roles.append(dict(id=str(rid), name='Admin' if rid == SPOOF else f'role-{rid}',
                position=position, permissions=str(permissions.value)))
        self.guild = discord.Guild(data=dict(id=str(GUILD_ID), name='Offline server',
            owner_id='999999999999999999', roles=roles), state=self.app._connection)
        self.app._connection._guilds[GUILD_ID] = self.guild

    def member(self, *roles, bot=False, uid=1):
        return discord.Member(data=dict(user=dict(id=str(uid), username=f'user{uid}',
            discriminator='0', avatar=None, bot=bot), roles=[str(rid) for rid in (CITIZENS, *roles)],
            joined_at='2026-01-01T00:00:00+00:00', flags=0, deaf=False, mute=False),
            guild=self.guild, state=self.app._connection)

    def interaction(self, member, name='ajustes panel', **extra):
        return SimpleNamespace(user=member, guild=self.guild, guild_id=GUILD_ID,
            client=self.app, command=self.app.tree.get_command(name.split()[0], guild=self.module.GUILD)
            if ' ' not in name else SimpleNamespace(name=name.split()[-1], qualified_name=name),
            channel_id=123, type=discord.InteractionType.application_command,
            response=SimpleNamespace(send_message=AsyncMock(), autocomplete=AsyncMock(), defer=AsyncMock()), **extra)

    async def test_every_registered_command_has_an_explicit_policy(self):
        names = {command.qualified_name for command in self.app.tree.walk_commands(guild=self.module.GUILD)
            if isinstance(command, discord.app_commands.Command)}
        self.assertEqual(set(self.inventory), names)
        self.assertGreaterEqual(len(names), 108)
        with self.assertRaises(ValueError):
            command_level('administracion_nueva')

    async def test_command_snapshot_keeps_permissions_omitted_by_discord_py_serialization(self):
        for permissions in (None, '0', '8', str(ADMIN_DISCOVERY.value)):
            data = dict(id='123', application_id='1567658433497399408', guild_id=str(GUILD_ID),
                type=1, name='ajustes', description='Settings', options=[], default_member_permissions=permissions)
            remote = discord.app_commands.AppCommand(data=data, state=self.app._connection)
            self.app.tree.fetch_commands = AsyncMock(return_value=[remote])
            snapshot = await self.app.command_snapshot()
            self.assertEqual(snapshot['guild_id'], GUILD_ID)
            self.assertEqual(snapshot['commands'][0]['default_member_permissions'], permissions)
            self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)

    async def test_member_support_and_moderator_cannot_run_any_administrative_command(self):
        for roles in [(), (SUPPORT,), (MODERATOR,), (SPOOF,), (TIMEOUT_ONLY,)]:
            member = self.member(*roles)
            for name, level in self.inventory.items():
                with self.subTest(roles=roles, command=name):
                    interaction = self.interaction(member, name)
                    if level in {'admin', 'economy', 'meeting'} or (level in {'staff', 'case_staff'} and roles not in [(SUPPORT,), (MODERATOR,)]):
                        with self.assertRaises(discord.app_commands.CheckFailure):
                            await command_access(interaction)
                    else:
                        self.assertTrue(await command_access(interaction))

    async def test_each_admin_rank_can_use_administrative_commands_without_global_administrator(self):
        for rid in ADMIN_ROLES:
            member = self.member(rid)
            self.assertFalse(member.guild_permissions.administrator)
            for name, level in self.inventory.items():
                if level in {'admin', 'economy'}:
                    with self.subTest(role=rid, command=name):
                        self.assertTrue(await command_access(self.interaction(member, name)))

    async def test_global_administrator_keeps_access_but_private_meeting_roles_remain_required(self):
        member = self.member(CUSTOM_ADMIN)
        self.assertTrue(await command_access(self.interaction(member, 'ajustes panel')))
        with self.assertRaises(discord.app_commands.CheckFailure):
            await command_access(self.interaction(member, 'reunion informe'))

    async def test_discord_discovery_permissions_never_authorize_a_timeout_only_member(self):
        member = self.member(TIMEOUT_ONLY)
        self.assertTrue(member.guild_permissions.moderate_members)
        self.assertFalse(is_bot_admin(member))
        self.assertEqual(self.app.tree.get_command('ajustes', guild=self.module.GUILD).default_permissions, ADMIN_DISCOVERY)
        interaction = self.interaction(member)
        self.assertFalse(await self.app.tree.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])

    async def test_changing_discord_integration_visibility_cannot_bypass_runtime_authorization(self):
        self.app.tree.get_command('ajustes', guild=self.module.GUILD).default_permissions = None
        interaction = self.interaction(self.member())
        self.assertFalse(await self.app.tree.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()
        self.assertIn('rol', interaction.response.send_message.call_args.args[0])
        self.assertTrue(await self.app.tree.interaction_check(self.interaction(self.member(), 'guia')))

    async def test_unauthorized_autocomplete_returns_no_administrative_choices(self):
        interaction = self.interaction(self.member(), 'economia producto')
        interaction.type = discord.InteractionType.autocomplete
        self.assertFalse(await self.app.tree.interaction_check(interaction))
        interaction.response.autocomplete.assert_awaited_once_with([])
        interaction.response.send_message.assert_not_awaited()

    async def test_finance_delegate_is_scoped_and_citizens_cannot_become_a_delegate(self):
        member = self.member(DELEGATE)
        self.config['admin_role'] = str(DELEGATE)
        self.assertTrue(await command_access(self.interaction(member, 'economia ajustar')))
        self.assertTrue(await command_access(self.interaction(member, 'foto premio')))
        for name in ('ajustes panel', 'respaldo crear', 'cambios detalle', 'ticket departamento'):
            with self.subTest(command=name), self.assertRaises(discord.app_commands.CheckFailure):
                await command_access(self.interaction(member, name))
        self.config['admin_role'] = str(CITIZENS)
        with self.assertRaises(discord.app_commands.CheckFailure):
            await command_access(self.interaction(self.member(), 'economia ajustar'))

    async def test_department_delegate_does_not_gain_other_staff_or_admin_functions(self):
        member = self.member(DELEGATE)
        from tickets_store import DEPARTMENTS
        self.config['route:' + next(key for key in DEPARTMENTS if key != 'staff')] = f'[{DELEGATE}]'
        self.assertTrue(await command_access(self.interaction(member, 'ticket gestion')))
        for name in ('staff pendientes', 'ticket configuracion', 'feedback resumen', 'economia ajustar'):
            with self.subTest(command=name), self.assertRaises(discord.app_commands.CheckFailure):
                await command_access(self.interaction(member, name))

    async def test_role_names_cannot_impersonate_staff_in_tickets_feedback_or_recruitment(self):
        member = self.member(SPOOF)
        role = self.guild.get_role(SPOOF)
        self.assertEqual(role.name, 'Admin')
        self.assertFalse(is_staff_role(role))
        self.assertFalse(is_staff(member))
        self.assertFalse(can_review(member))
        self.assertTrue(is_staff_role(self.guild.get_role(SUPPORT)))

    async def test_bots_foreign_guild_and_direct_messages_are_rejected_even_with_admin_role(self):
        for member, guild_id in [(self.member(ADMIN, bot=True), GUILD_ID),
            (self.member(ADMIN), GUILD_ID + 1), (self.member(ADMIN), None)]:
            interaction = self.interaction(member)
            interaction.guild_id = guild_id
            with self.assertRaises(discord.app_commands.CheckFailure):
                await command_access(interaction)

    async def test_admin_and_super_admin_work_in_the_actual_private_handler_guards(self):
        forum = SimpleNamespace(permissions_for=lambda member:discord.Permissions(view_channel=True, read_message_history=True))
        for rid in (ADMIN, SUPER_ADMIN):
            member = self.member(rid)
            interaction = self.interaction(member)
            with patch.object(discord.Guild, 'fetch_member', AsyncMock(return_value=member)), \
                patch.object(self.app.bugs, 'forum', AsyncMock(return_value=forum)), \
                patch.object(self.app.suggestions, 'target', AsyncMock(return_value=forum)):
                await self.app.settings_panel.authorize(interaction, refresh=True)
                self.app.changes.authorize(interaction)
                self.assertTrue(await self.app.backups.admin(interaction))
                self.app.economy.authorized(interaction)
                self.app.tickets.admin(member)
                await self.app.feedback.member(interaction, admin=True)
                await self.app.bugs.member(interaction, admin=True)
                await self.app.suggestions.member(interaction, admin=True)

    async def test_members_and_support_are_rejected_by_private_handler_guards_too(self):
        for roles in [(), (SUPPORT,), (MODERATOR,), (SPOOF,)]:
            member = self.member(*roles)
            interaction = self.interaction(member)
            with self.assertRaises(ValueError):
                self.app.tickets.admin(member)
            with self.assertRaises(ValueError):
                self.app.economy.authorized(interaction)
            with self.assertRaises(discord.app_commands.CheckFailure):
                self.app.changes.authorize(interaction)
            with self.assertRaises(discord.app_commands.CheckFailure):
                await self.app.backups.admin(interaction)
            with patch.object(discord.Guild, 'fetch_member', AsyncMock(return_value=member)):
                with self.assertRaises(ValueError):
                    await self.app.settings_panel.authorize(interaction, refresh=True)
                with self.assertRaises(ValueError):
                    await self.app.feedback.member(interaction, admin=True)

    async def test_losing_the_role_before_saving_is_rechecked_from_discord(self):
        interaction = self.interaction(self.member(ADMIN))
        with patch.object(discord.Guild, 'fetch_member', AsyncMock(return_value=self.member())):
            with self.assertRaises(ValueError):
                await self.app.settings_panel.authorize(interaction, refresh=True)

    async def test_bot_admin_role_does_not_override_reserved_ticket_privacy(self):
        row = dict(id=10, department='staff', owner=20, excluded=None)
        for rid in (ADMIN, SUPER_ADMIN):
            with self.subTest(role=rid), self.assertRaises(ValueError):
                self.app.tickets.authorize(self.member(rid), row, staff=True)

    async def test_reserved_ticket_recovery_is_authorized_before_any_operation(self):
        row = dict(id=10, department='staff', owner=20, excluded=None)
        self.app.tickets.store.get = lambda rid, **kwargs:row
        self.app.tickets.recover = AsyncMock()
        with self.assertRaises(ValueError):
            await self.app.tickets.group.get_command('recuperar').callback(self.interaction(self.member(ADMIN)), 10)
        self.app.tickets.recover.assert_not_awaited()

    async def test_bot_change_history_does_not_bypass_reserved_case_permissions(self):
        row = dict(before_json=json.dumps({'ticket':{'department':'staff','form':'PRIVATE'}}), after_json='{}')
        self.assertFalse(self.app.changes.can_read(self.member(ADMIN), row))
        self.assertTrue(self.app.changes.can_read(self.member(CUSTOM_ADMIN), row))
        normal = dict(before_json=json.dumps({'settings':{'value':1}}), after_json='{}')
        self.assertTrue(self.app.changes.can_read(self.member(ADMIN), normal))
        self.assertFalse(self.app.changes.can_read(self.member(), normal))

    async def test_feedback_change_history_resolves_the_reserved_ticket_reference(self):
        row = dict(before_json=json.dumps({'feedback':{'ticket':10,'comment':'PRIVATE'}}), after_json='{}')
        self.app.tickets.store.get = lambda rid:dict(id=rid, department='staff')
        self.assertFalse(self.app.changes.can_read(self.member(ADMIN), row))
        self.app.tickets.store.get = lambda rid:dict(id=rid, department='technical')
        self.assertTrue(self.app.changes.can_read(self.member(ADMIN), row))
