"""Bounded Spanish embeds for Discord's evidenced audit-log entries.

This formatter never resolves an actor or affected member by proximity in time.
Voice-move/disconnect audit rows are aggregates, not per-member evidence.
"""
from datetime import datetime, timedelta, timezone
import re

import discord


GREEN, AMBER, RED = 0x45D483, 0xFFB44B, 0xF06478
PR_TIME = timezone(timedelta(hours=-4), 'AST')
ACTION_NAMES = {
    1: 'Servidor actualizado',
    10: 'Canal creado', 11: 'Canal actualizado', 12: 'Canal eliminado',
    13: 'Permiso de canal añadido', 14: 'Permiso de canal actualizado',
    15: 'Permiso de canal eliminado', 16: 'Canales reordenados',
    20: 'Miembro expulsado', 21: 'Depuración de miembros', 22: 'Miembro baneado',
    23: 'Baneo retirado', 24: 'Miembro actualizado', 25: 'Roles de miembro actualizados',
    26: 'Miembros movidos en voz', 27: 'Miembros desconectados de voz', 28: 'Bot añadido',
    30: 'Rol creado', 31: 'Rol actualizado', 32: 'Rol eliminado', 33: 'Roles reordenados',
    40: 'Invitación creada', 41: 'Invitación actualizada', 42: 'Invitación eliminada',
    50: 'Webhook creado', 51: 'Webhook actualizado', 52: 'Webhook eliminado',
    60: 'Emoji creado', 61: 'Emoji actualizado', 62: 'Emoji eliminado',
    72: 'Mensajes eliminados', 73: 'Borrado de mensajes en bloque',
    74: 'Mensaje fijado', 75: 'Mensaje desfijado',
    80: 'Integración creada', 81: 'Integración actualizada', 82: 'Integración eliminada',
    83: 'Escenario iniciado', 84: 'Escenario actualizado', 85: 'Escenario finalizado',
    90: 'Sticker creado', 91: 'Sticker actualizado', 92: 'Sticker eliminado',
    100: 'Evento programado creado', 101: 'Evento programado actualizado',
    102: 'Evento programado cancelado',
    110: 'Hilo creado', 111: 'Hilo actualizado', 112: 'Hilo eliminado',
    121: 'Permisos de comando actualizados',
    130: 'Sonido creado', 131: 'Sonido actualizado', 132: 'Sonido eliminado',
    140: 'Regla de AutoMod creada', 141: 'Regla de AutoMod actualizada',
    142: 'Regla de AutoMod eliminada', 143: 'AutoMod bloqueó un mensaje',
    144: 'AutoMod notificó un mensaje', 145: 'AutoMod aplicó un tiempo de espera',
    146: 'AutoMod restringió a un miembro',
    150: 'Solicitud de monetización creada', 151: 'Términos de monetización aceptados',
    163: 'Pregunta de incorporación creada', 164: 'Pregunta de incorporación actualizada',
    165: 'Pregunta de incorporación eliminada', 166: 'Incorporación configurada',
    167: 'Incorporación actualizada', 190: 'Guía del servidor creada',
    191: 'Guía del servidor actualizada', 192: 'Estado de canal de voz creado',
    193: 'Estado de canal de voz eliminado',
}
LABELS = {
    'name': 'Nombre', 'nick': 'Apodo', 'description': 'Descripción', 'topic': 'Tema',
    'roles': 'Roles', 'permissions': 'Permisos', 'allow': 'Permitir', 'deny': 'Denegar',
    'overwrites': 'Permisos por rol/miembro', 'colour': 'Color', 'color': 'Color',
    'hoist': 'Mostrar por separado', 'mentionable': 'Mencionable', 'position': 'Posición',
    'channel': 'Canal', 'category': 'Categoría', 'parent_id': 'Categoría / padre',
    'afk_channel': 'Canal AFK', 'system_channel': 'Canal del sistema',
    'rules_channel': 'Canal de normas', 'public_updates_channel': 'Canal de avisos oficiales',
    'widget_channel': 'Canal del widget', 'user_limit': 'Cupo', 'bitrate': 'Tasa de audio',
    'slowmode_delay': 'Modo lento (segundos)', 'default_thread_slowmode_delay': 'Modo lento de hilos',
    'nsfw': 'Restringido por edad', 'type': 'Tipo', 'mute': 'Silenciado por el servidor',
    'deaf': 'Ensordecido por el servidor', 'timed_out_until': 'Tiempo de espera hasta',
    'communication_disabled_until': 'Tiempo de espera hasta', 'owner': 'Propietario',
    'inviter': 'Invitador', 'user': 'Usuario', 'icon': 'Icono', 'avatar': 'Avatar',
    'banner': 'Banner', 'splash': 'Imagen de invitación', 'cover_image': 'Portada',
    'archived': 'Archivado', 'locked': 'Bloqueado', 'invitable': 'Permite invitaciones',
    'auto_archive_duration': 'Archivo automático (minutos)',
    'status': 'Estado', 'entity_type': 'Tipo de evento', 'location': 'Lugar',
    'scheduled_start_time': 'Inicio', 'scheduled_end_time': 'Fin',
    'verification_level': 'Verificación', 'explicit_content_filter': 'Filtro de contenido',
    'default_notifications': 'Notificaciones predeterminadas', 'mfa_level': 'Verificación del equipo',
    'preferred_locale': 'Idioma', 'premium_progress_bar_enabled': 'Barra de mejoras',
    'max_age': 'Validez (segundos)', 'max_uses': 'Usos máximos', 'uses': 'Usos',
    'temporary': 'Temporal', 'code': 'Código', 'enabled': 'Habilitado',
    'trigger_type': 'Activador de AutoMod', 'event_type': 'Tipo de evento AutoMod',
    'actions': 'Acciones', 'exempt_roles': 'Roles exentos', 'exempt_channels': 'Canales exentos',
    'available_tags': 'Etiquetas disponibles', 'applied_tags': 'Etiquetas aplicadas',
    'flags': 'Opciones', 'system_channel_flags': 'Opciones del canal del sistema',
    'privacy_level': 'Privacidad', 'video_quality_mode': 'Calidad de vídeo',
    'volume': 'Volumen', 'emoji': 'Emoji', 'default_reaction': 'Reacción predeterminada',
    'default_channels': 'Canales predeterminados', 'prompts': 'Preguntas', 'options': 'Opciones',
    'app_command_permissions': 'Permisos de comandos', 'format_type': 'Formato',
    'expire_behavior': 'Comportamiento al expirar', 'expire_grace_period': 'Gracia al expirar',
}
PERMISSION_NAMES = {
    'administrator': 'Administrador', 'view_channel': 'Ver canal',
    'read_message_history': 'Leer historial', 'send_messages': 'Enviar mensajes',
    'manage_messages': 'Gestionar mensajes', 'manage_channels': 'Gestionar canales',
    'manage_roles': 'Gestionar roles', 'manage_guild': 'Gestionar servidor',
    'kick_members': 'Expulsar miembros', 'ban_members': 'Banear miembros',
    'moderate_members': 'Tiempo de espera', 'view_audit_log': 'Ver auditoría',
    'connect': 'Conectar a voz', 'speak': 'Hablar', 'move_members': 'Mover miembros',
    'mute_members': 'Silenciar miembros', 'deafen_members': 'Ensordecer miembros',
    'add_reactions': 'Añadir reacciones', 'embed_links': 'Insertar enlaces',
    'attach_files': 'Adjuntar archivos', 'manage_webhooks': 'Gestionar webhooks',
    'mention_everyone': 'Mencionar a todos', 'send_messages_in_threads': 'Mensajes en hilos',
    'create_public_threads': 'Crear hilos públicos', 'create_private_threads': 'Crear hilos privados',
}
_SENSITIVE_KEY = re.compile(r'token|secret|password|authorization|credential|webhook_url|reason|^url$|^content$|message_content', re.I)
_WEBHOOK_URL = re.compile(r'(?:https?://)?(?:\w+\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/[^\s<>]+', re.I)
_TOKEN = re.compile(r'\b(?:mfa\.[\w-]{20,}|[\w-]{23,28}\.[\w-]{6}\.[\w-]{20,})\b')
_NAMED_SECRET = re.compile(r'\b(token|secret|password|authorization|contrase(?:ñ|n)a)\s*[:=]\s*\S+', re.I)
_MISSING = object()


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return getattr(obj, key, default)
    except (AttributeError, TypeError, ValueError, KeyError):
        return default


