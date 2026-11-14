import asyncio
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import discord

from change_log import ChangeLog
from interview_reminders import notice_details
from recruitment import CHANNELS, RecruitmentSystem
from recruitment_store import QUESTIONS, RecruitmentStore
from tickets_store import ALL_STAFF


def application(store, owner=99):
    row = store.begin(owner)
    for step, questions in enumerate((QUESTIONS[:5], QUESTIONS[5:])):
        store.save_step(row['id'], owner, step, {q[0]: 'Mi respuesta' for q in questions}, row['revision'])
        row = store.get(row['id'])
    store.submit(row['id'], owner, row['revision'])
    for notice in store.pending():
        store.notice_done(notice['id'], 'sent', 100)
    return store.get(row['id'])


class InterviewReminderStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'recruitment.sqlite3'
        self.store = RecruitmentStore(self.path)
        self.store.initialize()
        self.now = int(time.time())
        self.at = self.now + 7200

    def book(self, owner=99, at=None):
        row = application(self.store, owner)
        self.store.schedule(row['id'], 1, at or self.at, 1, 'Trae el micrófono listo.', row['revision'], now=self.now)
        return self.store.get(row['id'])

    def reminders(self):
        return [n for n in self.store.pending() if n['kind'].startswith('recordatorio:')]

    def test_three_private_reminders_each_with_durable_receipts_after_restart(self):
        row = self.book()
        for notice in self.store.pending():
            self.store.notice_done(notice['id'], 'sent', 100)
        for offset, phase in [(3600, 'previo'), (900, 'pronto'), (0, 'hora')]:
            now = self.at - offset
            self.store.remind(now=now)
            self.store.remind(now=now)
            notices = self.reminders()
            self.assertEqual({n['user'] for n in notices}, {99, 1})
            self.assertEqual(len(notices), 2)
            self.assertEqual({notice_details(n['kind'])['phase'] for n in notices}, {phase})
            for notice in notices:
                self.assertIsNotNone(self.store.notice_ready(notice['id'], now=now))
                self.store.notice_done(notice['id'], 'sent', 101)
            self.store = RecruitmentStore(self.path)
            self.store.initialize()
            self.store.remind(now=now)
            self.assertEqual(self.reminders(), [])
        self.assertEqual(self.store.get(row['id'])['status'], 'entrevista')

    def test_booking_near_start_uses_confirmation_instead_of_two_immediate_dms(self):
        for owner, offset in [(99, 1800), (100, 600)]:
            row = self.book(owner, self.now + offset)
            self.store.remind(now=self.now)
            self.assertFalse([n for n in self.reminders() if n['application'] == row['id']])
            confirmations = [n for n in self.store.pending() if n['application'] == row['id']]
            self.assertEqual({n['user'] for n in confirmations}, {owner, 1})
            self.assertTrue(all(notice_details(n['kind'])['phase'] == 'confirmada' for n in confirmations))
            self.store.remind(now=self.now + offset)
            reminders = [n for n in self.reminders() if n['application'] == row['id']]
            self.assertEqual(len(reminders), 2)
            self.assertTrue(all(notice_details(n['kind'])['phase'] == 'hora' for n in reminders))

    def test_rescheduling_even_back_to_same_date_cancels_old_generation(self):
        row = self.book()
        self.store.remind(now=self.at - 3600)
        old = self.store.pending()
        for at in (self.at + 3600, self.at):
            current = self.store.get(row['id'])
            self.store.schedule(row['id'], 1, at, 1, 'Nueva fecha', current['revision'], now=self.now)
        for notice in old:
            self.assertEqual(self.store.notice_snapshot(notice['id'])['state'], 'cancelled')
            self.assertIsNone(self.store.notice_ready(notice['id'], now=self.at - 3600))
        self.store.remind(now=self.at - 3600)
        new = self.reminders()
        self.assertEqual(len(new), 2)
        self.assertTrue({n['kind'] for n in old}.isdisjoint({n['kind'] for n in new}))

    def test_completing_rejecting_or_withdrawing_stops_all_interview_notices(self):
        for owner, action in [(99, 'interviewed'), (100, 'reject'), (101, 'withdraw')]:
            row = self.book(owner)
            self.store.remind(now=self.at - 3600)
            pending = [n for n in self.store.pending() if n['application'] == row['id']]
            if action == 'interviewed':
                self.store.interviewed(row['id'], 1, 'Terminamos', row['revision'])
            elif action == 'reject':
                self.store.decide(row['id'], 1, False, 'Esta vez no', row['revision'])
            else:
                self.store.withdraw(row['id'], owner, row['revision'])
            self.store.remind(now=self.at)
            for notice in pending:
                self.assertIsNone(self.store.notice_ready(notice['id'], now=self.at))
                self.assertEqual(self.store.notice_snapshot(notice['id'])['state'], 'cancelled')

    def test_restart_coalesces_missed_phases_and_discards_expired_notices(self):
        self.book()
        self.store.remind(now=self.at - 300)
        soon = self.reminders()
        self.assertEqual({notice_details(n['kind'])['phase'] for n in soon}, {'pronto'})
        self.store.remind(now=self.at + 30)
        for notice in soon:
            self.assertIsNone(self.store.notice_ready(notice['id'], now=self.at + 30))
        start = self.reminders()
        self.assertEqual(len(start), 2)
        self.assertTrue(all(notice_details(n['kind'])['phase'] == 'hora' for n in start))
        for notice in start:
            self.assertIsNone(self.store.notice_ready(notice['id'], now=self.at + 601))
        self.store.remind(now=self.at + 601)
        self.assertEqual(self.reminders(), [])

    def test_late_booking_confirmation_is_replaced_by_current_reminder_with_instructions(self):
        self.book()
        confirmations = self.store.pending()
        self.store.remind(now=self.at - 900)
        for notice in confirmations:
            self.assertIsNone(self.store.notice_ready(notice['id'], now=self.at - 900))
        reminders = self.reminders()
        self.assertEqual(len(reminders), 2)
        self.assertTrue(all('Trae el micrófono listo.' in n['text'] for n in reminders))
        self.assertTrue(all(self.store.notice_ready(n['id'], now=self.at - 900) for n in reminders))

    def test_existing_legacy_receipt_is_honored_but_does_not_suppress_new_booking(self):
        row = self.book()
        with self.store.db() as db:
            db.execute('DELETE FROM lv_recruit_notices WHERE application=?', (row['id'],))
            self.store._notice(db, row, f'recordatorio:{self.at}', 'Aviso antiguo', 99, state='sent')
        self.store.remind(now=self.at - 3600)
        self.assertEqual([n['user'] for n in self.reminders()], [1])
        current = self.store.get(row['id'])
        self.store.schedule(row['id'], 1, self.at, 1, 'Nueva cita', current['revision'], now=self.now)
        self.store.remind(now=self.at - 3600)
        self.assertEqual({n['user'] for n in self.reminders()}, {99, 1})

    def test_short_configured_advance_avoids_an_extra_fifteen_minute_notice(self):
        self.store.config('interview_notice_minutes', 5)
        self.book()
        self.store.remind(now=self.at - 900)
        self.assertEqual(self.reminders(), [])
        self.store.remind(now=self.at - 300)
        self.assertEqual(len(self.reminders()), 2)
        self.assertIsNone(self.store.interview_reminder_settings()['second_minutes'])

    def test_followup_question_keeps_scheduled_interview_reminders(self):
        row = self.book()
        self.store.staff_text(row['id'], 1, 'pregunta', '¿Tienes micrófono?', row['revision'])
        self.store.remind(now=self.at - 900)
        self.assertEqual(len(self.reminders()), 2)
        for notice in self.reminders():
            self.assertIsNotNone(self.store.notice_ready(notice['id'], now=self.at - 900))

    def test_no_general_or_unscheduled_application_reminders(self):
        application(self.store)
        self.store.begin(100)
        self.store.remind(now=self.now)
        self.assertEqual(self.store.pending(), [])


