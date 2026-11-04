
import asyncio
import json
import logging
import os
import re
import time
import unicodedata

import aiohttp
import discord

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

STATE_FILE = os.getenv(
    "STATE_FILE",
    "/tmp/la_venganza_alert_state.json"
)

# ==========================================
# CONFIGURACION DISCORD
# ==========================================

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

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
# IDENTIFICAR ESTADOS
# ==========================================

def parse_status(value):
    text = clean_text(value)

    # Evitar interpretar mensajes ambiguos.
    # Partial nunca genera una alerta.

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
# LEER ESTADO DEL PANEL ORIGINAL
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
# GUARDAR ESTADO
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
# ENVIAR ALERTAS A DISCORD
# ==========================================

async def send_alert(state):

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
        return False

    payload = {
        "username": "La Venganza RP | Alertas",
        "allowed_mentions": {
            "parse": []
        },
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {
                    "text": (
                        "La Venganza RP | "
                        "Sistema de Alertas"
                    )
                }
            }
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
        "Alerta enviada: %s",
        state
    )

    return True


# ==========================================
# MONITOREAR PANEL TXADMIN
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

            # Registrar solamente cuando
            # cambia el estado observado.

            if current_state != last_observed_state:

                logger.info(
                    "Estado observado: %s",
                    current_state
                )

                last_observed_state = current_state

            # ==================================
            # ESTADO DESCONOCIDO
            # ==================================

            if current_state is None:

                pending_state = None
                pending_since = None

                logger.warning(
                    "Estado no reconocido. "
                    "No se enviara ninguna alerta."
                )

            # ==================================
            # ESTADO PARTIAL
            # ==================================

            elif current_state == "partial":

                pending_state = None
                pending_since = None

                # Partial no cambia el ultimo
                # estado confirmado.
                # No se envia ningun mensaje.

            # ==================================
            # ESTADO INICIAL
            # ==================================

            elif last_state is None:

                last_state = current_state

                save_state(
                    current_state
                )

                logger.info(
                    "Estado inicial detectado: %s",
                    current_state
                )

            # ==================================
            # SIN CAMBIOS
            # ==================================

            elif current_state == last_state:

                pending_state = None
                pending_since = None

            # ==================================
            # NUEVO CAMBIO
            # ==================================

            elif pending_state != current_state:

                pending_state = current_state

                pending_since = time.monotonic()

                logger.info(
                    "Cambio detectado: %s. "
                    "Confirmando durante %s segundos.",
                    current_state,
                    CONFIRM_SECONDS
                )

            # ==================================
            # CAMBIO CONFIRMADO
            # ==================================

            elif (
                pending_since is not None
                and time.monotonic() - pending_since
                >= CONFIRM_SECONDS
            ):

                logger.info(
                    "Cambio confirmado: %s",
                    current_state
                )

                success = await send_alert(
                    current_state
                )

                if success:

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
                "El bot no tiene permisos "
                "para leer Connect."
            )

        except discord.NotFound:

            logger.error(
                "No se encontro el panel "
                "original de txAdmin."
            )

        except Exception:

            logger.exception(
                "Error monitoreando el servidor."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# EVENTOS DEL BOT
# ==========================================

@client.event
async def on_ready():

    logger.info(
        "Bot conectado como %s",
        client.user
    )


# ==========================================
# INICIAR SISTEMA
# ==========================================

async def main():

    async with client:

        await client.login(
            TOKEN
        )

        monitor_task = asyncio.create_task(
            monitor_server()
        )

        try:

            await client.connect(
                reconnect=True
            )

        finally:

            monitor_task.cancel()

            await asyncio.gather(
                monitor_task,
                return_exceptions=True
            )


if __name__ == "__main__":

    asyncio.run(main())
