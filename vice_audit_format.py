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


def _avatar(user):
    url = _get(_get(user, 'display_avatar'), 'url')
    return _safe_avatar(url)


def _safe_avatar(url):
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


def _cut(value, maximum):
    value = str(value)
    return value if len(value) <= maximum else value[:maximum-1] + '…'


def _rich(value, maximum=240):
    """Keep our generated mentions while stripping legacy journal markers and secrets."""
    text = str(value or '')
    text = re.sub(r'\s*[•|]?\s*ref:[a-f0-9]{8,64}', '', text, flags=re.I)
    text = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)
    text = _WEBHOOK_URL.sub('[webhook oculto]', text)
    text = _TOKEN.sub('[credencial oculta]', text)
    text = _NAMED_SECRET.sub(lambda m: m.group(1) + '=[oculto]', text)
    text = ''.join(part if re.fullmatch(r'<(?:@!?|@&|#)\d+>', part) else discord.utils.escape_mentions(part)
                   for part in re.split(r'(<(?:@!?|@&|#)\d+>)', text))
    return _cut(text.strip(), maximum)


def _ref(value, kind=None, *, fallback='el objeto', deleted=False):
    identifier = _id(value)
    name = _get(value, 'display_name') or _get(value, 'name')
    if deleted and isinstance(name, str):
        return '«' + _text(name, 65) + '»'
    if identifier and kind in ('user', 'channel', 'role'):
        return {'user': f'<@{identifier}>', 'channel': f'<#{identifier}>',
                'role': f'<@&{identifier}>'}[kind]
    if isinstance(name, str) and name:
        return '«' + _text(name, 65) + '»'
    return fallback


PERMISSION_NAMES.update({
    'create_instant_invite': 'Crear invitaciones', 'priority_speaker': 'Prioridad de voz',
    'stream': 'Transmitir', 'read_messages': 'Ver canal', 'send_tts_messages': 'Texto a voz',
    'external_emojis': 'Emojis externos', 'view_guild_insights': 'Estadísticas del servidor',
    'use_voice_activation': 'Actividad de voz', 'change_nickname': 'Cambiar apodo',
    'manage_nicknames': 'Gestionar apodos', 'manage_expressions': 'Gestionar expresiones',
    'use_application_commands': 'Usar comandos', 'request_to_speak': 'Solicitar palabra',
    'manage_events': 'Gestionar eventos', 'manage_threads': 'Gestionar hilos',
    'external_stickers': 'Stickers externos', 'use_embedded_activities': 'Iniciar actividades',
    'view_creator_monetization_analytics': 'Estadísticas de monetización',
    'use_soundboard': 'Panel de sonidos', 'create_expressions': 'Crear expresiones',
    'create_events': 'Crear eventos', 'use_external_sounds': 'Sonidos externos',
    'send_voice_messages': 'Mensajes de voz', 'set_voice_channel_status': 'Estado del canal de voz',
    'send_polls': 'Enviar encuestas', 'use_external_apps': 'Aplicaciones externas',
    'pin_messages': 'Fijar mensajes', 'bypass_slowmode': 'Omitir modo lento',
})


