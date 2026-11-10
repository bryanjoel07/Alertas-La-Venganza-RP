from pathlib import Path
import sqlite3
import tempfile
import unittest
from backup import snapshot
from tickets_store import TicketStore
from ticket_delete_backup import covers_ticket

class BackupCoverageTests(unittest.TestCase):
 def setUp(self):
  temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.path=Path(temp.name)/'db.sqlite'
  self.store=TicketStore(self.path);self.store.initialize()
  self.rid=self.store.create(1,'soporte','Ayuda',{},now=1000);self.store.update(self.rid,status='nuevo',channel=100)
  self.store.transition(self.rid,'cerrado',5,'Solucionado');self.store.update(self.rid,transcript='Conversación completa',archive_state='completo')
  self.store.file(self.rid,1,2,'prueba.txt','https://cdn.discordapp.com/prueba',5);self.store.save_blob(self.rid,2,b'proof')
 def backup(self,name='copy.sqlite'):
  manifest=snapshot(self.path,self.path.parent/name);manifest.update(drive_state='verified',restore_state='verified');return manifest
 def covered(self,manifest):return covers_ticket(manifest,self.store.get(self.rid),self.store.files(self.rid))
 def test_unchanged_case_and_original_evidence_are_covered(self):self.assertTrue(self.covered(self.backup()))
 def test_changed_transcript_or_new_evidence_need_a_new_copy(self):
  manifest=self.backup();self.store.update(self.rid,transcript='Conversación con mensaje nuevo')
  self.assertFalse(self.covered(manifest))
  self.store.update(self.rid,transcript='Conversación completa')
  self.store.file(self.rid,3,4,'nuevo.txt','https://cdn.discordapp.com/nuevo',5);self.store.save_blob(self.rid,4,b'other')
  self.assertFalse(self.covered(manifest))
 def test_missing_or_modified_snapshot_is_not_reused(self):
  manifest=self.backup();Path(manifest['file']).write_bytes(b'damaged')
  self.assertFalse(self.covered(manifest));Path(manifest['file']).unlink();self.assertFalse(self.covered(manifest))
 def test_external_verification_is_required(self):
  manifest=self.backup();manifest['restore_state']='failed';self.assertFalse(self.covered(manifest))
  manifest['restore_state']='verified';manifest['drive_state']='pending';self.assertFalse(self.covered(manifest))
 def test_snapshot_with_corrupt_proof_is_rejected_even_if_sqlite_is_valid(self):
  with self.store.db() as db:db.execute('UPDATE lv_ticket_blobs SET data=? WHERE ticket=?',(b'wrong',self.rid))
  self.assertFalse(self.covered(self.backup()))
