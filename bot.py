
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

# ==========================================
# LA VENGANZA RP | BOT OFICIAL
# ALERTAS + MANTENIMIENTO + EVENTOS
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("LaVenganzaRP")

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# ==========================================
# IDENTIFICADORES DE DISCORD
# ==========================================

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

DATA_DIR = (
    os.getenv("DATA_DIR")
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or "/tmp"
)

DB_PATH = os.path.join(
    DATA_DIR,
    "lavenganza.sqlite3"
)

# ==========================================
# FECHAS
# ==========================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def as_epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def duration(start, end):
    a = datetime.fromisoformat(start)
    b = datetime.fromisoformat(end)
    seconds = max(0, int((b - a).total_seconds()))

    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    return f"{minutes}m {seconds}s"


# ==========================================
# BASE DE DATOS
# ==========================================

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


def init_database():
    os.makedirs(DATA_DIR, exist_ok=True)

    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS outages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started TEXT NOT NULL,
            ended TEXT,
            duration_seconds INTEGER
        );

        CREATE TABLE IF NOT EXISTS maintenance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started TEXT NOT NULL,
            ended TEXT,
            reason TEXT NOT NULL,
            author_id TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
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
            winner1 TEXT,
            winner2 TEXT,
            winner3 TEXT
        );

        CREATE TABLE IF NOT EXISTS registrations (
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY (event_id, user_id)
        );
        """)


def get_setting(key, default=""):
    with database() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        ).fetchone()

    return row["value"] if row else default


def set_setting(key, value):
    with database() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)",
            (key, str(value))
        )


def record_outage(state):
    moment = now_iso()

    with database() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?,?)",
            ("last_state", state)
        )

        if state == "down":
            existing = db.execute(
                "SELECT id FROM outages "
                "WHERE ended IS NULL LIMIT 1"
            ).fetchone()

            if not existing:
                db.execute(
                    "INSERT INTO outages(started) VALUES (?)",
                    (moment,)
                )

        elif state == "up":
            row = db.execute(
                "SELECT id,started FROM outages "
                "WHERE ended IS NULL "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()

            if row:
                seconds = max(
                    0,
                    int((
                        datetime.fromisoformat(moment)
                        - datetime.fromisoformat(row["started"])
                    ).total_seconds())
                )

                db.execute(
                    "UPDATE outages SET ended=?,"
                    "duration_seconds=? WHERE id=?",
                    (moment, seconds, row["id"])
                )


# ==========================================
# DETECCION ONLINE / OFFLINE
# ==========================================

def clean(value):
    text = unicodedata.normalize(
        "NFKC", str(value or "")
    )

    for mark in ("```", "`", "**", "__"):
        text = text.replace(mark, "")

    return text.strip().lower()


def parse_status(value):
    text = clean(value)

    if re.search(r"\b(partial|parcial|degraded)\b", text):
        return "partial"

    if re.search(
        r"\b(offline|down|cerrado|ca[ií]do)\b",
        text
    ):
        return "down"

    if re.search(
        r"\b(online|up|abierto|operativo)\b",
        text
    ):
        return "up"

    return None


def detect_status(message):
    for embed in message.embeds:
        for field in embed.fields:
            if re.search(
                r"\b(status|estado)\b",
                clean(field.name)
            ):
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


# ==========================================
# CLIENTE DISCORD
# ==========================================

intents = discord.Intents.default()
intents.message_content = True


class LaVenganzaBot(discord.Client):
    def __init__(self):
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none()
        )

        self.tree = app_commands.CommandTree(self)
        self.lock = asyncio.Lock()
        self.tracker = None
        self.monitor_task = None

    async def setup_hook(self):
        init_database()

        state = get_setting("last_state")
        self.tracker = StateTracker(
            state if state in ("up", "down") else None
        )

        self.add_view(EventButtons())

        commands = await self.tree.sync(guild=GUILD)

        log.info(
            "Comandos sincronizados: %s",
            ", ".join(x.name for x in commands)
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = LaVenganzaBot()


# ==========================================
# WEBHOOK DE ALERTAS
# ==========================================

async def post_webhook(embed):
    payload = {
        "username": "La Venganza RP | Alertas",
        "allowed_mentions": {"parse": []},
        "embeds": [embed.to_dict()]
    }

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.post(
            WEBHOOK_URL,
            json=payload
        ) as response:
            if response.status not in (200, 204):
                error = await response.text()

                raise RuntimeError(
                    f"Webhook HTTP {response.status}: "
                    f"{error[:120]}"
                )


def make_alert(state, test=False):
    if state == "down":
        title = "🚨 SERVER DOWN | LA VENGANZA RP"
        body = (
            "🔴 **La ciudad está fuera de servicio.**\n\n"
            "🛠️ Estamos verificando la situación.\n\n"
            "📢 Avisaremos cuando vuelva a funcionar."
        )
        color = 0xFF0000
    else:
        title = "🟢 SERVER RESTORED | LA VENGANZA RP"
        body = (
            "✅ **¡La ciudad está disponible nuevamente!**\n\n"
            f"🎮 {CONNECT_URL}"
        )
        color = 0x22C55E

    if test:
        title = "🧪 PRUEBA | " + title
        body = (
            "⚠️ **SIMULACIÓN. NO ES UN ESTADO REAL.**\n\n"
            + body
        )

    embed = discord.Embed(
        title=title,
        description=body,
        color=color
    )

    embed.set_footer(
        text="La Venganza RP | Sistema de Alertas"
    )

    return embed


async def send_alert(state, test=False):
    await post_webhook(make_alert(state, test))

    log.info(
        "Alerta enviada: %s | prueba=%s",
        state, test
    )


async def fetch_panel_state():
    channel = await client.fetch_channel(
        CONNECT_CHANNEL_ID
    )

    message = await channel.fetch_message(
        PANEL_MESSAGE_ID
    )

    return detect_status(message)


# ==========================================
# MONITOREO AUTOMATICO
# ==========================================

async def monitor_server():
    await client.wait_until_ready()

    observed = object()

    log.info("Monitor de La Venganza RP iniciado")

    while not client.is_closed():
        try:
            state = await fetch_panel_state()

            if state != observed:
                log.info("Estado observado: %s", state)
                observed = state

            async with client.lock:
                if get_setting(
                    "maintenance_active", "0"
                ) == "1":
                    client.tracker.reset()
                else:
                    change = client.tracker.observe(
                        state,
                        time.monotonic()
                    )

                    if change == "initial":
                        set_setting(
                            "last_state",
                            client.tracker.last
                        )

                    elif change in ("up", "down"):
                        await send_alert(change)
                        record_outage(change)
                        client.tracker.confirmed(change)

        except Exception:
            log.exception("Error monitoreando Connect")

        await asyncio.sleep(CHECK_INTERVAL)


# ==========================================
# PERMISOS ADMINISTRATIVOS
# ==========================================

async def only_admin(interaction):
    if (
        not interaction.guild
        or interaction.guild.id != GUILD_ID
    ):
        raise app_commands.CheckFailure(
            "Servidor no autorizado"
        )

    if not interaction.user.guild_permissions.administrator:
        raise app_commands.MissingPermissions(
            ["administrator"]
        )

    return True


# ==========================================
# EVENTOS: BASE DE DATOS
# ==========================================

def fetch_event(event_id):
    with database() as db:
        return db.execute(
            "SELECT * FROM events WHERE id=?",
            (event_id,)
        ).fetchone()


def event_from_message(message_id):
    with database() as db:
        return db.execute(
            "SELECT * FROM events WHERE message_id=?",
            (message_id,)
        ).fetchone()


def registered_count(event_id):
    with database() as db:
        return db.execute(
            "SELECT COUNT(*) FROM registrations "
            "WHERE event_id=?",
            (event_id,)
        ).fetchone()[0]


def registered_users(event_id, limit=None):
    sql = (
        "SELECT user_id FROM registrations "
        "WHERE event_id=? ORDER BY joined_at"
    )

    params = [event_id]

    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with database() as db:
        return db.execute(
            sql, params
        ).fetchall()


# ==========================================
# EVENTOS: EMBED CON BANNER
# ==========================================

def make_event_embed(event, count, image_url=None):
    status_names = {
        "open": "🟢 Inscripciones abiertas",
        "closed": "🔒 Inscripciones cerradas",
        "finished": "🏆 Evento finalizado"
    }

    embed = discord.Embed(
        title=(
            f"🏁 {event['title']} "
            "| LA VENGANZA RP"
        ),
        description=(
            event["description"]
            or "¡Participa en nuestro evento oficial!"
        ),
        color=0xD80000
    )

    epoch = as_epoch(event["starts_at"])

    embed.add_field(
        name="📅 Fecha y hora",
        value=(
            f"<t:{epoch}:F>\n"
            "🇵🇷 Hora de Puerto Rico"
        ),
        inline=False
    )

    embed.add_field(
        name="📍 Lugar",
        value=event["location"],
        inline=True
    )

    embed.add_field(
        name="👥 Participantes",
        value=f"**{count}/{event['capacity']}**",
        inline=True
    )

    embed.add_field(
        name="📋 Estado",
        value=status_names.get(
            event["status"],
            event["status"]
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Premios",
        value=event["prizes"],
        inline=False
    )

    if event["status"] == "finished":
        embed.add_field(
            name="🏅 Ganadores",
            value=(
                f"🥇 {event['winner1']}\n"
                f"🥈 {event['winner2']}\n"
                f"🥉 {event['winner3']}"
            ),
            inline=False
        )

    image = image_url or event["image_url"]

    if image:
        embed.set_image(url=image)

    embed.set_footer(
        text=f"La Venganza RP | Evento #{event['id']}"
    )

    return embed


async def refresh_event(event_id, message=None):
    event = fetch_event(event_id)

    if not event or not event["message_id"]:
        return

    if message is None:
        channel = await client.fetch_channel(
            event["channel_id"]
        )

        message = await channel.fetch_message(
            event["message_id"]
        )

    image_url = None

    if message.embeds and message.embeds[0].image:
        image_url = message.embeds[0].image.url

    embed = make_event_embed(
        event,
        registered_count(event_id),
        image_url=image_url
    )

    await message.edit(
        embed=embed,
        view=EventButtons(),
        attachments=message.attachments
    )


# ==========================================
# BOTONES PERSISTENTES
# ==========================================

class EventButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Inscribirme",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="lvrp:event:join"
    )
    async def join(self, interaction, button):
        await self.registration(interaction, True)

    @discord.ui.button(
        label="Cancelar",
        emoji="❌",
        style=discord.ButtonStyle.secondary,
        custom_id="lvrp:event:leave"
    )
    async def leave(self, interaction, button):
        await self.registration(interaction, False)

    @discord.ui.button(
        label="Participantes",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="lvrp:event:list"
    )
    async def participants(self, interaction, button):
        event = event_from_message(
            interaction.message.id
        )

        if not event:
            await interaction.response.send_message(
                "❌ Evento no encontrado.",
                ephemeral=True
            )
            return

        rows = registered_users(event["id"], 30)
        total = registered_count(event["id"])

        text = "\n".join(
            f"{i}. <@{row['user_id']}>"
            for i, row in enumerate(rows, 1)
        ) or "Todavía no hay participantes."

        if total > 30:
            text += f"\n... y {total - 30} más."

        await interaction.response.send_message(
            f"📋 **{event['title']}**\n"
            f"👥 {total}/{event['capacity']}\n\n"
            f"{text}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )

    async def registration(self, interaction, joining):
        if (
            not interaction.guild
            or interaction.guild.id != GUILD_ID
        ):
            await interaction.response.send_message(
                "❌ Servidor no autorizado.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        async with client.lock:
            event = event_from_message(
                interaction.message.id
            )

            if not event:
                answer = "❌ Evento no disponible."

            elif event["status"] != "open":
                answer = "🔒 Inscripciones cerradas."

            else:
                changed = False

                with database() as db:
                    existing = db.execute(
                        "SELECT 1 FROM registrations "
                        "WHERE event_id=? AND user_id=?",
                        (
                            event["id"],
                            interaction.user.id
                        )
                    ).fetchone()

                    total = db.execute(
                        "SELECT COUNT(*) FROM registrations "
                        "WHERE event_id=?",
                        (event["id"],)
                    ).fetchone()[0]

                    if joining and existing:
                        answer = "✅ Ya estás inscrito."

                    elif not joining and not existing:
                        answer = "ℹ️ No estabas inscrito."

                    elif joining and total >= event["capacity"]:
                        answer = "⛔ No quedan cupos."

                    elif joining:
                        db.execute(
                            "INSERT INTO registrations "
                            "(event_id,user_id,joined_at) "
                            "VALUES (?,?,?)",
                            (
                                event["id"],
                                interaction.user.id,
                                now_iso()
                            )
                        )
                        changed = True
                        answer = "✅ ¡Inscripción completada!"

                    else:
                        db.execute(
                            "DELETE FROM registrations "
                            "WHERE event_id=? AND user_id=?",
                            (
                                event["id"],
                                interaction.user.id
                            )
                        )
                        changed = True
                        answer = "✅ Cancelaste tu inscripción."

                if changed:
                    try:
                        await refresh_event(
                            event["id"],
                            interaction.message
                        )
                    except Exception:
                        log.exception(
                            "Error actualizando participantes"
                        )
                        answer += (
                            "\n⚠️ El contador no pudo "
                            "actualizarse."
                        )

        await interaction.followup.send(
            answer,
            ephemeral=True
        )


# ==========================================
# GRUPO /EVENTO
# ==========================================

event_group = app_commands.Group(
    name="evento",
    description="Eventos oficiales de La Venganza RP"
)


# ==========================================
# /EVENTO CREAR
# ==========================================

@event_group.command(
    name="crear",
    description="Crear evento con banner e inscripciones"
)
@app_commands.describe(
    nombre="Nombre del evento",
    fecha="Fecha AAAA-MM-DD",
    hora="Hora de Puerto Rico HH:MM",
    lugar="Lugar del evento",
    cupos="Número máximo de participantes",
    premios="Premios del evento",
    imagen="Banner opcional desde tu galería",
    descripcion="Descripción opcional"
)
@app_commands.check(only_admin)
async def evento_crear(
    interaction: discord.Interaction,
    nombre: str,
    fecha: str,
    hora: str,
    lugar: str,
    cupos: app_commands.Range[int, 1, 500],
    premios: str,
    imagen: discord.Attachment = None,
    descripcion: str = "¡Participa en nuestro evento!"
):
    await interaction.response.defer(
        ephemeral=True,
        thinking=True
    )

    try:
        local_date = datetime.strptime(
            f"{fecha} {hora}",
            "%Y-%m-%d %H:%M"
        ).replace(tzinfo=PR_TZ)

        if local_date <= datetime.now(PR_TZ):
            await interaction.followup.send(
                "❌ La fecha debe ser futura.",
                ephemeral=True
            )
            return

    except ValueError:
        await interaction.followup.send(
            "❌ Formato: AAAA-MM-DD y HH:MM.",
            ephemeral=True
        )
        return

    if (
        not 1 <= len(nombre.strip()) <= 90
        or not 1 <= len(lugar.strip()) <= 200
        or not 1 <= len(premios.strip()) <= 900
        or len(descripcion) > 1800
    ):
        await interaction.followup.send(
            "❌ Revisa el tamaño de los textos.",
            ephemeral=True
        )
        return

    image_file = None
    image_name = None

    if imagen:
        if not (
            imagen.content_type or ""
        ).startswith("image/"):
            await interaction.followup.send(
                "❌ Debes subir una imagen.",
                ephemeral=True
            )
            return

        if imagen.size > 8 * 1024 * 1024:
            await interaction.followup.send(
                "❌ Banner máximo: 8 MB.",
                ephemeral=True
            )
            return

        extension = (
            imagen.filename.rsplit(".", 1)[-1].lower()
            if "." in imagen.filename else "png"
        )

        if extension not in (
            "png", "jpg", "jpeg", "webp", "gif"
        ):
            await interaction.followup.send(
                "❌ Usa PNG, JPG, WEBP o GIF.",
                ephemeral=True
            )
            return

        image_name = f"evento_banner.{extension}"

        try:
            data = await imagen.read()
            image_file = discord.File(
                io.BytesIO(data),
                filename=image_name
            )
        except Exception:
            await interaction.followup.send(
                "❌ No se pudo cargar el banner.",
                ephemeral=True
            )
            return

    async with client.lock:
        with database() as db:
            cursor = db.execute(
                """
                INSERT INTO events (
                    channel_id,title,description,
                    location,starts_at,capacity,
                    prizes,status,created_by
                )
                VALUES (?,?,?,?,?,?,?,'open',?)
                """,
                (
                    EVENT_CHANNEL_ID,
                    nombre.strip(),
                    descripcion.strip(),
                    lugar.strip(),
                    local_date.astimezone(
                        timezone.utc
                    ).isoformat(),
                    cupos,
                    premios.strip(),
                    str(interaction.user.id)
                )
            )

            event_id = cursor.lastrowid

        event = fetch_event(event_id)

        image_reference = (
            f"attachment://{image_name}"
            if image_name else None
        )

        embed = make_event_embed(
            event,
            0,
            image_url=image_reference
        )

        try:
            channel = await client.fetch_channel(
                EVENT_CHANNEL_ID
            )

            options = {
                "embed": embed,
                "view": EventButtons(),
                "allowed_mentions":
                    discord.AllowedMentions.none()
            }

            if image_file:
                options["file"] = image_file

            message = await channel.send(**options)

            image_url = None

            if message.embeds and message.embeds[0].image:
                image_url = message.embeds[0].image.url

            with database() as db:
                db.execute(
                    "UPDATE events SET "
                    "message_id=?,image_url=? "
                    "WHERE id=?",
                    (
                        message.id,
                        image_url,
                        event_id
                    )
                )

        except Exception:
            log.exception("Error publicando evento")

            with database() as db:
                db.execute(
                    "DELETE FROM events "
                    "WHERE id=? AND message_id IS NULL",
                    (event_id,)
                )

            await interaction.followup.send(
                "❌ No se pudo publicar el evento.",
                ephemeral=True
            )
            return

        finally:
            if image_file:
                image_file.close()

    await interaction.followup.send(
        f"✅ Evento #{event_id} publicado.\n"
        f"{message.jump_url}",
        ephemeral=True
    )


# ==========================================
# /EVENTO CERRAR
# ==========================================

@event_group.command(
    name="cerrar",
    description="Cerrar las inscripciones"
)
@app_commands.describe(
    evento_id="Número del evento"
)
@app_commands.check(only_admin)
async def evento_cerrar(
    interaction: discord.Interaction,
    evento_id: int
):
    await interaction.response.defer(ephemeral=True)

    async with client.lock:
        event = fetch_event(evento_id)

        if not event:
            result = "❌ Evento no encontrado."

        elif event["status"] != "open":
            result = "ℹ️ Inscripciones ya cerradas."

        else:
            with database() as db:
                db.execute(
                    "UPDATE events SET status='closed' "
                    "WHERE id=?",
                    (evento_id,)
                )

            await refresh_event(evento_id)

            result = (
                f"🔒 Inscripciones del evento "
                f"#{evento_id} cerradas."
            )

    await interaction.followup.send(
        result,
        ephemeral=True
    )


# ==========================================
# /EVENTO FINALIZAR
# ==========================================

@event_group.command(
    name="finalizar",
    description="Finalizar evento y anunciar ganadores"
)
@app_commands.describe(
    evento_id="Número del evento",
    primero="Primer lugar",
    segundo="Segundo lugar",
    tercero="Tercer lugar"
)
@app_commands.check(only_admin)
async def evento_finalizar(
    interaction: discord.Interaction,
    evento_id: int,
    primero: str,
    segundo: str,
    tercero: str
):
    await interaction.response.defer(ephemeral=True)

    winners = (primero, segundo, tercero)

    if any(
        not value.strip() or len(value) > 120
        for value in winners
    ):
        await interaction.followup.send(
            "❌ Escribe los tres ganadores.",
            ephemeral=True
        )
        return

    async with client.lock:
        event = fetch_event(evento_id)

        if not event:
            result = "❌ Evento no encontrado."

        elif event["status"] == "finished":
            result = "ℹ️ Evento ya finalizado."

        else:
            with database() as db:
                db.execute(
                    """
                    UPDATE events
                    SET status='finished',
                        winner1=?,
                        winner2=?,
                        winner3=?
                    WHERE id=?
                    """,
                    (
                        *[
                            discord.utils.escape_markdown(
                                value.strip()
                            )
                            for value in winners
                        ],
                        evento_id
                    )
                )

            await refresh_event(evento_id)

            result = (
                f"🏆 Evento #{evento_id} finalizado. "
                "Ganadores publicados."
            )

    await interaction.followup.send(
        result,
        ephemeral=True
    )


# ==========================================
# /EVENTO PARTICIPANTES
# ==========================================

@event_group.command(
    name="participantes",
    description="Consultar participantes de un evento"
)
@app_commands.describe(
    evento_id="Número del evento"
)
@app_commands.check(only_admin)
async def evento_participantes(
    interaction: discord.Interaction,
    evento_id: int
):
    event = fetch_event(evento_id)

    if not event:
        await interaction.response.send_message(
            "❌ Evento no encontrado.",
            ephemeral=True
        )
        return

    rows = registered_users(evento_id)

    names = [
        f"{i}. <@{row['user_id']}>"
        for i, row in enumerate(rows, 1)
    ]

    if not names:
        names = ["No hay participantes."]

    text = (
        f"📋 **{event['title']}**\n"
        f"👥 {len(rows)} inscritos\n\n"
        + "\n".join(names)
    )

    if len(text) > 1900:
        text = text[:1850] + "\n... Lista truncada."

    await interaction.response.send_message(
        text,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none()
    )


client.tree.add_command(
    event_group,
    guild=GUILD
)


# ==========================================
# /TESTALERT
# ==========================================

@client.tree.command(
    name="testalert",
    description="Enviar una alerta de prueba",
    guild=GUILD
)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.check(only_admin)
@app_commands.choices(
    estado=[
        app_commands.Choice(
            name="🔴 Server Down",
            value="down"
        ),
        app_commands.Choice(
            name="🟢 Server Restored",
            value="up"
        )
    ]
)
async def testalert(
    interaction: discord.Interaction,
    estado: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=True)

    await send_alert(
        estado.value,
        test=True
    )

    await interaction.followup.send(
        "✅ Alerta de prueba enviada.",
        ephemeral=True
    )


# ==========================================
# /SIMULAR-CICLO
# ==========================================

def simulate_cycle():
    tracker = StateTracker()

    assert tracker.observe("up", 0) == "initial"
    assert tracker.observe("down", 10) is None
    assert tracker.observe("up", 15) is None
    assert tracker.observe("partial", 20) is None

    assert tracker.observe("down", 100) is None
    assert tracker.observe("down", 189) is None
    assert tracker.observe("down", 190) == "down"

    tracker.confirmed("down")

    assert tracker.observe("down", 200) is None
    assert tracker.observe("up", 300) is None
    assert tracker.observe("up", 390) == "up"

    tracker.confirmed("up")

    assert tracker.observe("up", 450) is None


@client.tree.command(
    name="simular-ciclo",
    description="Simular caída y recuperación",
    guild=GUILD
)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.check(only_admin)
async def simular_ciclo(
    interaction: discord.Interaction
):
    await interaction.response.defer(ephemeral=True)

    simulate_cycle()

    await send_alert("down", test=True)
    await send_alert("up", test=True)

    await interaction.followup.send(
        "✅ Simulación completada.\n"
        "🔴 Down enviado.\n"
        "🟢 Restored enviado.\n"
        "🟠 Partial ignorado.\n"
        "✅ Estado real sin cambios.",
        ephemeral=True
    )


# ==========================================
# /MANTENIMIENTO
# ==========================================

maintenance_group = app_commands.Group(
    name="mantenimiento",
    description="Administrar mantenimientos"
)


@maintenance_group.command(
    name="iniciar",
    description="Anunciar mantenimiento"
)
@app_commands.describe(
    motivo="Motivo del mantenimiento"
)
@app_commands.check(only_admin)
async def mantenimiento_iniciar(
    interaction: discord.Interaction,
    motivo: str
):
    await interaction.response.defer(ephemeral=True)

    motivo = motivo.strip()[:300]

    if not motivo:
        await interaction.followup.send(
            "❌ Escribe un motivo.",
            ephemeral=True
        )
        return

    async with client.lock:
        if get_setting(
            "maintenance_active", "0"
        ) == "1":
            result = "⚠️ Ya existe mantenimiento activo."

        else:
            embed = discord.Embed(
                title=(
                    "🛠️ MANTENIMIENTO INICIADO "
                    "| LA VENGANZA RP"
                ),
                description=(
                    "🔧 **Motivo:** "
                    f"{discord.utils.escape_markdown(motivo)}\n\n"
                    "⛔ El acceso podría estar limitado.\n"
                    "📢 Avisaremos cuando finalice."
                ),
                color=0xF59E0B
            )

            await post_webhook(embed)

            moment = now_iso()

            with database() as db:
                db.execute(
                    "UPDATE outages SET "
                    "ended=?,duration_seconds=NULL "
                    "WHERE ended IS NULL",
                    (moment,)
                )

                db.execute(
                    "INSERT INTO maintenance "
                    "(started,reason,author_id) "
                    "VALUES (?,?,?)",
                    (
                        moment,
                        motivo,
                        str(interaction.user.id)
                    )
                )

                db.execute(
                    "INSERT OR REPLACE INTO settings "
                    "VALUES ('maintenance_active','1')"
                )

            client.tracker.reset()

            result = (
                "✅ Mantenimiento anunciado. "
                "Alertas automáticas pausadas."
            )

    await interaction.followup.send(
        result,
        ephemeral=True
    )


@maintenance_group.command(
    name="finalizar",
    description="Finalizar mantenimiento"
)
@app_commands.check(only_admin)
async def mantenimiento_finalizar(
    interaction: discord.Interaction
):
    await interaction.response.defer(ephemeral=True)

    async with client.lock:
        if get_setting(
            "maintenance_active", "0"
        ) != "1":
            result = "⚠️ No hay mantenimiento activo."

        else:
            state = None

            try:
                state = await fetch_panel_state()
            except Exception:
                log.exception(
                    "No se pudo consultar Connect"
                )

            embed = discord.Embed(
                title=(
                    "✅ MANTENIMIENTO FINALIZADO "
                    "| LA VENGANZA RP"
                ),
                description=(
                    "🛠️ Los trabajos han finalizado.\n\n"
                    "📡 Consulta Connect para conocer "
                    "el estado actual.\n\n"
                    f"🎮 {CONNECT_URL}"
                ),
                color=0x22C55E
            )

            await post_webhook(embed)

            with database() as db:
                db.execute(
                    "UPDATE maintenance SET ended=? "
                    "WHERE ended IS NULL",
                    (now_iso(),)
                )

                db.execute(
                    "INSERT OR REPLACE INTO settings "
                    "VALUES ('maintenance_active','0')"
                )

                db.execute(
                    "INSERT OR REPLACE INTO settings "
                    "VALUES ('last_state',?)",
                    (
                        state if state in (
                            "up", "down"
                        ) else "",
                    )
                )

            client.tracker = StateTracker(
                state if state in (
                    "up", "down"
                ) else None
            )

            result = (
                "✅ Mantenimiento finalizado. "
                "Monitor reactivado."
            )

    await interaction.followup.send(
        result,
        ephemeral=True
    )


client.tree.add_command(
    maintenance_group,
    guild=GUILD
)


# ==========================================
# /HISTORIAL-CAIDAS
# ==========================================

@client.tree.command(
    name="historial-caidas",
    description="Consultar últimas caídas",
    guild=GUILD
)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.check(only_admin)
async def historial_caidas(
    interaction: discord.Interaction
):
    with database() as db:
        rows = db.execute(
            "SELECT * FROM outages "
            "ORDER BY id DESC LIMIT 10"
        ).fetchall()

    if not rows:
        text = (
            "📊 No hay caídas registradas.\n"
            "Las simulaciones no cuentan."
        )

    else:
        lines = []

        for row in rows:
            if row["ended"] is None:
                result = "🔴 En curso"

            elif row["duration_seconds"] is None:
                result = (
                    "⚪ Interrumpida por mantenimiento"
                )

            else:
                result = "✅ " + duration(
                    row["started"],
                    row["ended"]
                )

            lines.append(
                f"**#{row['id']}** "
                f"<t:{as_epoch(row['started'])}:f> "
                f"— {result}"
            )

        text = (
            "📊 **HISTORIAL DE CAÍDAS**\n"
            + "\n".join(lines)
        )

    await interaction.response.send_message(
        text,
        ephemeral=True
    )


# ==========================================
# MANEJO DE ERRORES
# ==========================================

@client.tree.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    log.error(
        "Error ejecutando comando: %s",
        error
    )

    if isinstance(
        error,
        (
            app_commands.MissingPermissions,
            app_commands.CheckFailure
        )
    ):
        message = (
            "❌ Solo administradores autorizados "
            "pueden utilizar este comando."
        )
    else:
        message = (
            "❌ No se pudo completar la acción. "
            "Revisa Railway."
        )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )
    except discord.HTTPException:
        log.exception(
            "No se pudo responder al comando"
        )


# ==========================================
# BOT ONLINE
# ==========================================

@client.event
async def on_ready():
    log.info(
        "Bot conectado como %s",
        client.user
    )

    if DATA_DIR == "/tmp":
        log.warning(
            "Base de datos temporal. "
            "Configura volumen Railway en /data."
        )


# ==========================================
# INICIAR
# ==========================================

if __name__ == "__main__":
    client.run(
        TOKEN,
        log_handler=None
    )
