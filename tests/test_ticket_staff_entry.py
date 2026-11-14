import json
import unittest
from unittest.mock import AsyncMock,patch

from tickets_ui import DeleteConfirm
from test_tickets import FakeMember
import test_ticket_outcome_privacy as fixtures


class StaffEntryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.OutcomePrivacyTests.asyncSetUp
    interaction=fixtures.OutcomePrivacyTests.interaction
    ids=staticmethod(fixtures.OutcomePrivacyTests.ids)

    def closed(self):
        self.system.store.transition(self.rid,'cerrado',self.staff.id,fixtures.SECRET)
        self.system.store.update(self.rid,transcript='EXISTING_TRANSCRIPT',archive_state='completo')
        return self.system.store.get(self.rid)

    async def test_existing_closed_header_gains_persistent_staff_access_without_new_messages(self):
        row=self.closed()
        self.messages[500].embeds=[self.system.embed(row)];self.messages[500].components=[]
        await self.system.publish_outcome(row)
        notice=next(m for m in self.messages.values() if m.content.startswith('🔒 Ticket #'))
        self.channel.send.reset_mock()
        await self.system.refresh(row)
        self.assertEqual(self.ids(self.messages[500]),[f'lv:ticket:case:{self.rid}:manage'])
        self.assertEqual(self.ids(notice),[f'lv:ticket:case:{self.rid}:rate'])
        self.assertNotIn(fixtures.SECRET,str([e.to_dict() for e in self.messages[500].embeds]))
        self.assertEqual(self.messages[600].content,'VISIBLE_PLAYER_CONVERSATION')
        self.assertEqual(self.system.store.get(self.rid)['transcript'],'EXISTING_TRANSCRIPT')
        self.channel.send.assert_not_awaited();self.owner.send.assert_not_awaited()
        record=next(r for r in self.bot.changes.journal.rows() if json.loads(r['before_json']).get('message')==500)
        self.assertEqual(json.loads(record['before_json'])['components'],[])
        self.assertTrue(json.loads(record['after_json'])['components'])

    async def test_staff_entry_opens_private_delete_confirmation_without_deleting(self):
        self.closed();self.system.delete_ticket=AsyncMock()
        click=self.interaction(self.staff)
        click.response.is_done=lambda:False
        async def defer(**kwargs):click.response.is_done=lambda:True
        click.response.defer=AsyncMock(side_effect=defer)
        await self.system.action(click,self.rid,'manage')
        self.assertTrue(click.response.defer.call_args.kwargs['ephemeral'])
        self.guild.fetch_member.assert_awaited_with(self.staff.id)
        panel=click.followup.send.call_args.kwargs
        self.assertTrue(panel['ephemeral']);self.assertIn(fixtures.SECRET,str(panel['embed'].to_dict()))
        self.assertIn(f'lv:ticket:case:{self.rid}:delete',[item.custom_id for item in panel['view'].children])
        click.response.is_done=lambda:True
        await self.system.action(click,self.rid,'delete')
        confirm=click.followup.send.call_args.kwargs['view']
        self.assertIsInstance(confirm,DeleteConfirm)
        self.system.delete_ticket.assert_not_awaited();self.channel.send.assert_not_awaited()

    async def test_player_and_unrelated_member_cannot_use_staff_entry(self):
        self.closed()
        for member in (self.owner,self.stranger):
            i=self.interaction(member)
            with self.subTest(user=member.id),self.assertRaises(ValueError):await self.system.action(i,self.rid,'manage')
            i.followup.send.assert_not_awaited()

    async def test_lost_staff_role_is_checked_again_before_showing_private_data(self):
        self.closed();self.guild.fetch_member.return_value=FakeMember(self.staff.id,guild=self.guild)
        self.guild.fetch_member.side_effect=None
        i=self.interaction(self.staff)
        with self.assertRaises(ValueError):await self.system.action(i,self.rid,'manage')
        i.followup.send.assert_not_awaited()

    async def test_staff_report_remains_reserved_to_discord_administrators(self):
        self.closed();self.system.store.update(self.rid,department='staff')
        i=self.interaction(self.staff)
        with self.assertRaises(ValueError):await self.system.action(i,self.rid,'manage')
        i.followup.send.assert_not_awaited()
        admin=FakeMember(8,admin=True,guild=self.guild);self.members[8]=admin
        privileged=self.interaction(admin);await self.system.action(privileged,self.rid,'manage')
        self.assertTrue(privileged.followup.send.call_args.kwargs['ephemeral'])

    async def test_wrong_guild_or_deleted_ticket_never_opens_the_manager(self):
        self.closed();i=self.interaction(self.staff);i.guild_id=999
        with self.assertRaises(ValueError):await self.system.action(i,self.rid,'manage')
        self.guild.fetch_member.assert_not_awaited();i.followup.send.assert_not_awaited()
        self.system.store.mark_deleted(self.rid,self.staff.id)
        i=self.interaction(self.staff)
        with self.assertRaises(ValueError):await self.system.action(i,self.rid,'manage')
        i.followup.send.assert_not_awaited()

    async def test_old_staff_entry_reads_reopened_state_and_does_not_offer_deletion(self):
        self.closed();self.system.store.transition(self.rid,'en_atencion',self.staff.id,'Reabrir')
        i=self.interaction(self.staff);await self.system.action(i,self.rid,'manage')
        controls=i.followup.send.call_args.kwargs['view']
        self.assertNotIn(f'lv:ticket:case:{self.rid}:delete',[item.custom_id for item in controls.children])

    async def test_staff_access_remains_after_the_player_has_already_rated(self):
        self.closed();self.system.store.rate(self.rid,self.owner.id,5,'Gracias')
        await self.system.refresh(self.system.store.get(self.rid))
        self.assertEqual(self.ids(self.messages[500]),[f'lv:ticket:case:{self.rid}:manage'])
        i=self.interaction(self.staff);await self.system.action(i,self.rid,'manage')
        self.assertIn(f'lv:ticket:case:{self.rid}:delete',[item.custom_id for item in i.followup.send.call_args.kwargs['view'].children])

    async def test_permission_inspection_failure_does_not_prevent_repairing_ticket_panels(self):
        for name in ('install','recover','selftest','delete_selftest','verify_reported_invitations'):
            setattr(self.system,name,AsyncMock())
        with patch.dict('os.environ',{'TICKETS_ENABLED':'1','TICKETS_SELFTEST_REQUEST_ID':'','TICKETS_INSTALL_REQUEST_ID':'','TICKETS_DELETE_SELFTEST_REQUEST_ID':''}), \
            patch('tickets.ensure_bot_delete_permission',new=AsyncMock(side_effect=RuntimeError('temporary'))), \
            self.assertLogs('LaVenganzaRP.tickets',level='ERROR'):
            await self.system.ready()
        self.system.install.assert_awaited_once();self.assertTrue(self.system.prepared)
