from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord

from change_log import ChangeLog
from feedback import FeedbackSystem
from ticket_privacy import outcome_text
from tickets import TicketSystem, transcript_html
from tickets_store import NORMAL_STAFF
from tickets_ui import TicketControls
from test_tickets import FakeMember

SECRET = 'STAFF INTERNAL SOLUTION 582'


class StoredMessage:
    def __init__(self, mid, author, content='', *, embed=None, view=None):
        self.id, self.author, self.content = mid, author, content
        self.embeds = [embed] if embed else []
        self.components = [discord.components.ActionRow(row) for row in view.to_components()] if view else []
        self.attachments = []
        self.created_at = datetime.now(timezone.utc)
        self.edited_at = None
        self.edit = AsyncMock(side_effect=self.update)

    async def update(self, **changes):
        if 'content' in changes:
            self.content = changes['content'] or ''
        if 'embed' in changes:
            self.embeds = [changes['embed']] if changes['embed'] else []
        if 'embeds' in changes:
            self.embeds = changes['embeds']
        if 'view' in changes:
            view = changes['view']
            self.components = [discord.components.ActionRow(row) for row in view.to_components()] if view else []
        self.edited_at = datetime.now(timezone.utc)
        return self


class OutcomePrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.guild = SimpleNamespace(id=10)
        self.owner = FakeMember(1, guild=self.guild)
        self.staff = FakeMember(5, roles=NORMAL_STAFF, guild=self.guild)
        self.stranger = FakeMember(7, guild=self.guild)
        self.bot_user = FakeMember(99, admin=True, guild=self.guild)
        self.bot_user.bot = True
        for member, name in [(self.owner, 'Jugador'), (self.staff, 'Soporte'),
            (self.stranger, 'Otro jugador'), (self.bot_user, 'Alertas')]:
            member.display_name = member.name = name
            member.display_avatar = SimpleNamespace(url='https://example.invalid/avatar.png')
        self.owner.send = AsyncMock(return_value=SimpleNamespace(id=9000))
        self.members = {member.id: member for member in (self.owner, self.staff, self.stranger, self.bot_user)}
        self.guild.get_member = lambda uid: self.members.get(uid)
        self.guild.fetch_member = AsyncMock(side_effect=lambda uid: self.members[uid])
        self.bot = SimpleNamespace(user=self.bot_user, get_guild=lambda gid:self.guild)
        self.path = Path(temporary.name) / 'tickets.db'
        self.system = TicketSystem(self.bot, self.path, 10)
        self.system.store.initialize()
        self.bot.tickets = self.system
        self.bot.changes = ChangeLog(self.bot, self.path, 10)
        self.bot.changes.journal.initialize()
        self.feedback = FeedbackSystem(self.bot, self.path, 10)
        self.feedback.store.initialize()
        self.feedback.prepared = True
        self.feedback.refresh_safely = AsyncMock()
        self.bot.feedback = self.feedback
        self.rid = self.system.store.create(1, 'soporte', 'Solicitud del jugador', {'detalles':'Consulta'}, now=1000)
        self.system.store.update(self.rid, status='nuevo', channel=100, control_message=500)
        self.system.store.claim(self.rid, self.staff.id)
        self.messages = {}
        row = self.system.store.get(self.rid)
        self.messages[500] = StoredMessage(500, self.bot_user, embed=self.system.embed(row), view=TicketControls.from_row(row))
        self.messages[600] = StoredMessage(600, self.owner, 'VISIBLE_PLAYER_CONVERSATION')
        async def history(*, limit=100, oldest_first=False, **kwargs):
            messages = sorted(self.messages.values(), key=lambda item:item.id, reverse=not oldest_first)
            for message in messages[:limit] if limit is not None else messages:
                yield message
        async def send(content=None, **kwargs):
            mid = max(self.messages) + 1
            message = StoredMessage(mid, self.bot_user, content or '', embed=kwargs.get('embed'), view=kwargs.get('view'))
            self.messages[mid] = message
            return message
        self.channel = SimpleNamespace(id=100, guild=self.guild, history=history,
            fetch_message=AsyncMock(side_effect=lambda mid:self.messages[mid]), send=AsyncMock(side_effect=send))
        self.system.channel = AsyncMock(return_value=self.channel)
        self.system.apply_permissions = AsyncMock()
        self.system.ensure_category = AsyncMock()
        self.system.move = AsyncMock()
        self.system.prepare_deletion_backup = AsyncMock(return_value=True)

    def interaction(self, member=None, *, dm=False):
        return SimpleNamespace(id=8000, user=member or self.owner, guild_id=None if dm else 10,
            guild=None if dm else self.guild, channel_id=100,
            response=SimpleNamespace(is_done=lambda:True, send_modal=AsyncMock(), defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()))

    @staticmethod
    def ids(message):
        return [component.custom_id for row in message.components for component in row.children]

    async def test_closure_has_only_status_and_rating_in_channel_and_dm(self):
        await self.system.close(self.system.store.get(self.rid), self.staff.id, SECRET)
        notices = [message for message in self.messages.values() if message.content.startswith('🔒 Ticket #')]
        self.assertEqual(len(notices), 1)
        self.assertEqual(self.ids(notices[0]), [f'lv:ticket:case:{self.rid}:rate'])
        self.assertEqual(self.ids(self.messages[500]), [f'lv:ticket:case:{self.rid}:manage'])
        for message in self.messages.values():
            payload = message.content + json.dumps([embed.to_dict() for embed in message.embeds])
            self.assertNotIn(SECRET, payload)
            self.assertNotIn('Transcripción y pruebas', payload)
            self.assertNotIn('Eliminar ticket', payload)
        self.owner.send.assert_awaited_once()
        self.assertNotIn(SECRET, self.owner.send.call_args.args[0])
        button = self.owner.send.call_args.kwargs['view'].children[0].item
        self.assertEqual(button.label, 'Valorar')
        self.assertEqual(button.custom_id, f'lvfb:ticket:{self.rid}')
        self.assertIn(SECRET, self.system.store.get(self.rid)['transcript'])

    async def test_staff_receives_full_details_only_in_private_case_panel(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        self.system.store.update(self.rid, archive_state='completo')
        interaction = self.interaction(self.staff)
        await self.system.show_case(interaction, self.system.store.get(self.rid), staff=True)
        payload = interaction.followup.send.call_args.kwargs
        self.assertTrue(payload['ephemeral'])
        self.assertIn(SECRET, json.dumps(payload['embed'].to_dict()))
        self.assertIn('Transcripción y pruebas', [field.name for field in payload['embed'].fields])
        self.assertIn(f'lv:ticket:case:{self.rid}:delete', [item.custom_id for item in payload['view'].children])
        self.channel.send.assert_not_awaited()
        self.owner.send.assert_not_awaited()

    async def test_ticket_owner_cannot_open_staff_view_or_delete(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        for member in (self.owner, self.stranger):
            with self.subTest(member=member.id), self.assertRaises(ValueError):
                await self.system.show_case(self.interaction(member), self.system.store.get(self.rid), staff=True)
            with self.subTest(delete=member.id), self.assertRaises(ValueError):
                await self.system.action(self.interaction(member), self.rid, 'delete')

    async def test_existing_notice_is_rewritten_in_place_with_durable_before_and_after(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        row = self.system.store.get(self.rid)
        legacy = discord.ui.View(timeout=None)
        for action in ('rate', 'delete'):
            legacy.add_item(discord.ui.Button(label=action, custom_id=f'lv:ticket:case:{self.rid}:{action}'))
        self.messages[700] = StoredMessage(700, self.bot_user,
            f'🔒 Ticket cerrado. Solución: {SECRET}\nTranscripción y pruebas: completo. Eliminar ticket.', view=legacy)
        self.messages[500].embeds = [self.system.embed(row, staff=True)]
        self.messages[500].components = self.messages[700].components
        await self.system.refresh(row)
        self.assertEqual(self.messages[700].content, outcome_text(row))
        self.assertEqual(self.ids(self.messages[700]), [f'lv:ticket:case:{self.rid}:rate'])
        self.assertEqual(self.ids(self.messages[500]), [f'lv:ticket:case:{self.rid}:manage'])
        self.channel.send.assert_not_awaited()
        self.owner.send.assert_not_awaited()
        record = next(record for record in self.bot.changes.journal.rows()
            if json.loads(record['before_json']).get('message') == 700)
        self.assertIn(SECRET, json.loads(record['before_json'])['content'])
        self.assertNotIn(SECRET, json.loads(record['after_json'])['content'])
        self.assertEqual(record['status'], 'completado')

    async def test_old_resolved_notice_and_main_panel_hide_solution_after_reopening(self):
        self.system.store.update(self.rid, resolution=SECRET)
        self.messages[700] = StoredMessage(700, self.bot_user, '✅ Solución: ' + SECRET)
        self.messages[500].embeds = [self.system.embed(self.system.store.get(self.rid), staff=True)]
        await self.system.refresh(self.system.store.get(self.rid))
        self.assertNotIn(SECRET, self.messages[700].content)
        self.assertEqual(self.messages[700].components, [])
        self.assertNotIn(SECRET, json.dumps(self.messages[500].embeds[0].to_dict()))

    async def test_resolution_notifies_once_with_rating_and_no_generic_reply_dm(self):
        await self.system.resolve_case(self.system.store.get(self.rid), self.staff.id, SECRET)
        self.owner.send.assert_awaited_once()
        self.assertIn('resuelto', self.owner.send.call_args.args[0])
        self.assertNotIn(SECRET, self.owner.send.call_args.args[0])
        self.assertFalse(await self.system.notify_player(self.rid, 'reply'))
        self.assertFalse(await self.system.notify_outcome(self.system.store.get(self.rid)))
        self.owner.send.assert_awaited_once()
        self.assertTrue(all(SECRET not in message.content for message in self.messages.values()))

    async def test_status_command_also_keeps_the_solution_in_the_private_staff_reply(self):
        interaction = self.interaction(self.staff)
        await self.system.group.get_command('estado').callback(interaction, 'resuelto', SECRET, self.rid)
        private = interaction.followup.send.call_args.kwargs
        self.assertTrue(private['ephemeral'])
        self.assertIn(SECRET, json.dumps(private['embed'].to_dict()))
        self.assertTrue(all(SECRET not in message.content for message in self.messages.values()))
        self.assertIn('resuelto', self.owner.send.call_args.args[0])

    async def test_blocked_dm_does_not_prevent_closure_or_publish_staff_information(self):
        response = SimpleNamespace(status=403, reason='Forbidden')
        self.owner.send.side_effect = discord.Forbidden(response, 'Cannot send messages to this user')
        await self.system.close(self.system.store.get(self.rid), self.staff.id, SECRET)
        self.assertEqual(self.system.store.get(self.rid)['status'], 'cerrado')
        self.assertEqual(self.system.store.notice(self.rid, 'outcome')['state'], 'blocked')
        notice = next(message for message in self.messages.values() if message.content.startswith('🔒 Ticket #'))
        self.assertEqual(self.ids(notice), [f'lv:ticket:case:{self.rid}:rate'])
        self.assertNotIn(SECRET, notice.content)

    async def test_resolved_reserved_report_rating_cannot_be_published_or_reviewed_by_normal_staff(self):
        rid = self.system.store.create(1, 'staff', 'Reporte reservado', {}, now=1100)
        self.system.store.update(rid, status='nuevo', channel=101, control_message=501)
        self.system.store.transition(rid, 'resuelto', self.bot_user.id, SECRET)
        feedback = self.feedback.store.save(1, 5, 'Atención del reporte', 'public', ticket=rid)
        self.assertEqual(self.feedback.store.get(feedback)['visibility'], 'private')
        with self.assertRaises(ValueError):
            await self.system.show_case(self.interaction(self.staff), self.system.store.get(rid), staff=True)

    async def test_rating_resolved_case_from_dm_is_owner_only_and_cannot_repeat_after_closing(self):
        await self.system.resolve_case(self.system.store.get(self.rid), self.staff.id, SECRET)
        with self.assertRaises(ValueError):
            await self.system.action(self.interaction(self.stranger, dm=True), self.rid, 'rate')
        interaction = self.interaction(dm=True)
        await self.system.action(interaction, self.rid, 'rate')
        form = interaction.response.send_modal.call_args.args[0]
        form.stars._values = ['5']
        form.comment._value = 'Buena atención'
        await form.on_submit(interaction)
        self.assertEqual(self.system.store.get(self.rid)['rating'], 5)
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, 'Cierre posterior')
        with self.assertRaises(ValueError):
            await self.feedback.ticket_form(self.interaction(dm=True), self.rid)
        self.assertEqual(len(self.feedback.store.rows(owner=self.owner.id)), 1)

    async def test_closed_notice_is_rating_only_while_staff_controls_remain_available(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        row = self.system.store.get(self.rid)
        self.assertEqual([item.item.label for item in TicketControls.from_row(row).children], ['Valorar'])
        self.assertIn('Eliminar ticket', [item.item.label for item in TicketControls.from_row(row, staff=True).children])
        row['rating'] = 5
        self.assertEqual(TicketControls.from_row(row).children, [])
        self.assertNotIn('Valorar', [item.item.label for item in TicketControls.from_row(row, staff=True).children])

    async def test_recovery_reuses_the_simplified_terminal_panel_if_its_saved_id_is_missing(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        self.system.store.update(self.rid, control_message=None)
        row = self.system.store.get(self.rid)
        self.messages[500].embeds = [self.system.embed(row)]
        self.messages[500].components = []
        await self.system.refresh(row)
        self.assertEqual(self.system.store.get(self.rid)['control_message'], 500)
        self.channel.send.assert_not_awaited()

    async def test_member_export_hides_internal_solution_without_removing_conversation(self):
        await self.system.close(self.system.store.get(self.rid), self.staff.id, SECRET)
        interaction = self.interaction()
        self.guild.filesize_limit = 8 * 1024 * 1024
        await self.system.export(interaction, self.system.store.get(self.rid))
        payload = interaction.followup.send.call_args.kwargs['file'].fp.read().decode()
        self.assertIn('VISIBLE_PLAYER_CONVERSATION', payload)
        self.assertNotIn(SECRET, payload)
        self.assertNotIn('Respaldo de pruebas', interaction.followup.send.call_args.args[0])

    async def test_saved_legacy_export_without_message_rows_preserves_chat_and_hides_staff_details(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        self.messages[700] = StoredMessage(700, self.bot_user, '🔒 Ticket cerrado. Solución: ' + SECRET)
        await self.system.archive(self.system.store.get(self.rid))
        with self.system.store.db() as db:
            db.execute('DELETE FROM lv_ticket_messages WHERE ticket=?', (self.rid,))
        self.system.store.mark_deleted(self.rid, self.staff.id)
        self.guild.filesize_limit = 8 * 1024 * 1024
        interaction = self.interaction()
        await self.system.export(interaction, self.system.store.get(self.rid))
        member_copy = interaction.followup.send.call_args.kwargs['file'].fp.read().decode()
        self.assertIn('VISIBLE_PLAYER_CONVERSATION', member_copy)
        self.assertNotIn(SECRET, member_copy)
        staff = self.interaction(self.staff)
        await self.system.export(staff, self.system.store.get(self.rid))
        self.assertIn(SECRET, staff.followup.send.call_args.kwargs['file'].fp.read().decode())

    async def test_full_history_migration_preserves_human_and_other_bot_messages(self):
        self.system.store.transition(self.rid, 'cerrado', self.staff.id, SECRET)
        self.messages[700] = StoredMessage(700, self.bot_user, '✅ Solución: ' + SECRET)
        self.messages[701] = StoredMessage(701, self.staff, '✅ Solución: VISIBLE_HUMAN_REPLY')
        self.messages[702] = StoredMessage(702, FakeMember(88), '🔒 Ticket cerrado. Otro bot.')
        for mid in range(800, 930):
            self.messages[mid] = StoredMessage(mid, self.owner, 'Mensaje del jugador')
        await self.system.sync_control_messages(self.system.store.get(self.rid), self.channel, 500, full=True)
        self.assertNotIn(SECRET, self.messages[700].content)
        self.messages[701].edit.assert_not_awaited()
        self.messages[702].edit.assert_not_awaited()

