"""Presencia observada en voz, separada de RSVP y de correcciones manuales."""
from contextlib import closing
from datetime import datetime, timezone
import re
import sqlite3

import discord
from summaries import mention_list

STAFF_SCHEMA = (
    'CREATE TABLE IF NOT EXISTS meeting_voice_tracking(meeting_id INTEGER PRIMARY KEY,started_at INTEGER NOT NULL,observed_since INTEGER NOT NULL,gap_detected INTEGER NOT NULL DEFAULT 0)',
    'CREATE TABLE IF NOT EXISTS meeting_voice_visits(meeting_id INTEGER NOT NULL,user_id INTEGER NOT NULL,channel_id INTEGER NOT NULL,first_seen INTEGER NOT NULL,last_seen INTEGER NOT NULL,source TEXT NOT NULL,PRIMARY KEY(meeting_id,user_id))',
)


def now_epoch():
    return int(datetime.now(timezone.utc).timestamp())


def voice_id(meeting):
    value = meeting['location']
    return int(value[2:-1]) if re.fullmatch(r'<#\d+>', value) else None


class StaffReports:
    def __init__(self, path):
        self.path = path

    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def initialize(self):
        with closing(self.connection()) as db, db:
            for sql in STAFF_SCHEMA:
                db.execute(sql)

    def observe(self, meeting_id, channel_id, users, source='join', now=None, resume=False):
        now = now_epoch() if now is None else now
        with closing(self.connection()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            meeting = db.execute("SELECT * FROM meetings WHERE id=? AND status='scheduled' AND kind='staff'", (meeting_id,)).fetchone()
            if not meeting or voice_id(meeting) != channel_id:
                return
            prior = db.execute('SELECT * FROM meeting_voice_tracking WHERE meeting_id=?', (meeting_id,)).fetchone()
            db.execute('INSERT OR IGNORE INTO meeting_voice_tracking VALUES (?,?,?,?)', (meeting_id, meeting['created_at'], now, int(resume)))
            if resume and prior:
                db.execute('UPDATE meeting_voice_tracking SET gap_detected=1 WHERE meeting_id=?', (meeting_id,))
            started = prior['started_at'] if prior else meeting['created_at']
            if now < started:
                return
            for user_id in set(users):
                db.execute('INSERT INTO meeting_voice_visits VALUES (?,?,?,?,?,?) ON CONFLICT(meeting_id,user_id) DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen)', (meeting_id, user_id, channel_id, now, now, source))

    def gap(self, meeting_id=None):
        with closing(self.connection()) as db, db:
            if meeting_id is None:
                db.execute("UPDATE meeting_voice_tracking SET gap_detected=1 WHERE meeting_id IN (SELECT id FROM meetings WHERE status='scheduled' AND kind='staff')")
            else:
                db.execute('UPDATE meeting_voice_tracking SET gap_detected=1 WHERE meeting_id=?', (meeting_id,))

    def report(self, meeting_id):
        with closing(self.connection()) as db:
            tracking = db.execute('SELECT * FROM meeting_voice_tracking WHERE meeting_id=?', (meeting_id,)).fetchone()
            visits = {r['user_id']: dict(r) for r in db.execute('SELECT * FROM meeting_voice_visits WHERE meeting_id=?', (meeting_id,))}
            manual = {r['user_id']: dict(r) for r in db.execute('SELECT * FROM meeting_attendance WHERE meeting_id=?', (meeting_id,))}
            responses = {r['user_id']: r['response'] for r in db.execute('SELECT * FROM meeting_responses WHERE meeting_id=?', (meeting_id,))}
        present = set(visits)
        for user_id, row in manual.items():
            if row['present']:
                present.add(user_id)
            else:
                present.discard(user_id)
        yes = {u for u, response in responses.items() if response == 'yes'}
        no = {u for u, response in responses.items() if response == 'no'}
        maybe = {u for u, response in responses.items() if response == 'maybe'}
        return dict(tracking=dict(tracking) if tracking else None, visits=visits, manual=manual, present=sorted(present), confirmed_present=sorted(yes & present), confirmed_missing=sorted(yes - present), declined=sorted(no), maybe=sorted(maybe), unconfirmed_present=sorted(present - set(responses)), declined_present=sorted(no & present))


def report_embed(meeting, report):
    title = discord.utils.escape_markdown(meeting['title']).replace('@', '@\u200b')
    tracking = report['tracking']
    observed = f"Observación desde <t:{tracking['observed_since']}:f>." if tracking else 'No hay observación automática de voz para esta reunión anterior.'
    gap = '\n⚠️ Hubo posibles interrupciones; sin registro no demuestra ausencia.' if tracking and tracking['gap_detected'] else '\nSin presencia registrada significa que el bot no observó una entrada ni hay registro manual.'
    label = 'INFORME FINAL' if meeting['status'] == 'finished' else 'INFORME PROVISIONAL'
    embed = discord.Embed(title=f'📋 {label} DE STAFF — {title}', description=f"👥 **Asistencia registrada: {len(report['present'])}**\n{observed}{gap}\nRegistros manuales prevalecen sobre la detección automática.", color=0xD60000)
    for key, label in (('present', '✅ Asistieron'), ('confirmed_present', '🤝 Confirmaron y asistieron'), ('confirmed_missing', '❌ Confirmaron · sin presencia registrada'), ('declined', '🚫 Dijeron que no asistirían'), ('maybe', '❔ Dijeron tal vez')):
        embed.add_field(name=f"{label} · {len(report[key])}", value=mention_list(report[key], limit=900), inline=False)
    embed.set_footer(text=f"LA VENGANZA RP | Reunión #{meeting['id']} | Informe completo: /reunion informe")
    return embed


def report_text(meeting, report):
    lines = [f"INFORME STAFF — REUNIÓN #{meeting['id']}", meeting['title'], f"Estado: {meeting['status']}", 'Confirmaciones y presencia son registros independientes.', 'Los registros manuales prevalecen.']
    tracking = report['tracking']
    lines.append(f"Observación: {tracking}" if tracking else 'No existe seguimiento de voz histórico. No se reconstruyen entradas anteriores.')
    lines.append('Sin registro no demuestra ausencia si el bot estuvo desconectado o no pudo observar el canal.')
    present = set(report['present'])
    for key, label in (('present', 'ASISTIERON'), ('confirmed_present', 'CONFIRMARON Y ASISTIERON'), ('confirmed_missing', 'CONFIRMARON Y SIN PRESENCIA REGISTRADA'), ('declined', 'DIJERON NO'), ('maybe', 'TAL VEZ'), ('unconfirmed_present', 'ASISTIERON SIN RESPUESTA'), ('declined_present', 'DIJERON NO PERO ASISTIERON')):
        lines.append(f'\n{label} ({len(report[key])})')
        for user_id in report[key]:
            detail = f"{user_id} | {'Presencia registrada' if user_id in present else 'Sin presencia registrada'}"
            if user_id in report['visits']:
                visit = report['visits'][user_id]
                detail += f" | voz primera observación={visit['first_seen']} última observación={visit['last_seen']} canal={visit['channel_id']} origen={visit['source']}"
            if user_id in report['manual']:
                manual = report['manual'][user_id]
                detail += f" | manual={manual['present']} por={manual['recorded_by']} fecha={manual['recorded_at']}"
            lines.append(detail)
    return '\n'.join(lines)
