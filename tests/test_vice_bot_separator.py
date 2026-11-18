import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import discord

from vice_bot_separator import BotSeparator, KEY, NAME
from vice_design import GUILD_ID


class Role(NS):
    def __hash__(self):
        return hash(self.id)


class BotSeparatorTests(unittest.IsolatedAsyncioTestCase):
    def setup_system(self):
        values = {}
        guild = NS(id=GUILD_ID)
        role = Role(id=123456789, guild=guild, name=NAME, position=1,
                  permissions=discord.Permissions.none(), colour=discord.Colour(0x33E5E9),
                  hoist=False, mentionable=False, managed=False, icon=NS(key='image'),
                  edit=AsyncMock())
        guild.create_role = AsyncMock(return_value=role)
        guild.fetch_roles = AsyncMock(return_value=[role])
        async def move(positions, reason):
            for item, position in positions.items():
                item.position = position
        guild.edit_role_positions = AsyncMock(side_effect=move)
        context = dict(guild=guild, roles={}, unlocked=True, top_role=NS(position=45))
        icons = NS(context=AsyncMock(return_value=context),
                   preflight_assets=Mock(return_value=[dict(key='bot', data=b'image')]))
        async def call(method, key, value=None):
            if method == 'put':
                values[key] = value
            return values.get(key)
        async def track(kind, title, operation, request, snapshot):
            await snapshot()
            return await operation()
        system = NS(store=NS(get=values.get), call=call, track=track, role_icons=icons)
        return system, guild, values, context

    async def test_create_cosmetic_then_restart_preserves_owner_placement(self):
        system, guild, values, context = self.setup_system()
        await BotSeparator(system).ready()
        kwargs = guild.create_role.call_args.kwargs
        self.assertEqual(kwargs['permissions'].value, 0)
        self.assertFalse(kwargs['hoist'])
        self.assertFalse(kwargs['mentionable'])
        self.assertEqual(kwargs['display_icon'], b'image')
        self.assertEqual(values[KEY]['role']['position'], 44)
        self.assertEqual(values[KEY]['state'], 'owner_ui_position_pending')
        system.role_icons.context.reset_mock()
        await BotSeparator(system).ready()
        system.role_icons.context.assert_not_awaited()
        guild.create_role.assert_awaited_once()

    async def test_ambiguous_prior_create_never_creates_another(self):
        system, guild, values, context = self.setup_system()
        values[KEY] = dict(state='creating', attempted=True)
        async def empty_audit(**kwargs):
            if False:
                yield None
        guild.audit_logs = empty_audit
        with self.assertRaises(ValueError):
            await BotSeparator(system).ready()
        guild.create_role.assert_not_awaited()

    async def test_name_collision_is_preserved(self):
        system, guild, values, context = self.setup_system()
        context['roles'][99] = NS(id=99, name=NAME, position=1, permissions=discord.Permissions.none(),
                                 colour=discord.Colour(0), hoist=False, mentionable=False, managed=False)
        with self.assertRaises(ValueError):
            await BotSeparator(system).ready()
        guild.create_role.assert_not_awaited()
