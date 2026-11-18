"""Conservative, guild-isolated spam protection; never stores message contents."""
import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
import time

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID


log = logging.getLogger(__name__)
PR_TIME = timezone(timedelta(hours=-4), 'AST')
FLOOD_COUNT, FLOOD_SECONDS = 6, 8
DUPLICATE_COUNT, DUPLICATE_SECONDS = 3, 15
MENTION_COUNT = 6
REPEAT_SECONDS, ALERT_SECONDS = 300, 30
INCIDENT_SECONDS = 10
JOIN_COUNT, JOIN_SECONDS = 5, 10
MAX_MEMBERS, MAX_CHANNELS = 2048, 8
LABELS = {'flood': 'mensajes demasiado seguidos', 'duplicates': 'mensajes repetidos',
          'mentions': 'menciones masivas', 'everyone': 'mención global no autorizada'}
GLOBAL_MENTION = re.compile(r'(?<![\w@\\])@(everyone|here)\b')


@dataclass
class _MemberState:
    # Timestamps, IDs and one-way digests are ephemeral, bounded and never journaled.
    messages: deque = field(default_factory=lambda: deque(maxlen=32))
    seen: deque = field(default_factory=lambda: deque(maxlen=32))
    violations: int = 0
    last_violation: float = float('-inf')
    last_alert: float = float('-inf')
    warnings: OrderedDict = field(default_factory=OrderedDict)


