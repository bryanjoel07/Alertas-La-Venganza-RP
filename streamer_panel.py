import asyncio
import logging

import discord
from discord.ext import tasks


CHANNEL_ID = 1568403146219454586
ROLE_ID = 1568399564887826486
PANEL_RED = 0xD60000
ROLE_COLOR = 0xFF3CAC
log = logging.getLogger(__name__)


def application_embed(minimum):
    embed = discord.Embed(
        title="📺 SOLICITAR ROL STREAMER",
        description=f"👥 **{minimum} seguidores** en una plataforma o **{minimum} suscriptores** en YouTube.\n"
                    "🎥 Un directo o una repetición pública de **La Venganza RP** en tu canal.",
        colour=PANEL_RED)
    embed.add_field(name="🎟️ Solicitar rol", value="Recibe un código privado válido por 24 horas. Ponlo junto a "
                    "**La Venganza RP** en el título. En **Verificar requisitos**, pega el enlace que abre ese "
                    "directo o su repetición para que el bot compruebe tu solicitud.", inline=False)
    embed.add_field(name="📋 Ver mi estado", value="Consulta el resultado en privado. Si faltan datos públicos, "
                    "el staff revisará tu prueba.", inline=False)
    embed.add_field(name="🔗 ¿Qué enlace guardo para mis próximos directos?",
                    value="Cuando te aprueben, pulsa **Ver mi estado → Enviar enlace**. Guarda una sola vez "
                    "la **dirección principal de tu canal o perfil**, la que puedes abrir incluso cuando estás "
                    "fuera de línea. Si el bot ya la rellenó, comprueba que sea tu canal y pulsa **Enviar**.", inline=False)
    embed.add_field(name="📱 Si el campo está vacío", value="Abre tu perfil en la plataforma y copia el enlace "
                    "desde **Compartir**. Estos son ejemplos de cómo se ve cada dirección:\n"
                    "🟣 Twitch · `https://www.twitch.tv/tuusuario`\n"
                    "🎵 TikTok · `https://www.tiktok.com/@tuusuario`\n"
                    "🔴 YouTube · `https://www.youtube.com/channel/UC…`\n"
                    "🟢 Kick · `https://kick.com/tuusuario`", inline=False)
    embed.add_field(name="🔔 ¿Cuándo sale el aviso?", value="Pon **La Venganza RP** en el título de tus próximos "
                    "directos. El bot usará el canal que guardaste para anunciarlos en <#1513653533340073994>.", inline=False)
    embed.set_footer(text="LA VENGANZA RP | Twitch · TikTok · YouTube · Otras plataformas")
    return embed


class StreamLinkForm(discord.ui.Modal, title="Verificar requisitos"):
    link = discord.ui.TextInput(label="Enlace del directo o la repetición",
                                placeholder="https://…", max_length=500)

    def __init__(self, streamers):
        super().__init__()
        self.streamers = streamers

    async def on_submit(self, interaction):
        await self.streamers.check_link(interaction, self.link.value.strip())


class ProofButtons(discord.ui.View):
    def __init__(self, streamers):
        super().__init__(timeout=900)
        self.streamers = streamers

    @discord.ui.button(label="Verificar requisitos", emoji="🔎", style=discord.ButtonStyle.primary)
    async def verify(self, interaction, button):
        await interaction.response.send_modal(StreamLinkForm(self.streamers))


class CreatorForm(discord.ui.Modal, title="Guardar mi canal de creador"):
    link = discord.ui.TextInput(label="Enlace a tu canal verificado", max_length=500)

    def __init__(self, streamers, profile):
        super().__init__()
        self.streamers = streamers
        self.link.default = profile

    async def on_submit(self, interaction):
        await self.streamers.save_profile(interaction, self.link.value.strip())


class ApprovedButtons(discord.ui.View):
    def __init__(self, streamers):
        super().__init__(timeout=900)
        self.streamers = streamers

    @discord.ui.button(label="Enviar enlace", emoji="🔗", style=discord.ButtonStyle.primary)
    async def open_form(self, interaction, button):
        row = self.streamers.request(interaction.guild_id, interaction.user.id)
        if not self.streamers.is_approved(row):
            return await interaction.response.send_message("Este paso se habilita cuando tu solicitud queda aprobada.", ephemeral=True)
        await interaction.response.send_modal(CreatorForm(self.streamers, self.streamers.profile(row)))


class ApplicationButtons(discord.ui.View):
    def __init__(self, streamers):
        super().__init__(timeout=None)
        self.streamers = streamers

    @discord.ui.button(label="Solicitar rol", emoji="🎟️", style=discord.ButtonStyle.success, custom_id="streamer:apply:v1")
    async def request_code(self, interaction, button):
        await self.streamers.issue_code(interaction)

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
        if self.install.is_running():return
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
                    if role.colour.value != ROLE_COLOR:
                        await role.edit(colour=discord.Colour(ROLE_COLOR), reason="Color del rol Streamer")
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
