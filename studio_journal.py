"""Private durable journal adapted from the original bot; independent guild only."""
import asyncio
from contextlib import closing
import json
import sqlite3
import time

class Journal:
    def __init__(self,path):
        self.path=path

    def db(self):
        return sqlite3.connect(self.path,timeout=10)

    def initialize(self):
        with closing(self.db()) as db,db:
            db.execute('''CREATE TABLE IF NOT EXISTS bot_changes(
                id INTEGER PRIMARY KEY, change_key TEXT UNIQUE NOT NULL, created INTEGER NOT NULL,
                finished INTEGER, title TEXT NOT NULL, status TEXT NOT NULL, summary TEXT NOT NULL,
                restore TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL DEFAULT '{}',
                message_id TEXT)''')

    def begin(self,key,title,summary,restore,before):
        with closing(self.db()) as db,db:
            db.execute("INSERT OR IGNORE INTO bot_changes(change_key,created,title,status,summary,restore,before_json) VALUES (?,?,?,'iniciado',?,?,?)",
                       (key,int(time.time()),title,summary,restore,json.dumps(before,ensure_ascii=False)))
            return db.execute('SELECT id FROM bot_changes WHERE change_key=?',(key,)).fetchone()[0]

    def finish(self,rid,status,after):
        with closing(self.db()) as db,db:
            db.execute('UPDATE bot_changes SET status=?,finished=?,after_json=? WHERE id=?',
                       (status,int(time.time()),json.dumps(after,ensure_ascii=False),rid))

    def rows(self,limit=10,offset=0,pending=False):
        with closing(self.db()) as db:
            db.row_factory=sqlite3.Row
            where="WHERE message_id IS NULL AND status!='iniciado'" if pending else ''
            return [dict(r) for r in db.execute(f'SELECT * FROM bot_changes {where} ORDER BY id DESC LIMIT ? OFFSET ?',(limit,offset))]

    def get(self,rid):
        with closing(self.db()) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM bot_changes WHERE id=?',(rid,)).fetchone()
            return dict(row) if row else None

    def by_key(self,key):
        with closing(self.db()) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM bot_changes WHERE change_key=?',(key,)).fetchone()
            return dict(row) if row else None

    def mark_sent(self,rid,message):
        with closing(self.db()) as db,db:
            db.execute('UPDATE bot_changes SET message_id=? WHERE id=?',(str(message),rid))

    def latest_state(self):
        with closing(self.db()) as db:
            row=db.execute("SELECT after_json FROM bot_changes WHERE change_key LIKE 'release:%' AND status='completado' ORDER BY id DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else {}


async def server_snapshot(guild):
    channels=await guild.fetch_channels()
    roles=await guild.fetch_roles()
    return dict(roles=[dict(id=str(r.id),name=r.name,position=r.position,permissions=str(r.permissions.value),
                           color=r.color.value,hoist=r.hoist) for r in roles],
                channels=[dict(id=str(c.id),name=c.name,parent=str(c.category_id) if c.category_id else None,
                    position=c.position,type=str(c.type),topic=getattr(c,'topic',None),
                    overwrites=[dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny))
                                for o in c._overwrites]) for c in channels])


class ChangeLog:
    def __init__(self, bot, path, guild_id):
        self.bot, self.guild_id = bot, guild_id
        self.journal = Journal(path)

    async def tracked(self, env, title, operation, request_id=None, snapshot=None):
        if not request_id:
            raise ValueError('Toda operación de EssChino Studio necesita un identificador duradero.')
        guild = self.bot.get_guild(self.guild_id)
        if guild is None or guild.id != self.guild_id:
            raise ValueError('El registro solo admite el servidor de EssChino Studio.')
        async def state():
            return await snapshot() if snapshot else await server_snapshot(guild)
        before = await state()
        rid = await asyncio.to_thread(self.journal.begin, f'operation:{env}:{request_id}', title,
            title, 'Conservar /data y la base actual. Comparar las copias antes y después; los canales borrados no recuperan sus IDs originales.', before)
        try:
            result = await operation()
            after = await state()
        except Exception as error:
            await asyncio.to_thread(self.journal.finish, rid, 'fallido', dict(error_type=type(error).__name__, state=await state()))
            raise
        await asyncio.to_thread(self.journal.finish, rid, 'completado', after)
        return result
