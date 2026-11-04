
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

GUILD = discord.Object(id=GUILD_ID)

intents = discord.Intents.default()
intents.message_content = True


# ==========================================
# MAQUINA DE ESTADOS
# ==========================================

class StateTracker:

    def __init__(self, initial=None):
        self.last_state = initial
        self.pending_state = None
        self.pending_since = None

    def observe(self, state, now):

        # Partial o valores desconocidos no
        # generan alertas y cancelan cambios
        # que no hayan sido confirmados.

        if state not in ("up", "down"):
            self.pending_state = None
            self.pending_since = None
            return None

        # Primer estado conocido:
        # establecer referencia sin alertar.

        if self.last_state is None:
            self.last_state = state
            return None

        # Estado sin cambios.

        if state == self.last_state:
            self.pending_state = None
            self.pending_since = None
            return None

        # Cambio detectado por primera vez.

        if self.pending_state != state:
            self.pending_state = state
            self.pending_since = now
            return None

        # Todavia no se ha confirmado.

        if (
            self.pending_since is None
            or now - self.pending_since
            < CONFIRM_SECONDS
        ):
            return None

        # Cambio confirmado.
        # El llamador debe enviar la alerta
        # y despues registrar el nuevo estado.

        return state

    def confirm_sent(self, state):
        self.last_state = state
        self.pending_state = None
        self.pending_since = None


# ==========================================
# BOT DE DISCORD
# ==========================================

class AlertClient(discord.Client):

    def __init__(self):
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.monitor_task = None

    async def setup_hook(self):

        commands = await self.tree.sync(
            guild=GUILD
        )

        logger.info(
            "Comandos sincronizados: %s",
            len(commands)
        )

        self.monitor_task = asyncio.create_task(
            monitor_server()
        )


client = AlertClient()


# ==========================================
# LIMPIEZA DE TEXTO
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
# LEER PANEL ORIGINAL DEL PROGRAMADOR
# ==========================================

def detect_status(message):

    for embed in message.embeds:

        for field in embed.fields:

            name = clean_text(field.name)

            if re.search(
                r"\b(status|estado)\b",
                name
            ):
                return parse_status(field.value)

    return None


# ==========================================
# PERSISTENCIA DEL ESTADO REAL
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
        directory = os.path.dirname(STATE_FILE)

        if directory:
            os.makedirs(
                directory,
                exist_ok=True
            )

        temporary = STATE_FILE + ".tmp"

        with open(
            temporary,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                {"state": state},
                file
            )

        os.replace(temporary, STATE_FILE)

    except OSError:
        logger.warning(
            "No se pudo guardar el estado."
        )


# ==========================================
# CREAR COMUNICADOS
# ==========================================

