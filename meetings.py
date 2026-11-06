"""Reuniones independientes de eventos; SQLite en hilos y vistas persistentes."""
import asyncio
import io
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

log = logging.getLogger("LaVenganzaRP.reuniones")
GUILD_ID = 1244988345327550565
CHANNELS = {"staff": 1515887549678223380, "general": 1513422089162330184}
ROLES = {1245008186440683530, 1245010156576833536, 1300619682486947931, 1300627506801541230}
PR = ZoneInfo("America/Puerto_Rico")
THRESHOLDS = (86400, 3600, 900)
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
                cur = db.execute("INSERT INTO meetings(kind,channel_id,title,starts_at,location,agenda,description,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (kind, CHANNELS[kind], *values, author, now))
                return cur.lastrowid
            old = db.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
            if not old or old["status"] != "scheduled":
                raise ValueError("La reunión ya no está activa.")
            db.execute("UPDATE meetings SET title=?,starts_at=?,location=?,agenda=?,description=? WHERE id=?", (*values, meeting_id))
            # Si cambia la fecha, se reprograman los avisos; las respuestas se conservan.
            if old["starts_at"] != values[1]:
                db.execute("DELETE FROM meeting_reminders WHERE meeting_id=?", (meeting_id,))
                db.execute("UPDATE meetings SET created_at=? WHERE id=?", (now, meeting_id))
            return meeting_id

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
        """Reserva como máximo el aviso vigente. Descarta umbrales anteriores."""
        with self.db() as db:
            m = db.execute("SELECT * FROM meetings WHERE id=? AND status='scheduled'", (meeting_id,)).fetchone()
            if not m:
                return None
            due = [s for s in THRESHOLDS if m["starts_at"] - s <= now]
            eligible = [s for s in due if m["starts_at"] - s > m["created_at"]]
            chosen = min(eligible) if eligible and now < m["starts_at"] else None
            for seconds in due:
                state = "claimed" if seconds == chosen else "skipped"
                cur = db.execute("INSERT OR IGNORE INTO meeting_reminders VALUES (?,?,?,?)", (meeting_id, seconds, state, now))
                if seconds == chosen and cur.rowcount == 0:
                    chosen = None
            return chosen

    def reminder_result(self, meeting_id, seconds, state):
        with self.db() as db:
            db.execute("UPDATE meeting_reminders SET state=?,updated_at=? WHERE meeting_id=? AND seconds=?", (state, int(datetime.now(timezone.utc).timestamp()), meeting_id, seconds))


def escaped(text):
    return discord.utils.escape_markdown(str(text)).replace("@", "@\u200b")


class MeetingSystem:
    def __init__(self, bot, path):
        self.bot = bot
        self.store = MeetingStore(path)
        self.lock = asyncio.Lock()
        self.task = None
        self.group = app_commands.Group(name="reunion", description="Reuniones oficiales de LA VENGANZA RP", guild_only=True)
        self.register_commands()

    async def call(self, method, *args, **kwargs):
        return await asyncio.to_thread(getattr(self.store, method), *args, **kwargs)

    async def start(self):
        await self.call("initialize")
        self.bot.add_view(MeetingButtons(self))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.reminders(), name="meeting-reminders")

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
        embed.add_field(name="📍 Lugar o canal de voz", value=escaped(meeting["location"]), inline=False)
        embed.add_field(name="📋 Agenda", value=escaped(meeting["agenda"]), inline=False)
        embed.add_field(name="Confirmaciones", value=" · ".join(f"{LABELS[k]}: **{counts[k]}**" for k in LABELS), inline=False)
        embed.add_field(name="Estado", value=f"{status}\n👥 Asistencia real registrada: {sum(r['present'] for r in attendance)}", inline=False)
        embed.set_footer(text=f"LA VENGANZA RP | Reunión #{meeting['id']}")
        return embed

    async def refresh(self, meeting_id):
        meeting = await self.call("get", meeting_id)
        channel = self.bot.get_channel(meeting["channel_id"]) or await self.bot.fetch_channel(meeting["channel_id"])
        message = await channel.fetch_message(meeting["message_id"])
        await message.edit(embed=await self.embed(meeting), view=MeetingButtons(self, disabled=meeting["status"] != "scheduled"))

    async def refresh_notice(self, meeting_id):
        try:
            await self.refresh(meeting_id)
            return ""
        except discord.HTTPException:
            log.exception("Registro guardado; no se pudo actualizar reunión #%s", meeting_id)
            return "\n⚠️ Registro guardado. No se pudo actualizar el anuncio; revisa los permisos del bot."

    def register_commands(self):
        @self.group.command(name="crear", description="Abre el formulario de una reunión oficial")
        @app_commands.choices(tipo=[app_commands.Choice(name="🔒 Staff", value="staff"), app_commands.Choice(name="🌎 General", value="general")])
        async def create(interaction: discord.Interaction, tipo: app_commands.Choice[str]):
            await self.channel_access(interaction, CHANNELS[tipo.value], admin=True)
            await interaction.response.send_modal(MeetingModal(self, tipo.value))

        @self.group.command(name="editar", description="Edita una reunión sin perder sus confirmaciones")
        async def edit(interaction: discord.Interaction, reunion_id: int):
            meeting = await self.authorized_meeting(interaction, reunion_id)
            if meeting["status"] != "scheduled":
                raise ValueError("La reunión ya no está activa.")
            await interaction.response.send_modal(MeetingModal(self, meeting["kind"], meeting))

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

        @self.group.command(name="asistencia", description="Consulta confirmaciones y asistencia real completa")
        async def attendance(interaction: discord.Interaction, reunion_id: int):
            await interaction.response.defer(ephemeral=True)
            await self.authorized_meeting(interaction, reunion_id)
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
            await self.authorized_meeting(interaction, meeting_id)
            await self.call("finish", meeting_id, status, interaction.user.id)
            notice = await self.refresh_notice(meeting_id)
        await interaction.followup.send(("🔒 Reunión cancelada." if status == "cancelled" else "✅ Reunión finalizada.") + " Registros conservados." + notice, ephemeral=True)

    async def reminders(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for meeting in await self.call("active"):
                    try:
                        async with self.lock:
                            seconds = await self.call("claim_reminder", meeting["id"], int(datetime.now(timezone.utc).timestamp()))
                            if seconds is None:
                                continue
                            # Se vuelve a leer para usar la fecha actual tras una edición.
                            current = await self.call("get", meeting["id"])
                            channel = self.bot.get_channel(current["channel_id"]) or await self.bot.fetch_channel(current["channel_id"])
                            label = {86400: "24 horas", 3600: "1 hora", 900: "15 minutos"}[seconds]
                            try:
                                await channel.send(f"🔔 **Recordatorio de {label} | LA VENGANZA RP**\n{escaped(current['title'])}\n📅 <t:{current['starts_at']}:F>\nhttps://discord.com/channels/{GUILD_ID}/{current['channel_id']}/{current['message_id']}", allowed_mentions=discord.AllowedMentions.none())
                            except Exception:
                                await self.call("reminder_result", current["id"], seconds, "failed")
                                raise
                            await self.call("reminder_result", current["id"], seconds, "sent")
                    except Exception:
                        log.exception("Error en recordatorio de reunión #%s", meeting["id"])
            except Exception:
                log.exception("Error revisando recordatorios")
            await asyncio.sleep(30)


class MeetingModal(discord.ui.Modal, title="Reunión | LA VENGANZA RP"):
    name = discord.ui.TextInput(label="Nombre", max_length=90)
    when = discord.ui.TextInput(label="Fecha y hora PR: AAAA-MM-DD HH:MM", max_length=16)
    location = discord.ui.TextInput(label="Lugar o canal de voz", max_length=200)
    agenda = discord.ui.TextInput(label="Agenda", style=discord.TextStyle.paragraph, max_length=500)
    description = discord.ui.TextInput(label="Descripción", style=discord.TextStyle.paragraph, max_length=1200)

    def __init__(self, system, kind, meeting=None):
        super().__init__(timeout=900)
        self.system, self.kind, self.meeting = system, kind, meeting
        if meeting:
            self.name.default = meeting["title"]
            self.when.default = datetime.fromtimestamp(meeting["starts_at"], PR).strftime("%Y-%m-%d %H:%M")
            for key in ("location", "agenda", "description"):
                getattr(self, key).default = meeting[key]

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        system = self.system
        channel = await system.channel_access(interaction, CHANNELS[self.kind], admin=True)
        try:
            date = datetime.strptime(self.when.value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=PR)
        except ValueError:
            raise ValueError("Usa AAAA-MM-DD HH:MM, hora de Puerto Rico en formato de 24 horas.")
        if date <= datetime.now(PR):
            raise ValueError("Selecciona una fecha futura.")
        values = (self.name.value.strip(), int(date.timestamp()), self.location.value.strip(), self.agenda.value.strip(), self.description.value.strip())
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
                notice = ""
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
