"""Reuniones independientes de eventos; SQLite en hilos y vistas persistentes."""
import asyncio
import io
import hashlib
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from summaries import SUMMARY_SCHEMA, SummaryMessages, meeting_summary
from staff_reports import STAFF_SCHEMA, StaffReports, voice_id, report_embed, report_text

log = logging.getLogger("LaVenganzaRP.reuniones")
GUILD_ID = 1244988345327550565
CHANNELS = {"staff": 1515887549678223380, "general": 1513422089162330184}
STAFF_VOICE_ID = 1515887667298963579
VOICE_TYPES = (discord.ChannelType.voice, discord.ChannelType.stage_voice)
ROLES = {1245008186440683530, 1245010156576833536, 1300619682486947931, 1300627506801541230}
PR = ZoneInfo("America/Puerto_Rico")
REMINDER_LABELS = {86400: "24 horas", 43200: "12 horas", 21600: "6 horas", 3600: "1 hora", 900: "15 minutos", 300: "5 minutos", 0: "inicio"}
START_GRACE = 180
LABELS = {"yes": "✅ Asistiré", "no": "❌ No asistiré", "maybe": "❔ Tal vez"}


class MeetingStore:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self):
        with self.db() as db:
            # Solo tablas nuevas: no se modifican eventos, settings ni inscripciones.
            for sql in (
                SUMMARY_SCHEMA,
                *STAFF_SCHEMA,
                "CREATE TABLE IF NOT EXISTS meetings (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, channel_id INTEGER NOT NULL, message_id INTEGER UNIQUE, title TEXT NOT NULL, starts_at INTEGER NOT NULL, location TEXT NOT NULL, agenda TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'publishing', created_by INTEGER NOT NULL, created_at INTEGER NOT NULL, ended_at INTEGER, ended_by INTEGER)",
                "CREATE TABLE IF NOT EXISTS meeting_responses (meeting_id INTEGER NOT NULL REFERENCES meetings(id), user_id INTEGER NOT NULL, response TEXT NOT NULL CHECK(response IN ('yes','no','maybe')), updated_at INTEGER NOT NULL, PRIMARY KEY(meeting_id,user_id))",
                "CREATE TABLE IF NOT EXISTS meeting_attendance (meeting_id INTEGER NOT NULL REFERENCES meetings(id), user_id INTEGER NOT NULL, present INTEGER NOT NULL CHECK(present IN (0,1)), recorded_by INTEGER NOT NULL, recorded_at INTEGER NOT NULL, PRIMARY KEY(meeting_id,user_id))",
                "CREATE TABLE IF NOT EXISTS meeting_reminders (meeting_id INTEGER NOT NULL REFERENCES meetings(id), seconds INTEGER NOT NULL, state TEXT NOT NULL, updated_at INTEGER NOT NULL, PRIMARY KEY(meeting_id,seconds))",
                "CREATE INDEX IF NOT EXISTS meetings_status_time ON meetings(status,starts_at)",
            ):
                db.execute(sql)

    def get(self, meeting_id=None, message_id=None):
        with self.db() as db:
            row = db.execute("SELECT * FROM meetings WHERE id=?" if meeting_id is not None else "SELECT * FROM meetings WHERE message_id=?", (meeting_id if meeting_id is not None else message_id,)).fetchone()
            return dict(row) if row else None

    def save(self, values, author, kind, meeting_id=None):
        now = int(datetime.now(timezone.utc).timestamp())
        with self.db() as db:
            if meeting_id is None:
                return self.insert(db, values, author, kind, now)
            old = db.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if not old or old["status"] != "scheduled":
                raise ValueError("La reunión ya no está activa.")
            db.execute("UPDATE meetings SET title=?,starts_at=?,location=?,agenda=?,description=? WHERE id=?", (*values, meeting_id))
            # Si cambia la fecha, se reprograman los avisos; las respuestas se conservan.
            if old["starts_at"] != values[1]:
                db.execute("DELETE FROM meeting_reminders WHERE meeting_id=?", (meeting_id,))
                db.execute("UPDATE meetings SET created_at=? WHERE id=?", (now, meeting_id))
            return meeting_id

    def insert(self, db, values, author, kind, now):
        cur = db.execute("INSERT INTO meetings(kind,channel_id,title,starts_at,location,agenda,description,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (kind, CHANNELS[kind], *values, author, now))
        return cur.lastrowid

    def publication(self, meeting_id, message_id=None):
        with self.db() as db:
            db.execute("UPDATE meetings SET message_id=?,status=? WHERE id=?", (message_id, "scheduled" if message_id else "publication_failed", meeting_id))

    def respond(self, meeting_id, user_id, response):
        with self.db() as db:
            row = db.execute("SELECT status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if not row or row[0] != "scheduled":
                raise ValueError("Esta reunión ya no acepta confirmaciones.")
            db.execute("INSERT INTO meeting_responses VALUES (?,?,?,?) ON CONFLICT(meeting_id,user_id) DO UPDATE SET response=excluded.response,updated_at=excluded.updated_at", (meeting_id, user_id, response, int(datetime.now(timezone.utc).timestamp())))

    def lists(self, meeting_id):
        with self.db() as db:
            responses = [dict(r) for r in db.execute("SELECT * FROM meeting_responses WHERE meeting_id=? ORDER BY updated_at", (meeting_id,))]
            attendance = [dict(r) for r in db.execute("SELECT * FROM meeting_attendance WHERE meeting_id=? ORDER BY recorded_at", (meeting_id,))]
            return responses, attendance

    def present(self, meeting_id, user_id, present, author):
        with self.db() as db:
            row = db.execute("SELECT status FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if not row or row[0] != "scheduled":
                raise ValueError("Solo se registra asistencia mientras la reunión está activa.")
            db.execute("INSERT INTO meeting_attendance VALUES (?,?,?,?,?) ON CONFLICT(meeting_id,user_id) DO UPDATE SET present=excluded.present,recorded_by=excluded.recorded_by,recorded_at=excluded.recorded_at", (meeting_id, user_id, int(present), author, int(datetime.now(timezone.utc).timestamp())))

    def finish(self, meeting_id, status, author):
        with self.db() as db:
            cur = db.execute("UPDATE meetings SET status=?,ended_at=?,ended_by=? WHERE id=? AND status='scheduled'", (status, int(datetime.now(timezone.utc).timestamp()), author, meeting_id))
            if cur.rowcount != 1:
                raise ValueError("La reunión ya está cancelada o finalizada.")

    def active(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM meetings WHERE status='scheduled' AND message_id IS NOT NULL")]

    def claim_reminder(self, meeting_id, now):
        claim = self.reserve_reminder(meeting_id, now)
        return claim[1] if claim else None

    def reserve_reminder(self, meeting_id, now):
        with self.db() as db:
            m = db.execute("SELECT * FROM meetings WHERE id=? AND status='scheduled' AND message_id IS NOT NULL", (meeting_id,)).fetchone()
            if not m:
                return None
            starts = m["starts_at"]
            if now >= starts + START_GRACE:
                return None
            due = [s for s in REMINDER_LABELS if m["created_at"] <= starts - s <= now]
            if not due:
                return None
            seconds = min(due)
            key = (meeting_id, seconds)
            inserted = db.execute("INSERT OR IGNORE INTO meeting_reminders VALUES (?,?,'claimed',?)", (*key, now)).rowcount
            if not inserted:
                retried = db.execute("""UPDATE meeting_reminders SET state='claimed',updated_at=?
                    WHERE meeting_id=? AND seconds=? AND
                    (state='failed' OR (state='claimed' AND updated_at<=?))""", (now,*key,now-60)).rowcount
                if not retried:
                    return None
            return dict(m), seconds, not inserted

    def reminder_result(self, meeting_id, seconds, state):
        with self.db() as db:
            db.execute("UPDATE meeting_reminders SET state=?,updated_at=? WHERE meeting_id=? AND seconds=?", (state, int(datetime.now(timezone.utc).timestamp()), meeting_id, seconds))


def escaped(text):
    return discord.utils.escape_markdown(str(text)).replace("@", "@\u200b")


def meeting_location(value):
    """Enlaza solo IDs de canal guardados; conserva texto de reuniones anteriores."""
    return value if re.fullmatch(r"<#\d+>", value) else escaped(value)


class MeetingSystem:
    def __init__(self, bot, path, summaries=None):
        self.bot = bot
        self.summaries = summaries if summaries is not None else SummaryMessages(bot, path)
        self.store = MeetingStore(path)
        from meeting_polls import MeetingPolls
        self.polls = MeetingPolls(self)
        self.staff = StaffReports(path)
        self.initialized = False
        self.last_check_at = None
        self.lock = asyncio.Lock()
        self.task = None
        self.group = app_commands.Group(name="reunion", description="Reuniones oficiales de LA VENGANZA RP", guild_only=True)
        self.register_commands()

    async def call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, method), *args, **kwargs)

    async def start(self):
        await self.call("initialize")
        await self.polls.start()
        self.initialized = True
        self.bot.add_view(MeetingButtons(self))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.reminders(), name="meeting-reminders")

    async def staff_call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.staff, method), *args, **kwargs)

    async def snapshot_voice(self, meeting, resume=False):
        if meeting["kind"] != "staff" or meeting["status"] != "scheduled":
            return
        channel_id = voice_id(meeting)
        if channel_id is None:
            return
        channel = self.bot.get_channel(channel_id)
        bot_member = channel.guild.me if channel else None
        observable = channel is not None and bot_member is not None and channel.permissions_for(bot_member).view_channel
        users = [member.id for member in channel.members if not member.bot] if observable else []
        await self.staff_call("observe", meeting["id"], channel_id, users, source="snapshot", resume=resume)
        if not observable:
            await self.staff_call("gap", meeting["id"])
            log.warning("No se pudo observar el canal de voz de reunión #%s", meeting["id"])

    async def snapshot_notice(self, meeting):
        try:
            await self.snapshot_voice(meeting)
            return ""
        except Exception:
            log.exception("No se pudo iniciar observación de voz de reunión #%s", meeting["id"])
            return "\n⚠️ Reunión guardada; revisa logs de asistencia automática."

    async def voice_ready(self):
        if not self.initialized:
            return
        async with self.lock:
            for meeting in await self.call("active"):
                await self.snapshot_voice(meeting, resume=True)

    async def voice_disconnected(self):
        if self.initialized:
            await self.staff_call("gap")

    async def voice_update(self, member, before, after):
        if member.bot or member.guild.id != GUILD_ID or after.channel is None:
            return
        if before.channel is not None and before.channel.id == after.channel.id:
            return
        async with self.lock:
            for meeting in await self.call("active"):
                if meeting["kind"] == "staff" and voice_id(meeting) == after.channel.id:
                    await self.staff_call("observe", meeting["id"], after.channel.id, [member.id], source="join")

    async def staff_report_notice(self, meeting):
        if meeting["kind"] != "staff" or meeting["status"] != "finished":
            return ""
        try:
            data = await self.staff_call("report", meeting["id"])
            await self.summaries.update("staff_report", meeting["id"], meeting["channel_id"], report_embed(meeting, data))
            return ""
        except Exception:
            log.exception("No se pudo publicar informe de reunión #%s", meeting["id"])
            return "\n⚠️ Datos conservados; consulta /reunion informe para revisar o reintentar el informe."

    async def send_staff_report(self, interaction, meeting):
        data = await self.staff_call("report", meeting["id"])
        notice = await self.staff_report_notice(meeting)
        await interaction.followup.send(content=notice or None, embed=report_embed(meeting, data), file=discord.File(io.BytesIO(report_text(meeting, data).encode()), filename=f"informe-staff-{meeting['id']}.txt"), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    def admin(self, interaction):
        if interaction.guild_id != GUILD_ID or not isinstance(interaction.user, discord.Member) or not ROLES.intersection(r.id for r in interaction.user.roles):
            raise app_commands.CheckFailure("Necesitas uno de los roles autorizados para reuniones.")

    async def channel_access(self, interaction, channel_id, admin=False):
        if admin:
            self.admin(interaction)
        if interaction.guild_id != GUILD_ID or not isinstance(interaction.user, discord.Member):
            raise app_commands.CheckFailure("Servidor no autorizado.")
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if channel.guild.id != GUILD_ID or not channel.permissions_for(interaction.user).view_channel:
            raise app_commands.CheckFailure("No tienes acceso al canal de esta reunión.")
        return channel

    async def voice_access(self, interaction, channel_id):
        try:
            voice = await self.channel_access(interaction, channel_id)
        except discord.NotFound:
            raise ValueError(f"No se encontró el canal de voz {channel_id} en este servidor.") from None
        if voice.type not in VOICE_TYPES:
            raise ValueError(f"El canal {channel_id} es de tipo {voice.type}; debe ser de voz o escenario.")
        if not voice.permissions_for(interaction.user).connect:
            raise app_commands.CheckFailure("Tu usuario necesita permiso Conectar en el canal de la reunión; los permisos del bot son independientes.")
        return voice

    async def preferred_voice(self, interaction, kind, meeting=None):
        if meeting and re.fullmatch(r"<#\d+>", meeting["location"]):
            return None  # Se conserva el canal anterior al editar.
        if kind != "staff":
            return None
        voice = await self.voice_access(interaction, STAFF_VOICE_ID)
        log.info("Canal de reunión Staff verificado: id=%s tipo=%s", voice.id, voice.type)
        return voice.id

    async def authorized_meeting(self, interaction, meeting_id):
        self.admin(interaction)
        meeting = await self.call("get", meeting_id)
        if not meeting:
            raise ValueError("Reunión no encontrada.")
        await self.channel_access(interaction, meeting["channel_id"], admin=True)
        return meeting

    async def embed(self, meeting):
        responses, attendance = await self.call("lists", meeting["id"])
        counts = {k: sum(r["response"] == k for r in responses) for k in LABELS}
        local = datetime.fromtimestamp(meeting["starts_at"], PR)
        status = {"scheduled": "Confirmaciones abiertas", "cancelled": "Cancelada", "finished": "Finalizada"}.get(meeting["status"], "Preparando anuncio")
        embed = discord.Embed(title=f"{'🔒' if meeting['kind'] == 'staff' else '🌎'} {escaped(meeting['title'])}", description=escaped(meeting["description"]), color=0xD60000)
        embed.add_field(name="📅 Fecha y hora", value=f"🇵🇷 {local:%d/%m/%Y · %I:%M %p} — Puerto Rico\n🌎 Tu hora: <t:{meeting['starts_at']}:F>", inline=False)
        embed.add_field(name="🔔 Recordatorios en este canal", value="24 h, 12 h, 6 h, 1 h, 15 min, 5 min y al comenzar.", inline=False)
        embed.add_field(name="📍 Lugar o canal de voz", value=meeting_location(meeting["location"]), inline=False)
        embed.add_field(name="📋 Agenda", value=escaped(meeting["agenda"]), inline=False)
        embed.add_field(name="Confirmaciones", value=" · ".join(f"{LABELS[k]}: **{counts[k]}**" for k in LABELS), inline=False)
        present_count = sum(r['present'] for r in attendance)
        if meeting["kind"] == "staff":
            present_count = len((await self.staff_call("report", meeting["id"]))["present"])
        embed.add_field(name="Estado", value=f"{status}\n👥 Asistencia real registrada: {present_count}", inline=False)
        embed.set_footer(text=f"LA VENGANZA RP | Reunión #{meeting['id']}")
        return embed

    async def refresh(self, meeting_id):
        meeting = await self.call("get", meeting_id)
        channel = self.bot.get_channel(meeting["channel_id"]) or await self.bot.fetch_channel(meeting["channel_id"])
        message = await channel.fetch_message(meeting["message_id"])
        await message.edit(embed=await self.embed(meeting), view=MeetingButtons(self, disabled=meeting["status"] != "scheduled"))

    async def refresh_summary_notice(self, meeting_id):
        try:
            meeting = await self.call("get", meeting_id)
            if not meeting or not meeting["message_id"]:
                return ""
            responses, _ = await self.call("lists", meeting_id)
            start = meeting["starts_at"] if meeting["status"] == "scheduled" else None
            await self.summaries.update("meeting", meeting_id, meeting["channel_id"], meeting_summary(meeting, responses), starts_at=start)
            return ""
        except Exception:
            log.exception("Registro conservado; no se pudo actualizar la lista pública de reunión #%s", meeting_id)
            return "\n⚠️ Datos guardados; no se pudo actualizar la lista pública. Consulta /reunion asistencia."

    async def refresh_notice(self, meeting_id):
        notice = ""
        try:
            await self.refresh(meeting_id)
        except discord.HTTPException:
            log.exception("Registro guardado; no se pudo actualizar reunión #%s", meeting_id)
            notice = "\n⚠️ Registro guardado. No se pudo actualizar el anuncio; revisa los permisos del bot."
        return notice + await self.refresh_summary_notice(meeting_id)

    def register_commands(self):
        @self.group.command(name="encuesta", description="Propón tres horarios y crea la reunión con el más votado")
        @app_commands.choices(tipo=[app_commands.Choice(name="🔒 Staff", value="staff"), app_commands.Choice(name="🌎 General", value="general")])
        async def poll(interaction: discord.Interaction, tipo: app_commands.Choice[str]):
            await self.channel_access(interaction, CHANNELS[tipo.value], admin=True)
            preferred = await self.preferred_voice(interaction, tipo.value)
            await interaction.response.send_modal(MeetingModal(self, tipo.value, preferred_voice_id=preferred, poll=True))

        @self.group.command(name="crear", description="Abre el formulario de una reunión oficial")
        @app_commands.choices(tipo=[app_commands.Choice(name="🔒 Staff", value="staff"), app_commands.Choice(name="🌎 General", value="general")])
        async def create(interaction: discord.Interaction, tipo: app_commands.Choice[str]):
            await self.channel_access(interaction, CHANNELS[tipo.value], admin=True)
            preferred = await self.preferred_voice(interaction, tipo.value)
            await interaction.response.send_modal(MeetingModal(self, tipo.value, preferred_voice_id=preferred))

        @self.group.command(name="editar", description="Edita una reunión sin perder sus confirmaciones")
        async def edit(interaction: discord.Interaction, reunion_id: int):
            meeting = await self.authorized_meeting(interaction, reunion_id)
            if meeting["status"] != "scheduled":
                raise ValueError("La reunión ya no está activa.")
            preferred = await self.preferred_voice(interaction, meeting["kind"], meeting)
            await interaction.response.send_modal(MeetingModal(self, meeting["kind"], meeting, preferred_voice_id=preferred))

        @self.group.command(name="cancelar", description="Cancela y conserva el anuncio y los registros")
        async def cancel(interaction: discord.Interaction, reunion_id: int):
            await self.end(interaction, reunion_id, "cancelled")

        @self.group.command(name="finalizar", description="Finaliza y bloquea nuevas confirmaciones")
        async def finish(interaction: discord.Interaction, reunion_id: int):
            await self.end(interaction, reunion_id, "finished")

        @self.group.command(name="presente", description="Registra asistencia real, separada de la confirmación")
        async def present(interaction: discord.Interaction, reunion_id: int, miembro: discord.Member, asistio: bool = True):
            await interaction.response.defer(ephemeral=True)
            async with self.lock:
                await self.authorized_meeting(interaction, reunion_id)
                await self.call("present", reunion_id, miembro.id, asistio, interaction.user.id)
                notice = await self.refresh_notice(reunion_id)
            await interaction.followup.send("✅ Asistencia real guardada." + notice, ephemeral=True)

        @self.group.command(name="informe", description="Compara confirmaciones de Staff con presencia registrada en voz")
        async def staff_report(interaction: discord.Interaction, reunion_id: int):
            await interaction.response.defer(ephemeral=True)
            meeting = await self.authorized_meeting(interaction, reunion_id)
            if meeting["kind"] != "staff":
                raise ValueError("El informe automático de voz corresponde a reuniones Staff. Usa /reunion asistencia para reuniones generales.")
            await self.send_staff_report(interaction, meeting)

        @self.group.command(name="asistencia", description="Consulta confirmaciones y asistencia real completa")
        async def attendance(interaction: discord.Interaction, reunion_id: int):
            await interaction.response.defer(ephemeral=True)
            meeting = await self.authorized_meeting(interaction, reunion_id)
            if meeting["kind"] == "staff":
                await self.send_staff_report(interaction, meeting)
                return
            responses, actual = await self.call("lists", reunion_id)
            lines = [f"ASISTENCIA — REUNIÓN #{reunion_id}"]
            for key, label in LABELS.items():
                lines.append("\n" + label)
                lines.extend(str(r["user_id"]) for r in responses if r["response"] == key)
            lines.append("\nASISTENCIA REAL (independiente de la confirmación)")
            lines.extend(f"{r['user_id']} | {'Presente' if r['present'] else 'Ausente'} | registró {r['recorded_by']} | <t:{r['recorded_at']}:f>" for r in actual)
            report = "\n".join(lines)
            if len(report) <= 1800:
                await interaction.followup.send(report, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            else:
                await interaction.followup.send("📋 Lista completa por ID de Discord:", file=discord.File(io.BytesIO(report.encode()), filename=f"asistencia-{reunion_id}.txt"), ephemeral=True)

    async def end(self, interaction, meeting_id, status):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            meeting = await self.authorized_meeting(interaction, meeting_id)
            if meeting["status"] == "scheduled":
                await self.snapshot_voice(meeting)
                await self.call("finish", meeting_id, status, interaction.user.id)
            elif meeting["status"] != status:
                raise ValueError("La reunión ya terminó con otro estado.")
            current = await self.call("get", meeting_id)
            notice = await self.refresh_summary_notice(meeting_id)
            notice += await self.staff_report_notice(current)
            try:
                channel = self.bot.get_channel(current["channel_id"]) or await self.bot.fetch_channel(current["channel_id"])
                if current["message_id"]:
                    panel = await channel.fetch_message(current["message_id"])
                    await panel.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception("No se pudo eliminar panel de reunión #%s", meeting_id)
                notice += "\n⚠️ No se pudo eliminar el panel. Revisa los permisos y repite este comando para reintentar."
        await interaction.followup.send(("🔒 Reunión cancelada." if status == "cancelled" else "✅ Reunión finalizada.") + " Registros conservados; se retira el panel de botones." + notice, ephemeral=True)

    async def send_due_reminder(self, meeting_id, now):
        async with self.lock:
            claim = await self.call("reserve_reminder", meeting_id, now)
            if not claim:
                return
            meeting, seconds, retry = claim
            starts = meeting["starts_at"]
            local = datetime.fromtimestamp(starts, PR)
            marker = f"LA VENGANZA RP | Reunión #{meeting_id} · {local:%d/%m/%Y %H:%M} PR · {REMINDER_LABELS[seconds]}"
            try:
                channel = self.bot.get_channel(meeting["channel_id"]) or await self.bot.fetch_channel(meeting["channel_id"])
                delivered = False
                if retry:
                    after = datetime.fromtimestamp(starts - seconds - 1, timezone.utc)
                    async for message in channel.history(limit=None, after=after):
                        if message.author.id == self.bot.user.id and any(e.footer.text == marker for e in message.embeds):
                            delivered = True
                            break
                if not delivered:
                    heading = "🔔 RECORDATORIO DE REUNIÓN"
                    if not seconds:
                        heading = "🎙️ LA REUNIÓN HA COMENZADO"
                    elif now - (starts - seconds) < 60:
                        heading = f"🔔 REUNIÓN EN {REMINDER_LABELS[seconds].upper()}"
                    url = f"https://discord.com/channels/{GUILD_ID}/{channel.id}/{meeting['message_id']}"
                    embed = discord.Embed(title=heading, description=f"**{escaped(meeting['title'])}**\n"
                        f"🇵🇷 {local:%d/%m/%Y · %I:%M %p} — Puerto Rico\n🌎 <t:{starts}:F> · <t:{starts}:R>\n"
                        f"📍 {meeting_location(meeting['location'])}\n[Ver reunión]({url})", color=0xD60000)
                    embed.set_footer(text=marker)
                    nonce = int.from_bytes(hashlib.blake2b(marker.encode(), digest_size=8).digest(), "big") >> 1
                    await channel.send(embed=embed, nonce=nonce, allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                await self.call("reminder_result", meeting_id, seconds, "failed")
                raise
            await self.call("reminder_result", meeting_id, seconds, "sent")

    async def reminders(self):
        await self.bot.wait_until_ready()
        log.info("Recordatorios de reuniones activos: staff y general")
        for kind, channel_id in CHANNELS.items():
            channel = self.bot.get_channel(channel_id)
            perms = channel.permissions_for(channel.guild.me) if channel and channel.guild.me else None
            ready = bool(perms and perms.view_channel and perms.send_messages and perms.embed_links and perms.read_message_history)
            log.info("Recordatorios de reuniones: %s canal=%s permisos=%s", kind, channel_id, ready)
        while not self.bot.is_closed():
            self.last_check_at = int(datetime.now(timezone.utc).timestamp())
            try:
                for meeting in await self.call("active"):
                    try:
                        await self.send_due_reminder(meeting["id"], int(datetime.now(timezone.utc).timestamp()))
                    except Exception:
                        log.exception("Error en recordatorio de reunión #%s", meeting["id"])
            except Exception:
                log.exception("Error revisando recordatorios")
            await asyncio.sleep(30)


class MeetingModal(discord.ui.Modal, title="Reunión | LA VENGANZA RP"):
    def __init__(self, system, kind, meeting=None, preferred_voice_id=None, poll=False):
        super().__init__(timeout=900)
        self.system, self.kind, self.meeting = system, kind, meeting
        self.poll = poll
        self.name = discord.ui.TextInput(max_length=90)
        self.when = discord.ui.TextInput(max_length=16, placeholder="2026-12-20 19:30")
        if poll:
            self.title = "Encuesta de horarios"
            self.when = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=100,
                                             placeholder="2026-12-20 19:30\n2026-12-20 21:00\n2026-12-21 18:00")
        defaults = []
        if preferred_voice_id is not None:
            defaults = [discord.SelectDefaultValue(id=preferred_voice_id, type=discord.SelectDefaultValueType.channel)]
        if meeting and re.fullmatch(r"<#\d+>", meeting["location"]):
            channel_id = int(meeting["location"][2:-1])
            defaults = [discord.SelectDefaultValue(id=channel_id, type=discord.SelectDefaultValueType.channel)]
        self.location = discord.ui.ChannelSelect(
            custom_id="lvrp:meeting:voice",
            channel_types=list(VOICE_TYPES),
            placeholder="Selecciona el canal de voz",
            min_values=1, max_values=1, required=True,
            default_values=defaults,
        )
        self.agenda = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=500)
        self.description = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=1200)
        for label, component in (
            ("Nombre", self.name),
            ("3 horarios PR (AAAA-MM-DD HH:MM por línea)" if poll else "Fecha y hora PR: AAAA-MM-DD HH:MM", self.when),
            ("Canal de voz", self.location),
            ("Agenda", self.agenda),
            ("Descripción", self.description),
        ):
            self.add_item(discord.ui.Label(text=label, component=component))
        if meeting:
            self.name.default = meeting["title"]
            self.when.default = datetime.fromtimestamp(meeting["starts_at"], PR).strftime("%Y-%m-%d %H:%M")
            for key in ("agenda", "description"):
                getattr(self, key).default = meeting[key]

    async def selected_location(self, interaction):
        if len(self.location.values) != 1:
            raise ValueError("Selecciona un canal de voz.")
        voice = await self.system.voice_access(interaction, self.location.values[0].id)
        return f"<#{voice.id}>"

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        system = self.system
        channel = await system.channel_access(interaction, CHANNELS[self.kind], admin=True)
        if self.poll:
            slots = system.polls.parse(self.when.value)
            location = await self.selected_location(interaction)
            await system.polls.publish(interaction, channel, self.kind, self.name.value.strip(), slots,
                                       location, self.agenda.value.strip(), self.description.value.strip())
            return
        try:
            date = datetime.strptime(self.when.value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=PR)
        except ValueError:
            raise ValueError("Usa AAAA-MM-DD HH:MM, hora de Puerto Rico en formato de 24 horas.")
        if date <= datetime.now(PR):
            raise ValueError("Selecciona una fecha futura.")
        location = await self.selected_location(interaction)
        values = (self.name.value.strip(), int(date.timestamp()), location, self.agenda.value.strip(), self.description.value.strip())
        if any(not value for value in values):
            raise ValueError("Completa todos los campos.")
        async with system.lock:
            if self.meeting:
                await system.authorized_meeting(interaction, self.meeting["id"])
                meeting_id = await system.call("save", values, interaction.user.id, self.kind, self.meeting["id"])
                notice = await system.refresh_notice(meeting_id)
            else:
                meeting_id = await system.call("save", values, interaction.user.id, self.kind)
                meeting = await system.call("get", meeting_id)
                meeting["status"] = "scheduled"
                try:
                    message = await channel.send(embed=await system.embed(meeting), view=MeetingButtons(system), allowed_mentions=discord.AllowedMentions.none())
                except Exception:
                    await system.call("publication", meeting_id)
                    raise
                await system.call("publication", meeting_id, message.id)
                notice = await system.refresh_summary_notice(meeting_id)
            current_meeting = await system.call("get", meeting_id)
            notice += await system.snapshot_notice(current_meeting)
        await interaction.followup.send(f"✅ Reunión #{meeting_id} {'actualizada' if self.meeting else 'publicada'}." + notice, ephemeral=True)

    async def on_error(self, interaction, error):
        await meeting_error(interaction, error)


