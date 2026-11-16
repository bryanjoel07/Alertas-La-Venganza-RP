from copy import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock

import discord

from change_log import ChangeLog
from tickets_store import PROTECTED
from voice_hours import BOT_ID, CHANNEL_ID, CITIZENS_ID, GUILD_ID, PR, VoiceHours, access_audit, closed_at, next_change


def local(hour, minute=0, second=0):
    return datetime(2026, 11, 16, hour, minute, second, tzinfo=PR)


class VoiceTimeTests(unittest.TestCase):
    def test_exact_opening_closing_and_utc_midnight(self):
        for at, expected in [(local(0), True), (local(6, 29, 59), True),
                (local(6, 30), False), (local(18, 29, 59), False), (local(18, 30), True),
                (local(23, 59), True)]:
            with self.subTest(at=at):
                self.assertEqual(closed_at(at), expected)
                self.assertEqual(closed_at(at.astimezone(timezone.utc)), expected)
        with self.assertRaises(ValueError):
            closed_at(datetime(2026, 11, 16, 6, 30))

    def test_next_transition_uses_puerto_rico_date_across_midnight(self):
        self.assertEqual(next_change(local(4)), local(6, 30))
        self.assertEqual(next_change(local(6, 30)), local(18, 30))
        tomorrow = datetime(2026, 11, 17, 6, 30, tzinfo=PR)
        self.assertEqual(next_change(local(18, 30).astimezone(timezone.utc)), tomorrow)


class Member:
    def __init__(self, guild, uid, admin=False):
        self.id, self.guild = uid, guild
        self.guild_permissions = discord.Permissions(administrator=admin)
        self.voice = NS(channel=None)
        self.moves = []

    async def move_to(self, destination, *, reason):
        self.moves.append(destination)
        self.voice = NS(channel=destination)
        self.guild._voice_states.pop(self.id, None)


class Room(discord.VoiceChannel):
    def __init__(self, guild):
        self.id, self.guild = CHANNEL_ID, guild
        self.name, self.category_id = 'Sala de voz', 123
        self.mapping = {}
        self.edits = []
        self.manage_permissions = True

    @property
    def overwrites(self):
        return {target: copy(overwrite) for target, overwrite in self.mapping.items()}

    def overwrites_for(self, target):
        match = next((o for t, o in self.mapping.items() if t.id == target.id), None)
        return copy(match) if match is not None else discord.PermissionOverwrite()

    def permissions_for(self, target):
        return discord.Permissions(manage_roles=self.manage_permissions, move_members=True)

    async def set_permissions(self, target, *, overwrite, reason):
        assert target.id not in PROTECTED
        journals = self.system.bot.changes.journal.rows()
        assert any(row['status'] == 'iniciado' and 'overwrites' in json.loads(row['before_json']) for row in journals)
        self.edits.append(target.id)
        existing = next((t for t in self.mapping if t.id == target.id), target)
        if overwrite is None:
            self.mapping.pop(existing, None)
        else:
            self.mapping[existing] = copy(overwrite)


class VoiceHoursTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'voice.sqlite3'
        self.guild = NS(id=GUILD_ID, _voice_states={})
        self.roles = {}
        for rid in [GUILD_ID, CITIZENS_ID, *PROTECTED, 200000000000000001]:
            self.roles[rid] = discord.Role(guild=self.guild, state=Mock(), data=dict(
                id=str(rid), name=str(rid), permissions='0', position=1, color=0))
        self.guild.default_role = self.roles[GUILD_ID]
        self.guild.roles = list(self.roles.values())
        self.guild.get_role = self.roles.get
        self.members = {}
        self.guild.get_member = self.members.get
        self.guild.fetch_member = AsyncMock(side_effect=lambda uid: self.members[uid])
        self.guild.me = Member(self.guild, BOT_ID, admin=True)
        self.room = Room(self.guild)
        self.room.mapping[self.roles[GUILD_ID]] = discord.PermissionOverwrite(send_messages=True)
        self.room.mapping[self.roles[CITIZENS_ID]] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        self.protected_role = self.roles[next(iter(PROTECTED))]
        self.room.mapping[self.protected_role] = discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=False)
        self.extra = self.roles[200000000000000001]
        self.room.mapping[self.extra] = discord.PermissionOverwrite(view_channel=True, stream=True)
        self.direct = Member(self.guild, 200000000000000002)
        self.members[self.direct.id] = self.direct
        self.room.mapping[self.direct] = discord.PermissionOverwrite(view_channel=True, connect=True, mute_members=False)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=Mock(return_value=self.guild),
            get_channel=Mock(return_value=self.room), fetch_channel=AsyncMock(return_value=self.room))
        self.bot.changes = ChangeLog(self.bot, self.path, GUILD_ID)
        self.bot.changes.journal.initialize()
        self.system = VoiceHours(self.bot, self.path)
        self.system.store.initialize()
        self.system.now = Mock(return_value=local(20))
        self.system.enabled = Mock(return_value=True)
        self.room.system = self.system
        self.before = {t.id: o.pair() for t, o in self.room.overwrites.items()}

    def enter(self, uid, admin=False):
        member = Member(self.guild, uid, admin)
        member.voice = NS(channel=self.room)
        self.members[uid] = member
        self.guild._voice_states[uid] = member.voice
        return member

    async def test_night_only_changes_everyone_and_citizens_preserving_every_other_overwrite(self):
        await self.system.reconcile()
        for target in [self.roles[GUILD_ID], self.roles[CITIZENS_ID]]:
            overwrite = self.room.overwrites_for(target)
            self.assertIs(overwrite.view_channel, False)
            self.assertIs(overwrite.connect, False)
        self.assertTrue(self.room.overwrites_for(self.roles[GUILD_ID]).send_messages)
        self.assertTrue(self.room.overwrites_for(self.roles[CITIZENS_ID]).speak)
        self.assertTrue(self.room.overwrites_for(self.extra).stream)
        self.assertEqual(self.room.overwrites_for(self.protected_role).pair(), self.before[self.protected_role.id])
        for target in (self.extra, self.direct):
            self.assertEqual(self.room.overwrites_for(target).pair(), self.before[target.id])
        self.assertEqual(set(self.room.edits), {GUILD_ID, CITIZENS_ID})
        edits = len(self.room.edits)
        await self.system.reconcile()
        self.assertEqual(len(self.room.edits), edits)

    async def test_day_only_opens_citizens_everyone_stays_denied_after_restart(self):
        await self.system.reconcile()
        restarted = VoiceHours(self.bot, self.path)
        restarted.store.initialize()
        restarted.now = Mock(return_value=local(6, 30))
        restarted.enabled = Mock(return_value=True)
        await restarted.reconcile()
        self.assertIs(self.room.overwrites_for(self.roles[GUILD_ID]).view_channel, False)
        self.assertIs(self.room.overwrites_for(self.roles[GUILD_ID]).connect, False)
        self.assertIs(self.room.overwrites_for(self.roles[CITIZENS_ID]).view_channel, True)
        self.assertIs(self.room.overwrites_for(self.roles[CITIZENS_ID]).connect, True)
        for target in (self.extra, self.direct, self.protected_role):
            self.assertEqual(self.room.overwrites_for(target).pair(), self.before[target.id])

    async def test_previous_staff_overwrite_is_restored_at_night_and_never_managed_again(self):
        previous = self.room.overwrites_for(self.extra)
        self.system.store.plan(self.extra.id, 'role', False,
            dict(view_channel=previous.view_channel, connect=previous.connect, present=True),
            dict(view_channel=False, connect=False))
        self.room.mapping[self.extra].view_channel = False
        self.room.mapping[self.extra].connect = False
        await self.system.reconcile()
        self.assertEqual(self.room.overwrites_for(self.extra).pair(), self.before[self.extra.id])
        self.assertEqual({r['target'] for r in self.system.store.rows()}, {GUILD_ID, CITIZENS_ID})
        edits = len(self.room.edits)
        self.system.invalidate()
        await self.system.reconcile()
        self.assertEqual(len(self.room.edits), edits)

    async def test_closed_startup_disconnects_every_occupant_including_administrator(self):
        ordinary, admin = self.enter(10), self.enter(11, admin=True)
        await self.system.reconcile()
        self.assertEqual(ordinary.moves, [None])
        self.assertEqual(admin.moves, [None])
        self.assertEqual(self.guild._voice_states, {})
        for row in self.bot.changes.journal.rows():
            self.assertEqual(row['status'], 'completado')

    async def test_rejoining_closed_room_disconnects_but_daytime_and_other_channels_are_untouched(self):
        member = self.enter(10)
        await self.system.voice_update(member, NS(channel=None), member.voice)
        self.assertEqual(member.moves, [None])
        member.voice = NS(channel=NS(id=77))
        await self.system.voice_update(member, NS(channel=None), member.voice)
        self.assertEqual(member.moves, [None])
        self.system.now.return_value = local(8)
        member.voice = NS(channel=self.room)
        await self.system.voice_update(member, NS(channel=None), member.voice)
        self.assertEqual(member.moves, [None])

    async def test_uncached_voice_member_is_fetched_and_disconnected(self):
        member = self.enter(10)
        self.members.pop(10)
        self.guild.fetch_member.side_effect = None
        self.guild.fetch_member.return_value = member
        await self.system.reconcile()
        self.guild.fetch_member.assert_awaited_once_with(10)
        self.assertEqual(member.moves, [None])

    async def test_one_failed_disconnect_does_not_leave_others_and_retries(self):
        failing, other = self.enter(10), self.enter(11)
        failing.move_to = AsyncMock(side_effect=discord.Forbidden(Mock(status=403, reason='Forbidden'), 'Denied'))
        with self.assertLogs('LaVenganzaRP.voice_hours', level='ERROR'):
            await self.system.reconcile()
        self.assertEqual(other.moves, [None])
        self.assertIn(10, self.guild._voice_states)
        failing.move_to.side_effect = None
        failing.move_to.side_effect = lambda destination, reason: self.guild._voice_states.pop(10)
        await self.system.reconcile()
        self.assertEqual(failing.move_to.await_count, 2)
        self.assertNotIn(10, self.guild._voice_states)

    async def test_disable_restores_original_permissions_and_does_not_disconnect(self):
        await self.system.reconcile()
        member = self.enter(10)
        self.system.enabled.return_value = False
        await self.system.reconcile()
        for target, overwrite in self.room.overwrites.items():
            self.assertEqual(overwrite.pair(), self.before[target.id])
        self.assertFalse(member.moves)
        self.assertFalse(self.system.store.rows())

    async def test_restoration_preserves_unrelated_and_manually_changed_flags(self):
        await self.system.reconcile()
        self.room.mapping[self.roles[CITIZENS_ID]].speak = False
        self.room.mapping[self.extra].view_channel = None
        self.system.now.return_value = local(9)
        await self.system.reconcile()
        self.assertIs(self.room.overwrites_for(self.roles[CITIZENS_ID]).speak, False)
        self.assertIsNone(self.room.overwrites_for(self.extra).view_channel)
        self.assertTrue(self.room.overwrites_for(self.extra).stream)

    async def test_opening_boundary_recheck_does_not_disconnect_someone_after_opening(self):
        member = self.enter(10)
        ticks = iter([local(6, 29, 59)])
        self.system.now.side_effect = lambda: next(ticks, local(6, 30))
        await self.system.disconnect(member)
        self.assertFalse(member.moves)

    async def test_wrong_bot_guild_and_channel_never_mutate_permissions(self):
        self.bot.user.id = BOT_ID + 1
        await self.system.reconcile()
        self.assertFalse(self.room.edits)
        self.bot.user.id = BOT_ID
        self.room.id = CHANNEL_ID + 1
        with self.assertRaises(ValueError):
            await self.system.permissions('closed')
        self.room.id = CHANNEL_ID
        self.guild.id = GUILD_ID + 1
        with self.assertRaises(ValueError):
            await self.system.permissions('closed')
        self.assertFalse(self.room.edits)

    async def test_typed_member_overwrite_uses_correct_discord_rest_endpoint(self):
        self.room._state = NS(http=NS(edit_channel_permissions=AsyncMock(), delete_channel_permissions=AsyncMock()))
        target = discord.Object(id=44, type=discord.Member)
        overwrite = discord.PermissionOverwrite(view_channel=False, connect=False)
        allow, deny = overwrite.pair()
        await self.system.write(self.room, target, overwrite, 'Horario')
        self.room._state.http.edit_channel_permissions.assert_awaited_once_with(CHANNEL_ID, 44, str(allow.value), str(deny.value), 1, reason='Horario')
        await self.system.write(self.room, target, None, 'Restaurar')
        self.room._state.http.delete_channel_permissions.assert_awaited_once_with(CHANNEL_ID, 44, reason='Restaurar')

    async def test_occupant_collection_uses_an_actual_discord_guild(self):
        guild = discord.Guild(data=dict(id=str(GUILD_ID), name='Offline', owner_id='1', roles=[]), state=Mock())
        guild._voice_states[10] = NS(channel=NS(id=CHANNEL_ID))
        guild._voice_states[11] = NS(channel=NS(id=77))
        guild._voice_states[12] = NS(channel=None)
        self.assertEqual(self.system.occupants(guild), [10])

    async def test_native_discord_access_distinguishes_citizens_from_staff_grants(self):
        guild = discord.Guild(data=dict(id=str(GUILD_ID), name='Offline', owner_id='1', roles=[
            dict(id=str(rid), name=name, permissions=str(discord.Permissions(view_channel=True, connect=True).value), position=position)
            for position, (rid, name) in enumerate([(GUILD_ID, '@everyone'), (CITIZENS_ID, 'Ciudadanos'), (77, 'Soporte')])]), state=Mock())
        denied = discord.PermissionOverwrite(view_channel=False, connect=False).pair()
        allowed = discord.PermissionOverwrite(view_channel=True, connect=True).pair()
        data = dict(id=str(CHANNEL_ID), type=2, name='Voice', position=0, bitrate=64000, user_limit=0,
            permission_overwrites=[dict(id=str(rid), type=0, allow=str(pair[0].value), deny=str(pair[1].value))
                for rid, pair in [(GUILD_ID, denied), (CITIZENS_ID, denied), (77, allowed)]])
        channel = discord.VoiceChannel(state=guild._state, guild=guild, data=data)
        audit = access_audit(channel)
        self.assertEqual(audit['everyone'], dict(view_channel=False, connect=False))
        self.assertEqual(audit['citizens'], dict(view_channel=False, connect=False))
        self.assertEqual(audit['other_roles'], [dict(id=77, name='Soporte', view_channel=True, connect=True)])
        self.assertTrue(channel.permissions_for(guild.get_role(77)).view_channel)
        for roles, visible in [([CITIZENS_ID], False), ([CITIZENS_ID, 77], True)]:
            member = discord.Member(data=dict(user=dict(id='88', username='player', discriminator='0', avatar=None),
                roles=[str(rid) for rid in roles], joined_at='2026-01-01T00:00:00+00:00', flags=0,
                deaf=False, mute=False), guild=guild, state=guild._state)
            self.assertEqual(channel.permissions_for(member).view_channel, visible)
