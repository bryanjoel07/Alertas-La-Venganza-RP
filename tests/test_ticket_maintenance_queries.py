from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from tickets import TicketSystem
from tickets_store import TicketStore


class TicketMaintenanceQueryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=TicketStore(Path(self.temp.name)/'tickets.db');self.store.initialize()

    def case(self,status='nuevo',**fields):
        owner=len(self.store.list(limit=1000))+1
        rid=self.store.create(owner,'soporte','Ayuda',{},now=1000)
        self.store.update(rid,status=status,channel=1000+rid,control_message=2000+rid,**fields)
        return rid

    async def test_followups_skip_closed_history_and_media_but_keep_pending_closed_panels(self):
        for _ in range(30):self.case('cerrado',transcript='x'*10000,archive_state='completo')
        active=[self.case(status) for status in ('nuevo','en_atencion','esperando_jugador','resuelto')]
        flagged=self.case('cerrado');self.store.config(f'priority-panel:{flagged}','alta')
        self.store.config(f'priority-panel:{active[0]}','normal')
        deleted=self.case('cerrado');self.store.config(f'priority-panel:{deleted}','alta')
        with self.store.db() as db:db.execute('UPDATE lv_tickets SET deleted_at=1 WHERE id=?',(deleted,))
        rows=self.store.followup_candidates()
        self.assertEqual({r['id'] for r in rows},set(active+[flagged]))
        self.assertTrue(next(r for r in rows if r['id']==flagged)['priority_pending'])
        self.assertFalse(next(r for r in rows if r['id']==active[1])['priority_pending'])
        self.assertTrue(all('transcript' not in row and 'form' in row for row in rows))

    async def test_recovery_only_returns_interrupted_operations_without_losing_any_kind(self):
        self.case('cerrado',archive_state='completo');self.case('en_atencion')
        expected={self.case('creando'),self.case('fallido'),self.case('cerrado',archive_state='pendiente'),
                  self.case('cerrado',archive_state='pendiente_actualizacion')}
        control=self.case();self.store.update(control,control_message=None);expected.add(control)
        deleting=self.case('cerrado',archive_state='completo');self.store.update(deleting,deletion_requested=1);expected.add(deleting)
        deleted=self.case('cerrado',archive_state='pendiente')
        with self.store.db() as db:db.execute('UPDATE lv_tickets SET deleted_at=1 WHERE id=?',(deleted,))
        self.assertEqual({r['id'] for r in self.store.recovery_candidates()},expected)

    async def test_idle_recovery_never_fetches_the_entire_discord_channel_list(self):
        self.case('en_atencion');self.case('cerrado',archive_state='completo')
        bot=SimpleNamespace(get_guild=lambda gid:SimpleNamespace(id=10))
        system=TicketSystem(bot,self.store.path,10)
        with patch('tickets.fetch_channels',AsyncMock(side_effect=AssertionError('inventory not needed'))) as inventory:
            await system.recover()
        inventory.assert_not_awaited()

    async def test_followup_query_uses_the_active_ticket_index(self):
        with self.store.db(readonly=True) as db:
            plan=' '.join(str(tuple(r)) for r in db.execute("EXPLAIN QUERY PLAN SELECT id,status,priority,form FROM lv_tickets WHERE deleted_at IS NULL AND status NOT IN ('creando','fallido','cerrado') ORDER BY id DESC"))
        self.assertIn('lv_ticket_followup',plan)

    async def test_history_queries_use_indexes_without_sorting_the_whole_history(self):
        queries=(('SELECT * FROM lv_ticket_events WHERE ticket=? ORDER BY id','lv_ticket_event_history'),
                 ('SELECT * FROM lv_ticket_notes WHERE ticket=? ORDER BY id','lv_ticket_note_history'),
                 ('SELECT saved FROM lv_ticket_message_versions WHERE ticket=? ORDER BY id','lv_ticket_version_history'))
        with self.store.db(readonly=True) as db:
            for sql,index in queries:
                with self.subTest(index=index):
                    plan=' '.join(str(tuple(r)) for r in db.execute('EXPLAIN QUERY PLAN '+sql,(1,)))
                    self.assertIn(index,plan)
                    self.assertNotIn('USE TEMP B-TREE',plan)
