"""Frozen, rename-only typography migration for VIce District channels."""
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import unicodedata

import discord


# Kept independent of vice_design so display-name constants can use stylize().
GUILD_ID = 1572462544302383164
BOT_ID = 1571639486591402174
OWNER_ID = 1509288420852109383
VERSION = 'vice-channel-style-v5'
MANIFEST = Path(__file__).parent / 'assets' / 'vice-district' / 'channel-style-v5.json'
RESTORE_REFERENCE = Path(__file__).parent / 'assets' / 'vice-district' / 'channel-style-v2.json'
TEAM_CATEGORY_ID = 1572467006999896074
ICON_SEPARATOR = '╎'
CATEGORY_EDGES = {'first': '↱', 'middle': '│', 'last': '↳'}
SUPPORTED_TYPES = frozenset((0, 2, 4, 5, 13, 15, 16))
SMALL_CAPS = dict(zip('abcdefghijklmnopqrstuvwxyz', 'ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘꞯʀꜱᴛᴜᴠᴡXʏᴢ'))
FROM_SMALL_CAPS = {value: key for key, value in SMALL_CAPS.items()}
log = logging.getLogger('ViceDistrict.channel_style')


def stylize(name):
    """Small-cap letters with normal digits, without changing emoji or separators.

    Normalize only letters/digits, never the whole string: NFKD on emoji such
    as a keycap would alter their appearance. Accents remain combining marks
    on the corresponding small-cap letter, including Spanish ñ and accented í.
    """
    result, text = [], str(name)
    for index, character in enumerate(text):
        if character in '0123456789#*' and (text[index + 1:index + 3] == '\ufe0f\u20e3'
                                            or text[index + 1:index + 2] == '\u20e3'):
            result.append(character)
            continue
        numeric = '0' <= character <= '9' or 0x1D7CE <= ord(character) <= 0x1D7FF
        if unicodedata.category(character)[0] != 'L' and not numeric:
            result.append(character)
            continue
        expanded = unicodedata.normalize('NFKD', FROM_SMALL_CAPS.get(character, character))
        if not all(('A' <= unit <= 'Z' or 'a' <= unit <= 'z' or '0' <= unit <= '9'
                    or unicodedata.combining(unit)) for unit in expanded):
            result.append(character)
            continue
        for unit in expanded:
            if unit.lower() in SMALL_CAPS:
                result.append(SMALL_CAPS[unit.lower()])
            else:
                result.append(unit)
    return ''.join(result)


def _first_separator(text):
    matches = [(text.index(separator), separator) for separator in (ICON_SEPARATOR, '│')
               if separator in text]
    return min(matches)[1] if matches else None


def _split_icon_label(text):
    separator = _first_separator(text)
    if separator:
        icon, label = text.split(separator, 1)
        return icon.strip(), label.strip()
    # Dynamic voice names have a leading emoji followed by a player's name.
    for index, character in enumerate(text):
        if (unicodedata.category(character) in ('So', 'Sk')
                or character in ('\ufe0f', '\ufe0e', '\u200d', '\u20e3')
                or character in '0123456789#*' and '\u20e3' in text[index + 1:index + 3]):
            continue
        if index:
            return text[:index].strip(), text[index:].strip()
        break
    return '', text


def format_name(name, *, category=False, edge='middle'):
    """Keep smallcaps and channel branches; use the owner's exact separators."""
    text = str(name).strip()
    if not text:
        return ''
    if category:
        if edge not in CATEGORY_EDGES:
            raise ValueError('La posición decorativa de la categoría no es válida.')
        for frame in ('━━', '──'):
            if text.startswith(frame) and text.endswith(frame):
                text = text[len(frame):-len(frame)].strip()
                break
        if text[:1] in CATEGORY_EDGES.values():
            text = text[1:].lstrip()
        icon, label = _split_icon_label(text)
        body = icon + ICON_SEPARATOR + stylize(label) if icon else stylize(label)
        return CATEGORY_EDGES[edge] + ' ' + body
    separator = _first_separator(text)
    if separator:
        prefix, label = text.split(separator, 1)
        return stylize(prefix) + ICON_SEPARATOR + stylize(label)
    branch = ''
    for candidate in ('╭・', '├・', '╰・', '┊・'):
        if text.startswith(candidate):
            branch, text = candidate, text[len(candidate):]
            break
    icon, label = _split_icon_label(text)
    return branch + (icon + ICON_SEPARATOR + stylize(label) if icon else stylize(label))



