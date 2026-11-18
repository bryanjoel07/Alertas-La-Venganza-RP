"""District audit/anti-spam dispatch stays isolated and cannot break other handlers."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

from store_bot import GUILD_ID as STUDIO_GUILD_ID, StoreBot
from vice_design import GUILD_ID


class AuditDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = NS(id=GUILD_ID)
        self.member = NS(id=123, guild=self.guild, bot=False)
        self.before, self.after = NS(channel=None), NS(channel=NS(id=456))
        self.payload = NS(guild_id=GUILD_ID, user=self.member)
        self.entry = NS(id=987, guild=self.guild)
        self.activity = NS(member_join=AsyncMock(), member_remove=AsyncMock(),
                           voice_state_update=AsyncMock())
        self.antispam = NS(message=AsyncMock(), member_join=AsyncMock())
        self.vice = NS(activity=self.activity, member_join=AsyncMock(), member_remove=AsyncMock(),
            antispam=self.antispam, voice=NS(voice_state_update=AsyncMock()),
            audit=NS(entry_create=AsyncMock()))
        self.bot = NS(vice=self.vice, get_guild=Mock(return_value=self.guild),
            configured_event=NS(wait=AsyncMock()), welcome=NS(joined=AsyncMock()),
            esschino=NS(observe=AsyncMock()))
        logger = patch('store_bot.log')
        self.logger = logger.start()
        self.addCleanup(logger.stop)

    def assert_no_district_calls(self):
        for callback in (self.activity.member_join, self.activity.member_remove,
                         self.activity.voice_state_update, self.vice.member_join,
                         self.vice.member_remove, self.vice.voice.voice_state_update,
                         self.vice.audit.entry_create, self.antispam.message,
                         self.antispam.member_join):
            callback.assert_not_awaited()

    async def test_unrelated_guild_is_rejected_before_any_district_callback(self):
        foreign = NS(id=987654321)
        member = NS(id=123, guild=foreign, bot=False)
        await StoreBot.on_member_join(self.bot, member)
        await StoreBot.on_raw_member_remove(self.bot, NS(guild_id=foreign.id, user=member))
        await StoreBot.on_voice_state_update(self.bot, member, self.before, self.after)
        await StoreBot.on_audit_log_entry_create(self.bot, NS(id=987, guild=foreign))
        await StoreBot.on_message(self.bot, NS(id=123, guild=foreign, channel=NS(id=456)))
        self.assert_no_district_calls()
        self.bot.get_guild.assert_not_called()
        self.bot.configured_event.wait.assert_not_awaited()
        self.bot.welcome.joined.assert_not_awaited()
        self.bot.esschino.observe.assert_not_awaited()

    async def test_join_activity_is_queued_before_welcome(self):
        order = []
        async def activity(member):
            order.append('activity')
        async def antispam(member):
            order.append('antispam')
        async def welcome(member):
            order.append('welcome')
        self.activity.member_join.side_effect = activity
        self.antispam.member_join.side_effect = antispam
        self.vice.member_join.side_effect = welcome
        await StoreBot.on_member_join(self.bot, self.member)
        self.assertEqual(order, ['antispam', 'activity', 'welcome'])
        self.antispam.member_join.assert_awaited_once_with(self.member)
        self.activity.member_join.assert_awaited_once_with(self.member)
        self.vice.member_join.assert_awaited_once_with(self.member)
        self.bot.welcome.joined.assert_not_awaited()

    async def test_activity_failure_does_not_prevent_welcome(self):
        self.activity.member_join.side_effect = RuntimeError('audit queue unavailable')
        await StoreBot.on_member_join(self.bot, self.member)
        self.activity.member_join.assert_awaited_once_with(self.member)
        self.vice.member_join.assert_awaited_once_with(self.member)
        self.logger.exception.assert_called()

    async def test_antispam_failure_does_not_prevent_join_audit_or_welcome(self):
        self.antispam.member_join.side_effect = RuntimeError('protection unavailable')
        await StoreBot.on_member_join(self.bot, self.member)
        self.antispam.member_join.assert_awaited_once_with(self.member)
        self.activity.member_join.assert_awaited_once_with(self.member)
        self.vice.member_join.assert_awaited_once_with(self.member)
        self.bot.welcome.joined.assert_not_awaited()
        self.logger.exception.assert_called()

    async def test_district_message_routes_only_to_antispam(self):
        message = NS(id=123, guild=self.guild, channel=NS(id=456))
        await StoreBot.on_message(self.bot, message)
        self.antispam.message.assert_awaited_once_with(message)
        self.bot.esschino.observe.assert_not_awaited()
        self.bot.configured_event.wait.assert_not_awaited()

    async def test_district_message_antispam_error_is_caught_without_studio_fallback(self):
        message = NS(id=123, guild=self.guild, channel=NS(id=456))
        self.antispam.message.side_effect = RuntimeError('protection unavailable')
        await StoreBot.on_message(self.bot, message)
        self.antispam.message.assert_awaited_once_with(message)
        self.bot.esschino.observe.assert_not_awaited()
        self.logger.exception.assert_called()

    async def test_studio_message_preserves_its_original_observer_without_antispam(self):
        message = NS(id=123, guild=NS(id=STUDIO_GUILD_ID), channel=NS(id=456))
        await StoreBot.on_message(self.bot, message)
        self.bot.esschino.observe.assert_awaited_once_with(message)
        self.assert_no_district_calls()

    async def test_dm_message_reaches_neither_district_nor_studio(self):
        await StoreBot.on_message(self.bot, NS(id=123, guild=None, channel=NS(id=456)))
        self.assert_no_district_calls()
        self.bot.esschino.observe.assert_not_awaited()
        self.bot.get_guild.assert_not_called()

    async def test_welcome_failure_does_not_undo_activity_dispatch(self):
        self.vice.member_join.side_effect = RuntimeError('welcome upload unavailable')
        await StoreBot.on_member_join(self.bot, self.member)
        self.activity.member_join.assert_awaited_once_with(self.member)
        self.vice.member_join.assert_awaited_once_with(self.member)
        self.logger.exception.assert_called()

    async def test_departure_activity_precedes_private_goodbye_with_same_user_and_guild(self):
        order = []
        async def activity(user, guild):
            self.assertIs(user, self.member)
            self.assertIs(guild, self.guild)
            order.append('activity')
        async def goodbye(user, *, guild):
            self.assertIs(user, self.member)
            self.assertIs(guild, self.guild)
            order.append('goodbye')
        self.activity.member_remove.side_effect = activity
        self.vice.member_remove.side_effect = goodbye
        await StoreBot.on_raw_member_remove(self.bot, self.payload)
        self.assertEqual(order, ['activity', 'goodbye'])

    async def test_departure_activity_failure_does_not_prevent_private_goodbye(self):
        self.activity.member_remove.side_effect = RuntimeError('audit queue unavailable')
        await StoreBot.on_raw_member_remove(self.bot, self.payload)
        self.activity.member_remove.assert_awaited_once()
        self.vice.member_remove.assert_awaited_once_with(self.member, guild=self.guild)
        self.logger.exception.assert_called()

    async def test_private_goodbye_failure_does_not_undo_departure_activity(self):
        self.vice.member_remove.side_effect = RuntimeError('banner upload unavailable')
        await StoreBot.on_raw_member_remove(self.bot, self.payload)
        self.activity.member_remove.assert_awaited_once()
        self.vice.member_remove.assert_awaited_once_with(self.member, guild=self.guild)
        self.logger.exception.assert_called()

    async def test_voice_activity_is_queued_before_room_cleanup(self):
        order = []
        async def activity(*args):
            order.append('activity')
        async def cleanup(*args):
            order.append('cleanup')
        self.activity.voice_state_update.side_effect = activity
        self.vice.voice.voice_state_update.side_effect = cleanup
        await StoreBot.on_voice_state_update(self.bot, self.member, self.before, self.after)
        self.assertEqual(order, ['activity', 'cleanup'])
        self.activity.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)
        self.vice.voice.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)

    async def test_voice_activity_failure_does_not_prevent_room_cleanup(self):
        self.activity.voice_state_update.side_effect = RuntimeError('audit queue unavailable')
        await StoreBot.on_voice_state_update(self.bot, self.member, self.before, self.after)
        self.activity.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)
        self.vice.voice.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)
        self.logger.exception.assert_called()

    async def test_room_cleanup_failure_does_not_undo_voice_activity(self):
        self.vice.voice.voice_state_update.side_effect = RuntimeError('cleanup retry required')
        await StoreBot.on_voice_state_update(self.bot, self.member, self.before, self.after)
        self.activity.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)
        self.vice.voice.voice_state_update.assert_awaited_once_with(self.member, self.before, self.after)
        self.logger.exception.assert_called()

    async def test_gateway_audit_entry_routes_exact_entry_and_catches_queue_failure(self):
        await StoreBot.on_audit_log_entry_create(self.bot, self.entry)
        self.vice.audit.entry_create.assert_awaited_once_with(self.entry)
        self.vice.audit.entry_create.reset_mock()
        self.vice.audit.entry_create.side_effect = RuntimeError('audit queue unavailable')
        await StoreBot.on_audit_log_entry_create(self.bot, self.entry)
        self.vice.audit.entry_create.assert_awaited_once_with(self.entry)
        self.logger.exception.assert_called()

    async def test_original_studio_welcome_stays_isolated(self):
        current = NS(id=123)
        guild = NS(id=STUDIO_GUILD_ID, fetch_member=AsyncMock(return_value=current))
        member = NS(id=123, guild=guild, bot=False)
        await StoreBot.on_member_join(self.bot, member)
        self.assert_no_district_calls()
        self.bot.configured_event.wait.assert_awaited_once()
        guild.fetch_member.assert_awaited_once_with(member.id)
        self.bot.welcome.joined.assert_awaited_once_with(current)


if __name__ == '__main__':
    unittest.main()
