"""Observed member/voice activity for the district's private staff register.

Gateway voice states describe what changed, not who caused it. Administrative
actors and reasons are published separately from real Discord audit entries.
"""
from datetime import datetime, timedelta, timezone
import uuid

import discord

from vice_design import GUILD_ID


GREEN, RED, AMBER = 0x35D596, 0xFF5D73, 0xFFA844
PR_TIME = timezone(timedelta(hours=-4), 'AST')
VOICE_FLAGS = (
    ('self_mute', 'Micrófono propio', 'Silenciado', 'Activado'),
    ('self_deaf', 'Audio propio', 'Desactivado', 'Activado'),
    ('mute', 'Silencio del servidor', 'Aplicado', 'Retirado'),
    ('deaf', 'Ensordecimiento del servidor', 'Aplicado', 'Retirado'),
    ('self_stream', 'Transmisión', 'Iniciada', 'Detenida'),
    ('self_video', 'Cámara', 'Encendida', 'Apagada'),
)


def _name(value, maximum=180):
    """Keep user-provided names readable without control or mention markup."""
    value = ' '.join(str(value or '').split())
    value = ''.join(c for c in value if ord(c) >= 32 and ord(c) != 127)
    return discord.utils.escape_mentions(discord.utils.escape_markdown(value))[:maximum]


def _avatar(user):
    asset = getattr(user, 'display_avatar', None)
    value = getattr(asset, 'url', None)
    if isinstance(value, str) and value.startswith(('https://cdn.discordapp.com/',
                                                    'https://media.discordapp.net/')):
        return value
    return None


def _channel_id(channel):
    return getattr(channel, 'id', None) if channel is not None else None


def _channel(channel):
    return f'<#{channel.id}> · {_name(getattr(channel, "name", "Canal"), 120)}'


def _user_id(user):
    return f'<@{user.id}> · `{_name(getattr(user, "name", user.id), 120)}`'


def _embed(user, title, description, color, occurred):
    result = discord.Embed(title=title, description=description, color=color, timestamp=occurred)
    name = (getattr(user, 'display_name', None) or getattr(user, 'global_name', None)
            or getattr(user, 'name', None) or str(user.id))
    avatar = _avatar(user)
    result.set_author(name=_name(name, 250) or str(user.id), icon_url=avatar)
    if avatar:
        result.set_thumbnail(url=avatar)
    result.set_footer(text='VIce District • Actividad • '
        + occurred.astimezone(PR_TIME).strftime('%d/%m/%Y %H:%M:%S')
        + ' AST · Puerto Rico')
    result.add_field(name='Usuario', value=_user_id(user), inline=False)
    return result


class ViceActivity:
    def __init__(self, audit):
        self.audit = audit
        self.system = audit.system

    def _allowed(self, guild):
        if guild is None or getattr(guild, 'id', None) != GUILD_ID:
            return False
        self.system.validate_guild(guild)
        return True

    @staticmethod
    def _voice_channels_allowed(*channels):
        # A malformed or mismatched event must never expose another guild.
        return all(channel is None or getattr(getattr(channel, 'guild', None), 'id', None) == GUILD_ID
                   for channel in channels)

    async def voice_state_update(self, member, before, after):
        occurred = datetime.now(timezone.utc)
        if not self._allowed(getattr(member, 'guild', None)):
            return
        origin, destination = getattr(before, 'channel', None), getattr(after, 'channel', None)
        if not self._voice_channels_allowed(origin, destination):
            return
        origin_id, destination_id = _channel_id(origin), _channel_id(destination)
        if origin_id is None and destination_id is None:
            return
        changed_flags = [(flag, label, enabled if bool(getattr(after, flag, False)) else disabled)
                         for flag, label, enabled, disabled in VOICE_FLAGS
                         if bool(getattr(before, flag, False)) != bool(getattr(after, flag, False))]

        if origin_id != destination_id:
            if origin_id is None:
                kind, title, color = 'voice_join', '📥 Entró al canal de voz', GREEN
                description = f'<@{member.id}> se unió a {_channel(destination)}.'
            elif destination_id is None:
                kind, title, color = 'voice_leave', '📤 Salió del canal de voz', RED
                description = f'<@{member.id}> dejó {_channel(origin)}.'
            else:
                kind, title, color = 'voice_move', '🔀 Cambio de canal de voz', AMBER
                description = f'<@{member.id}> cambió de canal de voz.'
        elif changed_flags:
            kind, title, color = 'voice_state', '🎙️ Estado de voz actualizado', AMBER
            description = f'<@{member.id}> actualizó su estado de voz en {_channel(destination)}.'
        else:
            return

        embed = _embed(member, title, description, color, occurred)
        ids = [f'Usuario: `{member.id}`']
        if origin_id and destination_id and origin_id != destination_id:
            embed.add_field(name='Canal', value=f'{_channel(origin)}\n➡️ {_channel(destination)}', inline=False)
            ids.extend((f'Canal de origen: `{origin_id}`', f'Canal de destino: `{destination_id}`'))
        else:
            current = destination or origin
            embed.add_field(name='Canal', value=_channel(current), inline=False)
            ids.append(f'Canal: `{current.id}`')
        # Disconnect resets may reflect cached state rather than new user actions.
        if destination_id and changed_flags:
            embed.add_field(name='Cambios de voz', value='\n'.join(
                f'**{label}:** {status}' for _, label, status in changed_flags), inline=False)
        if kind in {'voice_move', 'voice_leave'} or any(flag in {'mute', 'deaf'} for flag, *_ in changed_flags):
            embed.add_field(name='Autoría', value='Este evento de voz no identifica al responsable. '
                'Las acciones de moderación se registran por separado cuando Discord aporta auditoría.', inline=False)
        embed.add_field(name='IDs', value='\n'.join(ids), inline=False)
        return await self.audit.publish('activity:' + kind + ':' + uuid.uuid4().hex, embed,
            event_type=kind, event_time=occurred)

    async def member_join(self, member):
        occurred = datetime.now(timezone.utc)
        if not self._allowed(getattr(member, 'guild', None)):
            return
        embed = _embed(member, '📥 Entró al servidor',
            f'<@{member.id}> se unió a **GTA VI Latino | VIce District**.', GREEN, occurred)
        created = getattr(member, 'created_at', None)
        if isinstance(created, datetime) and created.tzinfo is not None:
            embed.add_field(name='Cuenta creada', value=f'<t:{int(created.timestamp())}:F>', inline=False)
        embed.add_field(name='IDs', value=f'Usuario: `{member.id}`\nServidor: `{GUILD_ID}`', inline=False)
        return await self.audit.publish('activity:member_join:' + uuid.uuid4().hex, embed,
            event_type='member_join', event_time=occurred)

    async def member_remove(self, user, guild):
        occurred = datetime.now(timezone.utc)
        if not self._allowed(guild):
            return
        embed = _embed(user, '📤 Salió del servidor',
            f'<@{user.id}> salió de **GTA VI Latino | VIce District**.', RED, occurred)
        embed.add_field(name='Información de salida', value='El evento de salida no indica por sí solo '
            'si fue voluntaria o una acción de moderación. Los motivos de expulsión o veto '
            'se conservan en despedidas, exclusivo de Administración.', inline=False)
        embed.add_field(name='IDs', value=f'Usuario: `{user.id}`\nServidor: `{GUILD_ID}`', inline=False)
        return await self.audit.publish('activity:member_leave:' + uuid.uuid4().hex, embed,
            event_type='member_leave', event_time=occurred)
