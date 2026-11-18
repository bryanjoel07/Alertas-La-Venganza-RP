"""Original server expressions and opt-in Discord events for the corillo."""
import asyncio
from datetime import datetime, timedelta, timezone
import logging

import discord

from vice_design import ASSETS, GUILD_ID, BOT_ID, OWNER_ID, CYAN, PINK

log = logging.getLogger('ViceDistrict.community')
ART_VERSION = 'vice-expressions-v1'
EVENT_VERSION = 'vice-opening-events-v1'
PR_TIME = timezone(timedelta(hours=-4), 'Puerto Rico AST')
OPENING_WEEKDAY = 4  # Friday, selected as the initial planning default.
EMOJIS = ('vd_logo', 'vd_boricua', 'vd_palmera', 'vd_fuego', 'vd_corazon', 'vd_gg')
STICKERS = (
    ('vd_wepa', 'VIce Wepa', 'Celebración boricua con bandera y palmera', '🎉'),
    ('vd_duro', 'VIce Duro', 'Aprobación del corillo con fuego y pulgar arriba', '🔥'),
    ('vd_corillo', 'VIce Corillo', 'Pa’l corillo: una invitación con estilo tropical', '🌴'),
)
OPENING = (
    ('gta', '🇵🇷 Noche de GTA · El corillo se reúne', 120,
     'Nos encontramos en Lobby para conocernos y organizar crews según juego y plataforma. '
     'Indica tu plataforma en busca-crew; cada grupo coordina una partida compatible. '
     'Puedes participar también en la conversación. Respeto, buen ambiente y cero spam.'),
    ('clips', '🎬 Clips del corillo · Primera edición', 90,
     'Comparte un clip propio de cualquier GTA en clips-y-capturas durante la semana previa. '
     'Máximo 60 segundos, una participación por persona y sin datos personales. '
     'Nos reunimos en Lobby para ver los clips y votar; el equipo revisa los votos y anuncia el destacado. '
     'Actividad por diversión, sin premios económicos anunciados.'),
    ('trivia', '🧠 Trivia GTA · ¿Cuánto sabe el corillo?', 60,
     'Trivia comunitaria sobre personajes, ciudades y momentos de la saga GTA. '
     'Nos reunimos en Lobby; el equipo explica las rondas y la forma de responder al empezar. '
     'Sin spoilers sin avisar, respuestas por turnos y buen ambiente. Actividad por diversión.'),
)


def opening_plan(now, weekday=OPENING_WEEKDAY):
    local = now.astimezone(PR_TIME)
    first = local.replace(hour=20, minute=0, second=0, microsecond=0)
    first += timedelta(days=(weekday - local.weekday()) % 7)
    if first <= local + timedelta(hours=1):
        first += timedelta(days=7)
    return [dict(key=key, name=name, start=(first + timedelta(weeks=i)).isoformat(),
                 minutes=minutes, description=description)
            for i, (key, name, minutes, description) in enumerate(OPENING)]


def parse_event_time(value, now):
    try:
        result = datetime.strptime(value.strip(), '%Y-%m-%d %H:%M').replace(tzinfo=PR_TIME)
    except ValueError:
        raise ValueError('Escribe la fecha como AAAA-MM-DD HH:MM, en hora de Puerto Rico.') from None
    if not now + timedelta(minutes=10) < result <= now + timedelta(days=180):
        raise ValueError('Programa el evento con más de 10 minutos de antelación y dentro de los próximos 180 días.')
    return result