def _bits(value):
    raw = _get(value, 'value', value)
    try:
        return max(0, int(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


PERMISSION_FIELD_NAMES = ('Permisos autorizados', 'Permisos denegados', 'Permisos restablecidos')


def is_permission_field(name):
    """Publisher contract: never truncate these fields, including continuations."""
    return any(str(name) == base or re.fullmatch(re.escape(base) + r' \(\d+\)', str(name))
               for base in PERMISSION_FIELD_NAMES)


def _permission_changes(before, after, *, overwrite=False):
    """Every changed flag, grouped by its new state; no raw bitmasks or omitted rows."""
    if overwrite:
        old_allow, old_deny = _bits(before.get('allow')), _bits(before.get('deny'))
        new_allow, new_deny = _bits(after.get('allow')), _bits(after.get('deny'))
    else:
        old_allow, new_allow = _bits(before.get('permissions')), _bits(after.get('permissions'))
        old_deny = new_deny = 0
    changes = {name: [] for name in PERMISSION_FIELD_NAMES}
    named_bits, seen = [], set()
    for name, _ in discord.Permissions.none():
        bit = discord.Permissions.VALID_FLAGS[name]
        if bit not in seen:
            named_bits.append((name, bit))
            seen.add(bit)
    # Include future library flags even if its iterator has not caught up.
    for name, bit in discord.Permissions.VALID_FLAGS.items():
        if bit not in seen:
            named_bits.append((name, bit))
            seen.add(bit)
    remaining = (old_allow ^ new_allow) | (old_deny ^ new_deny)
    for bit in seen:
        remaining &= ~bit
    while remaining:
        bit = remaining & -remaining
        named_bits.append((f'Permiso desconocido (bit {bit.bit_length()-1})', bit))
        remaining &= ~bit
    for name, bit in named_bits:
        old = 1 if old_allow & bit else (-1 if old_deny & bit else 0)
        new = 1 if new_allow & bit else (-1 if new_deny & bit else 0)
        if old == new:
            continue
        group = 0 if new == 1 else (2 if overwrite and new == 0 else 1)
        icon = ('✅', '❌', '↩️')[group]
        changes[PERMISSION_FIELD_NAMES[group]].append(icon + ' ' + PERMISSION_NAMES.get(name, name))
    return {name: lines for name, lines in changes.items() if lines}


def _append_permission_fields(embed, groups):
    """Split only between complete permission lines; preserve all supplied rows."""
    for base in PERMISSION_FIELD_NAMES:
        chunks, chunk = [], []
        for line in groups.get(base, []):
            if len(line) > 1024:
                raise ValueError('El nombre de un permiso excede el límite de Discord.')
            if chunk and len('\n'.join(chunk + [line])) > 1024:
                chunks.append('\n'.join(chunk))
                chunk = []
            chunk.append(line)
        if chunk:
            chunks.append('\n'.join(chunk))
        for index, value in enumerate(chunks, 1):
            name = base if index == 1 else f'{base} ({index})'
            embed.add_field(name=name, value=value, inline=False)


def _simple(value, key=''):
    if value is None or value is _MISSING:
        return '—'
    if isinstance(value, bool):
        return 'Sí' if value else 'No'
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return value.astimezone(PR_TIME).strftime('%d/%m %H:%M AST')
    if isinstance(value, discord.Colour):
        return f'#{value.value:06X}'
    if isinstance(value, discord.Asset):
        return 'Imagen'
    if isinstance(value, (str, int, float)):
        return _text(value, 65) or '—'
    if _id(value):
        return _ref(value, 'channel' if 'channel' in key else None)
    name = _get(value, 'name')
    return _text(name, 65) if isinstance(name, str) else 'Actualizado'


def _roles(values, sign):
    refs = [f'<@&{_id(v)}>' for v in (values or []) if _id(v)]
    return sign + ' ' + ' '.join(refs[:4]) + (f' +{len(refs)-4}' if len(refs) > 4 else '') if refs else ''


def _role_summary(added, removed, actor, target):
    if added and not removed:
        return GREEN, f'{actor} añadió roles a {target}.'
    if removed and not added:
        return RED, f'{actor} retiró roles de {target}.'
    return AMBER, f'{actor} actualizó los roles de {target}.'


def _changes(code, category, before, after):
    if code in (13, 14, 15):
        return _permission_changes(before, after, overwrite=True)
    if code == 25:
        return ' · '.join(filter(None, (_roles(after.get('roles'), '+'), _roles(before.get('roles'), '−'))))
    if category != 'update' and code not in (1, 24, 31, 192, 193):
        return ''
    if 'permissions' in before or 'permissions' in after:
        return _permission_changes(before, after)
    keys = ('name', 'nick', 'topic', 'channel', 'timed_out_until', 'mute', 'deaf', 'colour',
            'user_limit', 'slowmode_delay', 'description', 'position', 'hoist', 'mentionable',
            'nsfw', 'archived', 'locked', 'status', 'enabled', 'icon', 'avatar', 'banner')
    lines = []
    for key in keys:
        if key not in before and key not in after:
            continue
        old, new = before.get(key, _MISSING), after.get(key, _MISSING)
        if _simple(old, key) == _simple(new, key):
            continue
        lines.append(f'{LABELS[key]}: {_simple(old, key)} → {_simple(new, key)}')
    return _cut(' · '.join(lines[:2]) + (f' · +{len(lines)-2} cambios' if len(lines) > 2 else ''), 180)


def _quantity(value, word):
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return f'{value} {word}' + ('' if value == 1 else 's')
    return word + 's'


def _sentence(code, actor, target, channel, extra_ref, count):
    target = target or 'el objeto'
    place = ' en ' + channel if channel else ''
    creates = {10: 'creó', 30: 'creó el rol', 40: 'creó una invitación',
               50: 'creó el webhook', 60: 'creó el emoji', 80: 'añadió la integración',
               83: 'inició el escenario', 90: 'creó el sticker', 100: 'programó el evento',
               110: 'creó el hilo', 130: 'añadió el sonido', 140: 'creó la regla de AutoMod',
               163: 'creó la pregunta', 166: 'configuró la incorporación', 190: 'creó la guía',
               192: 'estableció el estado de voz'}
    updates = {11: 'actualizó', 31: 'actualizó el rol', 41: 'actualizó una invitación',
               51: 'actualizó el webhook', 61: 'actualizó el emoji', 81: 'actualizó la integración',
               84: 'actualizó el escenario', 91: 'actualizó el sticker', 101: 'actualizó el evento',
               111: 'actualizó el hilo', 131: 'actualizó el sonido', 141: 'actualizó la regla de AutoMod',
               164: 'actualizó la pregunta', 167: 'actualizó la incorporación', 191: 'actualizó la guía'}
    deletes = {12: 'eliminó', 32: 'eliminó el rol', 42: 'eliminó una invitación',
               52: 'eliminó el webhook', 62: 'eliminó el emoji', 82: 'retiró la integración',
               85: 'finalizó el escenario', 92: 'eliminó el sticker', 102: 'canceló el evento',
               112: 'eliminó el hilo', 132: 'eliminó el sonido', 142: 'eliminó la regla de AutoMod',
               165: 'eliminó la pregunta', 193: 'retiró el estado de voz'}
    if code in (13, 14, 15):
        verb = {13: 'añadió', 14: 'actualizó', 15: 'retiró'}[code]
        return f'{actor} {verb} permisos{(" de " + extra_ref) if extra_ref else ""} en {target}.'
    if code == 26:
        return f'{actor} movió a {_quantity(count, "miembro")}{(" a " + channel) if channel else ""}.'
    if code == 27:
        return f'{actor} desconectó de voz a {_quantity(count, "miembro")}.'
    if code in (72, 73):
        author = ' de ' + target if code == 72 and target != 'el objeto' else ''
        return f'{actor} eliminó {_quantity(count, "mensaje")}{author}{place}.'
    special = {
        1: f'{actor} actualizó el servidor.', 16: f'{actor} reordenó los canales.',
        20: f'{actor} expulsó a {target}.', 21: f'{actor} retiró {_quantity(count, "miembro")} inactivos.',
        22: f'{actor} baneó a {target}.', 23: f'{actor} retiró el baneo de {target}.',
        24: f'{actor} actualizó a {target}.', 25: f'{actor} actualizó los roles de {target}.',
        28: f'{actor} añadió al bot {target}.', 33: f'{actor} reordenó los roles.',
        74: f'{actor} fijó un mensaje{place}.', 75: f'{actor} desfijó un mensaje{place}.',
        121: f'{actor} actualizó los permisos de un comando.',
        143: f'AutoMod bloqueó un mensaje de {target}{place}.',
        144: f'AutoMod notificó un mensaje de {target}{place}.',
        145: f'AutoMod aplicó un tiempo de espera a {target}.',
        146: f'AutoMod restringió a {target}.',
        150: f'{actor} creó una solicitud de monetización.',
        151: f'{actor} aceptó los términos de monetización.',
    }
    if code in special:
        return special[code]
    for verbs in (creates, updates, deletes):
        if code in verbs:
            subject = '' if target == 'el objeto' else ' ' + target
            return f'{actor} {verbs[code]}{subject}{place}.'
    return f'{actor} registró {ACTION_NAMES.get(code, f"la acción {code}").lower()}.'


def _ids(pairs):
    seen, items = set(), []
    for label, identifier in pairs:
        identifier = _id(identifier)
        if identifier and identifier not in seen:
            seen.add(identifier)
            items.append(f'{label} {chr(96)}{identifier}{chr(96)}')
    chosen = []
    for item in items:
        if len(' · '.join(chosen + [item])) > 350:
            break
        chosen.append(item)
    suffix = f' · +{len(items)-len(chosen)} IDs' if len(chosen) < len(items) else ''
    return ' · '.join(chosen) + suffix


def _card(description, color, created, *, author_name=None, avatar=None, thumbnail=None,
          change='', reason='', identifiers=''):
    result = discord.Embed(description=_rich(description, 240), color=color, timestamp=created)
    if isinstance(author_name, str) and author_name.strip():
        result.set_author(name=_text(author_name, 80), icon_url=_safe_avatar(avatar))
    if _safe_avatar(thumbnail):
        result.set_thumbnail(url=thumbnail)
    stamp = ''
    if isinstance(created, datetime):
        created = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
        stamp = ' • ' + created.astimezone(PR_TIME).strftime('%d/%m %H:%M AST')
    result.set_footer(text='VIce District' + stamp)
    permissions = isinstance(change, dict)
    if permissions:
        _append_permission_fields(result, change)
    for name, value, maximum in (('Cambio', '' if permissions else change, 280),
                                 ('Razón', reason, 160), ('IDs', identifiers, 370)):
        if value:
            result.add_field(name=name, value=_cut(value, maximum), inline=False)
    if permissions:
        if len(result.fields) > 25 or len(result) >= 5900:
            raise ValueError('Los permisos completos exceden la capacidad de una tarjeta de Discord.')
        return result
    # Keep room for the durable marker added by the publisher.
    while len(result) > 1050:
        candidates = [(len(f.value), i) for i, f in enumerate(result.fields) if f.name != 'IDs']
        if not candidates:
            result.description = _cut(result.description, max(20, len(result.description)-(len(result)-1050)))
            break
        _, index = max(candidates)
        current = result.fields[index]
        length = max(20, len(current.value)-(len(result)-1050))
        result.set_field_at(index, name=current.name, value=_cut(current.value, length), inline=False)
    return result


def format_audit_entry(entry, *, historical=False):
    """Small Koya-style cards. Actor and counts come only from this audit entry."""
    action = _get(entry, 'action')
    try:
        code = int(_get(action, 'value', action))
    except (ValueError, TypeError):
        code = -1
    category = _get(_get(action, 'category'), 'name', '')
    before, after = _diff(_get(entry, 'before')), _diff(_get(entry, 'after'))
    color = GREEN if category == 'create' or code in (23, 28, 150, 151, 192) else (
        RED if category == 'delete' or code in (20, 21, 22, 27, 143, 145, 146, 193) else AMBER)
    actor = _get(entry, 'user')
    actor_id = _id(actor) or _id(_get(entry, 'user_id'))
    target = _get(entry, 'target')
    target_id = _id(target) or _id(_get(entry, '_target_id'))
    if code in (26, 27):
        target = target_id = None
    kind = _get(action, 'target_type')
    if code == 72:
        kind = 'user'
    elif kind == 'thread':
        kind = 'channel'
    extra = _get(entry, 'extra')
    channel = _get(extra, 'channel')
    count = _get(extra, 'members_removed' if code == 21 else 'count')
    extra_ref = None
    if code in (13, 14, 15) and _id(extra):
        extra_type = _get(extra, 'type')
        kind_extra = 'role' if isinstance(extra, discord.Role) or extra_type is discord.Role else 'user'
        extra_ref = _ref(extra, kind_extra)
    target_ref = _ref(target if _id(target) else target_id, kind,
                      deleted=category == 'delete' and kind != 'user')
    # Deleted entities often resolve only to an ID. Their original name is
    # evidence in before.name; never substitute an unrelated/current name.
    prior_name = before.get('name')
    if (category == 'delete' and kind != 'user' and not _get(target, 'name')
            and isinstance(prior_name, str) and prior_name.strip()):
        target_ref = '«' + _text(prior_name, 65) + '»'
    actor_ref = _ref(actor_id, 'user', fallback='Se')
    sentence = _sentence(code, actor_ref, target_ref, _ref(channel, 'channel') if channel else '',
                         extra_ref, count)
    if code == 25:
        color, sentence = _role_summary(after.get('roles'), before.get('roles'), actor_ref, target_ref)
    pairs = [('Actor', actor_id), ('Canal' if kind == 'channel' else 'Afectado', target_id)]
    if _id(extra) and code in (13, 14, 15):
        pairs.append(('Permiso', _id(extra)))
    pairs.extend((('Canal', _id(channel)), ('Mensaje', _id(_get(extra, 'message_id')))))
    reason = _get(entry, 'reason')
    reason = _text(reason.strip(), 160) if code not in (20, 22) and isinstance(reason, str) and reason.strip() else ''
    created = _get(entry, 'created_at')
    if not isinstance(created, datetime):
        created = discord.utils.snowflake_time(_id(entry)) if _id(entry) else None
    return _card(sentence, color, created,
                 author_name=_get(actor, 'display_name') or _get(actor, 'name'), avatar=_avatar(actor),
                 thumbnail=_avatar(target) if kind == 'user' and code not in (26, 27) else None,
                 change=_changes(code, category, before, after), reason=reason, identifiers=_ids(pairs))


def _stored_ref(value, kind=None):
    matches = re.findall(r'<(?:@!?|@&|#)\d+>', str(value or ''))
    if matches:
        return matches[0]
    without_ids = re.sub(r'\(?\x60\d+\x60\)?', '', str(value or '')).strip(' ·')
    if without_ids and not re.search(r'no disponible|no identifica', without_ids, re.I):
        return _rich(without_ids, 70)
    return ''


def _stored_count(value):
    text = str(value or '').strip()
    return int(text) if text.isdigit() else None


def _stored_pair(value):
    match = re.search(r'\*\*Antes:\*\*(.*?)\*\*Después:\*\*(.*)', str(value or ''), re.S)
    return (match.group(1).strip(), match.group(2).strip()) if match else None


def _stored_bits(value):
    matches = re.findall(r'\x60(\d+)\x60', value)
    if matches:
        return int(matches[-1])
    return int(value) if value.strip().isdigit() else None


def _stored_changes(fields, code):
    groups = {}
    for name, value in fields.items():
        if is_permission_field(name):
            base = next(base for base in PERMISSION_FIELD_NAMES if name.startswith(base))
            groups.setdefault(base, []).extend(_rich(line, 1024) for line in value.splitlines() if line.strip())
    if groups:
        return groups
    if code in (13, 14, 15, 31) or any(name in fields for name in ('Permitir', 'Denegar', 'Permisos')):
        before, after = {}, {}
        for label, key in (('Permitir', 'allow'), ('Denegar', 'deny'), ('Permisos', 'permissions')):
            pair = _stored_pair(fields.get(label))
            if pair:
                old, new = map(_stored_bits, pair)
                if old is not None and new is not None:
                    before[key], after[key] = old, new
            elif code in (13, 15):
                value = _stored_bits(fields.get(label, ''))
                if value is not None:
                    (after if code == 13 else before)[key] = value
        if before or after:
            overwrite = code in (13, 14, 15) or 'allow' in before or 'deny' in before or 'allow' in after or 'deny' in after
            return _permission_changes(before, after, overwrite=overwrite)
    # Older compact cards may only retain their already-visible permission rows.
    # A fresh audit read is required to recover anything previously omitted.
    for part in re.split(r'\s*·\s*|\n', fields.get('Cambio', '')):
        part = part.strip()
        for icon, base in zip(('✅', '❌', '↩️'), PERMISSION_FIELD_NAMES):
            if part.startswith(icon + ' '):
                groups.setdefault(base, []).append(_rich(part, 1024))
                break
    if groups:
        return groups
    if code == 25:
        pieces = []
        for label, sign in (('Roles añadidos', '+'), ('Roles retirados', '−')):
            roles = re.findall(r'<@&\d+>', fields.get(label, ''))
            if roles:
                pieces.append(sign + ' ' + ' '.join(roles[:4]) + (f' +{len(roles)-4}' if len(roles) > 4 else ''))
        return ' · '.join(pieces)
    if code in (10, 12, 20, 22, 30, 32, 40, 42, 50, 52, 60, 62, 80, 82, 90, 92, 100, 102, 110, 112):
        return ''
    for label in ('Cambio', 'Cambios de voz', 'Nombre', 'Apodo', 'Tema', 'Canal', 'Color', 'Cupo'):
        raw = fields.get(label, '')
        if not raw:
            continue
        pair = _stored_pair(raw)
        if pair:
            return _rich(f'{label}: {_cut(pair[0], 70)} → {_cut(pair[1], 70)}', 180)
        if label in ('Cambio', 'Cambios de voz'):
            return _rich(raw, 180)
    return ''


def compact_stored_embed(embed, *, event_type='audit'):
    """Compact our old persisted cards without guessing missing audit details."""
    source = discord.Embed.from_dict(embed) if isinstance(embed, dict) else embed
    fields = {str(f.name): str(f.value) for f in source.fields}
    title = str(source.title or '')
    code = next((code for code, label in ACTION_NAMES.items() if label in title), None)
    actor = _stored_ref(fields.get('Responsable')) or 'Se'
    target = _stored_ref(fields.get('Objeto afectado') or fields.get('Autor de los mensajes'))
    channels = re.findall(r'<#\d+>', fields.get('Canal de destino') or fields.get('Canal', ''))
    channel = channels[-1] if channels else ''
    description = str(source.description or '')
    color = source.color or AMBER
    if event_type == 'audit' and code is not None:
        description = _sentence(code, actor, target, channel,
                                _stored_ref(fields.get('Permiso aplicado a')),
                                _stored_count(fields.get('Cantidad acumulada') or fields.get('Miembros retirados')))
        if code == 25:
            color, description = _role_summary(re.findall(r'<@&\d+>', fields.get('Roles añadidos', '')),
                                               re.findall(r'<@&\d+>', fields.get('Roles retirados', '')),
                                               actor, target or 'el miembro')
    elif event_type != 'audit':
        member = _stored_ref(fields.get('Usuario'))
        if not member:
            found = re.search(r'<@!?\d+>', description)
            member = found.group(0) if found else 'Un miembro'
        if not channels:
            channels = re.findall(r'<#\d+>', description)
        if event_type == 'voice_join':
            description = f'{member} se unió{(" a " + channels[-1]) if channels else " a voz"}.'
        elif event_type == 'voice_leave':
            description = f'{member} dejó{(" " + channels[0]) if channels else " el canal de voz"}.'
        elif event_type == 'voice_move':
            description = (f'{member} cambió de {channels[0]} a {channels[-1]}.' if len(channels) >= 2
                           else f'{member} cambió de canal de voz.')
        elif event_type == 'voice_state':
            description = f'{member} actualizó su estado de voz{(" en " + channels[-1]) if channels else ""}.'
        elif event_type == 'member_join':
            description = f'{member} entró al servidor.'
        elif event_type == 'member_leave':
            description = f'{member} salió del servidor.'
    if not description:
        description = _rich(title, 150) or 'Actividad registrada.'
    pairs = []
    for line in fields.get('IDs', '').replace(' · ', '\n').splitlines():
        for identifier in re.findall(r'\x60(\d+)\x60', line):
            label = line.split(':', 1)[0] if ':' in line else line.split(chr(96), 1)[0]
            label = re.sub(r'[\s:]+$', '', label)
            if code in (26, 27) and re.search(r'afectado|origen', label, re.I):
                continue
            pairs.append((_text(label, 18) or 'ID', identifier))
    # Include evidenced mentions when the stored IDs block was absent or incomplete.
    identity_keys = ('Responsable', 'Canal de destino') if code in (26, 27) else (
        'Responsable', 'Objeto afectado', 'Autor de los mensajes', 'Usuario', 'Canal', 'Canal de destino')
    identity_values = [description] + [fields.get(k, '') for k in identity_keys]
    for text in identity_values:
        for mention in re.findall(r'<(?:@!?|@&|#)(\d+)>', text):
            pairs.append(('ID', mention))
    reason = fields.get('Razón') or fields.get('Motivo', '')
    if (code in (20, 22) or event_type == 'member_leave'
            or re.search(r'no indicado|no disponible|no identifica|despedidas|exclusivo de Administración', reason, re.I)):
        reason = ''
    change = _stored_changes(fields, code)
    return _card(description, color, source.timestamp,
                 author_name=source.author.name, avatar=source.author.icon_url,
                 thumbnail=source.thumbnail.url,
                 change=change, reason=_rich(reason, 160) if reason.strip() else '', identifiers=_ids(pairs))
