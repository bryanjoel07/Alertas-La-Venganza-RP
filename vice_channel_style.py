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
VERSION = 'vice-channel-style-v2'
MANIFEST = Path(__file__).parent / 'assets' / 'vice-district' / 'channel-style-v2.json'
TEAM_CATEGORY_ID = 1572467006999896074
CATEGORY_SEPARATOR = '၊၊||၊'
ALIGN_BLANK = '\u2800'
ALIGN_TARGET_PX = 190
ALIGN_MAX_CHANNEL = 8
ALIGN_MAX_CATEGORY = 12
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


def _icon_only(text):
    """Recognize existing icon clusters without guessing from channel names."""
    text = text.strip(' \t\r\n' + ALIGN_BLANK)
    if not text:
        return False
    for index, character in enumerate(text):
        if character == ALIGN_BLANK:
            return False
        if character.isspace() or character in ('\ufe0f', '\ufe0e', '\u200d', '\u20e3'):
            continue
        if character in '0123456789#*' and (text[index + 1:index + 3] == '\ufe0f\u20e3'
                                            or text[index + 1:index + 2] == '\u20e3'):
            continue
        if unicodedata.category(character) not in ('So', 'Sk'):
            return False
    return True


def _leading_icon(text):
    # Prefixes use symbols, flag pairs, variation selectors and ZWJ clusters.
    # Try boundaries from longest to shortest so a full emoji is never split.
    for index in range(len(text), 0, -1):
        prefix = text[:index].strip(' \t\r\n' + ALIGN_BLANK)
        tail = text[index:].strip(' \t\r\n' + ALIGN_BLANK)
        if tail and _icon_only(prefix):
            return prefix, tail
    return '', text


def _text_width(text):
    """Conservative fixed 16 px font estimate, never a device-width promise."""
    total = 0.0
    narrow = {'i': 3.5, 'l': 4.5, 'j': 4.5, 'f': 6, 'r': 6, 't': 6,
              'm': 10, 'w': 11, ' ': 4, '-': 5, '|': 4, '│': 4}
    for character in text:
        if unicodedata.combining(character) or character in ('\ufe0f', '\ufe0e', '\u200d'):
            continue
        base = FROM_SMALL_CAPS.get(character, character).lower()
        total += narrow.get(base, 16 if unicodedata.category(character) in ('So', 'Sk') else 8)
    return total


def _rightward(icon, words, *, category):
    words = stylize(words)
    # Icons stay on the left. A short cap limits blank space on narrower mobile
    # sidebars; long labels remain whole and receive no extra blank padding.
    if category:
        prefix = CATEGORY_SEPARATOR + ' ' + icon
        available = ALIGN_TARGET_PX - 26 - (12 if icon else 0) - _text_width(words) * .75
        count = min(ALIGN_MAX_CATEGORY, max(0, int(available / 8)))
    else:
        prefix = icon + '│' if icon else ''
        available = ALIGN_TARGET_PX - (20 if icon else 0) - _text_width(words)
        count = min(ALIGN_MAX_CHANNEL, max(0, int(available / 10)))
    # Discord names have a 100-character limit. Never truncate an actual name.
    count = min(count, max(0, 100 - len(prefix) - len(words)))
    return prefix + ALIGN_BLANK * count + words


def format_name(name, *, category=False):
    """Place icons left and smallcap words right with bounded blank spacing.

    U+2800 is visible-width whitespace, not a bidi control. Width is an
    approximation; native Discord sidebars cannot enforce flush-right text.
    Generated padding is stripped before parsing, so repeated calls are stable.
    """
    trim = ' \t\r\n' + ALIGN_BLANK
    text = str(name).strip(trim)
    if not text:
        return ''
    if category:
        if text.startswith(CATEGORY_SEPARATOR):
            text = text[len(CATEGORY_SEPARATOR):].strip(trim)
        # The previous layout framed categories with heavy horizontal bars.
        text = text.strip('━─').strip(trim)
        icon, words = _leading_icon(text)
        return _rightward(icon, words, category=True)
    for branch in ('╭・', '├・', '╰・', '┊・'):
        if text.startswith(branch):
            text = text[len(branch):].strip(trim)
            break
    if '│' in text:
        head, tail = text.rsplit('│', 1)
        if head.strip(trim) and _icon_only(tail):
            return _rightward(tail.strip(trim), head.strip(trim), category=False)
        head, tail = text.split('│', 1)
        if tail.strip(trim) and _icon_only(head):
            return _rightward(head.strip(trim), tail.strip(trim), category=False)
    icon, words = _leading_icon(text)
    return _rightward(icon, words, category=False)


def type_number(channel):
    value = getattr(channel.type, 'value', channel.type)
    return int(value)


def channel_state(channel):
    return dict(id=str(channel.id), guild=str(channel.guild.id), name=channel.name,
        type=type_number(channel), parent=str(channel.category_id) if channel.category_id else None,
        position=channel.position, topic=getattr(channel, 'topic', None),
        overwrites=[dict(id=str(item.id), type=item.type, allow=str(item.allow), deny=str(item.deny))
                    for item in getattr(channel, '_overwrites', ())])


def load_manifest(path=MANIFEST):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if (value.get('version') != VERSION or str(value.get('guild_id')) != str(GUILD_ID)
            or str(value.get('bot_id')) != str(BOT_ID) or str(value.get('owner_id')) != str(OWNER_ID)):
        raise ValueError('La tipografía no pertenece al distrito autorizado.')
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
                or not 1 <= len(row['target_name']) <= 100):
            raise ValueError('La lista congelada de nombres necesita revisión.')
        expected = format_name(row['name'], category=row['type'] == 4)
        if channel_id == team_id:
            if row['type'] != 4:
                raise ValueError('Staff ya no es una categoría.')
        if row['target_name'] != expected:
            raise ValueError('El cambio excede la tipografía y la categoría Staff autorizadas.')
        row['id'] = channel_id
        seen.add(channel_id)
        rows.append(row)
    if not rows or team_id not in seen:
        raise ValueError('Falta la categoría del equipo en la lista comprobada.')
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
            await fresh.edit(name=row['target_name'], reason='Tipografía y Staff solicitados por el propietario • ' + VERSION)
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
