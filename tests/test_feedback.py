import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from change_log import ChangeLog
from feedback import FeedbackSystem, CHANNEL_ID, PANEL_MARKER, clean
from feedback_store import FeedbackStore
from feedback_ui import FeedbackForm, FeedbackAction, Picker
from tickets_store import TicketStore, ALL_STAFF


class StoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'db.sqlite'
        self.tickets = TicketStore(self.path); self.tickets.initialize()
        self.store = FeedbackStore(self.path); self.store.initialize()

    def case(self, owner=1, department='soporte', assignee=2, form=None):
        rid = self.tickets.create(owner, department, 'Asunto privado', form or {}, now=1000)
        self.tickets.update(rid, status='nuevo', channel=100+rid)
        if assignee is not None:
            self.tickets.claim(rid, assignee)
        self.tickets.transition(rid, 'cerrado', 2, 'Solución privada')
        return rid

    def test_ticket_feedback_is_atomic_under_duplicate_submissions(self):
        rid = self.case()
        def submit(_):
            try: return self.store.save(1, 4, 'Buena ayuda', 'public', ticket=rid)
            except ValueError: return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            saved = list(pool.map(submit, range(6)))
        self.assertEqual(sum(v is not None for v in saved), 1)
        self.assertEqual(self.tickets.get(rid)['rating'], 4)
        self.assertEqual(len(self.store.rows(owner=1)), 1)
        self.assertEqual(self.store.summary()['total'], 1)

    def test_only_owner_can_rate_closed_real_ticket_even_after_channel_deletion(self):
        rid = self.case()
        with self.assertRaises(ValueError): self.store.save(9, 5, '', 'public', ticket=rid)
        self.tickets.update(rid, status='en_atencion')
        with self.assertRaises(ValueError): self.store.save(1, 5, '', 'public', ticket=rid)
        self.tickets.update(rid, status='cerrado')
        with self.tickets.db() as db: db.execute('UPDATE lv_tickets SET deleted_at=2000 WHERE id=?',(rid,))
        saved = self.store.save(1, 5, '', 'public', ticket=rid)
        self.assertEqual(self.store.get(saved)['ticket'], rid)
        rid = self.case(owner=3, form={'selftest': 'probe'})
        with self.assertRaises(ValueError): self.store.save(3, 5, '', 'public', ticket=rid)

    def test_staff_reports_are_private_even_when_payload_requests_public(self):
        rid = self.case(department='staff')
        saved = self.store.save(1, 1, 'No me ayudaron', 'public', ticket=rid)
        self.assertEqual(self.store.get(saved)['visibility'], 'private')
        self.assertEqual(self.store.summary()['total'], 0)
        self.assertEqual(self.store.summary(public=False)['total'], 1)
        self.assertFalse(self.store.rows(pending=True))

    def test_original_private_ratings_are_imported_once_without_publication(self):
        rid = self.case()
        self.tickets.rate(rid, 1, 2, 'Opinión privada anterior')
        self.store.initialize(); self.store.initialize()
        rows = self.store.rows(owner=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['comment'], 'Opinión privada anterior')
        self.assertEqual(rows[0]['visibility'], 'private')
        self.assertEqual(self.store.summary()['total'], 0)

    def test_self_review_is_blocked_for_tickets_and_outside(self):
        rid = self.case(assignee=1)
        with self.assertRaises(ValueError): self.store.save(1, 5, '', 'public', ticket=rid)
        with self.assertRaises(ValueError): self.store.save(1, 5, '', 'public', staff=1, topic='Ayuda por voz')

    def test_outside_cooldown_survives_withdrawal_and_restart(self):
        rid = self.store.save(1, 1, 'No resolvieron el problema', 'public', staff=2, topic='Ayuda por voz', now=1000)
        self.store.hide(rid, 1, 'Retirada por su autor')
        self.store = FeedbackStore(self.path)
        with self.assertRaisesRegex(ValueError, 'hoy'):
            self.store.save(1, 5, '', 'private', staff=3, topic='Otra ayuda', now=87399)
        self.store.save(1, 5, '', 'private', staff=3, topic='Otra ayuda', now=87400)

    def test_response_requires_authorized_staff_and_is_once_only(self):
        rid = self.store.save(1, 3, 'Tardaron en atender', 'public', staff=2, topic='Ayuda por voz')
        with self.assertRaises(ValueError): self.store.respond(rid, 3, 'Respuesta ajena')
        self.store.respond(rid, 2, 'Gracias, vamos a mejorar el tiempo.')
        with self.assertRaises(ValueError): self.store.respond(rid, 2, 'Otra respuesta')
        self.assertEqual(self.store.get(rid)['response_by'], 2)

    def test_withdraw_preserves_original_text_but_excludes_public_counts(self):
        rid = self.store.save(1, 1, 'No me ayudaron', 'public', staff=2, topic='Ayuda por voz')
        with self.assertRaises(ValueError): self.store.hide(rid, 99, 'No autorizado')
        self.store.hide(rid, 1, 'Retirada por su autor')
        self.assertEqual(self.store.get(rid)['comment'], 'No me ayudaron')
        self.assertEqual(self.store.summary()['total'], 0)
        self.assertEqual(len(self.store.rows(owner=1)), 1)

    def test_manual_discord_deletion_is_not_republished(self):
        rid = self.store.save(1, 5, '', 'public', staff=2, topic='Ayuda por voz')
        self.store.publication(rid, 'posted', 777)
        self.store.deleted(777)
        self.assertFalse(self.store.rows(pending=True))
        self.assertIsNotNone(self.store.get(rid)['hidden_at'])

    def test_bad_values_and_blank_context_do_not_write_partial_rows(self):
        for score in (0, 6, True, '5'):
            with self.assertRaises(ValueError): self.store.save(1, score, '', 'public', staff=2, topic='Ayuda')
        with self.assertRaises(ValueError): self.store.save(1, 5, '', 'public', staff=2, topic='')
        self.assertFalse(self.store.rows(owner=1))