def create_alert_embed(state, test=False):

    if state == "down":

        title = (
            "🚨 SERVER DOWN | LA VENGANZA RP"
        )

        description = (
            "🔴 **LA CIUDAD SE ENCUENTRA "
            "FUERA DE SERVICIO**\n\n"
            "🛠️ Mi gente, el servidor se "
            "encuentra temporalmente "
            "fuera de servicio.\n\n"
            "🔧 Nuestro equipo estará "
            "verificando la situación.\n\n"
            "📢 Les notificaremos cuando "
            "la ciudad vuelva a estar disponible.\n\n"
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
            "🚗 Preparen sus máquinas y "
            "entren a disfrutar del roleplay.\n\n"
            "🎮 **CONÉCTATE AQUÍ:**\n"
            f"{CONNECT_URL}\n\n"
            "🔴 **LA VENGANZA RP**\n"
            "*La ciudad más real • "
            "El rol más duro*"
        )

        color = 0x22C55E

    else:
        raise ValueError("Estado invalido.")

    if test:
        title = "🧪 PRUEBA | " + title

        description = (
            "⚠️ **SIMULACIÓN DEL BOT**\n"
            "**ESTO NO REPRESENTA EL ESTADO "
            "REAL DEL SERVIDOR.**\n\n"
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
# ENVIAR ALERTA AL WEBHOOK
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

                raise RuntimeError(
                    "Error del webhook: "
                    f"HTTP {response.status}"
                )

    logger.info(
        "Alerta enviada | Estado: %s | Prueba: %s",
        state,
        test
    )


# ==========================================
# COMANDO /TESTALERT
# ==========================================

@client.tree.command(
    name="testalert",
    description="Enviar una alerta de prueba."
)
@app_commands.guilds(GUILD)
@app_commands.default_permissions(
    administrator=True
)
@app_commands.checks.has_permissions(
    administrator=True
)
@app_commands.describe(
    estado="Selecciona el comunicado de prueba"
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
            "❌ No se pudo enviar la prueba. "
            "Revisa Railway.",
            ephemeral=True
        )


# ==========================================
# SIMULACION COMPLETA DEL SISTEMA
# ==========================================

def run_simulation():

    # Esta instancia es independiente.
    # No modifica el estado real del bot.

    tracker = StateTracker()

    results = []

    def check(state, simulated_second):

        event = tracker.observe(
            state,
            simulated_second
        )

        results.append(
            (state, simulated_second, event)
        )

        if event is not None:
            tracker.confirm_sent(event)

        return event

    # Establecer Online como estado inicial.

    assert check("up", 0) is None

    # Una caida momentanea debe cancelarse.

    assert check("down", 10) is None
    assert check("up", 50) is None

    # Caida confirmada despues de 90 segundos.

    assert check("down", 100) is None
    assert check("down", 189) is None
    assert check("down", 190) == "down"

    # Evitar alertas duplicadas.

    assert check("down", 220) is None
    assert check("down", 250) is None

    # Partial debe ignorarse.

    assert check("partial", 260) is None

    # Recuperacion confirmada.

    assert check("up", 300) is None
    assert check("up", 389) is None
    assert check("up", 390) == "up"

    # Evitar duplicados de recuperacion.

    assert check("up", 420) is None

    # Verificar secuencia exacta.

    emitted = [
        event
        for _, _, event in results
        if event is not None
    ]

    assert emitted == ["down", "up"]

    return {
        "success": True,
        "checks": len(results),
        "alerts": emitted,
        "confirmation_seconds": CONFIRM_SECONDS,
        "partial_ignored": True,
        "duplicates_prevented": True
    }


# ==========================================
# COMANDO /SIMULAR-CICLO
# ==========================================

@client.tree.command(
    name="simular-ciclo",
    description=(
        "Simular una caida y recuperacion "
        "sin apagar FiveM."
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

        # Comprobar la logica primero.

        result = run_simulation()

        if not result["success"]:
            raise RuntimeError(
                "La simulacion no fue exitosa."
            )

        # Enviar solamente comunicados
        # identificados como simulacion.

        await send_alert(
            "down",
            test=True
        )

        await send_alert(
            "up",
            test=True
        )

        message = (
            "✅ **SIMULACIÓN COMPLETADA**\n\n"
            "🔴 Server Down: enviado.\n"
            "🟢 Server Restored: enviado.\n"
            "🟠 Partial: ignorado.\n"
            "🛡️ Duplicados: bloqueados.\n"
            f"⏱️ Confirmación: "
            f"{CONFIRM_SECONDS} segundos "
            "simulados.\n\n"
            "✅ El estado real del servidor "
            "no fue modificado.\n\n"
            "📢 Revisa el canal "
            "Alertas-Servidor."
        )

        await interaction.followup.send(
            message,
            ephemeral=True
        )

        logger.info(
            "Simulacion completada por %s",
            interaction.user.id
        )

    except Exception:

        logger.exception(
            "Error ejecutando /simular-ciclo"
        )

        await interaction.followup.send(
            "❌ La simulación falló. "
            "Revisa los registros de Railway.",
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

    if isinstance(
        error,
        app_commands.MissingPermissions
    ):

        message = (
            "❌ Este comando requiere "
            "permisos de administrador."
        )

    else:

        logger.error(
            "Error de comando: %s",
            error
        )

        message = (
            "❌ Ocurrió un error "
            "ejecutando el comando."
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
        logger.exception(
            "No se pudo responder al comando."
        )


# ==========================================
# MONITOREO AUTOMATICO REAL
# ==========================================

async def monitor_server():

    await client.wait_until_ready()

    tracker = StateTracker(
        initial=load_state()
    )

    last_observed = None

    logger.info(
        "Monitor automatico iniciado."
    )

    logger.info(
        "Origen: %s | Mensaje: %s",
        CONNECT_CHANNEL_ID,
        PANEL_MESSAGE_ID
    )

    logger.info(
        "Alertas por webhook configuradas."
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

            if current_state != last_observed:

                logger.info(
                    "Estado observado: %s",
                    current_state
                )

                last_observed = current_state

            event = tracker.observe(
                current_state,
                time.monotonic()
            )

            if event is not None:

                logger.info(
                    "Cambio confirmado: %s",
                    event
                )

                # No confirmar la transicion
                # hasta que el webhook responda.

                await send_alert(
                    event,
                    test=False
                )

                tracker.confirm_sent(event)

                save_state(event)

                logger.info(
                    "Estado actualizado: %s",
                    event
                )

            elif (
                tracker.last_state is not None
                and load_state() is None
            ):

                save_state(
                    tracker.last_state
                )

        except discord.Forbidden:

            logger.error(
                "Sin permisos para leer Connect."
            )

        except discord.NotFound:

            logger.error(
                "No se encontro el panel original."
            )

        except Exception:

            logger.exception(
                "Error monitoreando el servidor."
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


# ==========================================
# EVENTO BOT ONLINE
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