def _text(value, maximum=300):
    text = str(value)
    text = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)
    text = _WEBHOOK_URL.sub('[webhook oculto]', text)
    text = _TOKEN.sub('[credencial oculta]', text)
    text = _NAMED_SECRET.sub(lambda m: m.group(1) + '=[oculto]', text)
    text = discord.utils.escape_mentions(discord.utils.escape_markdown(text))
    return text if len(text) <= maximum else text[:maximum-1] + '…'


def _id(value):
    result = _get(value, 'id', value if isinstance(value, (int, str)) else None)
    if isinstance(result, bool):
        return None
    try:
        number = int(result)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def _entity(value, kind=None, maximum=230):
    identifier = _id(value)
    name = _get(value, 'display_name') or _get(value, 'name')
    display = _text(name, 100) if isinstance(name, str) and name else None
    if identifier:
        mention = {'user': f'<@{identifier}>', 'channel': f'<#{identifier}>',
                   'role': f'<@&{identifier}>'}.get(kind)
        label = (mention + (' · ' + display if display else '')) if mention else (display or 'Objeto')
        return (label + f' (`{identifier}`)')[:maximum]
    return display or 'No disponible en Discord'


def _avatar(user):
    url = _get(_get(user, 'display_avatar'), 'url')
    if isinstance(url, str) and url.startswith(('https://cdn.discordapp.com/', 'https://media.discordapp.net/')):
        return url
    return None


