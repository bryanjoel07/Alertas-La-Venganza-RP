"""Panel público del monitor de FiveM."""
import asyncio
import logging
import time

import discord

TITLE = "📡 SALUD DEL SERVIDOR | LA VENGANZA RP"
KEY = "health_panel_message_id"
log = logging.getLogger("LaVenganzaRP.salud")
SOURCES = {"up":"En línea","down":"Fuera de servicio","partial":"Servicio parcial",
           "stale":"Desactualizado","unreachable":"Sin respuesta","unknown":"Sin datos",
           "unavailable":"Sin acceso","unconfigured":"Sin configurar"}


def health_embed(sample, now, connect_url):
    observed, confirmed, sources, maintenance, checked = sample
    if maintenance:
        label, color = "🛠️ En mantenimiento", 0xF59E0B
    elif now - checked > 150 or observed is None:
        label, color = "⚪ Estado sin confirmar", 0x737880
    elif observed == "partial":
        label, color = "🟠 Servicio parcial", 0xF59E0B
    elif observed != confirmed:
        label = "🟠 Comprobando posible caída" if observed == "down" else "🟠 Comprobando recuperación"
        color = 0xF59E0B
    elif observed == "up":
        label, color = "🟢 Ciudad en línea", 0x22C55E
    else:
        label, color = "🔴 Ciudad fuera de servicio", 0xD60000
    embed = discord.Embed(title=TITLE,description=f"**{label}**",color=color)
    for name, source in zip(("🎮 FiveM","📋 txAdmin"),sources):
        embed.add_field(name=name,value=SOURCES.get(source,"Sin datos"),inline=True)
    embed.add_field(name="🕒 Última comprobación en tu hora local",value=f"<t:{checked}:F>",inline=False)
    if label == "🟢 Ciudad en línea":
        embed.add_field(name="Entrar a la ciudad",value=f"[Conectar a La Venganza RP]({connect_url})",inline=False)
    return embed


class ServerHealthPanel:
    def __init__(self, bot, channel_id, connect_url, read_setting, save_setting):
        self.bot, self.channel_id, self.connect_url = bot, channel_id, connect_url
        self.key = f"{KEY}_{channel_id}"
        self.read_setting, self.save_setting = read_setting, save_setting
        self.sample = self.message = self.last_version = None
        self.task = None
        self.removed = False

    async def refresh(self):
        if self.sample is None or self.removed:
            return
        now = int(time.time())
        checked = self.sample[-1]
        version = (self.sample[:-1], checked//60, now-checked > 150)
        if version == self.last_version:
            return
        embed = health_embed(self.sample,now,self.connect_url)
        channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
        if self.message is None:
            saved = self.read_setting(self.key)
            if not saved and self.channel_id == 1513421828415164546:
                saved = self.read_setting(KEY)
                if saved:
                    self.save_setting(self.key,saved)
            if saved:
                try:
                    candidate = await channel.fetch_message(int(saved))
                    if candidate.author.id == self.bot.user.id and any(e.title == TITLE for e in candidate.embeds):
                        self.message = candidate
                except discord.NotFound:
                    self.removed = True
                    log.info("Panel de salud eliminado en %s; se respeta la eliminación.", self.channel_id)
                    return
            if self.message is None:
                async for candidate in channel.history(limit=100):
                    if candidate.author.id == self.bot.user.id and any(e.title == TITLE for e in candidate.embeds):
                        self.message = candidate
                        break
            if self.message is None:
                self.message = await channel.send(embed=embed,allowed_mentions=discord.AllowedMentions.none(),
                                                  nonce=f"h{self.channel_id}")
                self.save_setting(self.key,self.message.id)
                self.last_version = version
                log.info("Panel de salud publicado: %s",self.message.id)
                return
            if str(self.message.id) != saved:
                self.save_setting(self.key,self.message.id)
        try:
            await self.message.edit(embed=embed,allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            self.removed = True
            log.info("Panel de salud eliminado en %s; se respeta la eliminación.", self.channel_id)
            return
        self.last_version = version

    async def run(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.refresh()
            except Exception:
                log.exception("No se pudo actualizar el panel de salud")
            await asyncio.sleep(8)
