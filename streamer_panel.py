import asyncio
import logging

import discord
from discord.ext import tasks


CHANNEL_ID = 1568403146219454586
ROLE_ID = 1568399564887826486
ACCENT = 0xFF3CAC
log = logging.getLogger(__name__)


def application_embed(minimum):
    embed = discord.Embed(
        title="📺 Solicitar el rol Streamer",
        description=f"¿Transmites en **La Venganza RP**? Necesitas **{minimum} seguidores en una plataforma** "
                    f"(o **{minimum} suscriptores en YouTube**) y un directo o una repetición pública de la ciudad.",
        colour=ACCENT)
    embed.add_field(name="1 · Solicitar código", value="Recibe tu código personal. Tienes 24 horas para usarlo.", inline=False)
    embed.add_field(name="2 · Enviar enlace", value="Pon **La Venganza RP** y tu código en el título del directo. "
                    "Pulsa el botón y pega el enlace al directo o a su repetición.", inline=False)
    embed.add_field(name="3 · Ver mi estado", value="Consulta tu resultado en privado. Si se verifican los requisitos, "
                    "recibirás el rol. Si faltan datos públicos, el staff revisará tu solicitud.", inline=False)
    embed.set_footer(text="Twitch · TikTok · YouTube · Otras plataformas")
    return embed


class StreamLinkForm(discord.ui.Modal, title="Enviar mi directo"):
    link = discord.ui.TextInput(label="Enlace del directo o la repetición",
                                placeholder="https://…", max_length=500)

    def __init__(self, streamers):
        super().__init__()
        self.streamers = streamers

    async def on_submit(self, interaction):
        await self.streamers.check_link(interaction, self.link.value.strip())


class ApplicationButtons(discord.ui.View):
    def __init__(self, streamers):
        super().__init__(timeout=None)
        self.streamers = streamers

    @discord.ui.button(label="Solicitar código", emoji="🎟️", style=discord.ButtonStyle.success, custom_id="streamer:apply:v1")
    async def request_code(self, interaction, button):
        await self.streamers.issue_code(interaction)

    @discord.ui.button(label="Enviar enlace", emoji="🔗", style=discord.ButtonStyle.primary, custom_id="streamer:link:v1")
    async def open_form(self, interaction, button):
        await interaction.response.send_modal(StreamLinkForm(self.streamers))

    @discord.ui.button(label="Ver mi estado", emoji="📋", style=discord.ButtonStyle.secondary, custom_id="streamer:status:v1")
    async def show_status(self, interaction, button):
        await self.streamers.show_status(interaction)


class StreamerPanel:
    def __init__(self, client, streamers):
        self.client = client
        self.streamers = streamers
        self.view = ApplicationButtons(streamers)
        self.lock = asyncio.Lock()
        self.published = False

    def start(self):
        with self.streamers.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS streamer_panel(channel INTEGER PRIMARY KEY,message INTEGER,colored INTEGER DEFAULT 0)")
            db.execute("INSERT OR IGNORE INTO streamer_panel(channel) VALUES(?)", (CHANNEL_ID,))
        self.client.add_view(self.view)
        self.install.start()

    async def publish(self, channel):
        async with self.lock:
            with self.streamers.db() as db:
                row = db.execute("SELECT message FROM streamer_panel WHERE channel=?", (CHANNEL_ID,)).fetchone()
            message = None
            if row["message"]:
                try:
                    message = await channel.fetch_message(row["message"])
                except discord.NotFound:
                    pass
            if message is None:
                async for candidate in channel.history(limit=30):
                    if candidate.author.id == self.client.user.id and any(
                            getattr(button, "custom_id", None) == "streamer:apply:v1"
                            for group in candidate.components for button in getattr(group, "children", [])):
                        message = candidate
                        break
            _, minimum = self.streamers.config(channel.guild)
            embed = application_embed(minimum)
            if message:
                await message.edit(embed=embed, view=self.view)
            else:
                message = await channel.send(embed=embed, view=self.view)
            with self.streamers.db() as db:
                db.execute("UPDATE streamer_panel SET message=? WHERE channel=?", (message.id, CHANNEL_ID))
            log.info("Panel Streamer publicado en %s, mensaje %s", CHANNEL_ID, message.id)

    @tasks.loop(minutes=2)
    async def install(self):
        channel = self.client.get_channel(CHANNEL_ID)
        if channel is None:
            return
        with self.streamers.db() as db:
            colored = db.execute("SELECT colored FROM streamer_panel WHERE channel=?", (CHANNEL_ID,)).fetchone()[0]
        if not colored:
            role = channel.guild.get_role(ROLE_ID)
            if role and role.is_assignable():
                try:
                    if role.colour.value != ACCENT:
                        await role.edit(colour=discord.Colour(ACCENT), reason="Color del rol Streamer")
                    with self.streamers.db() as db:
                        db.execute("UPDATE streamer_panel SET colored=1 WHERE channel=?", (CHANNEL_ID,))
                    colored = True
                except discord.HTTPException as error:
                    log.warning("Color de Streamer pendiente: %s", error)
        if not self.published:
            try:
                await self.publish(channel)
                self.published = True
            except discord.HTTPException as error:
                log.warning("Panel de Streamer pendiente: %s", error)
        if colored and self.published:
            self.install.stop()

    @install.before_loop
    async def wait_ready(self):
        await self.client.wait_until_ready()