def _diff(value):
    if isinstance(value, dict):
        return value
    try:
        return dict(value) if value is not None else {}
    except (TypeError, ValueError):
        return vars(value) if hasattr(value, '__dict__') else {}


def _value(value, key='', depth=0):
    if value is _MISSING:
        return 'No informado'
    if value is None:
        return 'Sin valor'
    if depth > 2:
        return 'Datos adicionales'
    if isinstance(value, bool):
        return 'Sí' if value else 'No'
    if isinstance(value, datetime):
        stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return stamp.astimezone(PR_TIME).strftime('%d/%m/%Y %H:%M:%S AST')
    if isinstance(value, discord.Colour):
        return f'#{value.value:06X}'
    if isinstance(value, discord.Permissions):
        flags = [PERMISSION_NAMES.get(k, k.replace('_', ' ')) for k, enabled in value if enabled]
        shown = ', '.join(flags[:12]) or 'Ninguno'
        if len(flags) > 12:
            shown += f' (+{len(flags)-12})'
        return _text(shown, 260) + f' · `{value.value}`'
    if isinstance(value, discord.PermissionOverwrite):
        allow, deny = value.pair()
        return 'Permitir: ' + _value(allow) + '\nDenegar: ' + _value(deny)
    if isinstance(value, discord.Asset):
        return 'Imagen configurada'
    if isinstance(value, str):
        return _text(value, 320) or '(vacío)'
    if isinstance(value, (int, float)):
        if key.endswith('_id') and value > 0:
            return f'`{value}`'
        return str(value)
    if isinstance(value, (list, tuple, set)):
        if not value:
            return 'Ninguno'
        rendered = []
        for item in list(value)[:8]:
            if key == 'overwrites' and isinstance(item, tuple) and len(item) == 2:
                rendered.append(_entity(item[0]) + ': ' + _value(item[1], depth=depth+1))
            elif key in ('roles', 'exempt_roles'):
                rendered.append(_entity(item, 'role'))
            elif key in ('channels', 'exempt_channels', 'default_channels'):
                rendered.append(_entity(item, 'channel'))
            else:
                rendered.append(_value(item, key, depth+1))
        if len(value) > 8:
            rendered.append(f'… y {len(value)-8} más')
        return '\n'.join(rendered)[:420]
    if isinstance(value, dict):
        pieces = [f'{_text(k, 35)}: {_value(v, str(k), depth+1)}'
                  for k, v in value.items() if not _SENSITIVE_KEY.search(str(k))]
        return '\n'.join(pieces[:6])[:420] or 'Datos no publicables'
    if _id(value):
        kind = 'channel' if 'channel' in key or key == 'category' else ('user' if key in ('owner', 'inviter', 'user') else None)
        return _entity(value, kind)
    name = _get(value, 'name')
    if isinstance(name, str):
        return _text(name, 180)
    # Do not serialize object __dict__/repr: webhook and integration objects can carry credentials.
    return 'Valor registrado por Discord'


def _field(embed, name, value, *, inline=False):
    if len(embed.fields) >= 24:
        return False
    name = str(name)[:128]
    available = min(1024, 5400-len(embed)-len(name))
    if available < 24:
        return False
    value = str(value) or 'No disponible'
    if len(value) > available:
        value = value[:available-1] + '…'
    embed.add_field(name=name, value=value, inline=inline)
    return True