class AgendaView(discord.ui.View):
    def __init__(self, community):
        super().__init__(timeout=None)
        self.community = community

    @discord.ui.button(label='Ver próximos eventos', emoji='📅', style=discord.ButtonStyle.primary,
                       custom_id='vice:community:v1:agenda')
    async def agenda(self, interaction, button):
        self.community.system.authorize(interaction)
        await interaction.response.defer(ephemeral=True)
        events = await self.community.upcoming(interaction.guild)
        if not events:
            await interaction.followup.send('No hay eventos próximos publicados. El equipo anunciará aquí la siguiente convocatoria.', ephemeral=True)
            return
        view = discord.ui.View(timeout=300)
        body = []
        for event in events[:5]:
            body.append(f'**{discord.utils.escape_markdown(event.name)}**\n'
                        f'{self.community.local_time(event.start_time)} · {discord.utils.format_dt(event.start_time, "R")}')
            view.add_item(discord.ui.Button(label=event.name[:80], url=event.url))
        await interaction.followup.send(embed=self.community.system.embed('📅 AGENDA DEL CORILLO',
            '\n\n'.join(body) + '\n\nAbre el evento y pulsa **Me interesa** para inscribirte.', CYAN), view=view, ephemeral=True)

    async def on_error(self, interaction, error, item):
        log.error('VICE_AGENDA_FAILED', exc_info=error)
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(str(error) if isinstance(error, ValueError) else 'No se pudo cargar la agenda. Inténtalo nuevamente.', ephemeral=True)


class EventModal(discord.ui.Modal, title='Programar evento del corillo'):
    name = discord.ui.TextInput(label='Nombre', max_length=80)
    when = discord.ui.TextInput(label='Fecha y hora de Puerto Rico', placeholder='2026-11-20 20:00', max_length=16)
    minutes = discord.ui.TextInput(label='Duración en minutos', default='60', max_length=3)
    details = discord.ui.TextInput(label='Descripción y reglas', style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, community):
        super().__init__(timeout=600)
        self.community = community

    async def on_submit(self, interaction):
        self.community.authorize_event(interaction)
        start = parse_event_time(str(self.when), datetime.now(timezone.utc))
        try:
            minutes = int(str(self.minutes))
        except ValueError:
            raise ValueError('La duración debe ser un número entre 15 y 240 minutos.') from None
        if not 15 <= minutes <= 240:
            raise ValueError('La duración debe estar entre 15 y 240 minutos.')
        await interaction.response.defer(ephemeral=True)
        event = await self.community.schedule(interaction.guild, dict(key='manual-' + str(interaction.id),
            name=str(self.name), start=start.isoformat(), minutes=minutes, description=str(self.details)))
        await interaction.followup.send('Evento publicado: ' + event.url, ephemeral=True)

    async def on_error(self, interaction, error):
        log.error('VICE_EVENT_MODAL_FAILED', exc_info=error)
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(str(error) if isinstance(error, ValueError) else 'No se pudo publicar el evento. Inténtalo otra vez.', ephemeral=True)