async def meeting_error(interaction, error):
    log.error("Error en reunión", exc_info=(type(error), error, error.__traceback__))
    message = f"❌ {error}" if isinstance(error, (ValueError, app_commands.CheckFailure)) else "❌ No se pudo completar la acción. Revisa Railway antes de repetirla."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        log.exception("No se pudo responder a la interacción")


class MeetingButtons(discord.ui.View):
    def __init__(self, system, disabled=False):
        super().__init__(timeout=None)
        self.system = system
        for item in self.children:
            item.disabled = disabled

    async def respond(self, interaction, response):
        await interaction.response.defer(ephemeral=True)
        async with self.system.lock:
            meeting = await self.system.call("get", message_id=interaction.message.id)
            if not meeting or meeting["channel_id"] != interaction.channel_id:
                raise ValueError("Reunión no encontrada.")
            await self.system.channel_access(interaction, meeting["channel_id"])
            await self.system.call("respond", meeting["id"], interaction.user.id, response)
            notice = await self.system.refresh_notice(meeting["id"])
        await interaction.followup.send(f"Confirmación guardada: {LABELS[response]}. Puedes cambiarla." + notice, ephemeral=True)

    @discord.ui.button(label="Asistiré", emoji="✅", style=discord.ButtonStyle.success, custom_id="lvrp:meeting:yes")
    async def yes(self, interaction, button):
        await self.respond(interaction, "yes")

    @discord.ui.button(label="No asistiré", emoji="❌", style=discord.ButtonStyle.danger, custom_id="lvrp:meeting:no")
    async def no(self, interaction, button):
        await self.respond(interaction, "no")

    @discord.ui.button(label="Tal vez", emoji="❔", style=discord.ButtonStyle.secondary, custom_id="lvrp:meeting:maybe")
    async def maybe(self, interaction, button):
        await self.respond(interaction, "maybe")

    async def on_error(self, interaction, error, item):
        await meeting_error(interaction, error)