def format_audit_entry(entry, *, historical=False):
    """Describe only fields evidenced by this entry; safe for a staff-only channel."""
    action = _get(entry, 'action')
    raw_code = _get(action, 'value', action)
    try:
        code = int(raw_code)
    except (TypeError, ValueError):
        code = -1
    category = _get(_get(action, 'category'), 'name', '')
    colour = GREEN if category == 'create' or code in (23, 28, 150, 151, 192) else (
        RED if category == 'delete' or code in (20, 21, 22, 27, 143, 145, 146, 193) else AMBER)
    symbol = '🟢' if colour == GREEN else ('🔴' if colour == RED else '🟠')
    title = ACTION_NAMES.get(code, f'Acción de Discord ({code})')
    actor = _get(entry, 'user')
    actor_id = _id(actor) or _id(_get(entry, 'user_id'))
    actor_ref = actor if _id(actor) else actor_id
    target = _get(entry, 'target')
    target_id = _id(target) or _id(_get(entry, '_target_id'))
    target_ref = target if _id(target) else target_id
    kind = _get(action, 'target_type')
    if code == 72:
        kind = 'user'  # Discord's message-delete target is the message author.
    elif kind == 'thread':
        kind = 'channel'
    extra = _get(entry, 'extra')
    channel = _get(extra, 'channel')
    before, after = _diff(_get(entry, 'before')), _diff(_get(entry, 'after'))
    created = _get(entry, 'created_at')
    if not isinstance(created, datetime):
        identifier = _id(entry)
        created = discord.utils.snowflake_time(identifier) if identifier else None
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    embed = discord.Embed(title=f'{symbol} {title}', color=colour, timestamp=created)
    display_name = _get(actor, 'display_name') or _get(actor, 'name')
    embed.set_author(name=_text(display_name, 150) if isinstance(display_name, str) else 'Responsable no disponible',
                     icon_url=_avatar(actor))
    if kind == 'user' and code not in (26, 27) and _avatar(target):
        embed.set_thumbnail(url=_avatar(target))
    stamp = created.astimezone(PR_TIME).strftime('%d/%m/%Y %H:%M:%S AST') if created else 'Hora no disponible'
    embed.set_footer(text=f'VIce District • {"Histórico de auditoría" if historical else "Auditoría"} • {stamp} · Puerto Rico')
    _field(embed, 'Responsable', _entity(actor_ref, 'user') if actor_id else 'Discord no identifica al responsable.')
    identifiers = []
    if actor_id:
        identifiers.append(f'Responsable: `{actor_id}`')
    if code in (26, 27):
        count = _get(extra, 'count')
        quantity = str(count) if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else 'No informada'
        embed.description = ('Movimiento administrativo de voz registrado por Discord.' if code == 26
                             else 'Desconexión administrativa de voz registrada por Discord.')
        _field(embed, 'Cantidad acumulada', quantity)
        if channel is not None:
            _field(embed, 'Canal de destino', _entity(channel, 'channel'))
        _field(embed, 'Alcance del registro',
               'Esta entrada puede agrupar varias acciones. Discord no identifica aquí a cada miembro afectado '
               'ni el canal de origen; los cambios individuales de voz se registran por separado.')
        # Never infer or expose a subject from a group-action target or a neighboring voice event.
        target_id = None
    else:
        if target_id:
            label = 'Autor de los mensajes' if code == 72 else 'Objeto afectado'
            _field(embed, label, _entity(target_ref, kind))
            identifiers.append(f'Afectado: `{target_id}`')
        if channel is not None:
            _field(embed, 'Canal', _entity(channel, 'channel'))
        count = _get(extra, 'count')
        if isinstance(count, int) and not isinstance(count, bool):
            _field(embed, 'Cantidad acumulada', str(count))
        if code == 21:
            for key, label in (('members_removed', 'Miembros retirados'), ('delete_member_days', 'Días de inactividad')):
                value = _get(extra, key)
                if isinstance(value, int):
                    _field(embed, label, str(value))
        if code in (13, 14, 15) and _id(extra):
            _field(embed, 'Permiso aplicado a', _entity(extra))
            identifiers.append(f'Rol / miembro: `{_id(extra)}`')
        rule_name = _get(extra, 'automod_rule_name')
        if isinstance(rule_name, str):
            _field(embed, 'Regla de AutoMod', _text(rule_name, 250))
    if _id(channel):
        identifiers.append(f'Canal: `{_id(channel)}`')
    message_id = _id(_get(extra, 'message_id'))
    if message_id:
        identifiers.append(f'Mensaje: `{message_id}`')
    if _id(entry):
        identifiers.append(f'Auditoría: `{_id(entry)}`')
    _field(embed, 'IDs', '\n'.join(identifiers) or 'No disponibles')
    if code in (20, 22):
        _field(embed, 'Motivo', 'Los detalles de la salida se conservan en despedidas, exclusivo de Administración.')
    else:
        reason = _get(entry, 'reason')
        _field(embed, 'Motivo', _text(reason, 700) if isinstance(reason, str) and reason else 'No indicado en la auditoría de Discord.')
    if code == 25:
        for key, label, values in (('roles', 'Roles retirados', before.get('roles')),
                                   ('roles', 'Roles añadidos', after.get('roles'))):
            if values:
                _field(embed, label, _value(values, key))
    for key in dict.fromkeys((*before, *after)):
        if _SENSITIVE_KEY.search(str(key)) or (code == 25 and key == 'roles'):
            continue
        label = LABELS.get(key, _text(str(key).replace('_', ' '), 70).capitalize())
        old, new = before.get(key, _MISSING), after.get(key, _MISSING)
        if old is _MISSING:
            value = _value(new, key)
        elif new is _MISSING:
            value = _value(old, key)
        else:
            value = '**Antes:** ' + _value(old, key) + '\n**Después:** ' + _value(new, key)
        if not _field(embed, label, value):
            break
    return embed
