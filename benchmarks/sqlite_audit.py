"""Compare maintenance reads on disposable data, never the production database.

Run: .venv/bin/python benchmarks/sqlite_audit.py --records 5000 --runs 5
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlite_runtime import configure_database,transaction
from tickets_store import TicketStore


def measure(read,runs):
    read()  # Both queries start with a warm local filesystem cache.
    samples=[];peaks=[]
    for _ in range(runs):
        tracemalloc.start();started=time.perf_counter()
        rows=read()
        samples.append((time.perf_counter()-started)*1000)
        peaks.append(tracemalloc.get_traced_memory()[1]);tracemalloc.stop()
    return dict(rows=len(rows),median_ms=round(statistics.median(samples),3),peak_python_bytes=max(peaks))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',type=int,default=5000)
    parser.add_argument('--runs',type=int,default=5)
    args=parser.parse_args()
    if not 1<=args.records<=9000 or not 1<=args.runs<=20:parser.error('Use 1–9000 closed records and 1–20 runs.')
    with tempfile.TemporaryDirectory(prefix='lv-benchmark-') as directory:
        path=Path(directory)/'disposable.db';store=TicketStore(path);store.initialize()
        with store.db() as db:
            db.executemany('''INSERT INTO lv_tickets(owner,department,status,subject,form,created,updated,last_user,transcript,channel,control_message)
                VALUES (?,'soporte',?,'Ayuda','{}',1000,1000,1000,?,?,?)''',
                ((n,'cerrado' if n<=args.records else 'nuevo','x'*8192 if n<=args.records else None,n,100000+n)
                 for n in range(1,args.records+6)))
        before=measure(lambda:store.list(limit=10000),args.runs)
        after=measure(store.followup_candidates,args.runs)
        with store.db() as writer:
            writer.execute("UPDATE lv_ticket_config SET value='3' WHERE key='max_open'")
            try:
                with closing(sqlite3.connect(path,timeout=.05)) as legacy:legacy.execute('BEGIN IMMEDIATE')
            except sqlite3.OperationalError:legacy_blocked=True
            else:legacy_blocked=False
            started=time.perf_counter();value=store.config('max_open')
            reader_ms=round((time.perf_counter()-started)*1000,3)
        mode=configure_database(path)['journal_mode']
        with transaction(path,readonly=True,timeout=.05) as reader:
            reader.execute('SELECT COUNT(*) FROM lv_tickets').fetchone()
            with transaction(path,timeout=.05) as writer:writer.execute("UPDATE lv_ticket_config SET value='3' WHERE key='max_open'")
        print(json.dumps(dict(fixture=dict(closed=args.records,active=5,transcript_bytes=8192,runs=args.runs),
            before=before,after=after,writer_contention=dict(legacy_blocked=legacy_blocked,
            current_reader_ms=reader_ms,committed_value=value),journal_mode=mode,concurrent_writer_committed=True),indent=2))


if __name__=='__main__':main()
