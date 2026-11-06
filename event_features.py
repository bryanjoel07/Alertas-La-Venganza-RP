"""Historial, clasificación histórica y recordatorios persistentes de eventos."""
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import logging
import sqlite3
from zoneinfo import ZoneInfo

import discord

log = logging.getLogger('LaVenganzaRP.eventos')
EVENT_THRESHOLDS = (86400, 43200, 21600, 3600, 900)
PR = ZoneInfo('America/Puerto_Rico')


def timestamp():
    return int(datetime.now(timezone.utc).timestamp())


class EventFeatureStore:
    def __init__(self, path):
        self.path = path

    def connection(self):
        return sqlite3.connect(self.path, timeout=5)

    def initialize(self):
        with closing(self.connection()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS event_reminder_schedules(event_id INTEGER PRIMARY KEY,starts_at INTEGER NOT NULL,revision INTEGER NOT NULL,baseline INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS event_reminders(event_id INTEGER NOT NULL,revision INTEGER NOT NULL,seconds INTEGER NOT NULL,state TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(event_id,revision,seconds))')

    def _schedule(self, db, event_id, starts_at, now):
        row = db.execute('SELECT starts_at,revision,baseline FROM event_reminder_schedules WHERE event_id=?', (event_id,)).fetchone()
        if row is None:
            db.execute('INSERT INTO event_reminder_schedules VALUES (?,?,1,?)', (event_id, starts_at, now))
            return 1, now
        if row[0] != starts_at:
            revision = row[1] + 1
            db.execute('UPDATE event_reminder_schedules SET starts_at=?,revision=?,baseline=? WHERE event_id=?', (starts_at, revision, now, event_id))
            return revision, now
        return row[1], row[2]

    def schedule(self, event_id, now=None):
        now = timestamp() if now is None else now
        with closing(self.connection()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT starts_at FROM events WHERE id=?', (event_id,)).fetchone()
            if row:
                self._schedule(db, event_id, int(datetime.fromisoformat(row[0]).timestamp()), now)

    def active(self):
        with closing(self.connection()) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM events WHERE status='open' AND message_id IS NOT NULL")]

    def claim(self, event_id, now=None):
        now = timestamp() if now is None else now
        with closing(self.connection()) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM events WHERE id=? AND status='open' AND message_id IS NOT NULL", (event_id,)).fetchone()
            if not row:
                return None
            starts = int(datetime.fromisoformat(row['starts_at']).timestamp())
            revision, baseline = self._schedule(db, event_id, starts, now)
            due = [s for s in EVENT_THRESHOLDS if starts - s <= now]
            eligible = [s for s in due if starts - s > baseline]
            chosen = min(eligible) if eligible and now < starts else None
            claimed = False
            for seconds in due:
                result = db.execute('INSERT OR IGNORE INTO event_reminders VALUES (?,?,?,?,?)', (event_id, revision, seconds, 'claimed' if seconds == chosen else 'skipped', now))
                if seconds == chosen:
                    claimed = result.rowcount == 1
            return (dict(row), revision, chosen) if claimed else None

    def result(self, event_id, revision, seconds, state):
        with closing(self.connection()) as db, db:
            db.execute('UPDATE event_reminders SET state=?,updated_at=? WHERE event_id=? AND revision=? AND seconds=?', (state, timestamp(), event_id, revision, seconds))

    def history(self, page=1):
        with closing(self.connection()) as db:
            db.row_factory = sqlite3.Row
            condition = "(status='finished' OR NULLIF(winner1,'') IS NOT NULL OR NULLIF(winner2,'') IS NOT NULL OR NULLIF(winner3,'') IS NOT NULL)"
            total = db.execute('SELECT COUNT(*) FROM events WHERE ' + condition).fetchone()[0]
            rows = [dict(r) for r in db.execute('SELECT * FROM events WHERE ' + condition + ' ORDER BY starts_at DESC,id DESC LIMIT 5 OFFSET ?', ((page - 1) * 5,))]
            return rows, total

    def ranking(self):
        with closing(self.connection()) as db:
            db.row_factory = sqlite3.Row
            completed = list(db.execute("SELECT id,winner1,winner2,winner3 FROM events WHERE status='finished' OR NULLIF(winner1,'') IS NOT NULL OR NULLIF(winner2,'') IS NOT NULL OR NULLIF(winner3,'') IS NOT NULL"))
            registrations = {}
            for row in db.execute("SELECT r.event_id,r.user_id FROM registrations r JOIN events e ON e.id=r.event_id WHERE e.status='finished' OR NULLIF(e.winner1,'') IS NOT NULL OR NULLIF(e.winner2,'') IS NOT NULL OR NULLIF(e.winner3,'') IS NOT NULL"):
                registrations.setdefault(row['event_id'], set()).add(int(row['user_id']))
            players = {}
            for event in completed:
                winners = [int(event[k]) if str(event[k] or '').isdigit() and int(event[k]) > 0 else None for k in ('winner1', 'winner2', 'winner3')]
                participants = registrations.get(event['id'], set()) | {w for w in winners if w is not None}
                for user_id in participants:
                    item = players.setdefault(user_id, dict(user_id=user_id, participations=0, first=0, second=0, third=0))
                    item['participations'] += 1
                    for key, winner in zip(('first', 'second', 'third'), winners):
                        item[key] += int(winner == user_id)
            # Empates: primeros, segundos, terceros y por último ID estable.
            return sorted(players.values(), key=lambda p: (-p['participations'], -p['first'], -p['second'], -p['third'], p['user_id']))[:10], len(completed)


class EventFeatures:
    def __init__(self, bot, path, lock):
        self.bot, self.lock = bot, lock
        self.store = EventFeatureStore(path)
        self.task = None

    async def call(self, method, *args):
        return await asyncio.to_thread(getattr(self.store, method), *args)

    async def start(self):
        await self.call('initialize')
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.reminders(), name='event-reminders')

    async def schedule_notice(self, event_id):
        try:
            await self.call('schedule', event_id)
            return ''
        except Exception:
            log.exception('Evento guardado; no se pudo preparar recordatorios #%s', event_id)
            return '\n⚠️ Evento guardado; revisa los logs de recordatorios.'

    async def reminders(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for event in await self.call('active'):
                    try:
                        async with self.lock:
                            claim = await self.call('claim', event['id'])
                            if claim is None:
                                continue
                            current, revision, seconds = claim
                            label = {86400: '24 horas', 43200: '12 horas', 21600: '6 horas', 3600: '1 hora', 900: '15 minutos'}[seconds]
                            name = discord.utils.escape_markdown(current['title']).replace('@', '@\u200b')
                            when = datetime.fromisoformat(current['starts_at']).astimezone(PR)
                            embed = discord.Embed(title=f'🔔 EVENTO EN {label.upper()} | LA VENGANZA RP', description=f'🎉 **{name}**\n🇵🇷 {when:%d/%m/%Y · %I:%M %p} — Puerto Rico\n🌎 <t:{int(when.timestamp())}:F>\n[Ver evento](https://discord.com/channels/1244988345327550565/{current["channel_id"]}/{current["message_id"]})', color=0xD60000)
                            try:
                                channel = self.bot.get_channel(current['channel_id']) or await self.bot.fetch_channel(current['channel_id'])
                                await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                            except Exception:
                                await self.call('result', current['id'], revision, seconds, 'failed')
                                raise
                            await self.call('result', current['id'], revision, seconds, 'sent')
                    except Exception:
                        log.exception('Error en recordatorio del evento #%s', event['id'])
            except Exception:
                log.exception('Error revisando recordatorios de eventos')
            await asyncio.sleep(30)
