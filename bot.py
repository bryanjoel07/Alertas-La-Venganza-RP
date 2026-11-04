
import asyncio
import json
import logging
import os
import re
import time
import unicodedata

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
# CONFIGURACION
# ==========================================

GUILD_ID = 1244988345327550565

CONNECT_CHANNEL_ID = 1513421828415164546

PANEL_MESSAGE_ID = 1536621817471696907

ALERT_CHANNEL_ID = 1567618111920807987

CONNECT_URL = "https://cfx.re/join/57vjg7"

CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90

STATE_FILE = os.getenv(
    "STATE_FILE",
    "/tmp/la_venganza_alert_state.json"
)

GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.message_content = True

# ==========================================
# CLIENTE DE DISCORD
# ==========================================

class AlertClient(discord.Client):

    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.monitor_task = None

    async def setup_hook(self):
        self.tree.copy_global_to(guild=GUILD)

        commands = await self.tree.sync(guild=GUILD)

        logger.info(
            "Comandos sincronizados: %s",
            len(commands)
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = AlertClient()

last_state = None
pending_state = None
pending_since = None
last_observed_state = None


# ==========================================
# LIMPIAR TEXTO
# ==========================================

def clean_text(value):
    text = str(value or "")

    text = unicodedata.normalize(
        "NFKC",
        text
    )

    text = text.replace("```", "")
    text = text.replace("`", "")
    text = text.replace("**", "")
    text = text.replace("__", "")

    return text.strip().lower()


# ==========================================
# DETECTAR ESTADO
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
# LEER PANEL ORIGINAL
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
# ESTADO GUARDADO
# ==========================================

def load_state():

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        state = data.get("state")

        if state in ("up", "down"):
            return state

    except (
        OSError,
        ValueError,
        TypeError
    ):
        pass

    return None


def save_state(state):

    try:

        directory = os.path.dirname(
            STATE_FILE
        )

        if directory:
            os.makedirs(
                directory,
                exist_ok=True
            )

        temporary_file = STATE_FILE + ".tmp"

        with open(
            temporary_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                {"state": state},
                file
            )

        os.replace(
            temporary_file,
            STATE_FILE
        )

    except OSError:

        logger.warning(
            "No se pudo guardar el estado."
        )


# ==========================================
# CREAR EMBED
# ==========================================

def create_alert_embed(state, test=False):

    if state == "down":

        title = (
            "🚨 SERVER DOWN | LA VENGANZA RP"
        )

        description = (
            "🔴 **LA CIUDAD SE ENCUENTRA "
            "FUERA DE SERVICIO**\n\n"
            "🛠️ Mi gente, nuestro servidor "
            "se encuentra temporalmente "
            "fuera de servicio.\n\n"
            "🔧 Nuestro equipo estará "
            "verificando la situación.\n\n"
            "📢 Les notificaremos cuando "
            "la ciudad esté disponible "
            "nuevamente.\n\n"
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
            "✅ **¡LA CIUDAD ESTÁ "
            "DISPONIBLE NUEVAMENTE!**\n\n"
            "🌴 ¡Mi gente, ya estamos de vuelta!\n\n"
            "🚗 Preparen sus máquinas, "
            "reúnan al corillo y entren "
            "a disfrutar del roleplay.\n\n"
            "🎮 **CONÉCTATE AQUÍ:**\n"
            f"{CONNECT_URL}\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • "
            "El rol más duro*"
        )

        color = 0x22C55E

    else:

        raise ValueError(
            "Estado no valido"
        )

    if test:

        title = "🧪 PRUEBA | " + title

        description = (
            "⚠️ **ESTO ES UNA PRUEBA DEL BOT.**\n"
            "**NO REPRESENTA EL ESTADO REAL "
            "DEL SERVIDOR.**\n\n"
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
# ENVIAR ALERTA POR WEBHOOK
# ==========================================

async def send_alert(state, test=False):

    embed = create_alert_embed(
        state,
        test=test
    )

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
                    f"{error[:150]}"
                )

    logger.info(
        "Alerta enviada: %s | Prueba: %s",
        state,
        test
    )

    return True


# ==========================================
# COMANDO /TESTALERT
# ==========================================

@client.tree.command(
    name="testalert",
    description=(
        "Enviar una alerta de prueba "
        "sin cambiar el estado real."
    )
)
@app_commands.guild_only()
@app_commands.default_permissions(
    administrator=True
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    estado="Tipo de alerta que deseas probar"
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
            "a 🚨 Alertas-Servidor.",
            ephemeral=True
        )

    except Exception:

        logger.exception(
            "Error enviando alerta de prueba."
        )

        await interaction.followup.send(
            "❌ No se pudo enviar la alerta. "
            "Revisa los registros de Railway.",
            ephemeral=True
        )


# ==========================================
# ERRORES DE COMANDOS
# ==========================================

@client.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "❌ Solo los administradores "
            "pueden utilizar este comando."
        )

    else:

        logger.error(
            "Error en comando: %s",
            error
        )

        message = (
            "❌ Ocurrio un error "
            "ejecutando el comando."
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
# MONITOREAR TXADMIN
# ==========================================

async def monitor_server():

    global last_state
    global pending_state
    global pending_since
    global last_observed_state

    await client.wait_until_ready()

    last_state = load_state()

    logger.info(
        "Monitor de La Venganza RP iniciado"
    )

    logger.info(
        "Canal de origen: %s",
        CONNECT_CHANNEL_ID
    )

    logger.info(
        "Mensaje original: %s",
        PANEL_MESSAGE_ID
    )

    logger.info(
        "Canal de alertas: %s",
        ALERT_CHANNEL_ID
    )

    while not client.is_closed():

        try:

            channel = await client.fetch_channel(
                CONNECT_CHANNEL_ID
            )

            message = await channel.fetch_message(
                PANEL_MESSAGE_ID
            )

            current_state = detect_status(
                message
            )

            if current_state != last_observed_state:

                logger.info(
                    "Estado observado: %s",
                    current_state
                )

                last_observed_state = current_state

            # ESTADO DESCONOCIDO

            if current_state is None:

                pending_state = None
                pending_since = None

                logger.warning(
                    "Estado no reconocido."
                )

            # PARTIAL NO GENERA ALERTAS

            elif current_state == "partial":

                pending_state = None
                pending_since = None

            # ESTADO INICIAL

            elif last_state is None:

                last_state = current_state

                save_state(
                    current_state
                )

                logger.info(
                    "Estado inicial detectado: %s",
                    current_state
                )

            # SIN CAMBIOS

            elif current_state == last_state:

                pending_state = None
                pending_since = None

            # CAMBIO DETECTADO

            elif pending_state != current_state:

                pending_state = current_state

                pending_since = time.monotonic()

                logger.info(
                    "Cambio detectado: %s",
                    current_state
                )

            # CAMBIO CONFIRMADO

            elif (
                pending_since is not None
                and time.monotonic() - pending_since
                >= CONFIRM_SECONDS
            ):

                await send_alert(
                    current_state
                )

                last_state = current_state

                save_state(
                    current_state
                )

                pending_state = None
                pending_since = None

                logger.info(
                    "Estado actualizado: %s",
                    current_state
                )

        except discord.Forbidden:

            logger.error(
                "Sin permisos para leer Connect."
            )

        except discord.NotFound:

            logger.error(
                "Panel original no encontrado."
            )

        except Exception:

            logger.exception(
                "Error monitoreando el panel."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
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


# ==========================================
# INICIAR BOT
# ==========================================

if __name__ == "__main__":

    client.run(
        TOKEN,
        log_handler=None
    )