def type_number(channel):
    value = getattr(channel.type, 'value', channel.type)
    return int(value)


def channel_state(channel):
    return dict(id=str(channel.id), guild=str(channel.guild.id), name=channel.name,
        type=type_number(channel), parent=str(channel.category_id) if channel.category_id else None,
        position=channel.position, topic=getattr(channel, 'topic', None),
        overwrites=[dict(id=str(item.id), type=item.type, allow=str(item.allow), deny=str(item.deny))
                    for item in getattr(channel, '_overwrites', ())])


def restore_reference():
    """Keep the original 38 identities/types as the authorized rename scope."""
    value = json.loads(RESTORE_REFERENCE.read_text(encoding='utf-8'))
    if (value.get('version') != 'vice-channel-style-v2'
            or str(value.get('guild_id')) != str(GUILD_ID)
            or str(value.get('bot_id')) != str(BOT_ID)
            or str(value.get('owner_id')) != str(OWNER_ID)
            or str(value.get('team_category_id')) != str(TEAM_CATEGORY_ID)):
        raise ValueError('La referencia original no pertenece al distrito autorizado.')
    rows = {}
    for row in value.get('channels', ()):
        channel_id = str(row.get('id'))
        if (not channel_id.isdigit() or int(channel_id) <= 0 or channel_id in rows
                or row.get('type') not in SUPPORTED_TYPES
                or not isinstance(row.get('name'), str) or not 1 <= len(row['name']) <= 100):
            raise ValueError('La referencia de nombres originales necesita revisión.')
        rows[channel_id] = row
    if len(rows) != 38 or str(TEAM_CATEGORY_ID) not in rows or rows[str(TEAM_CATEGORY_ID)]['type'] != 4:
        raise ValueError('La referencia no contiene los 38 canales originales.')
    return rows


def load_manifest(path=MANIFEST):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if (value.get('version') != VERSION or str(value.get('guild_id')) != str(GUILD_ID)
            or str(value.get('bot_id')) != str(BOT_ID) or str(value.get('owner_id')) != str(OWNER_ID)):
        raise ValueError('La tipografía no pertenece al distrito autorizado.')
    reference = restore_reference()
    rows, seen = [], set()
    team_id = str(value.get('team_category_id'))
    if team_id != str(TEAM_CATEGORY_ID):
        raise ValueError('La categoría Staff no coincide con su identidad comprobada.')
    for raw in value.get('channels', ()):
        row = dict(raw)
        channel_id = str(row.get('id'))
        if (not channel_id.isdigit() or int(channel_id) <= 0 or channel_id in seen
                or row.get('type') not in SUPPORTED_TYPES or not isinstance(row.get('name'), str)
                or not row['name'] or not isinstance(row.get('target_name'), str)
                or not 1 <= len(row['target_name']) <= 100
                or type(row.get('position')) is not int or row['position'] < 0):
            raise ValueError('La lista congelada de nombres necesita revisión.')
        original = reference.get(channel_id)
        if original is None or original['type'] != row['type']:
            raise ValueError('El canal no pertenece a la restauración original autorizada.')
        if channel_id == team_id:
            if row['type'] != 4:
                raise ValueError('Staff ya no es una categoría.')
        row['id'] = channel_id
        seen.add(channel_id)
        rows.append(row)
    if seen != set(reference):
        raise ValueError('La lista no coincide con los 38 canales originales.')
    categories = sorted((row for row in rows if row['type'] == 4),
                        key=lambda row: (row['position'], int(row['id'])))
    for row in rows:
        edge = ('first' if row['id'] == categories[0]['id'] else
                'last' if row['id'] == categories[-1]['id'] else 'middle')
        expected = format_name(row['name'], category=row['type'] == 4, edge=edge)
        if row.get('edge', 'middle') != (edge if row['type'] == 4 else 'middle'):
            raise ValueError('La posición decorativa no coincide con el orden comprobado.')
        if row['target_name'] != expected:
            raise ValueError('El destino cambia más que los separadores autorizados.')
    fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return rows, fingerprint


