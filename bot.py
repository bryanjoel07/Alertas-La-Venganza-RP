import asyncio
import io
import logging
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord import app_commands

# LA VENGANZA RP — ALERTAS + MANTENIMIENTO + EVENTOS
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("LaVenganzaRP")
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
GUILD_ID = 1244988345327550565
CONNECT_CHANNEL_ID = 1513421828415164546
PANEL_MESSAGE_ID = 1536621817471696907
ALERT_CHANNEL_ID = 1567618111920807987
EVENT_CHANNEL_ID = 1545468565120098364
CONNECT_URL = "https://cfx.re/join/57vjg7"
GUILD = discord.Object(id=GUILD_ID)
PR_TZ = ZoneInfo("America/Puerto_Rico")
CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90
DATA_DIR = os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "/tmp"
DB_PATH = os.path.join(DATA_DIR, "lavenganza.sqlite3")
DRAFT_SECONDS = 1800
DRAFTS = {}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def epoch(iso):
    return int(datetime.fromisoformat(iso).timestamp())


def duration(start, end):
    seconds = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"


@contextmanager
def database():
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outages(id INTEGER PRIMARY KEY AUTOINCREMENT,started TEXT NOT NULL,ended TEXT,duration_seconds INTEGER);
        CREATE TABLE IF NOT EXISTS maintenance(id INTEGER PRIMARY KEY AUTOINCREMENT,started TEXT NOT NULL,ended TEXT,reason TEXT NOT NULL,author_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER UNIQUE,
            channel_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            capacity INTEGER NOT NULL,
            prizes TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_by TEXT NOT NULL,
            image_url TEXT,
            winner1 TEXT,winner2 TEXT,winner3 TEXT
        );
        CREATE TABLE IF NOT EXISTS registrations(
            event_id INTEGER NOT NULL,user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,PRIMARY KEY(event_id,user_id)
        );
        """)


def get_setting(key, default=""):
    with database() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with database() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))


def record_outage(state):
    moment = now_iso()
    with database() as db:
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("last_state", state))
        if state == "down":
            existing = db.execute("SELECT id FROM outages WHERE ended IS NULL LIMIT 1").fetchone()
            if not existing:
                db.execute("INSERT INTO outages(started) VALUES (?)", (moment,))
        elif state == "up":
            row = db.execute("SELECT id,started FROM outages WHERE ended IS NULL ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                total = max(0, int((datetime.fromisoformat(moment) - datetime.fromisoformat(row["started"])).total_seconds()))
                db.execute("UPDATE outages SET ended=?,duration_seconds=? WHERE id=?", (moment, total, row["id"]))


def clean(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    for marker in ("```", "`", "**", "__"):
        text = text.replace(marker, "")
    return text.strip().lower()


def parse_status(value):
    text = clean(value)
    if re.search(r"\b(partial|parcial|degraded)\b", text):
        return "partial"
    if re.search(r"\b(offline|down|cerrado|ca[ií]do)\b", text):
        return "down"
    if re.search(r"\b(online|up|abierto|operativo)\b", text):
        return "up"
    return None


def detect_status(message):
    for embed in message.embeds:
        for field in embed.fields:
            if re.search(r"\b(status|estado)\b", clean(field.name)):
                return parse_status(field.value)
    return None


class StateTracker:
    def __init__(self, initial=None):
        self.last = initial
        self.pending = None
        self.since = None

    def reset(self):
        self.pending = None
        self.since = None

    def observe(self, state, clock):
        if state not in ("up", "down"):
            self.reset()
            return None
        if self.last is None:
            self.last = state
            return "initial"
        if state == self.last:
            self.reset()
            return None
        if self.pending != state:
            self.pending = state
            self.since = clock
            return None
        if clock - self.since >= CONFIRM_SECONDS:
            return state
        return None

    def confirmed(self, state):
        self.last = state
        self.reset()


intents = discord.Intents.default()
intents.message_content = True


class LaVenganzaBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)
        self.lock = asyncio.Lock()
        self.tracker = None
        self.monitor_task = None

    async def setup_hook(self):
        init_db()
        state = get_setting("last_state")
        self.tracker = StateTracker(state if state in ("up", "down") else None)
        self.add_view(EventButtons())
        commands = await self.tree.sync(guild=GUILD)
        log.info("Comandos sincronizados: %s", ", ".join(c.name for c in commands))
        self.monitor_task = asyncio.create_task(monitor_server())


client = LaVenganzaBot()


async def post_webhook(embed):
    payload = {"username": "La Venganza RP | Alertas", "allowed_mentions": {"parse": []}, "embeds": [embed.to_dict()]}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.post(WEBHOOK_URL, json=payload) as response:
            if response.status not in (200, 204):
                raise RuntimeError(f"Webhook HTTP {response.status}: {(await response.text())[:120]}")


def make_alert(state, test=False):
    if state == "down":
        title = "🚨 SERVER DOWN | LA VENGANZA RP"
        body = "🔴 **La ciudad está fuera de servicio.**\n\n🛠️ Estamos verificando la situación.\n\n📢 Avisaremos cuando vuelva a funcionar."
        color = 0xFF0000
    else:
        title = "🟢 SERVER RESTORED | LA VENGANZA RP"
        body = f"✅ **¡La ciudad está disponible nuevamente!**\n\n🎮 {CONNECT_URL}"
        color = 0x22C55E
    if test:
        title = "🧪 PRUEBA | " + title
        body = "⚠️ **SIMULACIÓN. NO ES UN ESTADO REAL.**\n\n" + body
    embed = discord.Embed(title=title, description=body, color=color)
    embed.set_footer(text="La Venganza RP | Sistema de Alertas")
    return embed


async def send_alert(state, test=False):
    await post_webhook(make_alert(state, test))
    log.info("Alerta enviada: %s | prueba=%s", state, test)


async def fetch_panel_state():
    channel = await client.fetch_channel(CONNECT_CHANNEL_ID)
    message = await channel.fetch_message(PANEL_MESSAGE_ID)
    return detect_status(message)


async def monitor_server():
    await client.wait_until_ready()
    last_observed = object()
    log.info("Monitor de Connect iniciado")
    while not client.is_closed():
        try:
            state = await fetch_panel_state()
            if state != last_observed:
                log.info("Estado observado: %s", state)
                last_observed = state
            async with client.lock:
                if get_setting("maintenance_active", "0") == "1":
                    client.tracker.reset()
                else:
                    event = client.tracker.observe(state, time.monotonic())
                    if event == "initial":
                        set_setting("last_state", client.tracker.last)
                    elif event in ("up", "down"):
                        await send_alert(event)
                        record_outage(event)
                        client.tracker.confirmed(event)
        except Exception:
            log.exception("Error monitoreando Connect")
        await asyncio.sleep(CHECK_INTERVAL)


async def only_admin(interaction):
    if not interaction.guild or interaction.guild.id != GUILD_ID:
        raise app_commands.CheckFailure("Servidor no autorizado")
    if not interaction.user.guild_permissions.administrator:
        raise app_commands.MissingPermissions(["administrator"])
    return True


# ==========================================
# EVENTOS — CONSULTAS
# ==========================================

def fetch_event(event_id):
    with database() as db:
        return db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()


def event_from_message(message_id):
    with database() as db:
        return db.execute("SELECT * FROM events WHERE message_id=?", (message_id,)).fetchone()


def registered_count(event_id):
    with database() as db:
        return db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (event_id,)).fetchone()[0]


def registered_users(event_id, limit=None):
    query = "SELECT user_id FROM registrations WHERE event_id=? ORDER BY joined_at"
    params = [event_id]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with database() as db:
        return db.execute(query, params).fetchall()


def safe(text):
    return discord.utils.escape_markdown(str(text)).replace("@", "@\u200b")


def prize_text(first, second, third):
    return f"🥇 {safe(first)}\n🥈 {safe(second)}\n🥉 {safe(third)}"


def event_embed(event, count, image_url=None):
    statuses = {"open": "🟢 Inscripciones abiertas", "closed": "🔒 Inscripciones cerradas", "finished": "🏆 Finalizado"}
    embed = discord.Embed(
        title=f"🏎️ {safe(event['title'])} | LA VENGANZA RP",
        description=safe(event["description"]), color=0xD60000
    )
    # Hora oficial fija de Puerto Rico; Discord adapta el timestamp al espectador.
    event_pr = datetime.fromisoformat(event["starts_at"]).astimezone(PR_TZ)
    weekdays = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    months = ("enero", "febrero", "marzo", "abril", "mayo", "junio",
              "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    date_pr = (
        f"{weekdays[event_pr.weekday()].capitalize()}, {event_pr.day} de "
        f"{months[event_pr.month - 1]} de {event_pr.year}"
    )
    hour_pr = event_pr.strftime("%I:%M %p").lstrip("0")
    embed.add_field(
        name="📅 Fecha y hora",
        value=(
            f"📅 {date_pr}\n"
            f"⏰ **{hour_pr} — Hora de Puerto Rico 🇵🇷**\n"
            f"🌎 Tu hora local: <t:{epoch(event['starts_at'])}:t>"
        ),
        inline=False
    )
    embed.add_field(name="📍 Lugar", value=safe(event["location"]), inline=True)
    embed.add_field(name="📋 Estado", value=statuses.get(event["status"], "Desconocido"), inline=False)
    embed.add_field(name="🏆 PREMIOS", value=event["prizes"], inline=False)
    if event["status"] == "finished":
        embed.add_field(name="🏅 Ganadores", value="\\n".join(f"{medal} <@{event[key]}>" for medal, key in (("🥇", "winner1"), ("🥈", "winner2"), ("🥉", "winner3"))), inline=False)
    image = image_url or event["image_url"]
    if image:
        embed.set_image(url=image)
    embed.set_footer(text=f"La Venganza RP | Evento #{event['id']}")
    return embed


async def refresh_event(event_id, message=None):
    event = fetch_event(event_id)
    if not event or not event["message_id"]:
        return
    if message is None:
        channel = await client.fetch_channel(event["channel_id"])
        message = await channel.fetch_message(event["message_id"])

    # Al editar un embed con un archivo adjunto, Discord puede invalidar la
    # referencia anterior. Volvemos a adjuntar los bytes en la misma edición.
    # Si falla la descarga, NO editamos el anuncio: así no perdemos el banner.
    if message.attachments:
        attachment = message.attachments[0]
        banner_bytes = await attachment.read(use_cached=True)
        filename = attachment.filename
        embed = event_embed(
            event, registered_count(event_id), f"attachment://{filename}"
        )
        updated = await message.edit(
            embed=embed,
            view=EventButtons(),
            attachments=[discord.File(io.BytesIO(banner_bytes), filename=filename)]
        )
        if updated.attachments:
            with database() as db:
                db.execute(
                    "UPDATE events SET image_url=? WHERE id=?",
                    (updated.attachments[0].url, event_id)
                )
    else:
        # No hay archivo en el anuncio. Evitamos usar una URL caducada.
        image_url = event["image_url"]
        if image_url and image_url.startswith("attachment://"):
            image_url = None
        await message.edit(
            embed=event_embed(event, registered_count(event_id), image_url),
            view=EventButtons()
        )


# ==========================================
# BOTONES DE INSCRIPCION PERSISTENTES
# ==========================================

class EventButtons(discord.ui.View):
    def __init__(self, count=None, capacity=None):
        super().__init__(timeout=None)
        # Every component needs a custom_id for persistent views, even disabled buttons.
        if count is not None and capacity is not None:
            self.counter.label = f"Inscritos: {count}/{capacity}"
        else:
            self.counter.label = "Inscritos"

    @discord.ui.button(label="Inscritos", emoji="👥", style=discord.ButtonStyle.secondary, disabled=True, row=1, custom_id="lvrp:event:counter")
    async def counter(self, interaction, button):
        pass

    @discord.ui.button(label="Inscribirme", emoji="✅", style=discord.ButtonStyle.success, custom_id="lvrp:event:join")
    async def join(self, interaction, button):
        await self.registration(interaction, True)

    @discord.ui.button(label="Cancelar", emoji="❌", style=discord.ButtonStyle.secondary, custom_id="lvrp:event:leave")
    async def leave(self, interaction, button):
        await self.registration(interaction, False)

    @discord.ui.button(label="Participantes", emoji="📋", style=discord.ButtonStyle.primary, custom_id="lvrp:event:list")
    async def participants(self, interaction, button):
        event = event_from_message(interaction.message.id)
        if not event:
            await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
            return
        rows = registered_users(event["id"], 30)
        total = registered_count(event["id"])
        lines = "\n".join(f"{i}. <@{row['user_id']}>" for i, row in enumerate(rows, 1)) or "Todavía no hay inscritos."
        if total > 30:
            lines += f"\n... y {total - 30} más."
        await interaction.response.send_message(
            f"📋 **{safe(event['title'])}**\n👥 {total}/{event['capacity']}\n\n{lines}",
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    async def registration(self, interaction, joining):
        if interaction.guild_id != GUILD_ID:
            await interaction.response.send_message("❌ Servidor incorrecto.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with client.lock:
            event = event_from_message(interaction.message.id)
            if not event:
                answer = "❌ Evento no encontrado."
            elif event["status"] != "open":
                answer = "🔒 Inscripciones cerradas."
            else:
                changed = False
                with database() as db:
                    exists = db.execute("SELECT 1 FROM registrations WHERE event_id=? AND user_id=?", (event["id"], interaction.user.id)).fetchone()
                    total = db.execute("SELECT COUNT(*) FROM registrations WHERE event_id=?", (event["id"],)).fetchone()[0]
                    if joining and exists:
                        answer = "✅ Ya estás inscrito."
                    elif not joining and not exists:
                        answer = "ℹ️ No estabas inscrito."
                    elif joining and total >= event["capacity"]:
                        answer = "⛔ Cupos agotados."
                    elif joining:
                        db.execute("INSERT INTO registrations VALUES (?,?,?)", (event["id"], interaction.user.id, now_iso()))
                        answer, changed = "✅ ¡Inscripción completada!", True
                    else:
                        db.execute("DELETE FROM registrations WHERE event_id=? AND user_id=?", (event["id"], interaction.user.id))
                        answer, changed = "✅ Inscripción cancelada.", True
                count_now = registered_count(event["id"])
                if changed:
                    # Only change message components. Do not modify embed or attachments.
                    try:
                        await interaction.message.edit(
                            view=EventButtons(count_now, event["capacity"]),
                            content=None
                        )
                    except Exception:
                        log.exception("Error actualizando botón de inscritos")
                        answer += "\n⚠️ La inscripción quedó guardada; consulta Participantes para el total."
                answer += f"\n👥 Inscritos actualmente: **{count_now}/{event['capacity']}**"
        await interaction.followup.send(answer, ephemeral=True)


# ==========================================
# FORMULARIO DE EVENTOS EN DOS PASOS
# ==========================================

def valid_datetime(date_text, hour_text):
    try:
        local = datetime.strptime(f"{date_text.strip()} {hour_text.strip()}", "%Y-%m-%d %H:%M").replace(tzinfo=PR_TZ)
    except ValueError:
        raise ValueError("Usa fecha AAAA-MM-DD y hora 24 h HH:MM (ej.: 2026-11-06 y 23:00).")
    if local <= datetime.now(PR_TZ):
        raise ValueError("La fecha del evento debe estar en el futuro.")
    return local.astimezone(timezone.utc).isoformat()


def purge_drafts():
    current = time.monotonic()
    for owner in list(DRAFTS):
        if current - DRAFTS[owner]["created"] > DRAFT_SECONDS:
            DRAFTS.pop(owner, None)


class DetailsModal(discord.ui.Modal, title="Evento - Datos principales"):
    name = discord.ui.TextInput(label="Nombre", placeholder="CAR SHOW", max_length=90)
    date = discord.ui.TextInput(label="Fecha AAAA-MM-DD", placeholder="2026-11-06", max_length=10)
    hour = discord.ui.TextInput(label="Hora de Puerto Rico (24 h)", placeholder="23:00", max_length=5)
    location = discord.ui.TextInput(label="Lugar", placeholder="Pista de Salinas | Sandy Shores", max_length=200)
    description = discord.ui.TextInput(label="Descripcion completa", style=discord.TextStyle.paragraph, max_length=1800)

    def __init__(self, banner=None):
        super().__init__()
        self.banner = banner

    async def on_submit(self, interaction):
        try:
            starts_at = valid_datetime(self.date.value, self.hour.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        if self.banner:
            if not (self.banner.content_type or "").startswith("image/") or self.banner.size > 8 * 1024 * 1024:
                await interaction.response.send_message("❌ Banner inválido o superior a 8 MB.", ephemeral=True)
                return
        await interaction.response.defer(ephemeral=True, thinking=True)
        banner_data = None
        if self.banner:
            try:
                extension = self.banner.filename.rsplit(".", 1)[-1].lower() if "." in self.banner.filename else "png"
                if extension not in ("png", "jpg", "jpeg", "webp", "gif"):
                    raise ValueError("Formato no permitido")
                banner_data = (await self.banner.read(), f"evento.{extension}")
            except Exception:
                log.exception("Error leyendo banner")
                await interaction.followup.send("❌ No se pudo leer el banner. Intenta subir otro.", ephemeral=True)
                return
        purge_drafts()
        DRAFTS[interaction.user.id] = {
            "created": time.monotonic(), "title": self.name.value.strip(),
            "description": self.description.value.strip(), "location": self.location.value.strip(),
            "starts_at": starts_at, "banner": banner_data,
        }
        await interaction.followup.send(
            "✅ **Paso 1 completado.** Pulsa **Premios y cupos** para continuar.",
            view=ContinueView(interaction.user.id), ephemeral=True
        )


class ContinueView(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=900)
        self.owner = owner

    @discord.ui.button(label="Premios y cupos", emoji="🏆", style=discord.ButtonStyle.primary)
    async def next(self, interaction, button):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("❌ Este formulario no es tuyo.", ephemeral=True)
            return
        if self.owner not in DRAFTS:
            await interaction.response.send_message("❌ Borrador caducado. Ejecuta /evento crear.", ephemeral=True)
            return
        await interaction.response.send_modal(PrizesModal(self.owner))


class PrizesModal(discord.ui.Modal, title="Evento - Premios y participantes"):
    capacity = discord.ui.TextInput(label="Cupos disponibles", placeholder="30", max_length=3)
    first = discord.ui.TextInput(label="Primer lugar", placeholder="$250,000 o Proximamente", max_length=200)
    second = discord.ui.TextInput(label="Segundo lugar", placeholder="$100,000 o Proximamente", max_length=200)
    third = discord.ui.TextInput(label="Tercer lugar", placeholder="$50,000 o Proximamente", max_length=200)

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction):
        draft = DRAFTS.get(self.owner)
        if not draft:
            await interaction.response.send_message("❌ El borrador expiró.", ephemeral=True)
            return
        try:
            capacity = int(self.capacity.value.strip())
            if capacity < 1 or capacity > 500:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ Cupos: un número entre 1 y 500.", ephemeral=True)
            return
        draft["capacity"] = capacity
        draft["prizes"] = prize_text(self.first.value, self.second.value, self.third.value)
        draft["created"] = time.monotonic()
        virtual = {
            "id": "PREVIA", "title": draft["title"], "description": draft["description"],
            "location": draft["location"], "starts_at": draft["starts_at"],
            "capacity": capacity, "prizes": draft["prizes"], "status": "open", "image_url": None,
        }
        embed = event_embed(virtual, 0)
        options = {"embed": embed, "view": PublishView(self.owner), "ephemeral": True}
        if draft.get("banner"):
            data, filename = draft["banner"]
            options["file"] = discord.File(io.BytesIO(data), filename=filename)
            embed.set_image(url=f"attachment://{filename}")
        await interaction.response.send_message(**options)


class PublishView(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=900)
        self.owner = owner

    @discord.ui.button(label="Publicar evento", emoji="📢", style=discord.ButtonStyle.success)
    async def publish(self, interaction, button):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("❌ Esta vista previa no es tuya.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with client.lock:
            draft = DRAFTS.get(self.owner)
            if not draft or "capacity" not in draft:
                await interaction.followup.send("❌ Borrador caducado. Crea el evento otra vez.", ephemeral=True)
                return
            if draft.get("publishing"):
                await interaction.followup.send("⚠️ Ya se está publicando este evento.", ephemeral=True)
                return
            draft["publishing"] = True
            try:
                channel = await client.fetch_channel(EVENT_CHANNEL_ID)
                with database() as db:
                    cursor = db.execute(
                        "INSERT INTO events(channel_id,title,description,location,starts_at,capacity,prizes,status,created_by) "
                        "VALUES (?,?,?,?,?,?,?,'open',?)",
                        (EVENT_CHANNEL_ID, draft["title"], draft["description"], draft["location"],
                         draft["starts_at"], draft["capacity"], draft["prizes"], str(self.owner))
                    )
                    event_id = cursor.lastrowid
                event = fetch_event(event_id)
                embed = event_embed(event, 0)
                kwargs = {"embed": embed, "view": EventButtons(0, event["capacity"]), "allowed_mentions": discord.AllowedMentions.none()}
                if draft.get("banner"):
                    data, filename = draft["banner"]
                    kwargs["file"] = discord.File(io.BytesIO(data), filename=filename)
                    embed.set_image(url=f"attachment://{filename}")
                try:
                    message = await channel.send(**kwargs)
                except Exception:
                    with database() as db:
                        db.execute("DELETE FROM events WHERE id=? AND message_id IS NULL", (event_id,))
                    raise
                image_ref = message.attachments[0].url if message.attachments else None
                with database() as db:
                    db.execute("UPDATE events SET message_id=?,image_url=? WHERE id=?", (message.id, image_ref, event_id))
                DRAFTS.pop(self.owner, None)
                await interaction.followup.send(f"✅ Evento **#{event_id}** publicado: {message.jump_url}", ephemeral=True)
            except Exception as error:
                draft["publishing"] = False
                log.exception("Error publicando evento")
                await interaction.followup.send(f"❌ No se pudo publicar: {type(error).__name__}. Revisa los logs de Railway.", ephemeral=True)

    @discord.ui.button(label="Cancelar borrador", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        if interaction.user.id != self.owner:
            await interaction.response.send_message("❌ Esta vista previa no es tuya.", ephemeral=True)
            return
        DRAFTS.pop(self.owner, None)
        await interaction.response.edit_message(content="🗑️ Borrador cancelado.", embed=None, attachments=[], view=None)


# ==========================================
# GRUPO /EVENTO
# ==========================================

event_group = app_commands.Group(name="evento", description="Eventos de La Venganza RP")


@event_group.command(name="crear", description="Crear evento: fecha/hora PR, lugar, descripción, premios, cupos y banner")
@app_commands.describe(imagen="Opcional: selecciona una imagen de tu galería (máximo 8 MB)")
@app_commands.check(only_admin)
async def evento_crear(interaction: discord.Interaction, imagen: discord.Attachment = None):
    await interaction.response.send_modal(DetailsModal(imagen))


# CAMBIO SOLICITADO: /evento cerrar ELIMINA EL MENSAJE COMPLETO.
# Conserva el registro y las inscripciones para consulta administrativa.
@event_group.command(name="cerrar", description="Borra el anuncio, banner y botones; conserva los registros")
@app_commands.describe(evento_id="ID del evento que deseas borrar por completo, por ejemplo 1")
@app_commands.check(only_admin)
async def evento_cerrar(interaction: discord.Interaction, evento_id: int):
    await interaction.response.defer(ephemeral=True, thinking=True)
    async with client.lock:
        event = fetch_event(evento_id)
        if not event:
            answer = "❌ Evento no encontrado."
        elif event["status"] == "closed":
            answer = f"ℹ️ El evento #{evento_id} ya está cerrado."
        else:
            try:
                if event["message_id"]:
                    channel = await client.fetch_channel(event["channel_id"])
                    try:
                        message = await channel.fetch_message(event["message_id"])
                        await message.delete()
                    except discord.NotFound:
                        log.warning("Mensaje del evento #%s ya no existe; se cierra el registro.", evento_id)
                with database() as db:
                    db.execute("UPDATE events SET status='closed' WHERE id=?", (evento_id,))
                answer = (
                    f"🗑️ **Evento #{evento_id} cerrado.**\n"
                    "✅ Anuncio, banner y botones eliminados del canal.\n"
                    "🔒 Inscripciones cerradas.\n"
                    "💾 Registro e inscripciones conservados."
                )
                log.info("Evento #%s eliminado del canal por administrador %s", evento_id, interaction.user.id)
            except discord.Forbidden:
                log.exception("Sin permisos para eliminar evento #%s", evento_id)
                answer = "❌ Discord denegó el acceso. Verifica Ver canal, Leer historial y permisos del bot."
            except discord.HTTPException:
                log.exception("Error HTTP eliminando evento #%s", evento_id)
                answer = "❌ Discord no permitió eliminar el anuncio. Revisa Railway."
            except Exception:
                log.exception("Error cerrando evento #%s", evento_id)
                answer = "❌ Ocurrió un error al cerrar el evento. Revisa Railway."
    await interaction.followup.send(answer, ephemeral=True)


@event_group.command(name="finalizar", description="Finaliza el evento y publica un podio mencionando a los 3 ganadores")
@app_commands.describe(
    evento_id="Número del evento, por ejemplo 1 (aparece al final del anuncio)",
    primero="Selecciona el usuario de Discord para el primer lugar",
    segundo="Selecciona el usuario de Discord para el segundo lugar",
    tercero="Selecciona el usuario de Discord para el tercer lugar"
)
@app_commands.check(only_admin)
async def evento_finalizar(
    interaction: discord.Interaction,
    evento_id: int,
    primero: discord.Member,
    segundo: discord.Member,
    tercero: discord.Member
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    winners = [primero, segundo, tercero]
    if len({winner.id for winner in winners}) != 3:
        await interaction.followup.send("❌ Debes elegir tres jugadores diferentes.", ephemeral=True)
        return

    async with client.lock:
        event = fetch_event(evento_id)
        if not event:
            answer = "❌ Evento no encontrado."
        elif event["status"] == "finished":
            answer = "ℹ️ Este evento ya fue finalizado."
        elif event["status"] == "closed":
            answer = "❌ Este evento fue cerrado y su anuncio eliminado."
        else:
            try:
                channel = await client.fetch_channel(event["channel_id"])
                podio = discord.Embed(
                    title="🏆 PODIO OFICIAL | LA VENGANZA RP",
                    description=(
                        f"🏎️ **{safe(event['title'])}**\n"
                        f"🎉 ¡Felicidades a los ganadores del evento #{evento_id}!"
                    ),
                    color=0xD60000,
                    timestamp=datetime.now(timezone.utc)
                )
                for position, emoji, member in zip(
                    ("PRIMER LUGAR", "SEGUNDO LUGAR", "TERCER LUGAR"),
                    ("🥇", "🥈", "🥉"),
                    winners
                ):
                    podio.add_field(
                        name=f"{emoji} {position}",
                        value=f"{member.mention}\n**{safe(member.display_name)}**",
                        inline=False
                    )
                podio.set_footer(text=f"La Venganza RP | Resultados del evento #{evento_id}")
                await channel.send(
                    embed=podio,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False, roles=False, users=True
                    )
                )
                with database() as db:
                    db.execute(
                        "UPDATE events SET status='finished', winner1=?, winner2=?, winner3=? WHERE id=?",
                        (str(winners[0].id), str(winners[1].id), str(winners[2].id), evento_id)
                    )
                # Deshabilitar las inscripciones sin editar embed ni banner.
                if event["message_id"]:
                    try:
                        original = await channel.fetch_message(event["message_id"])
                        finished_view = EventButtons(
                            registered_count(evento_id), event["capacity"]
                        )
                        for item in finished_view.children:
                            if isinstance(item, discord.ui.Button):
                                item.disabled = True
                        await original.edit(view=finished_view)
                    except (discord.HTTPException, discord.NotFound):
                        log.exception("No se pudieron desactivar los botones del evento #%s", evento_id)
                answer = (
                    f"🏆 Evento #{evento_id} finalizado. "
                    "Podio publicado con las menciones y nombres de Discord. "
                    "Las inscripciones quedaron cerradas."
                )
            except discord.Forbidden:
                log.exception("Sin permisos para publicar ganadores del evento #%s", evento_id)
                answer = "❌ No tengo permiso para publicar el podio en el canal de eventos."
            except discord.HTTPException:
                log.exception("Error publicando podio del evento #%s", evento_id)
                answer = "❌ Discord rechazó la publicación del podio. Revisa Railway."
            except Exception:
                log.exception("Error finalizando evento #%s", evento_id)
                answer = "❌ No se pudo finalizar el evento. Revisa Railway."
    await interaction.followup.send(answer, ephemeral=True)


@event_group.command(name="participantes", description="Muestra la lista de jugadores inscritos en el evento indicado")
@app_commands.describe(evento_id="ID del evento para consultar los jugadores inscritos")
@app_commands.check(only_admin)
async def evento_participantes(interaction: discord.Interaction, evento_id: int):
    event = fetch_event(evento_id)
    if not event:
        await interaction.response.send_message("❌ Evento no encontrado.", ephemeral=True)
        return
    rows = registered_users(evento_id)
    lines = [f"{i}. <@{row['user_id']}>" for i, row in enumerate(rows, 1)]
    text = f"📋 **{safe(event['title'])}**\n👥 {len(rows)} inscritos\n\n" + ("\n".join(lines) or "No hay inscritos.")
    if len(text) > 1900:
        text = text[:1850] + "\n... Lista truncada."
    await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


# ==========================================
# EDITAR EVENTO CON FORMULARIO
# ==========================================

class EditEventModal(discord.ui.Modal, title="Editar evento"):
    name = discord.ui.TextInput(label="Nombre", max_length=90)
    date = discord.ui.TextInput(label="Fecha AAAA-MM-DD", max_length=10)
    hour = discord.ui.TextInput(label="Hora Puerto Rico HH:MM", max_length=5)
    location = discord.ui.TextInput(label="Lugar", max_length=200)
    description = discord.ui.TextInput(label="Descripcion", style=discord.TextStyle.paragraph, max_length=1800)

    def __init__(self, event):
        super().__init__()
        self.event_id = event["id"]
        when = datetime.fromisoformat(event["starts_at"]).astimezone(PR_TZ)
        self.name.default = event["title"]
        self.date.default = when.strftime("%Y-%m-%d")
        self.hour.default = when.strftime("%H:%M")
        self.location.default = event["location"]
        self.description.default = event["description"]

    async def on_submit(self, interaction):
        try:
            when = valid_datetime(self.date.value, self.hour.value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with client.lock:
            event = fetch_event(self.event_id)
            if not event or event["status"] == "finished":
                await interaction.followup.send("❌ Evento inexistente o finalizado.", ephemeral=True)
                return
            with database() as db:
                db.execute("UPDATE events SET title=?,description=?,location=?,starts_at=? WHERE id=?",
                           (self.name.value.strip(), self.description.value.strip(), self.location.value.strip(), when, self.event_id))
            await refresh_event(self.event_id)
        await interaction.followup.send("✅ Evento actualizado sin perder inscripciones.", ephemeral=True)


@event_group.command(name="editar", description="Edita fecha, hora, lugar, título y descripción del evento")
@app_commands.describe(evento_id="ID del evento que deseas editar sin perder inscritos")
@app_commands.check(only_admin)
async def evento_editar(interaction: discord.Interaction, evento_id: int):
    event = fetch_event(evento_id)
    if not event or event["status"] == "finished":
        await interaction.response.send_message("❌ Evento no encontrado o finalizado.", ephemeral=True)
        return
    await interaction.response.send_modal(EditEventModal(event))


class EditPrizesModal(discord.ui.Modal, title="Editar premios y cupos"):
    capacity = discord.ui.TextInput(label="Cupos", max_length=3)
    first = discord.ui.TextInput(label="Primer lugar", max_length=200)
    second = discord.ui.TextInput(label="Segundo lugar", max_length=200)
    third = discord.ui.TextInput(label="Tercer lugar", max_length=200)

    def __init__(self, event):
        super().__init__()
        self.event_id = event["id"]
        self.capacity.default = str(event["capacity"])

    async def on_submit(self, interaction):
        try:
            capacity = int(self.capacity.value)
            if capacity not in range(1, 501):
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ Cupos entre 1 y 500.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with client.lock:
            event = fetch_event(self.event_id)
            if not event or event["status"] == "finished":
                await interaction.followup.send("❌ Evento no encontrado o finalizado.", ephemeral=True)
                return
            total = registered_count(self.event_id)
            if capacity < total:
                await interaction.followup.send(f"❌ Ya hay {total} inscritos; no puedes bajar cupos de ese número.", ephemeral=True)
                return
            with database() as db:
                db.execute("UPDATE events SET capacity=?,prizes=? WHERE id=?",
                           (capacity, prize_text(self.first.value, self.second.value, self.third.value), self.event_id))
            await refresh_event(self.event_id)
        await interaction.followup.send("✅ Premios y cupos actualizados.", ephemeral=True)


@event_group.command(name="premios", description="Cambia los premios de los tres lugares y el máximo de inscritos")
@app_commands.describe(evento_id="ID del evento cuyos premios y cupos deseas cambiar")
@app_commands.check(only_admin)
async def evento_premios(interaction: discord.Interaction, evento_id: int):
    event = fetch_event(evento_id)
    if not event or event["status"] == "finished":
        await interaction.response.send_message("❌ Evento no encontrado o finalizado.", ephemeral=True)
        return
    await interaction.response.send_modal(EditPrizesModal(event))


@event_group.command(name="banner", description="Reemplaza la imagen del anuncio sin perder inscripciones")
@app_commands.describe(evento_id="ID del evento que tendrá nuevo banner", imagen="Nueva imagen de tu galería, máximo 8 MB")
@app_commands.check(only_admin)
async def evento_banner(interaction: discord.Interaction, evento_id: int, imagen: discord.Attachment):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not (imagen.content_type or "").startswith("image/") or imagen.size > 8 * 1024 * 1024:
        await interaction.followup.send("❌ Imagen inválida o mayor de 8 MB.", ephemeral=True)
        return
    data = await imagen.read()
    filename = "banner_actualizado.png"
    async with client.lock:
        event = fetch_event(evento_id)
        if not event or event["status"] == "finished":
            await interaction.followup.send("❌ Evento no encontrado o finalizado.", ephemeral=True)
            return
        channel = await client.fetch_channel(event["channel_id"])
        message = await channel.fetch_message(event["message_id"])
        embed = event_embed(event, registered_count(evento_id), f"attachment://{filename}")
        edited_message = await message.edit(
            embed=embed,
            attachments=[discord.File(io.BytesIO(data), filename=filename)],
            view=EventButtons()
        )
        updated_url = (
            edited_message.attachments[0].url
            if edited_message.attachments else None
        )
        if updated_url:
            embed.set_image(url=updated_url)
            await edited_message.edit(embed=embed, attachments=edited_message.attachments)
        with database() as db:
            db.execute("UPDATE events SET image_url=? WHERE id=?", (updated_url, evento_id))
    await interaction.followup.send("✅ Banner actualizado.", ephemeral=True)


client.tree.add_command(event_group, guild=GUILD)


# ==========================================
# ALERTAS DE PRUEBA
# ==========================================

@client.tree.command(name="testalert", description="Envía una alerta de prueba DOWN o RESTORED sin cambiar el estado real", guild=GUILD)
@app_commands.default_permissions(administrator=True)
@app_commands.check(only_admin)
@app_commands.choices(estado=[
    app_commands.Choice(name="🔴 Server Down", value="down"),
    app_commands.Choice(name="🟢 Server Restored", value="up")
])
async def testalert(interaction: discord.Interaction, estado: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True)
    await send_alert(estado.value, test=True)
    await interaction.followup.send("✅ Alerta de prueba enviada.", ephemeral=True)


def simulate_cycle():
    tracker = StateTracker()
    assert tracker.observe("up", 0) == "initial"
    assert tracker.observe("down", 10) is None
    assert tracker.observe("up", 15) is None
    assert tracker.observe("partial", 20) is None
    assert tracker.observe("down", 100) is None
    assert tracker.observe("down", 190) == "down"
    tracker.confirmed("down")
    assert tracker.observe("down", 200) is None
    assert tracker.observe("up", 300) is None
    assert tracker.observe("up", 390) == "up"
    tracker.confirmed("up")
    assert tracker.observe("up", 450) is None


@client.tree.command(name="simular-ciclo", description="Prueba DOWN/RESTORED y confirma que el monitor real no cambia", guild=GUILD)
@app_commands.default_permissions(administrator=True)
@app_commands.check(only_admin)
async def simular_ciclo(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    simulate_cycle()
    await send_alert("down", test=True)
    await send_alert("up", test=True)
    await interaction.followup.send("✅ Simulación completada. Partial ignorado; estado real intacto.", ephemeral=True)


# ==========================================
# MANTENIMIENTO
# ==========================================

maintenance_group = app_commands.Group(name="mantenimiento", description="Administrar mantenimientos")


@maintenance_group.command(name="iniciar", description="Anuncia mantenimiento y suspende las alertas automáticas")
@app_commands.describe(motivo="Explica brevemente por qué la ciudad estará en mantenimiento")
@app_commands.check(only_admin)
async def mantenimiento_iniciar(interaction: discord.Interaction, motivo: str):
    await interaction.response.defer(ephemeral=True)
    motivo = motivo.strip()[:300]
    if not motivo:
        await interaction.followup.send("❌ Escribe un motivo.", ephemeral=True)
        return
    async with client.lock:
        if get_setting("maintenance_active", "0") == "1":
            answer = "⚠️ Ya hay un mantenimiento activo."
        else:
            embed = discord.Embed(
                title="🛠️ MANTENIMIENTO INICIADO | LA VENGANZA RP",
                description=f"🔧 **Motivo:** {safe(motivo)}\n\n⛔ El acceso podría estar limitado.\n📢 Avisaremos al finalizar.",
                color=0xF59E0B
            )
            await post_webhook(embed)
            moment = now_iso()
            with database() as db:
                db.execute("UPDATE outages SET ended=?,duration_seconds=NULL WHERE ended IS NULL", (moment,))
                db.execute("INSERT INTO maintenance(started,reason,author_id) VALUES (?,?,?)", (moment, motivo, str(interaction.user.id)))
                db.execute("INSERT OR REPLACE INTO settings VALUES ('maintenance_active','1')")
            client.tracker.reset()
            answer = "✅ Mantenimiento anunciado; alertas automáticas suspendidas."
    await interaction.followup.send(answer, ephemeral=True)


@maintenance_group.command(name="finalizar", description="Anuncia el fin del mantenimiento y reactiva el monitor")
@app_commands.check(only_admin)
async def mantenimiento_finalizar(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    async with client.lock:
        if get_setting("maintenance_active", "0") != "1":
            answer = "⚠️ No hay mantenimiento activo."
        else:
            try:
                state = await fetch_panel_state()
            except Exception:
                log.exception("No se pudo leer Connect")
                state = None
            await post_webhook(discord.Embed(
                title="✅ MANTENIMIENTO FINALIZADO | LA VENGANZA RP",
                description=f"🛠️ Los trabajos finalizaron.\n📡 Consulta Connect para conocer el estado actual.\n🎮 {CONNECT_URL}",
                color=0x22C55E
            ))
            with database() as db:
                db.execute("UPDATE maintenance SET ended=? WHERE ended IS NULL", (now_iso(),))
                db.execute("INSERT OR REPLACE INTO settings VALUES ('maintenance_active','0')")
                db.execute("INSERT OR REPLACE INTO settings VALUES ('last_state',?)", (state if state in ("up", "down") else "",))
            client.tracker = StateTracker(state if state in ("up", "down") else None)
            answer = "✅ Mantenimiento finalizado y monitor reactivado."
    await interaction.followup.send(answer, ephemeral=True)


client.tree.add_command(maintenance_group, guild=GUILD)


# ==========================================
# HISTORIAL DE CAIDAS
# ==========================================

@client.tree.command(name="historial-caidas", description="Consulta las 10 caídas más recientes y su duración", guild=GUILD)
@app_commands.default_permissions(administrator=True)
@app_commands.check(only_admin)
async def historial_caidas(interaction: discord.Interaction):
    with database() as db:
        rows = db.execute("SELECT * FROM outages ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        text = "📊 Todavía no hay caídas registradas. Las simulaciones no cuentan."
    else:
        lines = []
        for row in rows:
            if row["ended"] is None:
                result = "🔴 En curso"
            elif row["duration_seconds"] is None:
                result = "⚪ Interrumpida por mantenimiento"
            else:
                result = "✅ " + duration(row["started"], row["ended"])
            lines.append(f"**#{row['id']}** <t:{epoch(row['started'])}:f> — {result}")
        text = "📊 **HISTORIAL DE CAÍDAS**\n" + "\n".join(lines)
    await interaction.response.send_message(text, ephemeral=True)


# ==========================================
# MANEJO DE ERRORES
# ==========================================

@client.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log.error("Error ejecutando comando: %r", error)
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        answer = "❌ Solo administradores autorizados pueden ejecutar este comando."
    else:
        answer = "❌ No se pudo completar la acción. Revisa Railway."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(answer, ephemeral=True)
        else:
            await interaction.response.send_message(answer, ephemeral=True)
    except discord.HTTPException:
        log.exception("No se pudo responder")


@client.event
async def on_ready():
    log.info("Bot conectado como %s", client.user)
    if DATA_DIR == "/tmp":
        log.warning("SQLite está en /tmp. Conecta un volumen Railway en /data para conservar inscripciones.")


if __name__ == "__main__":
    client.run(TOKEN, log_handler=None)