class CommunityExtras:
    def __init__(self, system):
        self.system = system
        self.lock = asyncio.Lock()

    async def start(self):
        self.system.bot.add_view(AgendaView(self))

    @staticmethod
    def local_time(value):
        return value.astimezone(PR_TIME).strftime('%d/%m/%Y · %I:%M %p') + ' · Puerto Rico (AST)'

    def authorize_event(self, interaction):
        self.system.authorize(interaction)
        member = interaction.user
        mod = self.system.role(interaction.guild, 'mod')
        if member.id != OWNER_ID and not member.guild_permissions.administrator and mod not in member.roles:
            raise ValueError('Solo Fundador, Administrador o Moderación puede programar eventos.')

    async def art_snapshot(self, guild):
        return dict(guild=guild.id,
            emojis=[dict(id=e.id, name=e.name, roles=[r.id for r in e.roles]) for e in await guild.fetch_emojis()],
            stickers=[dict(id=s.id, name=s.name) for s in await guild.fetch_stickers()])

    async def install_art(self, guild):
        self.system.validate_guild(guild)
        emojis, stickers = await guild.fetch_emojis(), await guild.fetch_stickers()
        pending_emoji = [name for name in EMOJIS if not any(e.id == self.system.store.get('emoji:' + name)
                          or (e.name == name and e.user and e.user.id == BOT_ID) for e in emojis)]
        pending_sticker = [key for key, name, *_ in STICKERS if not any(s.id == self.system.store.get('sticker:' + key)
                            or (s.name == name and s.user and s.user.id == BOT_ID) for s in stickers)]
        if sum(not e.animated for e in emojis) + len(pending_emoji) > guild.emoji_limit:
            raise ValueError('No hay suficientes espacios de emoji para el paquete del distrito.')
        if len(stickers) + len(pending_sticker) > guild.sticker_limit:
            raise ValueError('No hay suficientes espacios de stickers para el paquete del distrito.')
        for name in EMOJIS:
            emoji = next((e for e in emojis if e.id == self.system.store.get('emoji:' + name)
                          or (e.name == name and e.user and e.user.id == BOT_ID)), None)
            if emoji is None:
                data = (ASSETS / 'emojis' / (name + '.png')).read_bytes()
                if len(data) > 256 * 1024:
                    raise ValueError('El emoji supera el tamaño permitido: ' + name)
                emoji = await guild.create_custom_emoji(name=name, image=data, roles=[], reason='Paquete original de VIce District solicitado por el propietario')
            await self.system.call('put', 'emoji:' + name, emoji.id)
        for key, name, description, tag in STICKERS:
            sticker = next((s for s in stickers if s.id == self.system.store.get('sticker:' + key)
                            or (s.name == name and s.user and s.user.id == BOT_ID)), None)
            if sticker is None:
                path = ASSETS / 'stickers' / (key + '.png')
                if path.stat().st_size > 512 * 1024:
                    raise ValueError('El sticker supera el tamaño permitido: ' + key)
                file = discord.File(path, filename=key + '.png')
                try:
                    sticker = await guild.create_sticker(name=name, description=description, emoji=tag, file=file,
                        reason='Stickers boricuas de VIce District solicitados por el propietario')
                finally:
                    file.close()
            await self.system.call('put', 'sticker:' + key, sticker.id)
        await self.system.call('put', 'art_release', ART_VERSION)
        log.info('VICE_ART_READY emojis=%s stickers=%s', len(EMOJIS), len(STICKERS))

    async def event_snapshot(self, guild):
        return dict(guild=guild.id, events=[dict(id=e.id, name=e.name, start=e.start_time.isoformat(),
                    status=str(e.status), channel=e.channel_id) for e in await guild.fetch_scheduled_events()])

    async def schedule(self, guild, plan):
        self.system.validate_guild(guild)
        async with self.lock:
            lobby = self.system.channel(guild, 'lobby')
            if not isinstance(lobby, discord.VoiceChannel) or lobby.guild.id != GUILD_ID:
                raise ValueError('No se confirmó el Lobby de voz del distrito.')
            permissions = lobby.permissions_for(guild.default_role)
            if not permissions.view_channel or not permissions.connect:
                raise ValueError('El evento comunitario requiere un Lobby visible y accesible para los miembros.')
            events = await guild.fetch_scheduled_events()
            known = self.system.store.get('event:' + plan['key'])
            start = datetime.fromisoformat(plan['start'])
            existing = next((e for e in events if e.id == known), None)
            if existing and (existing.creator_id != BOT_ID or existing.channel_id != lobby.id):
                raise ValueError('El evento guardado cambió de autor o canal y necesita revisión del equipo.')
            existing = existing or next((e for e in events if e.creator_id == BOT_ID and
                e.channel_id == lobby.id and e.name == plan['name'] and abs((e.start_time-start).total_seconds()) < 1), None)
            if existing:
                await self.system.call('put', 'event:' + plan['key'], existing.id)
                return existing
            if start <= datetime.now(timezone.utc) + timedelta(minutes=1):
                raise ValueError('La convocatoria ya no está en el futuro; el equipo debe elegir otra fecha.')
            description = (plan['description'] + '\n\n📍 Punto de encuentro: Lobby de VIce District.\n'
                '🕒 ' + self.local_time(start) + '\n'
                'Pulsa «Me interesa» para inscribirte y recibir el aviso de Discord. '
                'El equipo iniciará la actividad desde el evento programado.')
            async def create():
                event = await guild.create_scheduled_event(name=plan['name'], description=description[:4000],
                    start_time=start, end_time=start + timedelta(minutes=plan['minutes']),
                    channel=lobby, entity_type=discord.EntityType.voice,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    image=(ASSETS / 'welcome-template.jpg').read_bytes(),
                    reason='Evento del corillo solicitado por el propietario')
                await self.system.call('put', 'event:' + plan['key'], event.id)
                return event
            return await self.system.track('EVENT_CREATE', 'Programar evento del corillo', create, plan['key'],
                snapshot=lambda: self.event_snapshot(guild))

    async def upcoming(self, guild):
        self.system.validate_guild(guild)
        lobby_id = self.system.channel_id('lobby')
        return sorted([e for e in await guild.fetch_scheduled_events() if e.creator_id == BOT_ID
                       and e.channel_id == lobby_id and e.status in (discord.EventStatus.scheduled, discord.EventStatus.active)],
                      key=lambda e:e.start_time)

    async def install_events(self, guild):
        plans = self.system.store.get('opening_events_plan')
        if not plans:
            plans = opening_plan(datetime.now(timezone.utc))
            await self.system.call('put', 'opening_events_plan', plans)
        events = [await self.schedule(guild, plan) for plan in plans]
        details = '\n\n'.join(f'**{e.name}**\n{self.local_time(e.start_time)}\n[Ver evento e inscribirme]({e.url})' for e in events)
        async def publish():
            await self.system.panel(guild, 'events', ('🎉 LA AGENDA DEL CORILLO',
                '**Desde Puerto Rico para toda Latinoamérica.**\n\n' + details + '\n\n'
                'Abre la convocatoria y pulsa **Me interesa**. Allí encontrarás las reglas y el punto de encuentro. '
                'Los horarios de referencia son de **Puerto Rico (AST, UTC−4)**. '
                'El botón de abajo muestra la agenda actualizada.', PINK), AgendaView(self))
            await self.system.call('put', 'events_release', EVENT_VERSION)
        await self.system.track('EVENT_PANEL', 'Publicar agenda del corillo', publish, EVENT_VERSION)
        log.info('VICE_EVENTS_READY events=%s', len(events))

    async def ready(self):
        guild = self.system.bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if self.system.store.get('community_commands_release') != EVENT_VERSION:
            target = discord.Object(id=GUILD_ID)
            async def command_snapshot():
                return dict(guild=GUILD_ID, commands=[c.to_dict() for c in await self.system.bot.tree.fetch_commands(guild=target)])
            async def sync():
                await self.system.bot.tree.sync(guild=target)
                await self.system.call('put', 'community_commands_release', EVENT_VERSION)
            await self.system.track('COMMUNITY_COMMANDS', 'Registrar agenda del corillo', sync,
                                    EVENT_VERSION, snapshot=command_snapshot)
        if self.system.store.get('art_release') != ART_VERSION:
            await self.system.track('ART_INSTALL', 'Añadir emojis y stickers originales del corillo',
                lambda:self.install_art(guild), ART_VERSION, snapshot=lambda:self.art_snapshot(guild))
        if self.system.store.get('events_release') != EVENT_VERSION:
            await self.install_events(guild)
        if self.system.store.get('community_tools_release') != ART_VERSION:
            if not self.system.channel_id('voicepanel'):
                raise ValueError('Falta el panel de salas del corillo.')
            emojis = '  '.join(f'<:{name}:{self.system.store.get("emoji:"+name)}>' for name in EMOJIS)
            async def publish():
                await self.system.panel(guild, 'announcements', ('🌴 NOVEDADES DEL CORILLO',
                    '**Tu comunidad, con identidad propia.**\n\n'
                    f'🎙️ **Salas para tu crew:** crea y administra tu sala en <#{self.system.channel_id("voicepanel")}>.\n\n'
                    f'🎉 **Eventos:** revisa las próximas convocatorias en <#{self.system.channel_id("events")}> y pulsa «Me interesa».\n\n'
                    '**Emojis exclusivos:**\n' + emojis + '\n\n'
                    '**Stickers:** ¡WEPA!, ¡DURO! y PA’L CORILLO. Búscalos en el selector de stickers del servidor.\n\n'
                    'Las salas temporales se eliminan al quedar vacías. El creador gestiona entradas y cupo desde el panel.', CYAN), None)
                await self.system.call('put', 'community_tools_release', ART_VERSION)
            await self.system.track('COMMUNITY_TOOLS', 'Presentar herramientas del corillo', publish, ART_VERSION)