class ChannelStyle:
    def __init__(self, system):
        self.system = system

    async def start(self):
        pass

    async def context(self):
        bot = self.system.bot
        guild = bot.get_guild(GUILD_ID)
        self.system.validate_guild(guild)
        if getattr(bot.user, 'id', None) != BOT_ID:
            raise ValueError('Se requiere el bot autorizado del distrito.')
        current = await bot.fetch_guild(GUILD_ID)
        self.system.validate_guild(current)
        if current.id != GUILD_ID or current.owner_id != OWNER_ID:
            raise ValueError('El distrito cambió de propietario.')
        return guild

    @staticmethod
    def key(channel_id):
        return VERSION + ':' + str(channel_id)

    async def rename(self, guild, row, fingerprint):
        key = self.key(row['id'])
        binding = dict(version=VERSION, guild=str(GUILD_ID), channel=row['id'],
                       type=row['type'], source_name=row['name'], target_name=row['target_name'],
                       manifest=fingerprint)
        receipt = await self.system.call('get', key) or {}
        if receipt and any(receipt.get(name) != value for name, value in binding.items()):
            raise ValueError('El recibo de tipografía no coincide con el canal autorizado.')
        if receipt.get('state') in ('completed', 'manual_change', 'absent', 'already_styled'):
            return receipt['state']
        if receipt.get('state') not in (None, 'pending'):
            raise ValueError('El estado del cambio de nombre necesita revisión.')
        try:
            channel = await guild.fetch_channel(int(row['id']))
        except discord.NotFound as error:
            if error.code != 10003:
                raise
            await self.system.call('put', key, dict(binding, state='absent'))
            return 'absent'
        self.system.validate_guild(channel.guild)
        if channel.id != int(row['id']) or type_number(channel) != row['type']:
            raise ValueError('El canal no coincide con su identidad congelada.')
        if channel.name == row['target_name']:
            state = 'completed' if receipt.get('state') == 'pending' else 'already_styled'
            await self.system.call('put', key, {**receipt, **binding,
                                               'state': state, 'after': channel_state(channel)})
            return state
        if channel.name != row['name']:
            await self.system.call('put', key, dict(binding, state='manual_change', observed_name=channel.name))
            return 'manual_change'
        before = deepcopy(channel_state(channel))

        async def snapshot():
            return dict(guild=GUILD_ID, channel=row['id'], before=before,
                        receipt=await self.system.call('get', key))

        async def apply():
            # Recheck identity and ownership at the name-only mutation boundary.
            current_guild = await self.context()
            fresh = await current_guild.fetch_channel(int(row['id']))
            self.system.validate_guild(fresh.guild)
            if fresh.id != int(row['id']) or type_number(fresh) != row['type']:
                raise ValueError('La identidad del canal cambió antes de renombrarlo.')
            if fresh.name != row['name']:
                await self.system.call('put', key, dict(binding, state='manual_change', observed_name=fresh.name))
                return 'manual_change'
            current_before = channel_state(fresh)
            await self.system.call('put', key, dict(binding, state='pending', before=current_before))
            await fresh.edit(name=row['target_name'], reason='Separadores solicitados por el propietario • ' + VERSION)
            verified = await current_guild.fetch_channel(int(row['id']))
            self.system.validate_guild(verified.guild)
            if (verified.id != int(row['id']) or type_number(verified) != row['type']
                    or verified.name != row['target_name']):
                raise ValueError('Discord no confirmó el nombre solicitado.')
            await self.system.call('put', key, dict(binding, state='completed', before=current_before,
                                                   after=channel_state(verified)))
            return 'changed'

        return await self.system.track('CHANNEL_STYLE', 'Actualizar letras del canal sin modificar su acceso',
                                       apply, key, snapshot=snapshot)

    async def ready(self):
        rows, fingerprint = load_manifest()
        guild = await self.context()
        team = int(self.system.store.get('category:team') or 0)
        if not team or team != TEAM_CATEGORY_ID:
            raise ValueError('La categoría del equipo no coincide con la lista autorizada.')
        counts = dict(changed=0, completed=0, manual_change=0, absent=0, already_styled=0, failed=0)
        for row in rows:
            try:
                counts[await self.rename(guild, row, fingerprint)] += 1
            except Exception as error:
                counts['failed'] += 1
                log.warning('VICE_CHANNEL_STYLE_PENDING channel=%s error=%s', row['id'], type(error).__name__)
        log.info('VICE_CHANNEL_STYLE_READY total=%s changed=%s completed=%s manual=%s absent=%s already=%s failed=%s',
                 len(rows), counts['changed'], counts['completed'], counts['manual_change'],
                 counts['absent'], counts['already_styled'], counts['failed'])
        if counts['failed']:
            raise ValueError('Algunos nombres quedan pendientes de verificar.')
        return counts
