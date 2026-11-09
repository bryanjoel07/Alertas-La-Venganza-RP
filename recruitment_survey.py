"""Read-only inventory and durable source backup for staff recruitment migration."""
import asyncio
from contextlib import closing
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import time
import unicodedata

import discord

log=logging.getLogger('LaVenganzaRP.recruitment')
REQUEST='staff-transfer-20261109-v1'


def key(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text or '').casefold() if c.isalnum())


class RecruitmentSource:
    def __init__(self,path):self.path=Path(path)
    def initialize(self):
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_surveys(request TEXT PRIMARY KEY,
                created INTEGER NOT NULL,completed INTEGER,report TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_sources(channel TEXT NOT NULL,message TEXT NOT NULL,
                payload TEXT NOT NULL,PRIMARY KEY(channel,message))''')
            db.execute('''CREATE TABLE IF NOT EXISTS lv_recruit_source_files(attachment TEXT PRIMARY KEY,message TEXT NOT NULL,
                filename TEXT NOT NULL,data BLOB NOT NULL,sha256 TEXT NOT NULL)''')
    def report(self):
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            row=db.execute('SELECT report FROM lv_recruit_surveys WHERE request=? AND completed IS NOT NULL',(REQUEST,)).fetchone()
            return json.loads(row[0]) if row else None
    def message(self,payload):
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute('INSERT OR IGNORE INTO lv_recruit_sources VALUES (?,?,?)',
                (str(payload['channel']),str(payload['id']),json.dumps(payload,ensure_ascii=False)))
    def file(self,message,attachment,data):
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute('INSERT OR IGNORE INTO lv_recruit_source_files VALUES (?,?,?,?,?)',
                (str(attachment.id),str(message.id),attachment.filename,data,hashlib.sha256(data).hexdigest()))
    def complete(self,report):
        with closing(sqlite3.connect(self.path,timeout=10)) as db,db:
            db.execute('INSERT OR REPLACE INTO lv_recruit_surveys VALUES (?,?,?,?)',
                (REQUEST,int(time.time()),int(time.time()),json.dumps(report,ensure_ascii=False)))


async def survey_recruitment(bot,path,guild_id):
    source=RecruitmentSource(path);await asyncio.to_thread(source.initialize)
    previous=await asyncio.to_thread(source.report)
    if previous:
        log.info('RECRUIT_SURVEY cached channels=%s messages=%s files=%s',len(previous['channels']),sum(previous['counts'].values()),previous['files']);return previous
    guild=bot.get_guild(guild_id)
    if guild is None:raise ValueError('No encuentro La Venganza RP para revisar el reclutamiento.')
    channels=await guild.fetch_channels()
    categories=[c for c in channels if isinstance(c,discord.CategoryChannel) and key(c.name)=='reclutamientostaff']
    if len(categories)!=1:raise ValueError('No hay una categoría única de Reclutamiento Staff.')
    category=categories[0]
    selected=[c for c in channels if getattr(c,'category_id',None)==category.id]
    names={'informacionstaff','aplicarstaff','solicitudesstaff','entrevistasstaff','salaentrevista'}
    report=dict(category=str(category.id),channels=[],panels=[],public_text=[],question_labels=[],counts={},files=0,files_pending=0)
    labels=set();total=0
    for channel in selected:
        if key(channel.name) not in names:continue
        report['channels'].append(dict(id=str(channel.id),name=channel.name,type=str(channel.type),
            overwrites=[dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny)) for o in channel._overwrites]))
        if not isinstance(channel,discord.TextChannel):continue
        count=0;public=key(channel.name) in {'informacionstaff','aplicarstaff'}
        async for message in channel.history(limit=None,oldest_first=True):
            payload=dict(id=str(message.id),channel=str(channel.id),author=str(message.author.id),bot=message.author.bot,
                author_name=str(message.author),content=message.content,created=message.created_at.isoformat(),
                embeds=[e.to_dict() for e in message.embeds],components=[c.to_dict() for c in message.components],
                mentions=[str(m.id) for m in message.mentions],pinned=message.pinned,
                attachments=[dict(id=str(a.id),filename=a.filename,url=a.url,size=a.size) for a in message.attachments])
            await asyncio.to_thread(source.message,payload);count+=1
            if public and message.components:
                report['panels'].append(dict(channel=str(channel.id),message=str(message.id),author=str(message.author),
                    author_id=str(message.author.id),components=[c.to_dict() for c in message.components]))
            if public and count<=12:
                text='\n'.join([message.content,*[e.title or '' for e in message.embeds],*[e.description or '' for e in message.embeds]])
                if text.strip():report['public_text'].append(dict(channel=str(channel.id),message=str(message.id),text=text[:3500]))
            if not public:
                for embed in message.embeds:
                    for field in embed.fields:labels.add(field.name)
            for attachment in message.attachments:
                if attachment.size>25*1024*1024 or total+attachment.size>100*1024*1024:
                    report['files_pending']+=1;continue
                try:data=await attachment.read()
                except discord.HTTPException:
                    report['files_pending']+=1;continue
                await asyncio.to_thread(source.file,message,attachment,data)
                total+=len(data);report['files']+=1
        report['counts'][str(channel.id)]=count
    report['question_labels']=sorted(labels)
    await asyncio.to_thread(source.complete,report)
    log.info('RECRUIT_SURVEY complete %s',json.dumps(report,ensure_ascii=False))
    return report
