
import asyncio
import logging
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands

# ==========================================
# LA VENGANZA RP
# ALERTAS, MANTENIMIENTO E HISTORIAL
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("LaVenganzaRP")

# ==========================================
# VARIABLES PRIVADAS DE RAILWAY
# ==========================================

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# ==========================================
# CONFIGURACION DEL SERVIDOR
# ==========================================

GUILD_ID = 1244988345327550565

CONNECT_CHANNEL_ID = 1513421828415164546

PANEL_MESSAGE_ID = 1536621817471696907

ALERT_CHANNEL_ID = 1567618111920807987

CONNECT_URL = "https://cfx.re/join/57vjg7"

CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90

DATA_DIR = os.getenv(
    "DATA_DIR",
    os.getenv(
        "RAILWAY_VOLUME_MOUNT_PATH",
        "/tmp"
    )
)

DB_PATH = os.path.join(
    DATA_DIR,
    "lavenganza_alertas.sqlite3"
)

GUILD = discord.Object(id=GUILD_ID)


# ==========================================
# FECHAS Y TIEMPOS
# ==========================================

def utcnow():
    return datetime.now(timezone.utc)


def stamp():
    return utcnow().isoformat()


def elapsed(start, end):
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)

    seconds = max(
        0,
        int(
            (end_dt - start_dt).total_seconds()
        )
    )

    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"

    return f"{minutes}m {seconds}s"


# ==========================================
# BASE DE DATOS SQLITE
# ==========================================

def connect_db():
    return sqlite3.connect(
        DB_PATH,
        timeout=10
    )


def init_db():
    os.makedirs(
        DATA_DIR,
        exist_ok=True
    )

    with connect_db() as db:

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS outages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started TEXT NOT NULL,
                ended TEXT,
                duration_seconds INTEGER
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started TEXT NOT NULL,
                ended TEXT,
                reason TEXT NOT NULL,
                author_id TEXT NOT NULL
            )
            """
        )


# ==========================================
# CONFIGURACIONES GUARDADAS
# ==========================================

def setting(key, default=""):
    with connect_db() as db:

        result = db.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,)
        ).fetchone()

        return result[0] if result else default


def put_setting(key, value):
    with connect_db() as db:

        db.execute(
            """
            INSERT OR REPLACE INTO settings
            (key, value)
            VALUES (?, ?)
            """,
            (
                key,
                str(value)
            )
        )


# ==========================================
# REGISTRAR CAIDAS REALES
# ==========================================

def outage_confirmed(state):
    now = stamp()

    with connect_db() as db:

        db.execute(
            """
            INSERT OR REPLACE INTO settings
            (key, value)
            VALUES (?, ?)
            """,
            (
                "last_state",
                state
            )
        )

        if state == "down":

            existing = db.execute(
                """
                SELECT id
                FROM outages
                WHERE ended IS NULL
                LIMIT 1
                """
            ).fetchone()

            if not existing:

                db.execute(
                    """
                    INSERT INTO outages(started)
                    VALUES (?)
                    """,
                    (now,)
                )

        elif state == "up":

            open_row = db.execute(
                """
                SELECT id, started
                FROM outages
                WHERE ended IS NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

            if open_row:

                duration = max(
                    0,
                    int(
                        (
                            datetime.fromisoformat(now)
                            - datetime.fromisoformat(
                                open_row[1]
                            )
                        ).total_seconds()
                    )
                )

                db.execute(
                    """
                    UPDATE outages
                    SET ended=?,
                        duration_seconds=?
                    WHERE id=?
                    """,
                    (
                        now,
                        duration,
                        open_row[0]
                    )
                )


# ==========================================
# LIMPIAR TEXTO DEL PANEL
# ==========================================

def clean_text(value):
    text = unicodedata.normalize(
        "NFKC",
        str(value or "")
    )

    for marker in (
        "```",
        "`",
        "**",
        "__"
    ):
        text = text.replace(
            marker,
            ""
        )

    return text.strip().lower()


# ==========================================
# DETECTAR ONLINE / OFFLINE / PARTIAL
# ==========================================

