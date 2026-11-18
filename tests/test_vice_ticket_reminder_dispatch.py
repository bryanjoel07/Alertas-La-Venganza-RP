"""VIce reminder routing and lifecycle stay independent of other services."""
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from store_bot import GUILD_ID as STUDIO_GUILD_ID, StoreBot
from vice_design import BOT_ID, GUILD_ID
from vice_district import ViceDistrict


class ReminderDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.antispam = AsyncMock()
        self.reminders = AsyncMock()
        self.studio = AsyncMock()
        self.bot = NS(
            vice=NS(antispam=NS(message=self.antispam),
                    ticket_reminders=NS(message=self.reminders)),
            esschino=NS(observe=self.studio))
        self.message = NS(id=991, channel=NS(id=77), guild=NS(id=GUILD_ID))
        logger = patch('store_bot.log')
        self.logger = logger.start()
        self.addCleanup(logger.stop)

    async def test_district_observes_after_antispam_and_never_calls_studio(self):
        sequence = []
        async def antispam(message):
            self.assertIs(message, self.message)
            sequence.append('antispam')
        async def reminders(message):
            self.assertIs(message, self.message)
            sequence.append('reminder')
        self.antispam.side_effect = antispam
        self.reminders.side_effect = reminders
        await StoreBot.on_message(self.bot, self.message)
        self.assertEqual(sequence, ['antispam', 'reminder'])
        self.antispam.assert_awaited_once_with(self.message)
        self.reminders.assert_awaited_once_with(self.message)
        self.studio.assert_not_awaited()

    async def test_antispam_failure_does_not_drop_ticket_activity(self):
        self.antispam.side_effect = RuntimeError('antispam temporarily unavailable')
        await StoreBot.on_message(self.bot, self.message)
        self.reminders.assert_awaited_once_with(self.message)
        self.studio.assert_not_awaited()
        self.logger.exception.assert_called_once()

    async def test_reminder_failure_does_not_undo_antispam_or_reach_studio(self):
        self.reminders.side_effect = RuntimeError('reminder metadata temporarily unavailable')
        await StoreBot.on_message(self.bot, self.message)
        self.antispam.assert_awaited_once_with(self.message)
        self.reminders.assert_awaited_once_with(self.message)
        self.studio.assert_not_awaited()
        self.logger.exception.assert_called_once()

    async def test_both_failures_are_independently_contained(self):
        self.antispam.side_effect = RuntimeError('antispam failed')
        self.reminders.side_effect = RuntimeError('reminders failed')
        await StoreBot.on_message(self.bot, self.message)
        self.antispam.assert_awaited_once_with(self.message)
        self.reminders.assert_awaited_once_with(self.message)
        self.studio.assert_not_awaited()
        self.assertEqual(self.logger.exception.call_count, 2)

    async def test_studio_messages_preserve_existing_observer_only(self):
        self.message.guild.id = STUDIO_GUILD_ID
        await StoreBot.on_message(self.bot, self.message)
        self.studio.assert_awaited_once_with(self.message)
        self.antispam.assert_not_awaited()
        self.reminders.assert_not_awaited()

    async def test_foreign_guild_messages_never_reach_reminder_or_studio(self):
        self.message.guild.id = 999999999999999999
        await StoreBot.on_message(self.bot, self.message)
        self.antispam.assert_not_awaited()
        self.reminders.assert_not_awaited()
        self.studio.assert_not_awaited()

    async def test_direct_messages_never_reach_reminder_or_studio(self):
        self.message.guild = None
        await StoreBot.on_message(self.bot, self.message)
        self.antispam.assert_not_awaited()
        self.reminders.assert_not_awaited()
        self.studio.assert_not_awaited()


class ReminderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(temporary.name) / 'district.sqlite3')
        # Construction itself must wire the isolated manager to this district.
        self.assertTrue(hasattr(self.system, 'ticket_reminders'))
        self.assertIs(self.system.ticket_reminders.system, self.system)
        self.helpers = {}
        for name in ('welcome', 'voice', 'community', 'audit', 'ticket_deletion',
                     'tickets', 'ticket_archive', 'ticket_feedback', 'ticket_reminders',
                     'antispam', 'optional_roles', 'role_icons', 'bot_separator',
                     'booster_club', 'boost_notices'):
            helper = NS(start=AsyncMock(), ready=AsyncMock(), close=AsyncMock())
            self.helpers[name] = helper
            setattr(self.system, name, helper)
        self.system.call = AsyncMock()
        self.system.changes.journal.initialize = Mock()
        self.system.refresh_ticket_panel = AsyncMock()
        self.system.start_ticket_backfill = Mock()
        identity = patch('vice_district.refresh_identity_panels', new_callable=AsyncMock)
        self.identity = identity.start()
        self.addCleanup(identity.stop)
        logger = patch('vice_district.log')
        self.logger = logger.start()
        self.addCleanup(logger.stop)

    async def test_start_initializes_reminder_manager(self):
        await self.system.start()
        self.helpers['ticket_reminders'].start.assert_awaited_once()
        self.helpers['tickets'].start.assert_awaited_once()
        self.helpers['antispam'].start.assert_awaited_once()
        self.helpers['ticket_reminders'].ready.assert_not_awaited()

    async def test_ready_includes_reminders_and_preserves_other_services(self):
        await self.system.ready_community_services()
        self.helpers['ticket_reminders'].ready.assert_awaited_once()
        self.helpers['ticket_feedback'].ready.assert_awaited_once()
        self.helpers['audit'].ready.assert_awaited_once()
        self.helpers['antispam'].ready.assert_awaited_once()

    async def test_another_service_failure_does_not_skip_reminder_readiness(self):
        self.helpers['tickets'].ready.side_effect = RuntimeError('panel repair unavailable')
        await self.system.ready_community_services()
        self.helpers['ticket_reminders'].ready.assert_awaited_once()
        self.helpers['audit'].ready.assert_awaited_once()
        self.logger.exception.assert_called_once()

    async def test_reminder_readiness_failure_leaves_other_services_running(self):
        self.helpers['ticket_reminders'].ready.side_effect = RuntimeError('reminder store unavailable')
        await self.system.ready_community_services()
        self.helpers['ticket_feedback'].ready.assert_awaited_once()
        self.helpers['audit'].ready.assert_awaited_once()
        self.helpers['antispam'].ready.assert_awaited_once()
        self.system.start_ticket_backfill.assert_called_once()
        self.logger.exception.assert_called_once()

    async def test_close_stops_reminders_and_existing_workers(self):
        await self.system.close()
        for name in ('ticket_reminders', 'tickets', 'ticket_feedback', 'audit', 'voice', 'welcome'):
            self.helpers[name].close.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