async def history(items):
    for item in list(items):
        yield item


class InterviewReminderDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'recruitment.sqlite3'
        reviewer = NS(id=1, roles=[NS(id=next(iter(ALL_STAFF)))], guild_permissions=discord.Permissions.none())
        self.guild = NS(fetch_member=AsyncMock(return_value=reviewer))
        self.bot = NS(user=NS(id=500), get_guild=Mock(return_value=self.guild), fetch_user=AsyncMock())
        self.system = RecruitmentSystem(self.bot, self.path, 55)
        await self.system.call('initialize')
        self.bot.changes = ChangeLog(self.bot, self.path, 55)
        self.bot.changes.journal.initialize()
        self.row = application(self.system.store)
        self.at = int(time.time()) + 1800
        self.system.store.schedule(self.row['id'], 1, self.at, 1, 'Trae el micrófono listo.', self.row['revision'])
        self.messages = {99: [], 1: []}
        self.channels = {}
        for uid in (99, 1):
            async def send(*, embed, view, allowed_mentions, uid=uid):
                # The before-state must be durable before a new interview DM.
                journals = self.bot.changes.journal.rows()
                self.assertTrue(any(r['status'] == 'iniciado' and json.loads(r['before_json'])['data']['user'] == uid for r in journals))
                message = NS(id=1000 + len(self.messages[uid]), author=self.bot.user, embeds=[embed], view=view)
                self.messages[uid].append(message)
                return message
            self.channels[uid] = NS(history=lambda limit, uid=uid: history(self.messages[uid]), send=AsyncMock(side_effect=send))
        self.bot.fetch_user.side_effect = lambda uid: NS(create_dm=AsyncMock(return_value=self.channels[uid]))

    async def test_private_confirmation_links_and_correct_controls_for_both_people(self):
        await self.system.notices()
        self.assertEqual([len(self.messages[uid]) for uid in (99, 1)], [1, 1])
        for uid, action in [(99, 'status'), (1, 'detail')]:
            message = self.messages[uid][0]
            self.assertIn(f'<t:{self.at}:F>', message.embeds[0].description)
            self.assertIn('Trae el micrófono listo.', message.embeds[0].description)
            self.assertIn(f'lv:recruit:{self.row["id"]}:{action}', [getattr(c, 'custom_id', None) for c in message.view.children])
            self.assertIn(f'https://discord.com/channels/55/{CHANNELS["voice"]}', [getattr(c, 'url', None) for c in message.view.children])
        for change in self.bot.changes.journal.rows():
            self.assertEqual(change['status'], 'completado')
            self.assertEqual(json.loads(change['after_json'])['data']['state'], 'sent')
        self.assertEqual(self.system.store.pending(), [])

    async def test_candidate_dms_blocked_alerts_assigned_interviewer_once(self):
        self.channels[99].send.side_effect = discord.Forbidden(Mock(status=403, reason='Forbidden'), 'DM closed')
        await self.system.notices()
        await self.system.notices()
        await self.system.notices()
        self.assertEqual(self.channels[99].send.await_count, 1)
        self.assertEqual(len(self.messages[1]), 2)
        self.assertEqual(sum('No pude avisarle' in m.embeds[0].description for m in self.messages[1]), 1)
        self.assertEqual(self.system.store.get(self.row['id'])['interview_at'], self.at)

    async def test_demoted_interviewer_does_not_receive_application_information(self):
        self.guild.fetch_member.return_value = NS(id=1, roles=[], guild_permissions=discord.Permissions.none())
        await self.system.notices()
        self.assertEqual(len(self.messages[99]), 1)
        self.assertEqual(self.messages[1], [])
        self.assertNotIn(1, [call.args[0] for call in self.bot.fetch_user.call_args_list])

    async def test_reschedule_during_network_read_cancels_old_dms_before_send(self):
        async def changed_history(limit):
            current = self.system.store.get(self.row['id'])
            self.system.store.schedule(current['id'], 1, self.at + 7200, 1, 'Cambiamos la hora', current['revision'])
            if False:
                yield
        for channel in self.channels.values():
            channel.history = changed_history
        await self.system.notices()
        self.assertFalse(self.messages[99])
        self.assertFalse(self.messages[1])
        self.assertEqual(self.system.store.get(self.row['id'])['interview_at'], self.at + 7200)

    async def test_ambiguous_send_is_reconciled_from_durable_marker_without_duplicate(self):
        original = self.channels[99].send.side_effect
        async def sent_then_timeout(**kwargs):
            await original(**kwargs)
            raise discord.HTTPException(Mock(status=503, reason='Unavailable'), 'response lost')
        self.channels[99].send.side_effect = sent_then_timeout
        await self.system.notices()
        self.assertEqual(len(self.messages[99]), 1)
        self.assertTrue(self.system.store.pending())
        self.channels[99].send.side_effect = original
        await self.system.notices()
        self.assertEqual(len(self.messages[99]), 1)
        self.assertEqual(self.channels[99].send.await_count, 1)
        self.assertEqual(self.system.store.pending(), [])
        self.assertTrue(all(row['status'] == 'completado' for row in self.bot.changes.journal.rows()))

    async def test_concurrent_delivery_only_sends_one_dm_per_recipient(self):
        await asyncio.gather(self.system.notices(), self.system.notices())
        self.assertEqual([len(self.messages[uid]) for uid in (99, 1)], [1, 1])
