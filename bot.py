
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
# LA VENGANZA RP
# ALERTAS + MANTENIMIENTO + EVENTOS
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

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

DATA_DIR = (
    os.getenv("DATA_DIR")
    or os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    or "/tmp"
)

DB_PATH = os.path.join(DATA_DIR, "lavenganza.sqlite3")

DRAFT_SECONDS = 1800
DRAFTS = {}


# ==========================================
# UTILIDADES
# ==========================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def epoch(iso):
    return int(datetime.fromisoformat(iso).timestamp())


def duration(start, end):
    seconds = max(
        0,
        int(
            (
                datetime.fromisoformat(end)
                - datetime.fromisoformat(start)
            ).total_seconds()
        )
    )

    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    return f"{minutes}m {seconds}s"


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
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS outages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started TEXT NOT NULL,
            ended TEXT,
            duration_seconds INTEGER
        );

        CREATE TABLE IF NOT EXISTS maintenance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started TEXT NOT NULL,
            ended TEXT,
            reason TEXT NOT NULL,
            author_id TEXT NOT NULL
        );

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
            winner1 TEXT,
            winner2 TEXT,
            winner3 TEXT
        );

        CREATE TABLE IF NOT EXISTS registrations(
            event_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TEXT NOT NULL,
            PRIMARY KEY(event_id,user_id)
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
                "SELECT id FROM outages WHERE ended IS NULL LIMIT 1"
            ).fetchone()

            if not existing:
                db.execute(
                    "INSERT INTO outages(started) VALUES (?)",
                    (moment,)
                )

        elif state == "up":
            row = db.execute(
                """
                SELECT id,started
                FROM outages
                WHERE ended IS NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

            if row:
                total = max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(moment)
                            - datetime.fromisoformat(row["started"])
                        ).total_seconds()
                    )
                )

                db.execute(
                    """
                    UPDATE outages
                    SET ended=?,duration_seconds=?
                    WHERE id=?
                    """,
                    (moment, total, row["id"])
                )


def clean(value):
    text = unicodedata.normalize(
        "NFKC",
        str(value or "")
    )

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
            if re.search(
                r"\b(status|estado)\b",
                clean(field.name)
            ):
                return parse_status(field.value)

    return None


# ==========================================
# MONITOR DE ESTADO
# ==========================================

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
        super().__init__(
            intents=intents,
            allowed_mentions=discord.AllowedMentions.none()
        )

        self.tree = app_commands.CommandTree(self)
        self.lock = asyncio.Lock()
        self.tracker = None
        self.monitor_task = None

    async def setup_hook(self):
        init_db()

        state = get_setting("last_state")

        self.tracker = StateTracker(
            state if state in ("up", "down") else None
        )

        self.add_view(EventButtons())

        commands = await self.tree.sync(guild=GUILD)

        log.info(
            "Comandos sincronizados: %s",
            ", ".join(c.name for c in commands)
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = LaVenganzaBot()


# ==========================================
# WEBHOOK Y ALERTAS
# ==========================================

async def post_webhook(embed):
    payload = {
        "username": "La Venganza RP | Alertas",
        "allowed_mentions": {"parse": []},
        "embeds": [embed.to_dict()]
    }

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20)
    ) as session:

        async with session.post(
            WEBHOOK_URL,
            json=payload
        ) as response:

            if response.status not in (200, 204):
                raise RuntimeError(
                    f"Webhook HTTP {response.status}: "
                    f"{(await response.text())[:120]}"
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
        state,
        test
    )


async def fetch_panel_state():
    channel = await client.fetch_channel(
        CONNECT_CHANNEL_ID
    )

    message = await channel.fetch_message(
        PANEL_MESSAGE_ID
    )

    return detect_status(message)


async def monitor_server():
    await client.wait_until_ready()

    last_observed = object()

    log.info("Monitor de Connect iniciado")

    while not client.is_closed():
        try:
            state = await fetch_panel_state()

            if state != last_observed:
                log.info(
                    "Estado observado: %s",
                    state
                )

                last_observed = state

            async with client.lock:
                if get_setting(
                    "maintenance_active",
                    "0"
                ) == "1":

                    client.tracker.reset()

                else:
                    event = client.tracker.observe(
                        state,
                        time.monotonic()
                    )

                    if event == "initial":
                        set_setting(
                            "last_state",
                            client.tracker.last
                        )

                    elif event in ("up", "down"):
                        await send_alert(event)

                        record_outage(event)

                        client.tracker.confirmed(event)

        except Exception:
            log.exception(
                "Error monitoreando Connect"
            )

        await asyncio.sleep(CHECK_INTERVAL)


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
# EVENTOS — CONSULTAS
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
            """
            SELECT COUNT(*)
            FROM registrations
            WHERE event_id=?
            """,
            (event_id,)
        ).fetchone()[0]


def registered_users(event_id, limit=None):
    query = (
        "SELECT user_id FROM registrations "
        "WHERE event_id=? ORDER BY joined_at"
    )

    params = [event_id]

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with database() as db:
        return db.execute(
            query,
            params
        ).fetchall()


def safe(text):
    return discord.utils.escape_markdown(
        str(text)
    ).replace("@", "@\u200b")


def prize_text(first, second, third):
    return (
        f"🥇 {safe(first)}\n"
        f"🥈 {safe(second)}\n"
        f"🥉 {safe(third)}"
    )


def event_embed(event, count, image_url=None):
    statuses = {
        "open": "🟢 Inscripciones abiertas",
        "closed": "🔒 Inscripciones cerradas",
        "finished": "🏆 Finalizado"
    }

    embed = discord.Embed(
        title=(
            f"🏎️ {safe(event['title'])} "
            "| LA VENGANZA RP"
        ),
        description=safe(event["description"]),
        color=0xD60000
    )

    embed.add_field(
        name="📅 Fecha y hora",
        value=(
            f"<t:{epoch(event['starts_at'])}:F>\n"
            "🇵🇷 Puerto Rico"
        ),
        inline=False
    )

    embed.add_field(
        name="📍 Lugar",
        value=safe(event["location"]),
        inline=True
    )

    embed.add_field(
        name="👥 Inscritos",
        value=f"**{count}/{event['capacity']}**",
        inline=True
    )

    embed.add_field(
        name="📋 Estado",
        value=statuses.get(
            event["status"],
            "Desconocido"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 PREMIOS",
        value=event["prizes"],
        inline=False
    )

    if event["status"] == "finished":
        embed.add_field(
            name="🏅 Ganadores",
            value=prize_text(
                event["winner1"],
                event["winner2"],
                event["winner3"]
            ),
            inline=False
        )

    image = image_url or event["image_url"]

    if image:
        embed.set_image(url=image)

    embed.set_footer(
        text=(
            "La Venganza RP | "
            f"Evento #{event['id']}"
        )
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

    image_url = event["image_url"]

    if message.attachments:
        image_url = (
            "attachment://"
            + message.attachments[0].filename
        )

    await message.edit(
        embed=event_embed(
            event,
            registered_count(event_id),
            image_url
        ),
        view=EventButtons(),
        attachments=message.attachments
    )


# ==========================================
# BOTONES DE INSCRIPCION
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

        lines = "\n".join(
            f"{i}. <@{row['user_id']}>"
            for i, row in enumerate(rows, 1)
        ) or "Todavía no hay inscritos."

        if total > 30:
            lines += f"\n... y {total - 30} más."

        await interaction.response.send_message(
            (
                f"📋 **{safe(event['title'])}**\n"
                f"👥 {total}/{event['capacity']}\n\n"
                f"{lines}"
            ),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none()
        )

    async def registration(self, interaction, joining):
        if interaction.guild_id != GUILD_ID:
            await interaction.response.send_message(
                "❌ Servidor incorrecto.",
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

            if