class AntiSpam:
    def __init__(self, system):
        self.system = system
        self.bot = system.bot
        self.configured = False
        self._states = OrderedDict()
        # Fixed stripes serialize the same member without retaining unbounded locks.
        self._locks = tuple(asyncio.Lock() for _ in range(64))
        self._joins = deque(maxlen=64)
        self._join_seen = OrderedDict()
        self._last_burst_alert = float('-inf')
        self._clock = time.monotonic
        self._now = lambda: datetime.now(timezone.utc)

    async def start(self):
        # No scheduler, client, durable content cache or background deletion task.
        self.configured = False

    def _scope(self, guild):
        if (getattr(guild, 'id', None) != GUILD_ID
                or getattr(guild, 'owner_id', None) != OWNER_ID
                or getattr(getattr(self.bot, 'user', None), 'id', None) != BOT_ID):
            return False
        self.system.validate_guild(guild)
        return True

    async def ready(self):
        self.configured = False
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not self._scope(guild) or not self.system.configured:
                return
            me = guild.me
            if me is None or me.id != BOT_ID:
                return
            permissions = me.guild_permissions
            if not permissions.manage_messages or not permissions.moderate_members:
                log.warning('VIce anti-spam: protección limitada por permisos de moderación.')
            if not self.bot.intents.message_content:
                log.warning('VIce anti-spam: repetición de contenido desactivada; intent no disponible.')
            self.configured = True
            log.info('VICE_ANTISPAM_READY content=%s manage_messages=%s moderate_members=%s',
                     self.bot.intents.message_content, permissions.manage_messages,
                     permissions.moderate_members)
        except Exception as error:
            log.warning('VIce anti-spam ready: %s', type(error).__name__)

    def _state(self, member_id):
        state = self._states.get(member_id)
        if state is None:
            state = self._states[member_id] = _MemberState()
            if len(self._states) > MAX_MEMBERS:
                self._states.popitem(last=False)
        self._states.move_to_end(member_id)
        return state

    def _message_scope(self, message):
        guild, author = getattr(message, 'guild', None), getattr(message, 'author', None)
        return (self.configured and self.system.configured and self._scope(guild)
                and getattr(getattr(message.channel, 'guild', None), 'id', None) == GUILD_ID
                and getattr(getattr(author, 'guild', None), 'id', None) == GUILD_ID
                and not getattr(author, 'bot', True) and not getattr(message, 'webhook_id', None))

    def _observe(self, message, state, tick):
        if message.id in state.seen:
            return []
        state.seen.append(message.id)
        digest = None
        global_attempt = False
        if self.bot.intents.message_content:
            original = getattr(message, 'content', '') or ''
            global_attempt = bool(GLOBAL_MENTION.search(original))
            content = ' '.join(original.split()).casefold()
            if content:
                digest = hashlib.sha256(content.encode('utf-8')).digest()
        state.messages.append((tick, digest))
        while state.messages and tick - state.messages[0][0] > DUPLICATE_SECONDS:
            state.messages.popleft()
        reasons = []
        if sum(tick - stamp <= FLOOD_SECONDS for stamp, _ in state.messages) >= FLOOD_COUNT:
            reasons.append('flood')
        if digest and sum(value == digest for _, value in state.messages) >= DUPLICATE_COUNT:
            reasons.append('duplicates')
        mentioned = {item.id for item in (*message.mentions, *message.role_mentions)}
        if len(mentioned) >= MENTION_COUNT:
            reasons.append('mentions')
        if message.mention_everyone or global_attempt:
            reasons.append('everyone')  # Fresh permissions decide whether this is unauthorized.
        return reasons

    async def message(self, message):
        """Return whether the current message was removed; isolate all handler failures."""
        try:
            if not self._message_scope(message):
                return False
            received = self._clock()
            async with self._locks[message.author.id % len(self._locks)]:
                if not self._message_scope(message) or self._clock() - received > 30:
                    return False
                state = self._state(message.author.id)
                reasons = self._observe(message, state, received)
                if not reasons:
                    return False
                member = await message.guild.fetch_member(message.author.id)
                if (not self._scope(member.guild) or member.id != message.author.id
                        or member.bot or member.id == OWNER_ID
                        or self.system.is_staff(member)):
                    state.messages.clear()
                    return False
                if message.channel.permissions_for(member).mention_everyone and 'everyone' in reasons:
                    reasons.remove('everyone')
                if not reasons:
                    return False
                me = message.guild.me
                if me is None or me.id != BOT_ID or member.top_role >= me.top_role:
                    return False
                if not self._message_scope(message):
                    return False
                tick, now = self._clock(), self._now()
                # A single burst can remove multiple current messages but earns one strike.
                new_incident = tick - state.last_violation >= INCIDENT_SECONDS
                if new_incident:
                    if tick - state.last_violation > REPEAT_SECONDS:
                        state.violations = 0
                    state.violations = min(3, state.violations + 1)
                    state.last_violation = tick
                actions = []
                removed = await self._remove(message, member, reasons, actions)
                if new_incident and state.violations > 1:
                    await self._timeout(message, member, reasons,
                                        60 if state.violations == 2 else 300, now, actions)
                if removed:
                    await self._warn(message, state, tick, reasons)
                if tick - state.last_alert >= ALERT_SECONDS:
                    state.last_alert = tick
                    await self._alert(message, member, reasons, actions, now)
                return removed
        except Exception as error:
            log.warning('VIce anti-spam message: %s', type(error).__name__)
            return False

    async def _remove(self, message, member, reasons, actions):
        if not message.channel.permissions_for(message.guild.me).manage_messages:
            actions.append('Eliminación pendiente: faltan permisos.')
            return False
        metadata = {'guild_id': GUILD_ID, 'channel_id': message.channel.id,
                    'message_id': message.id, 'member_id': member.id,
                    'detectors': list(reasons), 'message_removed': False}
        async def snapshot():
            return dict(metadata)
        async def apply():
            # Scope and privilege are checked again at the mutation boundary.
            if not self._message_scope(message) or self.system.is_staff(member):
                raise ValueError('Moderación fuera de alcance')
            await message.delete()
            metadata['message_removed'] = True
        try:
            await self.system.track('ANTISPAM_DELETE', 'Retirar el mensaje que activó anti-spam',
                                    apply, f'antispam:delete:{message.id}', snapshot=snapshot)
            actions.append('Mensaje retirado.')
            return True
        except discord.NotFound:
            actions.append('Mensaje ya ausente.')
        except Exception as error:
            actions.append('No se pudo retirar el mensaje.')
            log.warning('VIce anti-spam delete: %s', type(error).__name__)
        return False

    async def _timeout(self, message, member, reasons, seconds, now, actions):
        me = message.guild.me
        if not me.guild_permissions.moderate_members:
            actions.append('Timeout pendiente: faltan permisos.')
            return
        until = now + timedelta(seconds=seconds)
        before = getattr(member, 'timed_out_until', None)
        if before and before >= until:
            actions.append('Se conserva el timeout existente.')
            return
        metadata = {'guild_id': GUILD_ID, 'member_id': member.id,
                    'message_id': message.id, 'detectors': list(reasons),
                    'timeout_until': before.isoformat() if before else None,
                    'requested_until': until.isoformat()}
        async def snapshot():
            return dict(metadata)
        async def apply():
            if (not self._message_scope(message) or self.system.is_staff(member)
                    or member.top_role >= message.guild.me.top_role):
                raise ValueError('Moderación fuera de alcance')
            await member.timeout(until, reason='VIce anti-spam: reincidencia ('
                                 + ', '.join(LABELS[item] for item in reasons) + ').')
            metadata['timeout_until'] = until.isoformat()
        try:
            await self.system.track('ANTISPAM_TIMEOUT', f'Aplicar timeout anti-spam de {seconds} s',
                                    apply, f'antispam:timeout:{message.id}', snapshot=snapshot)
            actions.append(f'Timeout: {seconds} s.')
        except Exception as error:
            actions.append('No se pudo aplicar el timeout.')
            log.warning('VIce anti-spam timeout: %s', type(error).__name__)

    async def _warn(self, message, state, tick, reasons):
        channel_id = message.channel.id
        if tick - state.warnings.get(channel_id, float('-inf')) < ALERT_SECONDS:
            return
        if not message.channel.permissions_for(message.guild.me).send_messages:
            return
        state.warnings[channel_id] = tick
        state.warnings.move_to_end(channel_id)
        if len(state.warnings) > MAX_CHANNELS:
            state.warnings.popitem(last=False)
        metadata = {'guild_id': GUILD_ID, 'channel_id': channel_id,
                    'member_id': message.author.id, 'trigger_message_id': message.id,
                    'warning_message_id': None}
        async def snapshot():
            return dict(metadata)
        async def apply():
            if not self._message_scope(message):
                raise ValueError('Aviso fuera de alcance')
            result = await message.channel.send(
                '⚠️ Se retiró un mensaje por ' + LABELS[reasons[0]]
                + '. Evita repetirlo; la reincidencia activa una pausa temporal.',
                allowed_mentions=discord.AllowedMentions.none(), silent=True)
            metadata['warning_message_id'] = result.id
            return result
        try:
            await self.system.track('ANTISPAM_WARNING', 'Aviso anti-spam sin menciones',
                                    apply, f'antispam:warning:{message.id}', snapshot=snapshot)
        except Exception as error:
            log.warning('VIce anti-spam warning: %s', type(error).__name__)

    @staticmethod
    def _embed(member, description, occurred):
        embed = discord.Embed(description=description, color=0xFFA844, timestamp=occurred)
        name = ' '.join(str(getattr(member, 'display_name', None) or member.id).split())[:80]
        name = discord.utils.escape_mentions(discord.utils.escape_markdown(name))
        avatar = str(getattr(getattr(member, 'display_avatar', None), 'url', ''))
        if not avatar.startswith(('https://cdn.discordapp.com/', 'https://media.discordapp.net/')):
            avatar = None
        embed.set_author(name=name, icon_url=avatar)
        embed.set_footer(text='VIce District • ' + occurred.astimezone(PR_TIME).strftime('%d/%m %H:%M AST'))
        return embed

    async def _alert(self, message, member, reasons, actions, now):
        embed = self._embed(member, '🛡️ Anti-spam: ' + ', '.join(LABELS[item] for item in reasons)
                            + '.\n' + ' '.join(actions), now)
        embed.add_field(name='IDs', value=f'Usuario: `{member.id}` · Canal: `{message.channel.id}`\n'
                        f'Mensaje: `{message.id}`', inline=False)
        await self.system.audit.publish(f'antispam:message:{message.id}', embed,
                                        event_type='antispam', event_time=now, source_id=str(message.id))

    async def member_join(self, member):
        """Age and arrival bursts only produce private observations, never sanctions."""
        try:
            if (not self.configured or not self.system.configured or not self._scope(member.guild)
                    or member.bot):
                return
            tick, now = self._clock(), self._now()
            # Gateway duplicates cannot inflate the burst counter.
            joined = getattr(member, 'joined_at', None)
            key = (member.id, joined.isoformat() if joined else None)
            if key in self._join_seen:
                return
            self._join_seen[key] = tick
            if len(self._join_seen) > MAX_MEMBERS:
                self._join_seen.popitem(last=False)
            self._joins.append(tick)
            while self._joins and tick - self._joins[0] > JOIN_SECONDS:
                self._joins.popleft()
            notices = []
            age = now - member.created_at
            if timedelta(0) <= age < timedelta(hours=24):
                notices.append('Cuenta creada hace menos de 24 h.')
            burst = len(self._joins) >= JOIN_COUNT and tick - self._last_burst_alert >= ALERT_SECONDS
            if burst:
                notices.append(f'Entradas recientes: {len(self._joins)} en {JOIN_SECONDS} s.')
            state = self._state(member.id)
            if not notices or tick - state.last_alert < ALERT_SECONDS:
                return
            state.last_alert = tick
            if burst:
                self._last_burst_alert = tick
            embed = self._embed(member, '🛡️ Revisión de entrada: ' + ' '.join(notices)
                                + '\nAviso preventivo; no se aplicó ninguna sanción.', now)
            embed.add_field(name='IDs', value=f'Usuario: `{member.id}`', inline=False)
            occurrence = joined or now
            await self.system.audit.publish(f'antispam:join:{member.id}:{occurrence.isoformat()}', embed,
                                            event_type='antispam', event_time=now,
                                            source_id=str(member.id))
        except Exception as error:
            log.warning('VIce anti-spam join: %s', type(error).__name__)
