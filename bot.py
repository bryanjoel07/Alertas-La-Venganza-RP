
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

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

GUILD_ID = 1244988345327550565
CHANNEL_ID = 1513421828415164546
MESSAGE_ID = 1536621817471696907

CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90

# Almacenamiento local para reinicios del proceso.
# Para persistencia entre despliegues de Railway,
# se requiere un volumen persistente.
STATE_FILE = os.getenv(
    "STATE_FILE",
    "/tmp/la_venganza_alert_state.json"
)

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

last_state = None
pending_state = None
pending_since = None


# ==========================================
# LIMPIAR TEXTO
# ==========================================

def clean_text(value):
    text = str(value or "")

    text = unicodedata.normalize("NFKC", text)

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

    down_words = (
        "offline",
        "down",
        "cerrado",
        "caido",
        "caído",
        "desconectado"
    )

    up_words = (
        "online",
        "up",
        "abierto",
        "operativo",
        "conectado"
    )

    # El estado debe aparecer como un valor
    # aislado, con emojis o formato adicional.
    text = re.sub(
        r"^[^\w]+",
        "",
        text
    )

    for word in down_words:
        if re.search(
            rf"\b{re.escape(word)}\b",
            text
        ):
            return "down"

    for word in up_words:
        if re.search(
            rf"\b{re.escape(word)}\b",
            text
        ):
            return "up"

    return None


# ==========================================
# LEER EL PANEL ORIGINAL
# ==========================================

def detect_status(message):
    for embed in message.embeds:
        for field in embed.fields:
            name = clean_text(field.name)

            if re.search(
                r"\b(status|estado)\b",
                name
            ):
                state = parse_status(field.value)

                if state:
                    return state

    # No inferir estado desde el titulo
    # ni desde el enlace de conexion.
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

    except (OSError, ValueError, TypeError):
        pass

    return None


def save_state(state):
    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                {"state": state},
                file
            )

    except OSError:
        logger.warning(
            "No se pudo guardar el estado local."
        )


# ==========================================
# ENVIAR ALERTAS
# ==========================================

async def send_alert(state):
    if state == "down":
        title = (
            "🚨 SERVER DOWN | LA VENGANZA RP"
        )

        description = (
            "🔴 **La ciudad se encuentra "
            "fuera de servicio.**\n\n"
            "🛠️ Estamos verificando la situación.\n\n"
            "📢 Les notificaremos cuando "
            "el servidor vuelva a estar disponible.\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0xFF0000

    else:
        title = (
            "🟢 SERVER RESTORED | LA VENGANZA RP"
        )

        description = (
            "✅ **¡La ciudad está disponible "
            "nuevamente!**\n\n"
            "🔥 ¡Mi gente, ya pueden entrar!\n\n"
            "🎮 **CONÉCTATE AQUÍ:**\n"
            "https://cfx.re/join/57vjg7\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • El rol más duro*"
        )

        color = 0x22C55E

    payload = {
        "username": "La Venganza RP | Alertas",
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
        total=15
    )

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:
        async with session.post(
            WEBHOOK_URL,
            json=payload
        ) as response:
            if response.status not in (200, 204):
                raise RuntimeError(
                    "Webhook HTTP "
                    f"{response.status}"
                )

    logger.info(
        "Alerta enviada correctamente: %s",
        state
    )


# ==========================================
# MONITOREAR SERVIDOR
# ==========================================

async def monitor_server():
    global last_state
    global pending_state
    global pending_since

    await client.wait_until_ready()

    last_state = load_state()

    channel = await client.fetch_channel(
        CHANNEL_ID
    )

    logger.info(
        "Monitor de La Venganza RP iniciado"
    )

    while not client.is_closed():
        try:
            message = await channel.fetch_message(
                MESSAGE_ID
            )

            current_state = detect_status(
                message
            )

            if current_state is None:
                logger.warning(
                    "Estado no reconocido."
                )

                pending_state = None
                pending_since = None

            elif last_state is None:
                last_state = current_state
                save_state(current_state)

                logger.info(
                    "Estado inicial detectado: %s",
                    current_state
                )

            elif current_state == last_state:
                pending_state = None
                pending_since = None

            elif pending_state != current_state:
                pending_state = current_state
                pending_since = time.monotonic()

                logger.info(
                    "Cambio detectado: %s. "
                    "Esperando confirmacion.",
                    current_state
                )

            elif (
                time.monotonic() - pending_since
                >= CONFIRM_SECONDS
            ):
                await send_alert(
                    current_state
                )

                last_state = current_state
                save_state(current_state)

                pending_state = None
                pending_since = None

        except discord.Forbidden:
            logger.error(
                "Sin permisos para leer Connect."
            )

        except discord.NotFound:
            logger.error(
                "Mensaje original no encontrado."
            )

        except Exception:
            logger.exception(
                "Error monitoreando el panel."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# EVENTOS
# ==========================================

@client.event
async def on_ready():
    logger.info(
        "Bot conectado como %s",
        client.user
    )


# ==========================================
# INICIO
# ==========================================

async def main():
    async with client:
        await client.login(TOKEN)

        task = asyncio.create_task(
            monitor_server()
        )

        try:
            await client.connect(
                reconnect=True
            )

        finally:
            task.cancel()

            await asyncio.gather(
                task,
                return_exceptions=True
            )


if __name__ == "__main__":
    asyncio.run(main())
