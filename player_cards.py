"""Tarjeta de jugador de Discord: estadísticas existentes y todas sus páginas de eventos."""
from datetime import datetime
import io
import logging

import discord
from discord import app_commands

log = logging.getLogger('LaVenganzaRP.perfiles')


def safe(value):
    return discord.utils.escape_markdown(str(value)).replace('@', '@\u200b')


def placing(event, user_id):
    for key, label in (('winner1', '🥇 Primer lugar'), ('winner2', '🥈 Segundo lugar'), ('winner3', '🥉 Tercer lugar')):
        if str(event.get(key) or '') == str(user_id):
            return label
    return 'Inscrito · sin podio registrado'


def event_status(event):
    if event['status'] == 'closed' and any(event.get(k) for k in ('winner1', 'winner2', 'winner3')):
        return 'Finalizado · anuncio retirado'
    return {'open': 'Inscripciones abiertas', 'finished': 'Finalizado', 'closed': 'Cerrado'}.get(event['status'], 'Sin estado conocido')


def profile_embed(member, data):
    stats = data['stats']
    avatar = str(member.display_avatar.url)
    embed = discord.Embed(title=f'🎖️ TARJETA DEL JUGADOR | {safe(member.display_name)}', description=f"**Usuario:** {safe(member.name)}\nParticipaciones basadas en inscripciones y podios guardados; no certifican asistencia real.", color=0xD60000)
    embed.set_thumbnail(url=avatar)
    embed.set_author(name='LA VENGANZA RP · Jugadores', icon_url=avatar)
    embed.add_field(name='🎮 Eventos registrados', value=str(data['total_events']), inline=True)
    embed.add_field(name='🏁 Participaciones finalizadas', value=str(stats['participations']), inline=True)
    embed.add_field(name='📊 Posición histórica', value=f"#{data['rank']} de {data['ranked_players']}" if data['rank'] else 'Sin clasificar todavía', inline=True)
    for key, title in (('first', '🥇 Primeros lugares'), ('second', '🥈 Segundos lugares'), ('third', '🥉 Terceros lugares')):
        embed.add_field(name=title, value=str(stats[key]), inline=True)
    if not data['events']:
        embed.add_field(name='📋 Historial', value='Todavía no hay eventos guardados para este jugador.', inline=False)
    for event in data['events']:
        stamp = int(datetime.fromisoformat(event['starts_at']).timestamp())
        value = f"📅 <t:{stamp}:f>\n📍 {safe(event.get('location', 'Sin lugar registrado'))}\n📋 {event_status(event)}\n🏅 {placing(event, member.id)}"
        embed.add_field(name=f"#{event['id']} · {safe(event['title'])}"[:256], value=value[:700], inline=False)
    embed.set_footer(text=f"ID {member.id} · Página {data['page']}/{data['pages']} · Historial completo en el botón de descarga")
    return embed


def profile_export(member, events):
    lines = [f'LA VENGANZA RP — PERFIL DE {member.display_name}', f'Usuario: {member.name} | ID: {member.id}', f'Eventos registrados: {len(events)}', 'Inscripción/podio guardado no certifica asistencia real.']
    for event in events:
        lines.extend(['', f"#{event['id']} — {event['title']}", f"Fecha UTC: {event['starts_at']}", f"Lugar: {event.get('location', 'Sin lugar registrado')}", f"Estado: {event_status(event)}", f"Resultado: {placing(event, member.id)}", f"Descripción: {event.get('description', '')}", f"Premios anunciados: {event.get('prizes', '')}"])
    return '\n'.join(lines)


class PlayerCard(discord.ui.View):
    def __init__(self, bot, owner_id, member, access_check, decorate=None):
        super().__init__(timeout=900)
        self.bot, self.owner_id, self.member, self.access_check = bot, owner_id, member, access_check
        self.page = 1
        self.decorate = decorate
        self.message = None

    async def render(self):
        data = await self.bot.event_features.call('profile', self.member.id, self.page)
        self.page = data['page']
        self.previous.disabled = self.page <= 1
        self.next.disabled = self.page >= data['pages']
        embed = profile_embed(self.member, data)
        if self.decorate:
            self.decorate(embed, self.member.id)
        return embed

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('Esta tarjeta la controla quien la consultó. Usa /perfil para abrir la tuya.', ephemeral=True)
            return False
        return True

    async def change(self, interaction, delta):
        await interaction.response.defer()
        await self.access_check(interaction)
        self.page = max(1, self.page + delta)
        member = interaction.guild.get_member(self.member.id)
        if member is not None:
            self.member = member
        await interaction.edit_original_response(embed=await self.render(), view=self)

    @discord.ui.button(label='Anterior', emoji='⬅️', style=discord.ButtonStyle.secondary, custom_id='lvrp:profile:previous')
    async def previous(self, interaction, button):
        await self.change(interaction, -1)

    @discord.ui.button(label='Siguiente', emoji='➡️', style=discord.ButtonStyle.secondary, custom_id='lvrp:profile:next')
    async def next(self, interaction, button):
        await self.change(interaction, 1)

    @discord.ui.button(label='Actualizar', emoji='🔄', style=discord.ButtonStyle.primary, custom_id='lvrp:profile:refresh')
    async def refresh(self, interaction, button):
        await self.change(interaction, 0)

    @discord.ui.button(label='Historial completo', emoji='📄', style=discord.ButtonStyle.secondary, custom_id='lvrp:profile:export', row=1)
    async def export(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.access_check(interaction)
        events = await self.bot.event_features.call('profile_history', self.member.id)
        file = discord.File(io.BytesIO(profile_export(self.member, events).encode()), filename=f'perfil-{self.member.id}.txt')
        await interaction.followup.send(file=file, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def on_timeout(self):
        for button in self.children:
            button.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                log.debug('No se pudieron desactivar controles de tarjeta expirada')

    async def on_error(self, interaction, error, item):
        log.error('Error en tarjeta del jugador', exc_info=(type(error), error, error.__traceback__))
        message = '❌ Ya no tienes acceso al canal de eventos.' if isinstance(error, app_commands.CheckFailure) else '❌ No se pudo actualizar la tarjeta. Vuelve a consultar /perfil.'
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
