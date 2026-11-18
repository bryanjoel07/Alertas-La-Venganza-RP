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


def _embed(user, description, color, occurred, *, thumbnail=False):
    result = discord.Embed(description=description, color=color, timestamp=occurred)
    name = (getattr(user, 'display_name', None) or getattr(user, 'global_name', None)
            or getattr(user, 'name', None) or str(user.id))
    avatar = _avatar(user)
    result.set_author(name=_name(name, 80) or str(user.id), icon_url=avatar)
    if avatar and thumbnail:
        result.set_thumbnail(url=avatar)
    result.set_footer(text='VIce District • '
        + occurred.astimezone(PR_TIME).strftime('%d/%m/%Y %H:%M:%S')
        + ' AST')
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
                kind, color = 'voice_join', GREEN
                description = f'📥 <@{member.id}> entró a <#{destination_id}>.'
            elif destination_id is None:
                kind, color = 'voice_leave', RED
                description = f'📤 <@{member.id}> dejó <#{origin_id}>.'
            else:
                kind, color = 'voice_move', AMBER
                description = f'🔀 <@{member.id}> cambió de canal de voz.'
        elif changed_flags:
            kind, color = 'voice_state', AMBER
            description = f'🎙️ <@{member.id}> actualizó su voz en <#{destination_id}>.'
        else:
            return

        # Moves already use a Canal field, so combine any simultaneous state
        # changes into that one sentence instead of adding a third field.
        if kind == 'voice_move' and changed_flags:
            description = description[:-1] + ' (' + '; '.join(
                f'{label.lower()}: {status.lower()}' for _, label, status in changed_flags) + ').'
        embed = _embed(member, description, color, occurred)
        ids = [f'Usuario: `{member.id}`']
        if origin_id and destination_id and origin_id != destination_id:
            embed.add_field(name='Canal', value=f'<#{origin_id}> ➜ <#{destination_id}>', inline=False)
            ids.extend((f'Origen: `{origin_id}`', f'Destino: `{destination_id}`'))
        else:
            current = destination or origin
            ids.append(f'Canal: `{current.id}`')
        # Disconnect resets may reflect cached state rather than new user actions.
        if destination_id and changed_flags and kind != 'voice_move':
            embed.add_field(name='Estado', value='\n'.join(
                f'{label}: {status.lower()}' for _, label, status in changed_flags), inline=False)
        embed.add_field(name='IDs', value='\n'.join(ids), inline=False)
        return await self.audit.publish('activity:' + kind + ':' + uuid.uuid4().hex, embed,
            event_type=kind, event_time=occurred)

    async def member_join(self, member):
        occurred = datetime.now(timezone.utc)
        if not self._allowed(getattr(member, 'guild', None)):
            return
        embed = _embed(member, f'📥 <@{member.id}> entró al servidor.', GREEN, occurred, thumbnail=True)
        created = getattr(member, 'created_at', None)
        if isinstance(created, datetime) and created.tzinfo is not None:
            embed.add_field(name='Cuenta creada', value=f'<t:{int(created.timestamp())}:F>', inline=False)
        embed.add_field(name='IDs', value=f'`{member.id}`', inline=False)
        return await self.audit.publish('activity:member_join:' + uuid.uuid4().hex, embed,
            event_type='member_join', event_time=occurred)

    async def member_remove(self, user, guild):
        occurred = datetime.now(timezone.utc)
        if not self._allowed(guild):
            return
        embed = _embed(user, f'📤 <@{user.id}> dejó el servidor.', RED, occurred, thumbnail=True)
        embed.add_field(name='IDs', value=f'`{user.id}`', inline=False)
        return await self.audit.publish('activity:member_leave:' + uuid.uuid4().hex, embed,
            event_type='member_leave', event_time=occurred)
