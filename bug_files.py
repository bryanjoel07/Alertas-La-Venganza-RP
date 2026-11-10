"""Durable groups of report attachments; legacy single-file evidence stays intact."""
import hashlib
import json
from pathlib import Path
import secrets
import time

from bug_limits import FILE_TYPES,MAX_CLIP_BYTES,MAX_REPORT_FILES
from bug_template import DETAILS_LIMIT,parse_details

FILE_COUNT="""(SELECT COUNT(*) FROM lv_bug_files f WHERE f.report=lv_bugs.id
    AND f.revision=json_extract(lv_bugs.data,'$.files_revision') AND f.state='complete') AS file_count"""
FILE_FIELDS='id,report,revision,position,filename,size,kind,state,sha256,token'


class ReportFiles:
    @staticmethod
    def initialize_files(db):
        db.execute('''CREATE TABLE IF NOT EXISTS lv_bug_files(id INTEGER PRIMARY KEY,
            report INTEGER NOT NULL,revision INTEGER NOT NULL,position INTEGER NOT NULL,
            filename TEXT NOT NULL,size INTEGER NOT NULL,kind TEXT NOT NULL,source TEXT NOT NULL,
            state TEXT NOT NULL,content BLOB,sha256 TEXT,token TEXT UNIQUE,created INTEGER NOT NULL,error TEXT,
            UNIQUE(report,revision,position))''')

    @staticmethod
    def file_rows(db,rid,revision):
        if revision is None:return []
        return [dict(r) for r in db.execute(f"SELECT {FILE_FIELDS} FROM lv_bug_files WHERE report=? AND revision=? AND state='complete' ORDER BY position",(rid,revision))]

    @staticmethod
    def discard_inactive_files(db,rid,active):
        if active is None:db.execute('DELETE FROM lv_bug_files WHERE report=?',(rid,))
        else:db.execute('DELETE FROM lv_bug_files WHERE report=? AND revision!=?',(rid,active))

    def prepare_files(self,rid,owner,values,revision,files):
        from bug_uploads import validate_source
        from bug_store import clip_url
        if not 1<=len(files)<=MAX_REPORT_FILES:raise ValueError('Puedes adjuntar hasta 10 archivos por reporte.')
        for field,limit in {'player_id':30,'title':100,'details':DETAILS_LIMIT}.items():
            if not values.get(field,'').strip() or len(values[field])>limit:raise ValueError('Completa el ID, el título y los detalles del problema.')
        sections=parse_details(values['details']);clip=clip_url(values.get('clip',''))
        for item in files:
            validate_source(item['source'])
            if Path(item['filename']).suffix.lower() not in FILE_TYPES:raise ValueError('Adjunta fotos o videos compatibles.')
            if not 0<item['size']<=MAX_CLIP_BYTES:raise ValueError('Cada archivo debe pesar hasta 60 MB.')
        with self.db() as db:
            row=db.execute('SELECT owner,status,revision,data FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['owner']!=owner or row['status']!='borrador' or row['revision']!=revision:
                raise ValueError('El formulario cambió. Abre tu borrador otra vez.')
            self.check_capacity(db,rid,sum(f['size'] for f in files))
            data=json.loads(row['data']);self.discard_inactive_files(db,rid,data.get('files_revision'))
            data.update({k:values[k].strip() for k in ('player_id','title','details')})
            data.update(sections,clip=clip,report_schema=4,discord_username=values.get('discord_username',''),
                upload_pending=True,files_total=len(files),files_done=0)
            db.execute('UPDATE lv_bugs SET data=?,step=1,revision=revision+1,updated=? WHERE id=?',(json.dumps(data,ensure_ascii=False),int(time.time()),rid))
            db.execute('DELETE FROM lv_bug_uploads WHERE report=?',(rid,))
            for position,item in enumerate(files):
                kind='image' if FILE_TYPES[Path(item['filename']).suffix.lower()].startswith('image/') else 'video'
                db.execute('''INSERT INTO lv_bug_files(report,revision,position,filename,size,kind,source,state,created)
                    VALUES (?,?,?,?,?,?,?,'pending',?)''',(rid,revision+1,position,item['filename'],item['size'],kind,json.dumps(item['source']),int(time.time())))
            return revision+1

    def file_jobs(self,rid,revision):
        with self.db() as db:
            row=db.execute('SELECT status,revision,data FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['status']!='borrador' or row['revision']!=revision or not json.loads(row['data']).get('upload_pending'):return []
            return [dict(r) for r in db.execute(f"SELECT {FILE_FIELDS},source FROM lv_bug_files WHERE report=? AND revision=? ORDER BY position",(rid,revision))]

    def pending_file_groups(self):
        with self.db() as db:return [dict(r) for r in db.execute('''SELECT DISTINCT f.report,f.revision FROM lv_bug_files f
            JOIN lv_bugs b ON b.id=f.report AND b.revision=f.revision
            WHERE b.status='borrador' AND json_extract(b.data,'$.upload_pending')=1 AND f.state='pending'
            AND NOT EXISTS(SELECT 1 FROM lv_bug_files other WHERE other.report=f.report AND other.revision=f.revision AND other.state='failed')''')]

    def complete_file(self,rid,revision,fid,content):
        with self.db() as db:
            row=db.execute('SELECT status,revision,data FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            job=db.execute('SELECT size,state FROM lv_bug_files WHERE id=? AND report=? AND revision=?',(fid,rid,revision)).fetchone()
            if not row or row['status']!='borrador' or row['revision']!=revision or not job or job['state']!='pending':return False
            if not content or len(content)!=job['size'] or len(content)>MAX_CLIP_BYTES:raise ValueError('Un archivo no se descargó completo. Vuelve a adjuntarlo.')
            total=db.execute('SELECT SUM(size) FROM lv_bug_files WHERE report=? AND revision=?',(rid,revision)).fetchone()[0]
            self.check_capacity(db,rid,total)
            db.execute("UPDATE lv_bug_files SET content=?,sha256=?,state='complete',error=NULL WHERE id=?",(content,hashlib.sha256(content).hexdigest(),fid))
            remaining=db.execute("SELECT COUNT(*) FROM lv_bug_files WHERE report=? AND revision=? AND state!='complete'",(rid,revision)).fetchone()[0]
            data=json.loads(row['data']);data['files_done']=data['files_total']-remaining
            if not remaining:
                data.update(upload_pending=False,files_revision=revision)
                self.discard_inactive_files(db,rid,revision)
                db.execute('UPDATE lv_bugs SET video=NULL,filename=NULL,sha256=NULL,step=2 WHERE id=?',(rid,))
                db.execute('DELETE FROM lv_bug_media WHERE report=?',(rid,))
            db.execute('UPDATE lv_bugs SET data=?,updated=? WHERE id=?',(json.dumps(data,ensure_ascii=False),int(time.time()),rid))
            return True

    def fail_files(self,rid,revision,error):
        with self.db() as db:db.execute("UPDATE lv_bug_files SET state='failed',error=? WHERE report=? AND revision=? AND state='pending'",(error[:120],rid,revision))

    def file_tokens(self,rid):
        with self.db() as db:
            row=db.execute('SELECT status,data FROM lv_bugs WHERE id=?',(rid,)).fetchone()
            if not row or row['status'] not in ('publicando','pendiente','revision','proceso','solucionado','cerrado'):
                raise ValueError('Los archivos solo se comparten después de confirmar la publicación.')
            files=self.file_rows(db,rid,json.loads(row['data']).get('files_revision'))
            if not files:raise ValueError('Todavía no se guardaron los archivos del reporte.')
            for item in files:
                if not item['token']:db.execute('UPDATE lv_bug_files SET token=? WHERE id=?',(secrets.token_urlsafe(32),item['id']))
