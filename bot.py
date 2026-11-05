
import asyncio
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

# ==========================================
# LA VENGANZA RP | ALERTAS AUTOMATICAS
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LaVenganzaRP")

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

STATE_FILE = Path(
    os.getenv(
        "STATE_FILE",
        "/tmp/la_venganza_alert_state.json"
    )
)

GUILD = discord.Object(id=GUILD_ID)

# ==========================================
# LIMPIAR TEXTO
# ==========================================

def clean_text(value):
    text = unicodedata.normalize(
        "NFKC",
        str(value or "")
    )

    for marker in ("```", "`", "**", "__"):
        text = text.replace(marker, "")

    return text.strip().lower()


# ==========================================
# DETECTAR ONLINE / OFFLINE / PARTIAL
# ==========================================

def parse_status(value):
    text = clean_text(value)

    if re.search(
        r"\b(partial|degraded|parcial)\b",
        text
    ):
        return "partial"

    if re.search(
        r"\b(offline|down|cerrado|caido|caído)\b",
        text
    ):
        return "down"

    if re.search(
        r"\b(online|up|abierto|operativo)\b",
        text
    ):
        return "up"

    return None


# ==========================================
# LEER PANEL ORIGINAL DE TXADMIN
# ==========================================

def detect_status(message):
    for embed in message.embeds:
        for field in embed.fields:
            field_name = clean_text(field.name)

            if re.search(
                r"\b(status|estado)\b",
                field_name
            ):
                return parse_status(field.value)

    return None


# ==========================================
# MAQUINA DE ESTADOS
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

        # Partial y valores desconocidos
        # nunca generan alertas.

        if state not in ("up", "down"):
            self.reset_pending()
            return None

        # Primer estado reconocido.

        if self.last_state is None:
            self.last_state = state
            self.reset_pending()
            return "baseline"

        # No hubo cambio.

        if state == self.last_state:
            self.reset_pending()
            return None

        # Empezar confirmacion.

        if self.pending_state != state:
            self.pending_state = state
            self.pending_since = now
            return None

        # Confirmar despues de 90 segundos.

        if (
            self.pending_since is not None
            and now - self.pending_since
            >= CONFIRM_SECONDS
        ):
            return state

        return None

    def confirm_sent(self, state):
        self.last_state = state
        self.reset_pending()


# ==========================================
# CARGAR DATOS GUARDADOS
# ==========================================

def load_state():
    try:
        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

    except (OSError, ValueError, TypeError):
        pass

    return {}


saved = load_state()

initial = saved.get("state")

if initial not in ("up", "down"):
    initial = None

tracker = StateTracker(initial=initial)

# ==========================================
# ESTADO DEL MANTENIMIENTO
# ==========================================

maintenance = {
    "active": (
        saved.get("maintenance_active") is True
    ),
    "reason": str(
        saved.get("maintenance_reason") or ""
    ),
    "started_at": str(
        saved.get("maintenance_started_at") or ""
    ),
    "started_by": str(
        saved.get("maintenance_started_by") or ""
    )
}

state_lock = asyncio.Lock()


def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")


# ==========================================
# GUARDAR ESTADO
# ==========================================

