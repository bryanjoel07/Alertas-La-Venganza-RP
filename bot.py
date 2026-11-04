
import asyncio
import logging
import os
import re
import time

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
# PANEL ORIGINAL DE TXADMIN
# ==========================================

GUILD_ID = 1244988345327550565
CHANNEL_ID = 1513421828415164546
MESSAGE_ID = 1536621817471696907

# ==========================================
# CONFIGURACION
# ==========================================

CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

last_state = None
pending_state = None
pending_since = None

# ==========================================
# NORMALIZAR TEXTO
# ==========================================

def clean_text(value):
    if value is None:
        return ""

    return str(value).strip().lower()


# ==========================================
# IDENTIFICAR ONLINE / OFFLINE
# ==========================================

def parse_status(value):
    text = clean_text(value)

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
# LEER ESTADO DEL EMBED
# ==========================================

def detect_status(message):

    logger.info(
        "DEBUG PANEL: content=%r embeds=%r",
        message.content,
        [embed.to_dict() for embed in message.embeds]
    )

    # Primero buscar en los campos del embed
    for embed in message.embeds:

        for field in embed.fields:

            field_name = clean_text(field.name)
            field_value = clean_text(field.value)

            if (
                "status" in field_name
                or "estado" in field_name
            ):
                result = parse_status(field_value)

                if result:
                    return result

    # Buscar en la descripcion del embed
    for embed in message.embeds:

        description = clean_text(embed.description)

        match = re.search(
            r"(?:status|estado)"
            r"[\s:*_`-]*"
            r"([^\n]{0,100})",
            description,
            re.IGNORECASE
        )

        if match:
            result = parse_status(match.group(1))

            if result:
                return result

    # Buscar en el contenido del mensaje
    content = clean_text(message.content)

    match = re.search(
        r"(?:status|estado)"
        r"[\s:*_`-]*"
        r"([^\n]{0,100})",
        content,
        re.IGNORECASE
    )

    if match:
        result = parse_status(match.group(1))

        if result:
            return result

    # Buscar en titulo o descripcion completa
    for embed in message.embeds:

        title = clean_text(embed.title)
        description = clean_text(embed.description)

        combined = title + "\n" + description

        lines = combined.splitlines()

        for index, line in enumerate(lines):

            if (
                "status" in line
                or "estado" in line
            ):

                result = parse_status(line)

                if result:
                    return result

                if index + 1 < len(lines):

                    result = parse_status(
                        lines[index + 1]
                    )

                    if result:
                        return result

    return None


# ==========================================
# ENVIAR ALERTAS A DISCORD
# ==========================================

async def send_alert(state):

    if state == "down":

        title = (
            "🚨 SERVER DOWN | LA VENGANZA RP"
        )

        description = (
            "🔴 **La ciudad se encuentra "
            "temporalmente fuera de servicio.**\n\n"
            "🛠️ Nuestro equipo estará verificando "
            "la situación.\n\n"
            "📢 Les notificaremos cuando el "
            "servidor vuelva a estar disponible.\n\n"
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
            "🔥 Mi gente, ya pueden entrar "
            "a disfrutar del roleplay.\n\n"
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

    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(
        timeout=timeout
    ) as session:

        async with session.post(
            WEBHOOK_URL,
            json=payload
        ) as response:

            if response.status not in (200, 204):

                raise RuntimeError(
                    "Error enviando alerta: "
                    f"HTTP {response.status}"
                )

    logger.info(
        "Alerta enviada correctamente: %s",
        state
    )


# ==========================================
# MONITOREAR EL PANEL ORIGINAL
# ==========================================

async def monitor_server():

    global last_state
    global pending_state
    global pending_since

    await client.wait_until_ready()

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
                    "No se pudo identificar "
                    "el estado del panel"
                )

                pending_state = None
                pending_since = None

            elif last_state is None:

                last_state = current_state

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
                    "Esperando confirmacion...",
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
                pending_state = None
                pending_since = None

        except discord.Forbidden:

            logger.error(
                "El bot no tiene permisos "
                "para leer el canal Connect"
            )

        except discord.NotFound:

            logger.error(
                "No se encontro el mensaje "
                "original de txAdmin"
            )

        except Exception:

            logger.exception(
                "Error monitoreando el panel"
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# EVENTOS DE DISCORD
# ==========================================

@client.event
async def on_ready():

    logger.info(
        "Bot conectado como %s",
        client.user
    )


# ==========================================
# INICIAR EL BOT
# ==========================================

async def main():

    async with client:

        await client.login(TOKEN)

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