def parse_status(value):
    value = clean_text(value)

    if re.search(
        r"\b(partial|degraded|parcial)\b",
        value
    ):
        return "partial"

    if re.search(
        r"\b(offline|down|cerrado|caido|caído)\b",
        value
    ):
        return "down"

    if re.search(
        r"\b(online|up|abierto|operativo)\b",
        value
    ):
        return "up"

    return None


# ==========================================
# LEER PANEL ORIGINAL DEL PROGRAMADOR
# ==========================================

def detect_status(message):

    for embed in message.embeds:

        for field in embed.fields:

            field_name = clean_text(
                field.name
            )

            if re.search(
                r"\b(status|estado)\b",
                field_name
            ):

                return parse_status(
                    field.value
                )

    return None


# ==========================================
# PROTECCION CONTRA FALSAS ALERTAS
# ==========================================

class StateTracker:

    def __init__(self, initial=None):
        self.last_state = initial
        self.pending_state = None
        self.pending_since = None

    def reset_pending(self):
        self.pending_state = None
        self.pending_since = None

    def observe(self, state, now):

        # Ignorar Partial o estados desconocidos.

        if state not in ("up", "down"):

            self.reset_pending()
            return None

        # Primer estado conocido.

        if self.last_state is None:

            self.last_state = state
            return "initial"

        # Sin cambio de estado.

        if state == self.last_state:

            self.reset_pending()
            return None

        # Nuevo cambio detectado.

        if self.pending_state != state:

            self.pending_state = state
            self.pending_since = now

            return None

        # Confirmar durante 90 segundos.

        if (
            self.pending_since is not None
            and now - self.pending_since
            >= CONFIRM_SECONDS
        ):

            return state

        return None

    def mark_sent(self, state):

        self.last_state = state
        self.reset_pending()


# ==========================================
# CLIENTE DISCORD
# ==========================================

intents = discord.Intents.default()
intents.message_content = True


