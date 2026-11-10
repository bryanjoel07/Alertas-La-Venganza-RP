"""Reuse an external backup only when it already contains this exact closed case."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3


def covers_ticket(manifest,row,proofs):
 if not isinstance(manifest,dict) or manifest.get('restore_state')!='verified' or manifest.get('drive_state')!='verified':return False
 try:
  path=Path(manifest['file']).resolve()
  if not path.is_file() or path.stat().st_size!=manifest['size_bytes']:return False
  digest=hashlib.sha256()
  with path.open('rb') as source:
   for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
  if digest.hexdigest()!=manifest['sha256']:return False
  with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
   db.row_factory=sqlite3.Row
   saved=db.execute('SELECT * FROM lv_tickets WHERE id=?',(row['id'],)).fetchone()
   if not saved or saved['status']!='cerrado' or saved['archive_state']!='completo':return False
   fields=('owner','department','channel','subject','form','resolution','transcript','excluded','assignee','priority')
   if any(saved[key]!=row[key] for key in fields):return False
   files={r['attachment']:r for r in db.execute('SELECT * FROM lv_ticket_files WHERE ticket=?',(row['id'],))}
   if set(files)!={p['attachment'] for p in proofs}:return False
   for proof in proofs:
    stored=files[proof['attachment']]
    if stored['state']!='guardado' or stored['sha256']!=proof['sha256']:return False
    blob=db.execute('SELECT data FROM lv_ticket_blobs WHERE ticket=? AND attachment=?',(row['id'],proof['attachment'])).fetchone()
    if not blob or hashlib.sha256(blob[0]).hexdigest()!=proof['sha256']:return False
  return True
 except (OSError,KeyError,IndexError,TypeError,ValueError,sqlite3.Error):return False
