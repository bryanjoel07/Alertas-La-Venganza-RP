"""The private pending dashboard has an independent district lifecycle."""
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from vice_design import BOT_ID
from vice_district import ViceDistrict


class DashboardLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bot = MagicMock()
        self.bot.user.id = BOT_ID
        self.system = ViceDistrict(self.bot, Path(temporary.name) / 'district.sqlite3')
        self.assertIs(self.system.ticket_dashboard.system, self.system)
        self.assertIs(self.system.channel_style.system, self.system)
        self.helpers = {}
        for name in ('welcome', 'voice', 'community', 'audit', 'ticket_deletion',
                     'tickets', 'ticket_archive', 'ticket_feedback', 'ticket_reminders',
                     'ticket_dashboard', 'channel_style', 'antispam', 'optional_roles',
                     'role_icons', 'bot_separator', 'booster_club', 'boost_notices'):
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

    async def test_start_binds_new_managers_without_replacing_ticket_services(self):
        await self.system.start()
        for name in ('tickets', 'ticket_reminders', 'ticket_dashboard', 'channel_style', 'antispam'):
            self.helpers[name].start.assert_awaited_once()
        self.helpers['ticket_dashboard'].ready.assert_not_awaited()
        self.helpers['channel_style'].ready.assert_not_awaited()

    async def test_dashboard_readiness_follows_ticket_and_reminder_initialization(self):
        sequence = []
        for name in ('tickets', 'ticket_reminders', 'ticket_dashboard', 'channel_style'):
            async def record(name=name):
                sequence.append(name)
            self.helpers[name].ready.side_effect = record
        await self.system.ready_community_services()
        self.assertEqual(sequence.count('ticket_dashboard'), 1)
        self.assertEqual(sequence.count('channel_style'), 1)
        self.assertLess(sequence.index('tickets'), sequence.index('ticket_dashboard'))
        self.assertLess(sequence.index('ticket_reminders'), sequence.index('ticket_dashboard'))
        self.helpers['audit'].ready.assert_awaited_once()
        self.helpers['antispam'].ready.assert_awaited_once()

    async def test_dashboard_failure_does_not_stop_reminders_or_audit(self):
        self.helpers['ticket_dashboard'].ready.side_effect = ValueError('Private destination unavailable')
        await self.system.ready_community_services()
        for name in ('ticket_reminders', 'channel_style', 'audit', 'antispam'):
            self.helpers[name].ready.assert_awaited_once()
        self.logger.exception.assert_called_once()
        self.system.start_ticket_backfill.assert_called_once()

    async def test_style_failure_does_not_stop_private_ticket_services(self):
        self.helpers['channel_style'].ready.side_effect = ValueError('A channel name changed manually')
        await self.system.ready_community_services()
        for name in ('ticket_dashboard', 'ticket_reminders', 'audit', 'antispam'):
            self.helpers[name].ready.assert_awaited_once()
        self.logger.exception.assert_called_once()

    async def test_ticket_panel_failure_does_not_skip_dashboard_readiness(self):
        self.helpers['tickets'].ready.side_effect = ValueError('Ticket panel needs review')
        await self.system.ready_community_services()
        self.helpers['ticket_dashboard'].ready.assert_awaited_once()
        self.helpers['ticket_reminders'].ready.assert_awaited_once()
        self.helpers['channel_style'].ready.assert_awaited_once()
        self.logger.exception.assert_called_once()

    async def test_shutdown_stops_dashboard_and_existing_background_workers(self):
        await self.system.close()
        for name in ('ticket_dashboard', 'ticket_reminders', 'tickets', 'ticket_feedback',
                     'audit', 'voice', 'welcome'):
            self.helpers[name].close.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