class AlertClient(discord.Client):

    def __init__(self):

        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(
            self
        )

        self.lock = asyncio.Lock()

        self.tracker = None
        self.monitor_task = None

    async def setup_hook(self):

        init_db()

        saved = setting("last_state")

        self.tracker = StateTracker(
            saved if saved in ("up", "down")
            else None
        )

        commands = await self.tree.sync(
            guild=GUILD
        )

        log.info(
            "Comandos registrados: %s",
            ", ".join(
                command.name
                for command in commands
            )
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = AlertClient()


# ==========================================
# CREAR ALERTAS AUTOMATICAS
# ==========================================

def alert_embed(state, test=False):

    if state == "down":

        title = (
            "🚨 SERVER DOWN | LA VENGANZA RP"
        )

        description = (
            "🔴 **LA CIUDAD SE ENCUENTRA "
            "FUERA DE SERVICIO**\n\n"
            "🛠️ El servidor no está disponible "
            "en este momento.\n\n"
            "📢 Informaremos cuando vuelva "
            "a funcionar.\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • "
            "El rol más duro*"
        )

        color = 0xFF0000

    elif state == "up":

        title = (
            "🟢 SERVER RESTORED | LA VENGANZA RP"
        )

        description = (
            "✅ **¡LA CIUDAD ESTÁ DISPONIBLE "
            "NUEVAMENTE!**\n\n"
            "🌴 ¡Mi gente, ya pueden volver "
            "a entrar!\n\n"
            "🎮 **CONÉCTATE AQUÍ:**\n"
            f"{CONNECT_URL}\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • "
            "El rol más duro*"
        )

        color = 0x22C55E

    else:

        raise ValueError(
            "Estado no válido."
        )

    if test:

        title = "🧪 PRUEBA | " + title

        description = (
            "⚠️ **SIMULACIÓN: NO REPRESENTA "
            "EL ESTADO REAL DEL SERVIDOR.**\n\n"
            + description
        )

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    embed.set_footer(
        text=(
            "La Venganza RP | "
            "Sistema de Alertas"
        )
    )

    return embed


# ==========================================
# PUBLICAR MEDIANTE WEBHOOK
# ==========================================

async def post_embed(embed):

    payload = {
        "username": "La Venganza RP | Alertas",
        "allowed_mentions": {
            "parse": []
        },
        "embeds": [
            embed.to_dict()
        ]
    }

    timeout = aiohttp.ClientTimeout(
        total=20
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            WEBHOOK_URL,
            json=payload
        ) as response:

            if response.status not in (
                200,
                204
            ):

                error = await response.text()

                raise RuntimeError(
                    f"Webhook HTTP "
                    f"{response.status}: "
                    f"{error[:120]}"
                )


async def send_alert(state, test=False):

    await post_embed(
        alert_embed(
            state,
            test=test
        )
    )

    log.info(
        "Alerta enviada: %s (prueba=%s)",
        state,
        test
    )


# ==========================================
# CONSULTAR EL PANEL CONNECT
# ==========================================

async def fetch_panel_state():

    channel = await client.fetch_channel(
        CONNECT_CHANNEL_ID
    )

    message = await channel.fetch_message(
        PANEL_MESSAGE_ID
    )

    return detect_status(message)


# ==========================================
# MONITOR AUTOMATICO
# ==========================================

async def monitor_server():

    await client.wait_until_ready()

    log.info(
        "Monitor iniciado; panel %s",
        PANEL_MESSAGE_ID
    )

    last_observed = object()

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

                # Suspender alertas durante mantenimiento.

                if setting(
                    "maintenance_active",
                    "0"
                ) == "1":

                    client.tracker.reset_pending()

                else:

                    event = client.tracker.observe(
                        state,
                        time.monotonic()
                    )

                    if event == "initial":

                        put_setting(
                            "last_state",
                            client.tracker.last_state
                        )

                        log.info(
                            "Estado inicial: %s",
                            client.tracker.last_state
                        )

                    elif event in ("up", "down"):

                        # Confirmar solo después de
                        # publicar correctamente.

                        await send_alert(
                            event
                        )

                        outage_confirmed(
                            event
                        )

                        client.tracker.mark_sent(
                            event
                        )

                        log.info(
                            "Cambio confirmado: %s",
                            event
                        )

        except (
            discord.Forbidden,
            discord.NotFound
        ):

            log.exception(
                "No se puede acceder al panel original."
            )

        except Exception:

            log.exception(
                "Error consultando el panel."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# PERMISOS ADMINISTRATIVOS
# ==========================================

async def only_admin(interaction):

    if (
        not interaction.guild
        or interaction.guild.id != GUILD_ID
    ):

        raise app_commands.CheckFailure(
            "Servidor incorrecto."
        )

    if not interaction.user.guild_permissions.administrator:

        raise app_commands.MissingPermissions(
            ["administrator"]
        )

    return True


# ==========================================
# COMANDO /TESTALERT
# ==========================================

@client.tree.command(
    name="testalert",
    description=(
        "Enviar una alerta de prueba "
        "al canal configurado."
    )
)
@app_commands.guilds(GUILD)
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

    await interaction.response.defer(
        ephemeral=True
    )

    await send_alert(
        estado.value,
        test=True
    )

    await interaction.followup.send(
        "✅ Prueba enviada sin modificar "
        "el monitor.",
        ephemeral=True
    )


# ==========================================
# SIMULAR CAIDA Y RECUPERACION
# ==========================================

def simulated_cycle():

    tracker = StateTracker()

    assert tracker.observe(
        "up", 0
    ) == "initial"

    assert tracker.observe(
        "down", 10
    ) is None

    assert tracker.observe(
        "up", 30
    ) is None

    assert tracker.observe(
        "partial", 40
    ) is None

    assert tracker.observe(
        "down", 100
    ) is None

    assert tracker.observe(
        "down", 189
    ) is None

    assert tracker.observe(
        "down", 190
    ) == "down"

    tracker.mark_sent("down")

    assert tracker.observe(
        "down", 240
    ) is None

    assert tracker.observe(
        "partial", 245
    ) is None

    assert tracker.observe(
        "up", 300
    ) is None

    assert tracker.observe(
        "up", 389
    ) is None

    assert tracker.observe(
        "up", 390
    ) == "up"

    tracker.mark_sent("up")

    assert tracker.observe(
        "up", 450
    ) is None


# ==========================================
# COMANDO /SIMULAR-CICLO
# ==========================================

@client.tree.command(
    name="simular-ciclo",
    description=(
        "Probar caída y recuperación "
        "sin apagar FiveM."
    )
)
@app_commands.guilds(GUILD)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.check(only_admin)
async def simular_ciclo(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    simulated_cycle()

    await send_alert(
        "down",
        test=True
    )

    await send_alert(
        "up",
        test=True
    )

    await interaction.followup.send(
        "✅ **Simulación completada**\n\n"
        "🔴 Server Down: enviado.\n"
        "🟢 Server Restored: enviado.\n"
        "🟠 Partial: ignorado.\n"
        "🛡️ Duplicados: bloqueados.\n\n"
        "El estado real no fue modificado.",
        ephemeral=True
    )


# ==========================================
# GRUPO /MANTENIMIENTO
# ==========================================

maintenance_group = app_commands.Group(
    name="mantenimiento",
    description=(
        "Publicar y finalizar "
        "mantenimientos manuales."
    ),
    guild_ids=[GUILD_ID],
    default_permissions=discord.Permissions(
        administrator=True
    )
)


# ==========================================
# /MANTENIMIENTO INICIAR
# ==========================================

@maintenance_group.command(
    name="iniciar",
    description=(
        "Anunciar el inicio "
        "de un mantenimiento."
    )
)
@app_commands.describe(
    motivo="Motivo breve del mantenimiento"
)
@app_commands.check(only_admin)
async def mantenimiento_iniciar(
    interaction: discord.Interaction,
    motivo: str
):

    await interaction.response.defer(
        ephemeral=True
    )

    motivo = motivo.strip()[:300]

    if not motivo:

        await interaction.followup.send(
            "❌ Escribe un motivo.",
            ephemeral=True
        )

        return

    async with client.lock:

        if setting(
            "maintenance_active",
            "0"
        ) == "1":

            await interaction.followup.send(
                "⚠️ Ya existe un mantenimiento activo.",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title=(
                "🛠️ MANTENIMIENTO INICIADO "
                "| LA VENGANZA RP"
            ),
            description=(
                "🔧 **Motivo:** "
                f"{discord.utils.escape_markdown(motivo)}"
                "\n\n"
                "⛔ El acceso a la ciudad podría "
                "estar limitado temporalmente.\n\n"
                "📢 Avisaremos cuando termine "
                "el mantenimiento."
            ),
            color=0xF59E0B
        )

        embed.set_footer(
            text=(
                "La Venganza RP | Administración"
            )
        )

        await post_embed(embed)

        with connect_db() as db:

            # Si había una caída abierta,
            # cerrarla como interrumpida.
            # No atribuir al incidente el
            # tiempo del mantenimiento.

            db.execute(
                """
                UPDATE outages
                SET ended=?,
                    duration_seconds=NULL
                WHERE ended IS NULL
                """,
                (stamp(),)
            )

            db.execute(
                """
                INSERT INTO maintenance
                (started, reason, author_id)
                VALUES (?, ?, ?)
                """,
                (
                    stamp(),
                    motivo,
                    str(interaction.user.id)
                )
            )

            db.execute(
                """
                INSERT OR REPLACE INTO settings
                (key, value)
                VALUES (?, ?)
                """,
                (
                    "maintenance_active",
                    "1"
                )
            )

        client.tracker.reset_pending()

    await interaction.followup.send(
        "✅ Mantenimiento anunciado.\n"
        "Las alertas automáticas "
        "están suspendidas.",
        ephemeral=True
    )


# ==========================================
# /MANTENIMIENTO FINALIZAR
# ==========================================

@maintenance_group.command(
    name="finalizar",
    description=(
        "Anunciar el final "
        "de un mantenimiento."
    )
)
@app_commands.check(only_admin)
async def mantenimiento_finalizar(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    async with client.lock:

        if setting(
            "maintenance_active",
            "0"
        ) != "1":

            await interaction.followup.send(
                "⚠️ No hay mantenimiento activo.",
                ephemeral=True
            )

            return

        # Consultar el estado actual
        # sin asumir que Partial es Online.

        try:

            state = await fetch_panel_state()

        except Exception:

            log.exception(
                "No se pudo consultar el estado "
                "al terminar mantenimiento."
            )

            state = None

        embed = discord.Embed(
            title=(
                "✅ MANTENIMIENTO FINALIZADO "
                "| LA VENGANZA RP"
            ),
            description=(
                "🛠️ La administración ha "
                "finalizado los trabajos "
                "anunciados.\n\n"
                "📡 Consulta el panel de Connect "
                "para conocer el estado actual.\n\n"
                f"🎮 {CONNECT_URL}"
            ),
            color=0x22C55E
        )

        embed.set_footer(
            text=(
                "La Venganza RP | Administración"
            )
        )

        await post_embed(embed)

        with connect_db() as db:

            db.execute(
                """
                UPDATE maintenance
                SET ended=?
                WHERE ended IS NULL
                """,
                (stamp(),)
            )

            db.execute(
                """
                INSERT OR REPLACE INTO settings
                (key, value)
                VALUES (?, ?)
                """,
                (
                    "maintenance_active",
                    "0"
                )
            )

            # Reiniciar referencia del monitor
            # después del mantenimiento.

            db.execute(
                """
                INSERT OR REPLACE INTO settings
                (key, value)
                VALUES (?, ?)
                """,
                (
                    "last_state",
                    state if state in (
                        "up",
                        "down"
                    ) else ""
                )
            )

        client.tracker = StateTracker(
            state if state in (
                "up",
                "down"
            ) else None
        )

    await interaction.followup.send(
        "✅ Finalización publicada.\n"
        "Monitor reactivado.",
        ephemeral=True
    )


# Registrar grupo de mantenimiento

client.tree.add_command(
    maintenance_group
)


# ==========================================
# /HISTORIAL-CAIDAS
# ==========================================

@client.tree.command(
    name="historial-caidas",
    description=(
        "Ver las últimas caídas "
        "detectadas del servidor."
    )
)
@app_commands.guilds(GUILD)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.check(only_admin)
async def historial_caidas(
    interaction: discord.Interaction
):

    with connect_db() as db:

        rows = db.execute(
            """
            SELECT
                id,
                started,
                ended,
                duration_seconds
            FROM outages
            ORDER BY id DESC
            LIMIT 10
            """
        ).fetchall()

    if not rows:

        text = (
            "📊 Todavía no hay caídas "
            "reales registradas.\n\n"
            "Las simulaciones no cuentan."
        )

    else:

        lines = []

        for (
            incident_id,
            started,
            ended,
            seconds
        ) in rows:

            started_epoch = int(
                datetime.fromisoformat(
                    started
                ).timestamp()
            )

            if ended is None:

                result = "🔴 En curso"

            elif seconds is None:

                result = (
                    "⚪ Interrumpida por mantenimiento; "
                    "duración no registrada"
                )

            else:

                result = (
                    "✅ Duración: "
                    f"{elapsed(started, ended)}"
                )

            lines.append(
                f"**#{incident_id}** "
                f"<t:{started_epoch}:f> — "
                f"{result}"
            )

        text = (
            "📊 **ÚLTIMAS CAÍDAS CONFIRMADAS**\n\n"
            + "\n".join(lines)
        )

    await interaction.response.send_message(
        text,
        ephemeral=True
    )


# ==========================================
# ERRORES DE COMANDOS
# ==========================================

@client.tree.error
async def command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    log.error(
        "Error de comando: %s",
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
            "pueden usar este comando."
        )

    else:

        message = (
            "❌ No se completó la acción. "
            "Revisa Railway."
        )

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


# ==========================================
# BOT CONECTADO
# ==========================================

@client.event
async def on_ready():

    log.info(
        "Bot conectado como %s",
        client.user
    )

    if DATA_DIR == "/tmp":

        log.warning(
            "Datos en /tmp: conecta un "
            "volumen Railway para persistencia."
        )


# ==========================================
# INICIAR BOT
# ==========================================

if __name__ == "__main__":

    client.run(
        TOKEN,
        log_handler=None
    )