class Message:
    def __init__(self, mid, author, embed, view):
        self.id, self.author, self.content = mid, author, ''
        self.update(embed, view)
        self.delete = AsyncMock()

    def update(self, embed, view):
        self.embeds = [embed]
        self.components = [discord.components.ActionRow(r) for r in view.to_components()] if view else []

    async def edit(self, *, embed, view, **kwargs):
        self.update(embed, view)
        return self


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)/'db.sqlite'
        self.tickets = TicketStore(self.path); self.tickets.initialize()
        self.members = {}
        self.guild = SimpleNamespace(id=10, me=SimpleNamespace(id=500), fetch_member=AsyncMock(side_effect=lambda uid: self.members[uid]))
        for uid in (1,2,3,4):
            self.members[uid] = SimpleNamespace(id=uid, name=f'usuario{uid}', display_name=f'Jugador {uid}',
                bot=False, guild=self.guild, roles=[SimpleNamespace(id=next(iter(ALL_STAFF)),name='Soporte')] if uid==2 else [],
                guild_permissions=discord.Permissions(administrator=uid==3), display_avatar=SimpleNamespace(url='https://example.com/avatar.png'))
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id, self.channel.guild, self.channel.name, self.channel._overwrites = CHANNEL_ID, self.guild, '✨┊𝐅𝐞𝐞𝐝𝐛𝐚𝐜𝐤', []
        self.channel.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
        self.messages = {}
        self.bot = SimpleNamespace(user=SimpleNamespace(id=500,display_avatar=SimpleNamespace(url='https://example.com/avatar.png')),
            get_guild=lambda gid: self.guild, fetch_channel=AsyncMock(return_value=self.channel))
        self.bot.changes = ChangeLog(self.bot, self.path, 10); self.bot.changes.journal.initialize()
        self.system = FeedbackSystem(self.bot, self.path, 10); self.system.store.initialize()
        # General feedback tests start after the separate, one-shot access grant.
        self.system.store.config('citizen_panel_access_v1', 'complete')
        self.system.directory.load = AsyncMock(return_value=list(self.members.values()))

        async def send(*, embed, view, **kwargs):
            message = Message(len(self.messages)+100, self.bot.user, embed, view)
            self.messages[message.id] = message
            return message
        async def fetch(mid):
            if mid not in self.messages:
                raise discord.NotFound(SimpleNamespace(status=404,reason='Not Found'), {'code':10008,'message':'Unknown Message'})
            return self.messages[mid]
        async def history(**kwargs):
            for message in list(self.messages.values()):
                yield message
        self.channel.send = AsyncMock(side_effect=send)
        self.channel.fetch_message = AsyncMock(side_effect=fetch)
        self.channel.history = history

    def interaction(self, uid=1, guild=10):
        return SimpleNamespace(id=9000+uid, guild_id=guild, user=self.members[uid],
            response=SimpleNamespace(is_done=lambda: True, defer=AsyncMock(), send_modal=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    def case(self, department='soporte'):
        rid = self.tickets.create(1, department, 'ASUNTO PRIVADO', {}, now=1000)
        self.tickets.update(rid,status='nuevo',channel=400)
        self.tickets.claim(rid,2); self.tickets.transition(rid,'cerrado',2,'SOLUCIÓN PRIVADA')
        return rid

    async def test_panel_is_persistent_and_does_not_repeat_a_completed_permission_grant(self):
        await self.system.ready(); await self.system.ready()
        self.assertTrue(self.system.prepared)
        self.channel.send.assert_awaited_once()
        self.channel.set_permissions.assert_not_called()
        self.channel.purge.assert_not_called()
        message = next(iter(self.messages.values()))
        self.assertEqual(message.embeds[0].footer.text, PANEL_MARKER)
        self.assertEqual([c.custom_id for r in message.components for c in r.children], ['lvfb:start:0','lvfb:mine:0','lvfb:stats:0'])
        self.assertEqual(self.bot.changes.journal.rows()[0]['status'], 'completado')

    async def test_public_feedback_credits_player_and_never_copies_ticket_secrets(self):
        rid = self.case()
        await self.system.submit(self.interaction(), 2, 'Me hicieron esperar demasiado', 'public', ticket=rid)
        row = self.system.store.rows(owner=1)[0]
        message = self.messages[row['message']]
        payload = json.dumps(message.embeds[0].to_dict(), ensure_ascii=False)
        self.assertIn('Jugador 1', payload)
        self.assertNotIn('ASUNTO PRIVADO', payload)
        self.assertNotIn('SOLUCIÓN PRIVADA', payload)
        self.assertIn('Ticket verificado', payload)
        self.assertEqual(self.channel.send.call_args_list[0].kwargs['allowed_mentions'].to_dict()['parse'], [])

    async def test_reserved_case_and_previous_private_opinions_never_publish(self):
        rid = self.case('staff')
        await self.system.submit(self.interaction(), 1, 'No me ayudaron', 'public', ticket=rid)
        row = self.system.store.rows(owner=1)[0]
        self.assertEqual(row['visibility'], 'private')
        self.assertIsNone(row['message'])
        self.assertEqual(len(self.messages), 1)  # Only the channel panel.
        with self.assertRaises(ValueError):
            await self.system.detail(self.interaction(2), row['id'])

    async def test_dm_invite_works_after_ticket_channel_was_deleted(self):
        rid = self.case()
        with self.tickets.db() as db: db.execute('UPDATE lv_tickets SET deleted_at=2000 WHERE id=?',(rid,))
        i = self.interaction(guild=None)
        await self.system.ticket_form(i, rid)
        form = i.response.send_modal.call_args.args[0]
        self.assertEqual(form.ticket, rid)
        self.assertEqual(form.default_visibility, 'private')
        self.assertEqual(self.system.invite(rid).children[0].item.custom_id, f'lvfb:ticket:{rid}')

    async def test_staff_directory_includes_offline_members_and_search(self):
        self.members[2].status = discord.Status.offline
        self.system.directory.load = AsyncMock(return_value=list(self.members.values()))
        i = self.interaction()
        await self.system.staff_picker(i)
        view = i.followup.send.call_args.kwargs['view']
        self.assertEqual({m.id for m in view.rows}, {2,3})
        view.query = 'usuario2'; view.build()
        self.assertEqual([m.id for m in view.filtered()], [2])
        self.system.directory.load.assert_awaited_once_with(self.guild, force=True)

    async def test_fresh_permissions_prevent_non_admin_private_access(self):
        self.members[3].guild_permissions = discord.Permissions.none()
        with self.assertRaises(ValueError): await self.system.stats(self.interaction(3), admin=True)
        self.members[2].roles = []
        with self.assertRaises(ValueError):
            await self.system.submit(self.interaction(), 5, '', 'public', staff=2, topic='Ayuda por voz')
        self.assertFalse(self.system.store.rows(owner=1))

    async def test_ambiguous_publication_is_reconciled_without_duplicate_message(self):
        rid = self.system.store.save(1, 5, 'Me ayudaron', 'public', staff=2, topic='Ayuda por voz')
        original = self.channel.send.side_effect
        async def uncertain(**kwargs):
            await original(**kwargs)
            raise TimeoutError('response lost')
        self.channel.send.side_effect = uncertain
        with self.assertRaises(TimeoutError): await self.system.publish(rid)
        self.assertEqual(self.system.store.get(rid)['publish_state'], 'sending')
        self.channel.send.side_effect = original
        await self.system.publish(rid)
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.system.store.get(rid)['publish_state'], 'posted')

    async def test_form_is_simple_and_reserved_visibility_cannot_be_public(self):
        form = FeedbackForm(self.system, ticket=5, reserved=True)
        self.assertEqual(len(form.to_dict()['components']), 3)
        self.assertEqual(len(form.stars.options), 5)
        self.assertFalse(form.comment.required)
        self.assertEqual([o.value for o in form.visibility.options], ['private'])
        self.assertEqual(len(FeedbackForm(self.system,staff=2).to_dict()['components']),4)

    async def test_staff_cannot_respond_to_someone_elses_feedback(self):
        rid = self.system.store.save(1, 3, '', 'public', staff=2, topic='Ayuda por voz')
        with self.assertRaises(ValueError): await self.system.reply_form(self.interaction(4), rid)
        await self.system.respond(self.interaction(2), rid, 'Gracias, vamos a mejorar.')
        self.assertEqual(self.system.store.get(rid)['response_by'], 2)

    async def test_failed_withdrawal_is_durable_and_can_finish_after_restart(self):
        rid = self.system.store.save(1, 1, 'No me ayudaron', 'public', staff=2, topic='Ayuda por voz')
        await self.system.publish(rid)
        message = self.messages[self.system.store.get(rid)['message']]
        message.delete.side_effect = TimeoutError('connection lost')
        await self.system.withdraw(self.interaction(), rid, 'Retirada por su autor')
        self.assertEqual(self.system.store.get(rid)['publish_state'], 'removing')
        self.assertEqual(self.system.store.summary()['total'], 0)
        self.system.store = FeedbackStore(self.path)
        pending = self.system.store.removals()
        self.assertEqual([r['id'] for r in pending], [rid])
        message.delete.side_effect = None
        await self.system.remove_post(pending[0])
        self.assertEqual(self.system.store.get(rid)['publish_state'], 'withdrawn')

    async def test_public_results_exclude_private_text_and_counts(self):
        self.system.store.save(1, 1, 'SECRETO PRIVADO', 'private', staff=2, topic='Ayuda por voz')
        self.system.store.save(4, 5, 'Muy buena ayuda', 'public', staff=2, topic='Ayuda por voz')
        public = self.interaction(4)
        await self.system.stats(public)
        payload = str(public.followup.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('5.0/5', payload)
        self.assertNotIn('SECRETO PRIVADO', payload)
        admin = self.interaction(3)
        await self.system.stats(admin, admin=True)
        payload = str(admin.followup.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('SECRETO PRIVADO', payload)
        self.assertIn('3.0/5', payload)

    async def test_ticket_buttons_and_old_private_form_use_the_same_feedback_store(self):
        from tickets import TicketSystem
        system = TicketSystem(self.bot, self.path, 10)
        self.bot.feedback = self.system
        self.system.prepared = True
        rid = self.case()
        i = self.interaction()
        await system.action(i, rid, 'rate')
        self.assertIsInstance(i.response.send_modal.call_args.args[0], FeedbackForm)
        await system.submit_rating(i, rid, 4, 'Me ayudaron bien')
        self.assertEqual(self.system.store.rows(owner=1)[0]['visibility'], 'private')
        self.assertEqual(self.tickets.get(rid)['rating'], 4)


class LanguageTests(unittest.TestCase):
    def test_negative_feedback_is_allowed_but_bot_cannot_bypass_obscenity_filter(self):
        self.assertEqual(clean('No me atendieron bien y tardaron mucho.'), 'No me atendieron bien y tardaron mucho.')
        for text in ('son unos cbnes', 'un CABRÓN', 'eres una perra'):
            with self.assertRaises(ValueError): clean(text)
