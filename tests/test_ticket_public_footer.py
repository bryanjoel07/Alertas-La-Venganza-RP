import json
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock

import discord
from discord.webhook.async_ import async_context

from ticket_privacy import outcome_text
from tickets_ui import DeleteTicketForm,TicketAction
from test_tickets import FakeMember
import test_ticket_outcome_privacy as fixtures


class PublicFooterTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.OutcomePrivacyTests.asyncSetUp
    interaction=fixtures.OutcomePrivacyTests.interaction
    ids=staticmethod(fixtures.OutcomePrivacyTests.ids)

    def closed(self):
        self.system.store.transition(self.rid,'cerrado',self.staff.id,fixtures.SECRET)
        return self.system.store.get(self.rid)

    def assert_footer(self,message):
        self.assertEqual(self.ids(message),[f'lv:ticket:case:{self.rid}:{action}' for action in ('download','rate','erase')])
        self.assertEqual([c.label for group in message.components for c in group.children],['Transcripción','Valorar','Eliminar ticket'])
        self.assertNotIn(fixtures.SECRET,message.content)

    async def form(self):
        i=self.interaction(self.staff)
        await self.system.action(i,self.rid,'erase')
        self.system.delete_ticket=AsyncMock(return_value=True)
        i.followup.send.assert_not_awaited()
        form=i.response.send_modal.call_args.args[0]
        self.assertIsInstance(form,DeleteTicketForm)
        return form

    async def test_closure_posts_one_footer_with_three_buttons_and_no_staff_menu(self):
        await self.system.close(self.system.store.get(self.rid),self.staff.id,fixtures.SECRET)
        notices=[m for m in self.messages.values() if m.content.startswith('🔒 Ticket #')]
        self.assertEqual(len(notices),1);self.assert_footer(notices[0])
        self.assertEqual(notices[0].id,max(self.messages))
        self.assertEqual(self.messages[500].components,[])
        self.assertEqual(self.messages[600].content,'VISIBLE_PLAYER_CONVERSATION')

    async def test_old_rating_notice_and_staff_header_are_repaired_in_place(self):
        row=self.closed();old=discord.ui.View(timeout=None);old.add_item(TicketAction(self.rid,'rate'))
        header=discord.ui.View(timeout=None);header.add_item(TicketAction(self.rid,'manage'))
        await self.messages[500].update(embed=self.system.embed(row),view=header)
        self.messages[700]=fixtures.StoredMessage(700,self.bot_user,outcome_text(row),view=old)
        await self.system.refresh(row)
        self.assert_footer(self.messages[700]);self.assertEqual(self.messages[500].components,[])
        self.channel.send.assert_not_awaited();self.owner.send.assert_not_awaited()
        receipts=[json.loads(r['before_json']) for r in self.bot.changes.journal.rows()]
        self.assertTrue(any(r.get('message')==500 and r.get('components') for r in receipts))
        self.assertTrue(any(r.get('message')==700 for r in receipts))

    async def test_only_author_downloads_the_player_copy_as_a_private_file(self):
        self.closed();i=self.interaction()
        await self.system.action(i,self.rid,'download')
        sent=i.followup.send.call_args.kwargs
        self.assertTrue(sent['ephemeral']);self.assertNotIn('view',sent)
        html=sent['file'].fp.read().decode();sent['file'].close()
        self.assertIn('VISIBLE_PLAYER_CONVERSATION',html);self.assertNotIn(fixtures.SECRET,html)
        self.assertIn(fixtures.SECRET,self.system.store.get(self.rid)['transcript'])
        self.channel.send.assert_not_awaited()

    async def test_staff_and_added_participant_cannot_use_the_authors_download_button(self):
        self.closed();self.system.store.participant(self.rid,self.stranger.id,self.staff.id,True)
        for member in (self.staff,self.stranger):
            i=self.interaction(member)
            with self.subTest(user=member.id),self.assertRaises(ValueError):await self.system.action(i,self.rid,'download')
            i.followup.send.assert_not_awaited()

    async def test_an_author_with_staff_roles_still_gets_the_player_transcript_from_this_button(self):
        self.closed();self.owner.guild_permissions=discord.Permissions(administrator=True)
        i=self.interaction();await self.system.action(i,self.rid,'download')
        file=i.followup.send.call_args.kwargs['file']
        html=file.fp.read().decode();file.close()
        self.assertNotIn(fixtures.SECRET,html);self.assertIn('VISIBLE_PLAYER_CONVERSATION',html)

    async def test_public_delete_button_rejects_players_and_does_not_open_a_management_panel(self):
        self.closed()
        for member in (self.owner,self.stranger):
            i=self.interaction(member)
            with self.subTest(user=member.id),self.assertRaises(ValueError):await self.system.action(i,self.rid,'erase')
            i.response.send_modal.assert_not_awaited();i.followup.send.assert_not_awaited()
        form=await self.form()
        self.system.delete_ticket.assert_not_awaited()
        self.assertEqual(len(form.to_dict()['components']),1)

    async def test_confirmation_requires_the_word_and_the_requesting_staff_member(self):
        self.closed();form=await self.form();form.confirmation._value='si'
        await form.on_submit(self.interaction(self.staff));self.system.delete_ticket.assert_not_awaited()
        form.confirmation._value='ELIMINAR'
        await form.on_submit(self.interaction(self.stranger));self.system.delete_ticket.assert_not_awaited()

    async def test_confirmation_acknowledges_the_origin_message_without_creating_a_private_panel(self):
        self.closed();form=await self.form();form.confirmation._value='ELIMINAR'
        i=self.interaction(self.staff);i.type=discord.InteractionType.modal_submit;i.token='test';i._session=None
        i._state=NS(http=NS(proxy=None,proxy_auth=None));i.response=discord.InteractionResponse(i)
        adapter=NS(create_interaction_response=AsyncMock(return_value={'interaction':{'id':str(i.id)}}))
        token=async_context.set(adapter)
        try:await form.on_submit(i)
        finally:async_context.reset(token)
        self.assertEqual(adapter.create_interaction_response.call_args.kwargs['params'].payload['type'],6)
        self.system.delete_ticket.assert_awaited_once_with(self.staff,self.rid)
        i.followup.send.assert_not_awaited();self.channel.send.assert_not_awaited()

    async def test_freshly_revoked_staff_access_blocks_deletion_after_opening_the_form(self):
        self.closed();form=await self.form();form.confirmation._value='ELIMINAR'
        self.guild.fetch_member.side_effect=None
        self.guild.fetch_member.return_value=FakeMember(self.staff.id,guild=self.guild)
        await form.on_submit(self.interaction(self.staff));self.system.delete_ticket.assert_not_awaited()

    async def test_rated_footer_keeps_download_and_delete_and_does_not_rewrite_itself_forever(self):
        row=self.closed();self.system.store.rate(self.rid,self.owner.id,5,'Gracias')
        await self.system.publish_outcome(self.system.store.get(self.rid))
        notice=next(m for m in self.messages.values() if m.content.startswith('🔒 Ticket #'))
        self.assert_footer(notice)
        buttons=[c for group in notice.components for c in group.children]
        self.assertFalse(buttons[0].disabled);self.assertTrue(buttons[1].disabled);self.assertFalse(buttons[2].disabled)
        await self.system.refresh(row);notice.edit.reset_mock()
        await self.system.refresh(row);notice.edit.assert_not_awaited()

    async def test_reclosing_places_the_only_active_footer_after_the_new_conversation(self):
        await self.system.close(self.system.store.get(self.rid),self.staff.id,fixtures.SECRET)
        old=next(m for m in self.messages.values() if m.content.startswith('🔒 Ticket #'))
        self.system.store.transition(self.rid,'en_atencion',self.staff.id,'Reabrir')
        await self.system.refresh(self.system.store.get(self.rid))
        for mid in range(800,930):self.messages[mid]=fixtures.StoredMessage(mid,self.owner,'Nueva conversación')
        await self.system.close(self.system.store.get(self.rid),self.staff.id,'Nuevo cierre')
        latest=self.messages[max(self.messages)]
        self.assert_footer(latest);self.assertEqual(old.components,[])
        active=[m for m in self.messages.values() if self.ids(m)]
        self.assertEqual([m.id for m in active],[latest.id])

    async def test_repeating_an_already_closed_operation_does_not_add_another_footer(self):
        await self.system.close(self.system.store.get(self.rid),self.staff.id,fixtures.SECRET)
        sent=self.channel.send.await_count
        with self.assertRaisesRegex(ValueError,'ya está cerrado'):
            await self.system.close(self.system.store.get(self.rid),self.staff.id,fixtures.SECRET)
        self.assertEqual(self.channel.send.await_count,sent)

    async def test_closing_from_the_button_does_not_open_a_private_staff_panel(self):
        i=self.interaction(self.staff);await self.system.action(i,self.rid,'close')
        form=i.response.send_modal.call_args.args[0];form.value._value='Listo'
        await form.on_submit(i)
        result=i.followup.send.call_args.kwargs
        self.assertNotIn('view',result);self.assertNotIn('embed',result)
        self.assertEqual(self.system.store.get(self.rid)['status'],'cerrado')
        self.assert_footer(self.messages[max(self.messages)])
