"""Puerto Rico event scheduling, access control, and safe restart recovery."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from vice_community import ART_VERSION, COMMUNITY_TOOLS_VERSION, EVENT_VERSION, OPENING, PR_TIME, opening_plan, parse_event_time
from vice_design import BOT_ID, GUILD_ID, OWNER_ID
from vice_district import ViceDistrict


class PuertoRicoScheduleTests(unittest.TestCase):
    def test_opening_events_use_friday_8pm_pr_and_weekly_spacing(self):
        plans = opening_plan(datetime(2026, 11, 18, 15, tzinfo=timezone.utc))
        self.assertEqual([p['key'] for p in plans], ['gta', 'clips', 'trivia'])
        starts = [datetime.fromisoformat(p['start']) for p in plans]
        self.assertEqual(starts[0], datetime(2026, 11, 20, 20, tzinfo=PR_TIME))
        self.assertEqual([p['minutes'] for p in plans], [120, 90, 60])
        for previous, current in zip(starts, starts[1:]):
            self.assertEqual(current - previous, timedelta(days=7))
        self.assertTrue(all(t.weekday() == 4 and t.hour == 20 for t in starts))

    def test_opening_uses_pr_calendar_even_after_utc_midnight(self):
        # 00:30 UTC Saturday is still 20:30 Friday in Puerto Rico.
        plans = opening_plan(datetime(2026, 11, 21, 0, 30, tzinfo=timezone.utc))
        self.assertEqual(datetime.fromisoformat(plans[0]['start']),
                         datetime(2026, 11, 27, 20, tzinfo=PR_TIME))

    def test_opening_requires_more_than_one_hour_notice(self):
        for minute, expected_day in [(59, 20), (60, 27), (61, 27)]:
            now = datetime(2026, 11, 20, 18, tzinfo=PR_TIME) + timedelta(minutes=minute)
            with self.subTest(now=now):
                first = datetime.fromisoformat(opening_plan(now)[0]['start'])
                self.assertEqual(first.day, expected_day)

    def test_pr_time_stays_utc_minus_four_in_winter_and_summer(self):
        for month in (1, 7):
            now = datetime(2026, month, 1, tzinfo=timezone.utc)
            first = datetime.fromisoformat(opening_plan(now)[0]['start'])
            self.assertEqual(first.utcoffset(), timedelta(hours=-4))
            self.assertEqual(first.astimezone(timezone.utc).hour, 0)

    def test_manual_date_is_interpreted_in_pr_not_machine_timezone(self):
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        parsed = parse_event_time(' 2026-11-20 20:00 ', now)
        self.assertEqual(parsed, datetime(2026, 11, 21, 0, tzinfo=timezone.utc))
        self.assertEqual(parsed.utcoffset(), timedelta(hours=-4))

    def test_manual_date_bounds_are_strict_ten_minutes_inclusive_180_days(self):
        now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
        for delta, accepted in [(timedelta(minutes=-1), False),
                                (timedelta(minutes=10), False),
                                (timedelta(minutes=11), True),
                                (timedelta(days=180), True),
                                (timedelta(days=180, minutes=1), False)]:
            value = (now + delta).astimezone(PR_TIME).strftime('%Y-%m-%d %H:%M')
            with self.subTest(delta=delta):
                if accepted:
                    self.assertEqual(parse_event_time(value, now), now + delta)
                else:
                    with self.assertRaisesRegex(ValueError, '10 minutos'):
                        parse_event_time(value, now)

    def test_invalid_dates_have_actionable_validation(self):
        now = datetime(2026, 11, 18, tzinfo=timezone.utc)
        for value in ('mañana', '20/11/2026 20:00', '2026-02-30 20:00', '2026-11-20 25:00'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'AAAA-MM-DD HH:MM'):
                parse_event_time(value, now)


class CommunityEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(self.tmp.name) / 'vice.db')
        self.system.store.initialize()
        self.community = self.system.community
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.bot.get_guild.return_value = self.guild
        self.lobby = MagicMock(spec=discord.VoiceChannel)
        self.lobby.id, self.lobby.guild = 101, self.guild
        self.lobby.permissions_for.return_value = discord.Permissions(view_channel=True, connect=True)
        self.guild.get_channel.side_effect = lambda cid: self.lobby if cid == 101 else None
        self.system.store.put('channel:lobby', 101)
        self.events = []

        async def fetch_events(*args, **kwargs):
            return list(self.events)

        async def create_event(**kwargs):
            event = self.event(1000 + len(self.events), name=kwargs['name'], start_time=kwargs['start_time'])
            self.events.append(event)
            return event

        self.guild.fetch_scheduled_events = AsyncMock(side_effect=fetch_events)
        self.guild.create_scheduled_event = AsyncMock(side_effect=create_event)

        async def track(kind, title, operation, request, snapshot=None):
            return await operation()

        self.system.track = AsyncMock(side_effect=track)
        self.system.panel = AsyncMock()
        self.plan = dict(key='test-gta', name='Noche del corillo',
                         start=(datetime.now(timezone.utc) + timedelta(days=14)).replace(second=0, microsecond=0).isoformat(),
                         minutes=120, description='Encuentro comunitario de GTA.')
        self.member = MagicMock(spec=discord.Member)
        self.member.id, self.member.bot, self.member.guild = 77, False, self.guild
        self.member.roles = []
        self.member.guild_permissions = discord.Permissions.none()
        self.mod = MagicMock(spec=discord.Role)
        self.mod.id = 201
        self.support = MagicMock(spec=discord.Role)
        self.support.id = 202
        self.system.store.put('role:mod', self.mod.id)
        self.system.store.put('role:support', self.support.id)
        self.guild.get_role.side_effect = lambda rid: {201: self.mod, 202: self.support}.get(rid)
        self.interaction = NS(guild=self.guild, guild_id=GUILD_ID, user=self.member, id=99)

    def event(self, event_id, **overrides):
        values = dict(id=event_id, name=self.plan['name'], creator_id=BOT_ID, channel_id=101,
                      start_time=datetime.fromisoformat(self.plan['start']),
                      status=discord.EventStatus.scheduled, url=f'https://discord.com/events/{GUILD_ID}/{event_id}')
        values.update(overrides)
        return NS(**values)

    async def test_owner_administrator_and_moderator_can_schedule(self):
        for role in ('owner', 'administrator', 'moderator'):
            self.member.id = OWNER_ID if role == 'owner' else 77
            self.member.guild_permissions = discord.Permissions(administrator=role == 'administrator')
            self.member.roles = [self.mod] if role == 'moderator' else []
            with self.subTest(role=role):
                self.community.authorize_event(self.interaction)

    async def test_support_and_regular_members_cannot_schedule(self):
        for roles, permissions in [([], discord.Permissions.none()),
                                   ([self.support], discord.Permissions.none()),
                                   ([self.support], discord.Permissions(manage_events=True))]:
            self.member.roles = roles
            self.member.guild_permissions = permissions
            with self.subTest(roles=roles), self.assertRaisesRegex(ValueError, 'Solo Fundador'):
                self.community.authorize_event(self.interaction)
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_admin_cannot_bypass_guild_or_bot_user_restrictions(self):
        self.member.guild_permissions = discord.Permissions(administrator=True)
        for wrong_id in (1514871828189941881, 1244988345327550565):
            foreign = NS(id=wrong_id, owner_id=OWNER_ID)
            interaction = NS(guild=foreign, guild_id=wrong_id, user=self.member)
            with self.subTest(guild=wrong_id), self.assertRaises(ValueError):
                self.community.authorize_event(interaction)
        for user in (NS(id=OWNER_ID, bot=False), self.member):
            self.member.bot = True
            with self.subTest(user=user), self.assertRaises(ValueError):
                self.community.authorize_event(NS(guild=self.guild, guild_id=GUILD_ID, user=user))
        with self.assertRaises(ValueError):
            self.community.authorize_event(NS(guild=None, guild_id=None, user=self.member))

    async def test_created_event_uses_public_lobby_pr_time_and_native_rsvp(self):
        event = await self.community.schedule(self.guild, self.plan)
        kwargs = self.guild.create_scheduled_event.await_args.kwargs
        self.assertIs(kwargs['channel'], self.lobby)
        self.assertIs(kwargs['entity_type'], discord.EntityType.voice)
        self.assertIs(kwargs['privacy_level'], discord.PrivacyLevel.guild_only)
        self.assertEqual(kwargs['end_time'] - kwargs['start_time'], timedelta(hours=2))
        self.assertIsNotNone(kwargs['start_time'].tzinfo)
        self.assertIn('Puerto Rico (AST)', kwargs['description'])
        self.assertIn('Me interesa', kwargs['description'])
        self.assertTrue(kwargs['image'].startswith(b'\xff\xd8\xff'))
        self.assertEqual(self.system.store.get('event:test-gta'), event.id)
        self.assertEqual(self.system.track.await_args.args[0], 'EVENT_CREATE')

    async def test_event_mutation_occurs_only_inside_tracking_with_event_snapshot(self):
        async def tracked(kind, title, operation, request, snapshot=None):
            self.guild.create_scheduled_event.assert_not_awaited()
            self.assertEqual(await snapshot(), {'guild': GUILD_ID, 'events': []})
            return await operation()
        self.system.track.side_effect = tracked
        await self.community.schedule(self.guild, self.plan)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_retry_uses_stored_event_without_duplicate(self):
        first = await self.community.schedule(self.guild, self.plan)
        second = await self.community.schedule(self.guild, self.plan)
        self.assertIs(first, second)
        self.guild.create_scheduled_event.assert_awaited_once()
        self.system.track.assert_awaited_once()

    async def test_restart_after_discord_success_before_database_write_recovers_event(self):
        real_call = self.system.call
        failed = False

        async def fail_once(method, *args):
            nonlocal failed
            if method == 'put' and args[0] == 'event:test-gta' and not failed:
                failed = True
                raise OSError('simulated database interruption')
            return await real_call(method, *args)

        self.system.call = AsyncMock(side_effect=fail_once)
        with self.assertRaises(OSError):
            await self.community.schedule(self.guild, self.plan)
        self.assertIsNone(self.system.store.get('event:test-gta'))
        # A fresh CommunityExtras instance models an in-memory state reset.
        restarted = type(self.community)(self.system)
        recovered = await restarted.schedule(self.guild, self.plan)
        self.assertIs(recovered, self.events[0])
        self.assertEqual(self.system.store.get('event:test-gta'), recovered.id)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_concurrent_requests_create_one_event(self):
        first, second = await asyncio.gather(self.community.schedule(self.guild, self.plan),
                                             self.community.schedule(self.guild, self.plan))
        self.assertIs(first, second)
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_name_time_recovery_does_not_adopt_other_creator_or_channel(self):
        self.events.extend([self.event(501, creator_id=OWNER_ID), self.event(502, channel_id=999)])
        created = await self.community.schedule(self.guild, self.plan)
        self.assertNotIn(created.id, (501, 502))
        self.guild.create_scheduled_event.assert_awaited_once()

    async def test_stored_id_with_wrong_creator_or_channel_fails_closed(self):
        for overrides in ({'creator_id': OWNER_ID}, {'channel_id': 999}):
            self.events[:] = [self.event(501, **overrides)]
            self.system.store.put('event:test-gta', 501)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                await self.community.schedule(self.guild, self.plan)
        self.guild.create_scheduled_event.assert_not_awaited()
        self.system.track.assert_not_awaited()

    async def test_foreign_guild_is_rejected_before_reads_or_mutations(self):
        for foreign in (None, NS(id=1514871828189941881, owner_id=OWNER_ID),
                        NS(id=1244988345327550565, owner_id=OWNER_ID),
                        NS(id=GUILD_ID, owner_id=123)):
            with self.subTest(guild=foreign), self.assertRaises(ValueError):
                await self.community.schedule(foreign, self.plan)
        self.guild.fetch_scheduled_events.assert_not_awaited()
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_missing_wrong_type_or_foreign_lobby_prevents_creation(self):
        foreign = NS(id=1514871828189941881)
        wrong_type = MagicMock(spec=discord.TextChannel)
        wrong_type.id, wrong_type.guild = 101, self.guild
        wrong_type.permissions_for.return_value = discord.Permissions(view_channel=True, connect=True)
        foreign_lobby = MagicMock(spec=discord.VoiceChannel)
        foreign_lobby.id, foreign_lobby.guild = 101, foreign
        for lobby in (None, wrong_type, foreign_lobby):
            self.guild.get_channel.side_effect = lambda cid, value=lobby: value
            with self.subTest(lobby=lobby), self.assertRaises(ValueError):
                await self.community.schedule(self.guild, self.plan)
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_lobby_must_be_visible_and_joinable_to_everyone(self):
        for permissions in (discord.Permissions(connect=True), discord.Permissions(view_channel=True)):
            self.lobby.permissions_for.return_value = permissions
            with self.subTest(permissions=permissions), self.assertRaises(ValueError):
                await self.community.schedule(self.guild, self.plan)
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_stale_unpublished_plan_does_not_create_past_event(self):
        self.plan['start'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'futuro'):
            await self.community.schedule(self.guild, self.plan)
        self.guild.create_scheduled_event.assert_not_awaited()

    async def test_upcoming_filters_bot_creator_lobby_and_status_then_sorts(self):
        start = datetime.fromisoformat(self.plan['start'])
        early = self.event(501, start_time=start, status=discord.EventStatus.active)
        later = self.event(502, start_time=start + timedelta(days=1))
        self.events[:] = [later, self.event(503, creator_id=OWNER_ID), early,
                          self.event(504, channel_id=999), self.event(505, status=discord.EventStatus.cancelled),
                          self.event(506, status=discord.EventStatus.completed)]
        self.assertEqual(await self.community.upcoming(self.guild), [early, later])

    async def test_partial_opening_install_retries_original_dates_and_reuses_success(self):
        create = self.guild.create_scheduled_event.side_effect
        attempts = 0

        async def fail_second(**kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError('simulated Discord outage')
            return await create(**kwargs)

        self.guild.create_scheduled_event.side_effect = fail_second
        with self.assertRaises(OSError):
            await self.community.install_events(self.guild)
        original_plan = self.system.store.get('opening_events_plan')
        first_event = self.events[0]
        self.assertEqual(len(original_plan), len(OPENING))
        self.assertIsNone(self.system.store.get('events_release'))
        self.system.panel.assert_not_awaited()
        with patch('vice_community.opening_plan', side_effect=AssertionError('must retain original plan')):
            await self.community.install_events(self.guild)
        self.assertIs(self.events[0], first_event)
        self.assertEqual(len(self.events), 3)
        self.assertEqual(self.system.store.get('opening_events_plan'), original_plan)
        self.assertEqual(self.system.store.get('events_release'), EVENT_VERSION)
        self.system.panel.assert_awaited_once()

    async def test_ready_does_not_repeat_completed_releases(self):
        for key, version in [('community_commands_release', EVENT_VERSION), ('events_release', EVENT_VERSION),
                             ('art_release', ART_VERSION), ('community_tools_release', COMMUNITY_TOOLS_VERSION)]:
            self.system.store.put(key, version)
        self.community.install_art = AsyncMock()
        self.community.install_events = AsyncMock()
        with patch('vice_community.install_expansion', new_callable=AsyncMock):
            await self.community.ready()
            await self.community.ready()
        self.community.install_art.assert_not_awaited()
        self.community.install_events.assert_not_awaited()
        self.system.panel.assert_not_awaited()
        self.system.track.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
