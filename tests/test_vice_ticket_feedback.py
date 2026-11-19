import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock

import discord

from esschino import StudioStore
from vice_design import GUILD_ID, BOT_ID, OWNER_ID
from vice_ticket_feedback import (TicketFeedback, FeedbackView, FeedbackModal, DESTINATION_KEY,
                                  FEEDBACK_CUSTOM_ID, REOPEN_CUSTOM_ID, TOPIC, close_key, review_key, reopen_key)
from vice_readonly import WRITE_FLAGS


async def history(items):
    for item in items:
        yield item


class TicketFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StudioStore(Path(self.tmp.name) / 'vice.sqlite3')
        self.store.initialize()
        for key, value in [('category:team', 80), ('category:closed', 88), ('role:admin', 11)]:
            self.store.put(key, value)
        self.store.add_ticket(55, 999, 'technical')
        self.store.ticket_state(55, 'closed')
        self.row = self.store.ticket(55)
        self.store.put('ticket_assignment:55', dict(guild=GUILD_ID, channel=55, owner='999',
            kind='technical', staff_id=77, staff_name='Soporte'))
        self.guild = MagicMock(spec=discord.Guild)
        self.guild.id, self.guild.owner_id = GUILD_ID, OWNER_ID
        self.roles = {}
        for role_id in [GUILD_ID, 11, 12, 13]:
            role = MagicMock(spec=discord.Role)
            role.id, role.guild = role_id, self.guild
            self.roles[role_id] = role
        self.guild.default_role = self.roles[GUILD_ID]
        self.guild.get_role.side_effect = self.roles.get
        self.guild.get_member.return_value = None
        self.guild.me = MagicMock(spec=discord.Member)
        self.guild.me.id = BOT_ID
        self.member = MagicMock(spec=discord.Member)
        self.member.id, self.member.bot, self.member.guild, self.member.display_name = 999, False, self.guild, 'Persona'
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.category_id = 55, self.guild, 88
        self.channel.name, self.channel.topic = 'cerrado-999', 'VIce ticket closed owner=999'
        self.panel = NS(id=100, author=NS(id=BOT_ID), channel=self.channel, content='', attachments=[],
            embeds=[discord.Embed(title='🔒 Conversación archivada').set_footer(text='VIce District • Ticket cerrado')],
            components=[NS(children=[NS(custom_id=FEEDBACK_CUSTOM_ID, disabled=False),
                NS(custom_id='vice:v1:ticket:delete', disabled=False)])])
        self.channel.fetch_message = AsyncMock(return_value=self.panel)
        self.store.put('ticket_delete:55', dict(guild=GUILD_ID, channel=55, owner='999', panel_id=100, state='ready'))
        self.category = MagicMock(spec=discord.CategoryChannel)
        self.category.id, self.category.guild, self.category.position = 80, self.guild, 10
        self.destination = MagicMock(spec=discord.TextChannel)
        self.destination.id, self.destination.guild, self.destination.category_id = 70, self.guild, 80
        self.destination.topic = TOPIC
        self.channels = {55: self.channel, 70: self.destination, 80: self.category}
        self.guild.fetch_channel = AsyncMock(side_effect=lambda key: self.channels[key])
        self.guild.fetch_channels = AsyncMock(return_value=list(self.channels.values()))
        self.entries = []
        self.guild.audit_logs.side_effect = lambda **kwargs: history(self.entries)
        self.bot = NS(user=NS(id=BOT_ID), get_guild=Mock(return_value=self.guild))
        self.states = []
        def validate(guild):
            if guild is None or guild.id != GUILD_ID or guild.owner_id != OWNER_ID:
                raise ValueError('wrong guild')
        async def call(method, *args):
            return getattr(self.store, method)(*args)
        async def track(kind, title, operation, request, snapshot=None):
            self.states.append(await snapshot())
            return await operation()
        self.system = NS(path=self.store.path, store=self.store, bot=self.bot, ticket_lock=asyncio.Lock(),
            validate_guild=validate, call=AsyncMock(side_effect=call), track=AsyncMock(side_effect=track))
        self.feedback = TicketFeedback(self.system)
        self.addAsyncCleanup(self.feedback.close)
        self.destination.overwrites = self.feedback.overwrites(self.guild)
        self.store.put(DESTINATION_KEY, dict(guild=GUILD_ID, channel=70, nonce='setup'))
        self.sent = []
        self.destination.history.side_effect = lambda **kwargs: history(list(self.sent))
        self.destination.fetch_message = AsyncMock(side_effect=lambda key: next(m for m in self.sent if m.id == key))
        async def send(**kwargs):
            message = NS(id=200 + len(self.sent), author=NS(id=BOT_ID), channel=self.destination,
                content='', embeds=[kwargs['embed']], attachments=[], components=[])
            self.sent.append(message)
            return message
        self.destination.send = AsyncMock(side_effect=send)
        self.interaction = self.interact()

    def interact(self):
        return NS(id=1000, guild_id=GUILD_ID, guild=self.guild, channel_id=55, user=self.member,
            message=self.panel, response=NS(defer=AsyncMock(), send_message=AsyncMock(),
                is_done=Mock(return_value=True), send_modal=AsyncMock()),
            followup=NS(send=AsyncMock()))

    async def test_rating_prompt_is_owner_only_ephemeral_and_explains_admin_privacy(self):
        view = await self.feedback.request(self.interaction)
        self.assertIsInstance(view, FeedbackView)
        payload = self.interaction.followup.send.await_args.kwargs
        self.assertTrue(payload['ephemeral'])
        self.assertIn('Solo Administración', payload['embed'].description)
        self.assertEqual([option.value for option in view.children[0].options], ['1', '2', '3', '4', '5'])
        self.destination.send.assert_not_awaited()
        self.assertIsNone(self.store.get(review_key(55)))

    async def test_score_opens_optional_private_comment_modal(self):
        view = FeedbackView(self.feedback, 55, 999)
        view.children[0]._values = ['4']
        await view.children[0].callback(self.interaction)
        modal = self.interaction.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, FeedbackModal)
        self.assertEqual(modal.score, 4)
        self.assertFalse(modal.comment.required)
        self.assertEqual(modal.comment.max_length, 1000)
        self.destination.send.assert_not_awaited()

    async def test_new_three_button_panel_allows_rating_but_unknown_controls_do_not(self):
        self.panel.components[0].children.append(NS(custom_id=REOPEN_CUSTOM_ID, disabled=False))
        view = await self.feedback.request(self.interaction)
        self.assertIsInstance(view, FeedbackView)
        self.panel.components[0].children[-1].custom_id = 'unexpected-control'
        with self.assertRaises(ValueError):
            await self.feedback.request(self.interact())

    async def test_reopen_archives_closure_and_next_close_captures_current_staff(self):
        original = await self.feedback.capture_close(self.channel, self.row, 77)
        self.store.ticket_state(55, 'open')
        row = self.store.ticket(55)
        receipt = await self.feedback.reopened(row, 'first-reopen')
        self.assertEqual(receipt['previous'], original)
        self.assertEqual(receipt['state'], 'completed')
        self.assertIsNone(self.store.get(close_key(55)))
        changed = self.store.get('ticket_assignment:55')
        changed.update(staff_id=88, staff_name='Nuevo responsable')
        self.store.put('ticket_assignment:55', changed)
        self.store.ticket_state(55, 'closed')
        current = await self.feedback.capture_close(self.channel, self.store.ticket(55), 88)
        self.assertEqual(current['staff_id'], 88)
        self.assertEqual(current['closed_by'], 88)
        self.assertEqual(self.store.get(reopen_key(55, 'first-reopen'))['previous'], original)
        self.store.ticket_state(55, 'open')
        await self.feedback.reopened(self.store.ticket(55), 'first-reopen')
        self.assertEqual(self.store.get(close_key(55)), current)
        self.destination.send.assert_not_awaited()

    async def test_reopen_preserves_existing_rating_and_prevents_second_rating_after_reclose(self):
        original_review = await self.feedback.submit(self.interaction, 55, 4, 'Privado')
        self.store.ticket_state(55, 'open')
        await self.feedback.reopened(self.store.ticket(55), 'reviewed-reopen')
        self.assertEqual(self.store.get(review_key(55)), original_review)
        self.store.ticket_state(55, 'closed')
        await self.feedback.capture_close(self.channel, self.store.ticket(55), 88)
        with self.assertRaisesRegex(ValueError, 'Ya enviaste'):
            await self.feedback.submit(self.interact(), 55, 5, 'Segunda')
        self.assertEqual(self.store.get(review_key(55)), original_review)
        self.destination.send.assert_awaited_once()

    async def test_reopen_recovers_after_clear_before_completion_without_losing_previous_close(self):
        original_close = await self.feedback.capture_close(self.channel, self.row, 77)
        self.store.ticket_state(55, 'open')
        original_call = self.system.call.side_effect
        async def fail_completion(method, *args):
            if (method == 'put' and args[0] == reopen_key(55, 'recover')
                    and args[1].get('state') == 'completed'):
                raise OSError('lost database response')
            return await original_call(method, *args)
        self.system.call.side_effect = fail_completion
        with self.assertRaises(OSError):
            await self.feedback.reopened(self.store.ticket(55), 'recover')
        self.assertIsNone(self.store.get(close_key(55)))
        self.assertEqual(self.store.get(reopen_key(55, 'recover'))['previous'], original_close)
        self.system.call.side_effect = original_call
        result = await self.feedback.reopened(self.store.ticket(55), 'recover')
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['previous'], original_close)

    async def test_reopen_rejects_wrong_scope_or_revision_without_clearing_closure(self):
        original = await self.feedback.capture_close(self.channel, self.row, 77)
        with self.assertRaises(ValueError):
            await self.feedback.reopened(self.row, 'closed-state')
        self.store.ticket_state(55, 'open')
        row = self.store.ticket(55)
        for revision in ('', '../bad', 'x' * 129, None):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                await self.feedback.reopened(row, revision)
        with self.assertRaises(ValueError):
            await self.feedback.reopened(dict(row, owner='other'), 'wrong-owner')
        self.bot.user.id = 1
        with self.assertRaises(ValueError):
            await self.feedback.reopened(row, 'wrong-bot')
        self.assertEqual(self.store.get(close_key(55)), original)

    async def test_rating_modal_from_previous_closure_is_rejected_after_reopen_and_close(self):
        view = await self.feedback.request(self.interaction)
        view.children[0]._values = ['4']
        await view.children[0].callback(self.interaction)
        modal = self.interaction.response.send_modal.await_args.args[0]
        self.assertEqual(modal.closure, self.store.get(close_key(55))['captured_at'])
        self.store.ticket_state(55, 'open')
        await self.feedback.reopened(self.store.ticket(55), 'modal-reopen')
        self.store.ticket_state(55, 'closed')
        await self.feedback.capture_close(self.channel, self.store.ticket(55), 88)
        with self.assertRaisesRegex(ValueError, 'cierre anterior'):
            await modal.on_submit(self.interact())
        self.assertIsNone(self.store.get(review_key(55)))
        self.destination.send.assert_not_awaited()

    async def test_non_owner_foreign_guild_and_bot_cannot_request_or_submit(self):
        self.member.id = 77
        with self.assertRaises(ValueError):
            await self.feedback.request(self.interaction)
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interaction, 55, 5, 'private')
        self.member.id = 999
        self.interaction.guild_id = 1514871828189941881
        with self.assertRaises(ValueError):
            await self.feedback.request(self.interaction)
        self.interaction.guild_id = GUILD_ID
        self.member.bot = True
        with self.assertRaises(ValueError):
            await self.feedback.request(self.interaction)
        self.destination.send.assert_not_awaited()

    async def test_wrong_registered_panel_or_disabled_control_is_rejected(self):
        self.interaction.message = NS(id=101, author=NS(id=BOT_ID), channel=self.channel)
        with self.assertRaises(ValueError):
            await self.feedback.request(self.interaction)
        self.interaction.message = self.panel
        self.panel.components[0].children[0].disabled = True
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interaction, 55, 5, 'private')
        self.destination.send.assert_not_awaited()

    async def test_open_deleted_and_wrong_category_tickets_are_rejected_even_after_prompt(self):
        await self.feedback.request(self.interaction)
        for state in ('open', 'deleted'):
            self.store.ticket_state(55, state)
            with self.assertRaises(ValueError):
                await self.feedback.submit(self.interact(), 55, 5, 'private')
        self.store.ticket_state(55, 'closed')
        self.channel.category_id = 99
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interact(), 55, 5, 'private')
        self.assertIsNone(self.store.get(review_key(55)))

    async def test_snapshot_freezes_responsible_and_preserves_unknown_historical_closer(self):
        first = await self.feedback.capture_close(self.channel, self.row, None)
        changed = self.store.get('ticket_assignment:55')
        changed['staff_id'] = 88
        self.store.put('ticket_assignment:55', changed)
        later = await self.feedback.capture_close(self.channel, self.row, 88)
        self.assertEqual(first, later)
        self.assertEqual(later['staff_id'], 77)
        self.assertIsNone(later['closed_by'])
        self.assertNotIn('closed_at', later)

    async def test_score_domain_and_comment_limit_are_checked_before_storage(self):
        for score in (True, False, 0, 6, '5', 3.5, None):
            with self.subTest(score=score), self.assertRaises(ValueError):
                await self.feedback.submit(self.interact(), 55, score, '')
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interact(), 55, 5, 'a' * 1001)
        self.destination.send.assert_not_awaited()
        self.assertIsNone(self.store.get(review_key(55)))

    async def test_submit_delivers_only_to_private_admin_channel_without_ping(self):
        await self.feedback.submit(self.interaction, 55, 4, '@everyone **gracias**')
        record = self.store.get(review_key(55))
        self.assertEqual(record['state'], 'delivered')
        self.assertEqual(record['staff_id'], 77)
        self.assertEqual(record['comment'], '@everyone **gracias**')
        self.assertEqual(record['score'], 4)
        kwargs = self.destination.send.await_args.kwargs
        self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        self.assertIn('4/5', kwargs['embed'].description)
        self.assertNotIn('@everyone **gracias**', kwargs['embed'].description)
        self.channel.send.assert_not_called()
        self.assertTrue(self.interaction.followup.send.await_args.kwargs['ephemeral'])
        self.assertTrue(all('comment' not in state for state in self.states))

    async def test_single_rating_wins_concurrent_submissions_and_persists_after_restart(self):
        outcomes = await asyncio.gather(self.feedback.submit(self.interact(), 55, 2, 'first'),
            self.feedback.submit(self.interact(), 55, 5, 'second'), return_exceptions=True)
        self.assertEqual(sum(isinstance(item, ValueError) for item in outcomes), 1)
        self.destination.send.assert_awaited_once()
        restarted = TicketFeedback(self.system)
        self.addAsyncCleanup(restarted.close)
        with self.assertRaisesRegex(ValueError, 'Ya enviaste'):
            await restarted.request(self.interact())
        self.assertEqual(self.store.get(review_key(55))['comment'], 'first')

    async def test_failed_publish_is_saved_truthfully_and_retried_without_source_channel(self):
        original = self.destination.send.side_effect
        self.destination.send.side_effect = OSError('network unavailable')
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            await self.feedback.submit(self.interaction, 55, 3, 'private')
        self.assertEqual(self.store.get(review_key(55))['state'], 'pending')
        self.assertIn('pendiente', self.interaction.followup.send.await_args.args[0])
        self.store.ticket_state(55, 'deleted')
        self.channels.pop(55)
        self.destination.send.side_effect = original
        restarted = TicketFeedback(self.system)
        self.addAsyncCleanup(restarted.close)
        await restarted.ready()
        self.assertEqual(self.store.get(review_key(55))['state'], 'delivered')
        self.assertEqual(len(self.sent), 1)
        await restarted.retry_pending()
        self.assertEqual(len(self.sent), 1)

    async def test_send_before_ack_recovers_exact_review_without_duplicate(self):
        original = self.destination.send.side_effect
        async def sent_but_lost(**kwargs):
            await original(**kwargs)
            raise OSError('lost acknowledgement')
        self.destination.send.side_effect = sent_but_lost
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            await self.feedback.submit(self.interaction, 55, 5, 'private')
        self.assertEqual(len(self.sent), 1)
        self.destination.send.side_effect = original
        await self.feedback.retry_pending()
        self.assertEqual(self.store.get(review_key(55))['state'], 'delivered')
        self.destination.send.assert_awaited_once()

    async def test_pending_review_is_delivered_even_if_closed_source_was_removed_manually(self):
        original = self.destination.send.side_effect
        self.destination.send.side_effect = OSError('network unavailable')
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            await self.feedback.submit(self.interaction, 55, 3, 'private')
        self.destination.send.side_effect = original
        async def fetch(channel_id):
            if channel_id == 55:
                raise discord.NotFound(NS(status=404, reason='Not Found'), {'code': 10003, 'message': 'Unknown Channel'})
            return self.channels[channel_id]
        self.guild.fetch_channel.side_effect = fetch
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            await self.feedback.ready()
        self.assertEqual(self.store.ticket(55)['state'], 'closed')
        self.assertEqual(self.store.get(review_key(55))['state'], 'delivered')
        self.assertEqual(len(self.sent), 1)

    async def test_delivered_reviews_are_not_refetched_or_published_by_retry(self):
        review = await self.feedback.submit(self.interaction, 55, 1, '')
        self.assertEqual(review['state'], 'delivered')
        self.guild.fetch_channel.reset_mock()
        self.destination.fetch_message.reset_mock()
        self.destination.send.reset_mock()
        self.assertEqual(await self.feedback.retry_pending(), 0)
        self.guild.fetch_channel.assert_not_awaited()
        self.destination.fetch_message.assert_not_awaited()
        self.destination.send.assert_not_awaited()

    async def test_retry_rotates_past_twenty_permanently_failing_reviews(self):
        for ticket_id in range(1001, 1026):
            self.store.add_ticket(ticket_id, 999, 'general')
            self.store.ticket_state(ticket_id, 'deleted')
            self.store.put(review_key(ticket_id), dict(state='pending'))
        async def deliver(ticket_id):
            if int(ticket_id) <= 1020:
                raise OSError('permanent failure')
            return dict(state='delivered')
        self.feedback.deliver = AsyncMock(side_effect=deliver)
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            self.assertEqual(await self.feedback.retry_pending(), 0)
        self.assertEqual(self.feedback.deliver.await_count, 20)
        with self.assertLogs('ViceDistrict.ticket_feedback', level='WARNING'):
            self.assertEqual(await self.feedback.retry_pending(), 5)
        second = self.feedback.deliver.await_args_list[20:]
        self.assertEqual([int(call.args[0]) for call in second[:5]], list(range(1021, 1026)))
        self.assertEqual(len(second), 20)

    async def test_database_failure_never_claims_saved_or_sends_review(self):
        original = self.system.call.side_effect
        async def fail(method, *args):
            if method == 'put' and args[0] == review_key(55):
                raise OSError('disk full')
            return await original(method, *args)
        self.system.call.side_effect = fail
        with self.assertRaises(OSError):
            await self.feedback.submit(self.interaction, 55, 5, 'private')
        self.interaction.followup.send.assert_not_awaited()
        self.destination.send.assert_not_awaited()

    async def test_admin_destination_needs_no_owner_cache_and_excludes_mod_support(self):
        rules = self.feedback.overwrites(self.guild)
        self.assertEqual({target.id for target in rules}, {GUILD_ID, OWNER_ID, BOT_ID, 11})
        self.assertIs(rules[self.guild.default_role].view_channel, False)
        for target, overwrite in rules.items():
            if target.id != BOT_ID:
                self.assertTrue(all(getattr(overwrite, flag) is False for flag in WRITE_FLAGS))
        self.feedback.validate_destination(self.destination, self.store.get(DESTINATION_KEY))

    async def test_public_extra_staff_or_unexpected_permissions_block_rating(self):
        self.destination.overwrites[self.guild.default_role].view_channel = True
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interact(), 55, 5, 'private')
        self.destination.overwrites = self.feedback.overwrites(self.guild)
        self.destination.overwrites[self.roles[12]] = discord.PermissionOverwrite(view_channel=True)
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interact(), 55, 5, 'private')
        self.destination.overwrites = self.feedback.overwrites(self.guild)
        self.destination.overwrites[self.roles[11]].send_messages = True
        with self.assertRaises(ValueError):
            await self.feedback.submit(self.interact(), 55, 5, 'private')
        self.destination.send.assert_not_awaited()
        self.assertIsNone(self.store.get(review_key(55)))

    async def test_creation_prepares_permissions_before_attempt_and_recovers_by_audit_only(self):
        self.store.put(DESTINATION_KEY, None)
        self.roles.pop(11)
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        with self.assertRaises(ValueError):
            await self.feedback.ensure_destination()
        self.assertIsNone(self.store.get(DESTINATION_KEY))
        self.guild.create_text_channel.assert_not_awaited()
        role = MagicMock(spec=discord.Role)
        role.id, role.guild = 11, self.guild
        self.roles[11] = role
        self.destination.overwrites = self.feedback.overwrites(self.guild)
        self.store.put(DESTINATION_KEY, dict(guild=GUILD_ID, nonce='exact-nonce',
            started_at=datetime.now(timezone.utc).isoformat(), attempted_at='unknown-api-outcome'))
        with self.assertRaisesRegex(ValueError, 'no se creará otro'):
            await self.feedback.ensure_destination()
        self.entries.append(NS(user=NS(id=BOT_ID), reason='VIce ticket feedback exact-nonce', target=NS(id=70)))
        await self.feedback.ensure_destination()
        self.guild.create_text_channel.assert_not_awaited()
        self.assertEqual(self.store.get(DESTINATION_KEY)['channel'], 70)

    async def test_create_admin_channel_once_and_ready_never_invents_ratings(self):
        self.store.put(DESTINATION_KEY, None)
        self.guild.create_text_channel = AsyncMock(return_value=self.destination)
        await self.feedback.ready()
        await self.feedback.ready()
        self.guild.create_text_channel.assert_awaited_once()
        self.destination.send.assert_not_awaited()
        self.assertIsNone(self.store.get(review_key(55)))
        self.assertIsNotNone(self.store.get(close_key(55)))
        self.assertIsNotNone(self.feedback.task)
        worker = self.feedback.task
        await self.feedback.close()
        self.assertTrue(worker.done())
        self.assertIsNone(self.feedback.task)


if __name__ == '__main__':
    unittest.main()
