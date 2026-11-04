
import asyncio
import logging
import os
import re
import time

import aiohttp
import discord

# ==========================================
# LA VENGANZA RP | SISTEMA DE ALERTAS
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LaVenganzaRP")

# Credenciales privadas desde Railway
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# Panel original del programador
CHANNEL_ID = 1513421828415164546
MESSAGE_ID = 1536621817471696907

# Configuracion del monitor
CHECK_INTERVAL = 30
CONFIRM_SECONDS = 90

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

last_state = None
pending_state = None
pending_since = None


# ==========================================
# DETECTAR ESTADO DEL SERVIDOR
# ==========================================

def detect_status(message):
    parts = [message.content or ""]

    for embed in message.embeds:
        data = embed.to_dict()

        for field in data.get("fields", []):
            name = str(field.get("name", "")).lower()
            value = str(field.get("value", ""))

            if any(
                word in name
                for word in ["status", "estado", "server"]
            ):
                parts.insert(0, f"STATUS: {value}")

        parts.append(str(data.get("description", "")))
        parts.append(str(data.get("title", "")))

    content = "\n".join(parts).lower()

    match = re.search(
        r"(?:status|estado)\s*[:\n ]+\s*[^\n]{0,40}",
        content
    )

    if not match:
        return None

    status_text = match.group(0)

    if re.search(
        r"\b(offline|down|cerrado|caido|caído)\b",
        status_text
    ):
        return "down"

    if re.search(
        r"\b(online|up|abierto|operativo)\b",
        status_text
    ):
        return "up"

    return None


# ==========================================
# ENVIAR ALERTAS A DISCORD
# ==========================================

async def send_alert(state):
    if state == "down":
        title = "🚨 SERVER DOWN | LA VENGANZA RP"
        description = (
            "🔴 **La ciudad se encuentra fuera de servicio.**\n\n"
            "🛠️ Nuestro equipo estará verificando la situación.\n\n"
            "📢 Notificaremos cuando el servidor vuelva "
            "a estar disponible.\n\n"
            "🔴 **LA VENGANZA RP**"
        )
        color = 0xFF0000

    else:
        title = "🟢 SERVER RESTORED | LA VENGANZA RP"
        description = (
            "✅ **La ciudad está disponible nuevamente.**\n\n"
            "🔥 ¡Mi gente, ya pueden volver a entrar!\n\n"
            "🎮 **Conéctate aquí:**\n"
            "https://cfx.re/join/57vjg7\n\n"
            "🔴 **LA VENGANZA RP**"
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
                    "text": "La Venganza RP | Sistema de Alertas"
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
                    f"Webhook error: HTTP {response.status}"
                )

    logger.info("Alerta enviada: %s", state)


# ==========================================
# MONITOREAR PANEL ORIGINAL
# ==========================================

async def monitor_server():
    global last_state
    global pending_state
    global pending_since

    await client.wait_until_ready()

    channel = await client.fetch_channel(CHANNEL_ID)

    logger.info("Monitor de La Venganza RP iniciado")

    while not client.is_closed():
        try:
            message = await channel.fetch_message(
                MESSAGE_ID
            )

            current_state = detect_status(message)

            if current_state is None:
                logger.warning(
                    "No se pudo identificar el estado del panel"
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
                    "Cambio detectado: %s",
                    current_state
                )

            elif (
                time.monotonic() - pending_since
                >= CONFIRM_SECONDS
            ):
                await send_alert(current_state)

                last_state = current_state
                pending_state = None
                pending_since = None

        except Exception:
            logger.exception(
                "Error monitoreando el panel"
            )

        await asyncio.sleep(CHECK_INTERVAL)


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
# INICIAR BOT
# ==========================================

async def main():
    async with client:
        await client.login(TOKEN)

        monitor_task = asyncio.create_task(
            monitor_server()
        )

        try:
            await client.connect(reconnect=True)

        finally:
            monitor_task.cancel()

            try:
                await monitor_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