def save_state():
    data = {
        "state": tracker.last_state,
        "maintenance_active": maintenance["active"],
        "maintenance_reason": maintenance["reason"],
        "maintenance_started_at": maintenance["started_at"],
        "maintenance_started_by": maintenance["started_by"]
    }

    try:
        STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary = STATE_FILE.with_name(
            STATE_FILE.name + ".tmp"
        )

        temporary.write_text(
            json.dumps(
                data,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

        os.replace(
            temporary,
            STATE_FILE
        )

    except OSError:
        logger.exception(
            "No se pudo guardar el estado local"
        )


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
            "🛠️ Mi gente, el servidor se encuentra "
            "temporalmente fuera de servicio.\n\n"
            "🔧 Nuestro equipo estará verificando "
            "la situación.\n\n"
            "📢 Avisaremos cuando la ciudad esté "
            "disponible nuevamente.\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0xFF0000

    elif state == "up":

        title = (
            "🟢 SERVER RESTORED | LA VENGANZA RP"
        )

        description = (
            "✅ **¡LA CIUDAD ESTÁ DISPONIBLE "
            "NUEVAMENTE!**\n\n"
            "🌴 ¡Mi gente, ya estamos de vuelta!\n\n"
            "🚗 Preparen sus máquinas y entren "
            "a disfrutar del roleplay.\n\n"
            "🎮 **CONÉCTATE AQUÍ:**\n"
            f"{CONNECT_URL}\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0x22C55E

    else:
        raise ValueError("Estado inválido")

    if test:
        title = "🧪 PRUEBA | " + title

        description = (
            "⚠️ **SIMULACIÓN DEL BOT. "
            "NO REPRESENTA EL ESTADO REAL "
            "DEL SERVIDOR.**\n\n"
            + description
        )

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    embed.set_footer(
        text="La Venganza RP | Sistema de Alertas"
    )

    return embed


# ==========================================
# CREAR COMUNICADOS DE MANTENIMIENTO
# ==========================================

def maintenance_embed(
    action,
    reason="",
    started_at=""
):

    if action == "start":

        title = (
            "🛠️ MANTENIMIENTO INICIADO "
            "| LA VENGANZA RP"
        )

        description = (
            "⚠️ **AVISO OFICIAL**\n\n"
            "Mi gente, la administración ha "
            "iniciado un mantenimiento en "
            "nuestra ciudad.\n\n"
            "🔧 Estaremos realizando ajustes "
            "y mejoras en el servidor.\n\n"
            "⛔ Durante este proceso podrían "
            "presentarse interrupciones de acceso.\n\n"
            f"📋 **Motivo:** "
            f"{discord.utils.escape_mentions(reason)}\n\n"
            "📢 Les notificaremos cuando "
            "finalice el mantenimiento.\n\n"
            "❤️ Gracias por la paciencia "
            "y el apoyo de siempre.\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0xF59E0B

    else:

        title = (
            "✅ MANTENIMIENTO FINALIZADO "
            "| LA VENGANZA RP"
        )

        description = (
            "🛠️ **MANTENIMIENTO FINALIZADO**\n\n"
            "Mi gente, la administración ha "
            "dado por finalizados los trabajos "
            "de mantenimiento.\n\n"
            "✅ Los ajustes programados "
            "han concluido.\n\n"
            "🎮 **COMPRUEBA EL ACCESO AQUÍ:**\n"
            f"{CONNECT_URL}\n\n"
            "❤️ Gracias por la paciencia.\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0x22C55E

    embed = discord.Embed(
        title=title,
        description=description,
        color=color
    )

    embed.set_footer(
        text="La Venganza RP | Aviso administrativo"
    )

    return embed


# ==========================================
# ENVIAR WEBHOOK A ALERTAS-SERVIDOR
# ==========================================

async def post_webhook(embed):

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
                raise RuntimeError(
                    "Webhook devolvió HTTP "
                    f"{response.status}"
                )


async def send_alert(state, test=False):

    embed = alert_embed(
        state,
        test=test
    )

    await post_webhook(embed)

    logger.info(
        "Alerta enviada: %s; prueba=%s",
        state,
        test
    )


# ==========================================
# OBTENER ESTADO ACTUAL DEL PANEL
# ==========================================

async def fetch_panel_status():

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

    logger.info(
        "Monitor iniciado | Connect: %s",
        CONNECT_CHANNEL_ID
    )

    logger.info(
        "Mensaje original: %s",
        PANEL_MESSAGE_ID
    )

    last_observed = None

    while not client.is_closed():

        try:

            current_state = await fetch_panel_status()

            async with state_lock:

                if current_state != last_observed:

                    logger.info(
                        "Estado observado: %s",
                        current_state
                    )

                    last_observed = current_state

                # Durante mantenimiento no
                # se envian alertas automaticas.

                if maintenance["active"]:

                    tracker.reset_pending()

                else:

                    event = tracker.observe(
                        current_state,
                        time.monotonic()
                    )

                    if event == "baseline":

                        save_state()

                        logger.info(
                            "Estado inicial: %s",
                            tracker.last_state
                        )

                    elif event in ("up", "down"):

                        await send_alert(event)

                        tracker.confirm_sent(event)

                        save_state()

                        logger.info(
                            "Cambio confirmado: %s",
                            event
                        )

        except discord.Forbidden:

            logger.error(
                "Sin permisos para leer Connect"
            )

        except discord.NotFound:

            logger.error(
                "No se encontro el panel original"
            )

        except Exception:

            logger.exception(
                "Error leyendo el panel "
                "o enviando una alerta"
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# SIMULACION SIN APAGAR FIVE M
# ==========================================

def run_simulation():

    simulated = StateTracker()

    assert simulated.observe(
        "up", 0
    ) == "baseline"

    assert simulated.observe(
        "down", 10
    ) is None

    assert simulated.observe(
        "up", 50
    ) is None

    assert simulated.observe(
        "down", 100
    ) is None

    assert simulated.observe(
        "down", 189
    ) is None

    assert simulated.observe(
        "down", 190
    ) == "down"

    simulated.confirm_sent("down")

    assert simulated.observe(
        "down", 220
    ) is None

    assert simulated.observe(
        "partial", 250
    ) is None

    assert simulated.observe(
        "up", 300
    ) is None

    assert simulated.observe(
        "up", 390
    ) == "up"

    simulated.confirm_sent("up")

    assert simulated.observe(
        "up", 420
    ) is None

    return True


# ==========================================
# CLIENTE DE DISCORD
# ==========================================

class AlertClient(discord.Client):

    def __init__(self):

        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            intents=intents
        )

        self.tree = app_commands.CommandTree(self)
        self.monitor_task = None

    async def setup_hook(self):

        synced = await self.tree.sync(
            guild=GUILD
        )

        logger.info(
            "Comandos sincronizados: %s",
            [command.name for command in synced]
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = AlertClient()


# ==========================================
# COMANDO /TESTALERT
# ==========================================

@client.tree.command(
    name="testalert",
    description="Enviar una alerta de prueba"
)
@app_commands.guilds(GUILD)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.checks.has_permissions(
    administrator=True
)
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

    try:

        await send_alert(
            estado.value,
            test=True
        )

        await interaction.followup.send(
            "✅ Alerta de prueba enviada "
            "a Alertas-Servidor.",
            ephemeral=True
        )

    except Exception:

        logger.exception(
            "Error ejecutando /testalert"
        )

        await interaction.followup.send(
            "❌ Falló el envío. Revisa Railway.",
            ephemeral=True
        )


# ==========================================
# COMANDO /SIMULAR-CICLO
# ==========================================

@client.tree.command(
    name="simular-ciclo",
    description=(
        "Simular una caida y recuperacion "
        "sin apagar FiveM"
    )
)
@app_commands.guilds(GUILD)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def simular_ciclo(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    try:

        run_simulation()

        await send_alert(
            "down",
            test=True
        )

        await send_alert(
            "up",
            test=True
        )

        await interaction.followup.send(
            "✅ **SIMULACIÓN COMPLETADA**\n\n"
            "🔴 Server Down: enviado.\n"
            "🟢 Server Restored: enviado.\n"
            "🟠 Partial: ignorado.\n"
            "🛡️ Duplicados: bloqueados.\n"
            "⏱️ Confirmación: 90 segundos "
            "simulados.\n\n"
            "El estado real no fue modificado.",
            ephemeral=True
        )

    except Exception:

        logger.exception(
            "Error ejecutando /simular-ciclo"
        )

        await interaction.followup.send(
            "❌ Simulación fallida. Revisa Railway.",
            ephemeral=True
        )


# ==========================================
# GRUPO /MANTENIMIENTO
# ==========================================

maintenance_group = app_commands.Group(
    name="mantenimiento",
    description="Comunicados manuales de mantenimiento",
    guild_only=True,
    default_permissions=discord.Permissions(
        administrator=True
    )
)


# ==========================================
# /MANTENIMIENTO INICIAR
# ==========================================

@maintenance_group.command(
    name="iniciar",
    description="Anunciar inicio de mantenimiento"
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    motivo="Motivo del mantenimiento"
)
async def mantenimiento_iniciar(
    interaction: discord.Interaction,
    motivo: str
):

    await interaction.response.defer(
        ephemeral=True
    )

    motivo = motivo.strip()

    if not motivo or len(motivo) > 250:

        await interaction.followup.send(
            "❌ El motivo debe tener entre "
            "1 y 250 caracteres.",
            ephemeral=True
        )

        return

    async with state_lock:

        if maintenance["active"]:

            await interaction.followup.send(
                "⚠️ Ya existe un mantenimiento activo.",
                ephemeral=True
            )

            return

        try:

            embed = maintenance_embed(
                "start",
                reason=motivo
            )

            await post_webhook(embed)

            maintenance.update({
                "active": True,
                "reason": motivo,
                "started_at": utc_now(),
                "started_by": str(
                    interaction.user.id
                )
            })

            tracker.reset_pending()

            save_state()

        except Exception:

            logger.exception(
                "Error anunciando mantenimiento"
            )

            await interaction.followup.send(
                "❌ No se pudo anunciar el "
                "mantenimiento. Revisa Railway.",
                ephemeral=True
            )

            return

    await interaction.followup.send(
        "✅ **MANTENIMIENTO INICIADO**\n\n"
        "El comunicado fue publicado en "
        "Alertas-Servidor.\n\n"
        "🛡️ Las alertas automáticas quedan "
        "suspendidas mientras dure "
        "el mantenimiento.",
        ephemeral=True
    )


# ==========================================
# /MANTENIMIENTO FINALIZAR
# ==========================================

@maintenance_group.command(
    name="finalizar",
    description="Anunciar fin de mantenimiento"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def mantenimiento_finalizar(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    async with state_lock:

        if not maintenance["active"]:

            await interaction.followup.send(
                "ℹ️ No hay mantenimiento activo.",
                ephemeral=True
            )

            return

        try:

            # Publicar finalizacion.
            # Esto no confirma por si mismo
            # que el servidor este Online.

            embed = maintenance_embed("end")

            await post_webhook(embed)

            # Crear una nueva referencia de estado
            # sin publicar alertas retrasadas.

            try:

                observed = await fetch_panel_status()

            except Exception:

                logger.exception(
                    "No se pudo consultar el panel "
                    "al finalizar mantenimiento"
                )

                observed = None

            if observed in ("up", "down"):

                tracker.last_state = observed

            else:

                tracker.last_state = None

            tracker.reset_pending()

            maintenance.update({
                "active": False,
                "reason": "",
                "started_at": "",
                "started_by": ""
            })

            save_state()

        except Exception:

            logger.exception(
                "Error finalizando mantenimiento"
            )

            await interaction.followup.send(
                "❌ No se pudo anunciar el fin "
                "del mantenimiento. Revisa Railway.",
                ephemeral=True
            )

            return

    await interaction.followup.send(
        "✅ **MANTENIMIENTO FINALIZADO**\n\n"
        "El comunicado fue publicado "
        "en Alertas-Servidor.\n\n"
        "🟢 El monitoreo automático "
        "se ha reanudado.",
        ephemeral=True
    )


# ==========================================
# /MANTENIMIENTO ESTADO
# ==========================================

@maintenance_group.command(
    name="estado",
    description="Consultar mantenimiento actual"
)
@app_commands.checks.has_permissions(
    administrator=True
)
async def mantenimiento_estado(
    interaction: discord.Interaction
):

    async with state_lock:

        if maintenance["active"]:

            reply = (
                "🛠️ **MANTENIMIENTO ACTIVO**\n\n"
                "📋 **Motivo:** "
                f"{discord.utils.escape_mentions(maintenance['reason'])}\n"
                "🕒 **Inicio UTC:** "
                f"{maintenance['started_at']}"
            )

        else:

            reply = (
                "🟢 No hay mantenimiento "
                "manual activo."
            )

    await interaction.response.send_message(
        reply,
        ephemeral=True
    )


# ==========================================
# REGISTRAR GRUPO DE COMANDOS
# ==========================================

client.tree.add_command(
    maintenance_group,
    guild=GUILD
)


# ==========================================
# MANEJAR ERRORES DE COMANDOS
# ==========================================

@client.tree.error
async def on_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        reply = (
            "❌ Necesitas permisos "
            "de administrador."
        )

    else:

        logger.error(
            "Error en comando: %r",
            error
        )

        reply = (
            "❌ Ocurrió un error. "
            "Revisa los registros de Railway."
        )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                reply,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                reply,
                ephemeral=True
            )

    except discord.HTTPException:

        logger.exception(
            "No se pudo informar del error"
        )


# ==========================================
# BOT CONECTADO
# ==========================================

@client.event
async def on_ready():

    logger.info(
        "Bot conectado como %s",
        client.user
    )

    if maintenance["active"]:

        logger.warning(
            "Mantenimiento activo recuperado "
            "del estado guardado"
        )


# ==========================================
# INICIAR BOT
# ==========================================

if __name__ == "__main__":

    client.run(
        TOKEN,
        log_handler=None
    )
