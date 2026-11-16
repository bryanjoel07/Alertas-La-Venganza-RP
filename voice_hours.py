"""Owner-requested opening hours for one voice channel, in Puerto Rico."""
import asyncio
from datetime import datetime, time, timedelta, timezone
import json
import logging
import os
import time as clock
from uuid import uuid4
from zoneinfo import ZoneInfo

import discord

from sqlite_runtime import transaction
from tickets_store import PROTECTED

GUILD_ID = 1244988345327550565
BOT_ID = 1567658433497399408
CHANNEL_ID = 1513652447371853937
CITIZENS_ID = 1245009164070158409
PR = ZoneInfo('America/Puerto_Rico')
OPEN = time(6, 30)
CLOSE = time(18, 30)
FIELDS = ('view_channel', 'connect')
log = logging.getLogger('LaVenganzaRP.voice_hours')


def closed_at(now):
    if now.tzinfo is None:
        raise ValueError('El horario requiere una fecha con zona horaria.')
    local = now.astimezone(PR).time()
    return local < OPEN or local >= CLOSE


def next_change(now):
    local = now.astimezone(PR)
    if local.time() < OPEN:
        return datetime.combine(local.date(), OPEN, PR)
    if local.time() < CLOSE:
        return datetime.combine(local.date(), CLOSE, PR)
    return datetime.combine(local.date() + timedelta(days=1), OPEN, PR)


def flags(overwrite):
    return {key: getattr(overwrite, key) for key in FIELDS}


def access_audit(channel):
    """Read effective access and exceptions without editing other roles."""
    guild = channel.guild
    citizens = guild.get_role(CITIZENS_ID)
    others, members = [], []
    for target, overwrite in channel.overwrites.items():
        if target.id in {GUILD_ID, CITIZENS_ID} or not any(getattr(overwrite, field) is True for field in FIELDS):
            continue
        if kind(target) == 'role':
            others.append(dict(id=target.id, name=getattr(target, 'name', str(target.id)), **flags(overwrite)))
        else:
            members.append(target.id)
    return dict(everyone=flags(channel.permissions_for(guild.default_role)),
        citizens=flags(channel.permissions_for(citizens)) if citizens else None,
        other_roles=others, member_grants=members,
        administrator_roles=[r.id for r in guild.roles if r.permissions.administrator])


def kind(target):
    return 'role' if isinstance(target, discord.Role) or getattr(target, 'type', None) is discord.Role else 'member'


class VoiceHoursStore:
    def __init__(self, path):
        self.path = path

    def initialize(self):
        with transaction(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS lv_voice_hours_targets(
                channel INTEGER NOT NULL, target INTEGER NOT NULL, kind TEXT NOT NULL,
                base INTEGER NOT NULL, before_json TEXT NOT NULL, last_json TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(channel,target,kind))''')

    def rows(self, active=True):
        with transaction(self.path, readonly=True) as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM lv_voice_hours_targets WHERE channel=?' + (' AND active=1' if active else ''), (CHANNEL_ID,))]

    def plan(self, target, target_kind, base, before, after):
        with transaction(self.path) as db:
            db.execute('''INSERT INTO lv_voice_hours_targets VALUES (?,?,?,?,?,?,1)
                ON CONFLICT(channel,target,kind) DO UPDATE SET
                before_json=CASE WHEN active=0 THEN excluded.before_json ELSE before_json END,
                last_json=excluded.last_json, active=1''',
                (CHANNEL_ID, target, target_kind, int(base), json.dumps(before), json.dumps(after)))

    def restored(self, target, target_kind):
        with transaction(self.path) as db:
            db.execute('UPDATE lv_voice_hours_targets SET active=0 WHERE channel=? AND target=? AND kind=?',
                (CHANNEL_ID, target, target_kind))


class VoiceHours:
    def __init__(self, bot, path):
        self.bot = bot
        self.store = VoiceHoursStore(path)
        self.lock = asyncio.Lock()
        self.task = None
        self.mode = None
        self.checked = 0
        self.last_occupants = None

    def now(self):
        return datetime.now(timezone.utc)

    def enabled(self):
        return os.getenv('VOICE_QUIET_HOURS_ENABLED', '1').strip().lower() not in {'0', 'false', 'off'}

    async def start(self):
        if self.task is not None and not self.task.done():
            return
        await asyncio.to_thread(self.store.initialize)
        self.task = asyncio.create_task(self.loop(), name='voice-channel-hours')

    def invalidate(self):
        self.checked = 0
        self.mode = None

    async def channel(self):
        channel = await self.bot.fetch_channel(CHANNEL_ID)
        if not isinstance(channel, discord.VoiceChannel) or channel.guild.id != GUILD_ID or channel.id != CHANNEL_ID:
            raise ValueError('El horario solo está autorizado para el canal de voz indicado de La Venganza RP.')
        if self.bot.user.id != BOT_ID:
            raise ValueError('El horario pertenece al bot original de La Venganza RP.')
        return channel

    async def snapshot(self):
        channel = await self.channel()
        return dict(channel=channel.id, name=channel.name, category=channel.category_id,
            overwrites=[dict(target=t.id, kind=kind(t), allow=o.pair()[0].value, deny=o.pair()[1].value)
                for t, o in channel.overwrites.items()],
            occupants=self.occupants(channel.guild), records=await asyncio.to_thread(self.store.rows))

    def occupants(self, guild):
        return sorted(uid for uid, state in guild._voice_states.items()
            if state.channel and state.channel.id == CHANNEL_ID)

    def protected(self, target):
        if target.id == BOT_ID or (kind(target) == 'role' and target.id in PROTECTED):
            return True
        permissions = getattr(target, 'permissions', None) if kind(target) == 'role' else getattr(target, 'guild_permissions', None)
        return bool(permissions and permissions.administrator)

    async def target(self, channel, record):
        if record['kind'] == 'role':
            return channel.guild.get_role(record['target'])
        return channel.guild.get_member(record['target']) or discord.Object(id=record['target'], type=discord.Member)

    async def write(self, channel, target, overwrite, reason):
        if channel.id != CHANNEL_ID or channel.guild.id != GUILD_ID:
            raise ValueError('No se pueden cambiar permisos fuera del canal autorizado.')
        # Discord may return an uncached member overwrite as a typed Object.
        # set_permissions rejects that type, although the REST endpoint uses its ID.
        if isinstance(target, discord.Object) and target.type is discord.Member:
            http = channel._state.http
            if overwrite is None:
                await http.delete_channel_permissions(CHANNEL_ID, target.id, reason=reason)
            else:
                allow, deny = overwrite.pair()
                await http.edit_channel_permissions(CHANNEL_ID, target.id, str(allow.value), str(deny.value), 1, reason=reason)
        else:
            await channel.set_permissions(target, overwrite=overwrite, reason=reason)

    async def restore(self, channel, include_base=False):
        for record in await asyncio.to_thread(self.store.rows):
            if record['base'] and not include_base:
                continue
            target = await self.target(channel, record)
            if target is None:
                await asyncio.to_thread(self.store.restored, record['target'], record['kind'])
                continue
            if self.protected(target):
                log.warning('VOICE_HOURS restore_skipped protected_target=%s', target.id)
                continue
            current = channel.overwrites_for(target)
            before, last = json.loads(record['before_json']), json.loads(record['last_json'])
            changed = False
            for field in FIELDS:
                if getattr(current, field) == last[field]:
                    changed |= getattr(current, field) != before[field]
                    setattr(current, field, before[field])
            if changed:
                expected = flags(current)
                await self.write(channel, target, None if current.is_empty() and not before['present'] else current,
                    'Restaurar acceso del canal tras el horario privado solicitado')
                channel = await self.channel()
                if flags(channel.overwrites_for(target)) != expected:
                    raise ValueError('Discord no confirmó la restauración del acceso anterior.')
                log.info('VOICE_HOURS target_restored channel=%s target=%s kind=%s fields=%s',
                    CHANNEL_ID, target.id, record['kind'], expected)
            await asyncio.to_thread(self.store.restored, record['target'], record['kind'])
        return channel

    async def permissions(self, mode):
        channel = await self.channel()
        if not channel.permissions_for(channel.guild.me).manage_roles:
            raise ValueError('El bot necesita Gestionar permisos en este canal.')
        roles = [channel.guild.default_role, channel.guild.get_role(CITIZENS_ID)]
        if mode != 'disabled' and roles[1] is None:
            raise ValueError('No encuentro el rol Ciudadanos; no se cambian otros roles.')
        protected_before = {t.id: o.pair() for t, o in channel.overwrites.items()
            if kind(t) == 'role' and t.id in PROTECTED}
        plans = []
        if mode != 'disabled':
            for role in roles:
                plans.append((role, True, dict.fromkeys(FIELDS, role.id == CITIZENS_ID and mode == 'open')))
        records = await asyncio.to_thread(self.store.rows)
        # Restore earlier temporary grants once, even at night. New schedules
        # only manage the two role overwrites explicitly named by the owner.
        needs_restore = any(mode == 'disabled' or not r['base'] for r in records)
        writes = [(t, base, wanted) for t, base, wanted in plans if flags(channel.overwrites_for(t)) != wanted]
        if not writes and not needs_restore:
            return channel

        async def operation():
            current = await self.channel()
            for target, base, wanted in writes:
                # Never apply last night's decision after the opening boundary.
                live_mode = 'disabled' if not self.enabled() else 'closed' if closed_at(self.now()) else 'open'
                if live_mode != mode:
                    raise ValueError('Cambió el horario durante la actualización; se volverá a comprobar.')
                overwrite = current.overwrites_for(target)
                before = dict(flags(overwrite), present=target in current.overwrites)
                await asyncio.to_thread(self.store.plan, target.id, kind(target), base, before, wanted)
                for field, value in wanted.items():
                    setattr(overwrite, field, value)
                await self.write(current, target, overwrite,
                    'Horario de voz solicitado: abierto 06:30–18:30, Puerto Rico')
                current = await self.channel()
                if flags(current.overwrites_for(target)) != wanted:
                    raise ValueError('Discord no confirmó los permisos del canal de voz.')
            if needs_restore:
                current = await self.restore(current, include_base=mode == 'disabled')
            protected_after = {t.id: o.pair() for t, o in current.overwrites.items()
                if kind(t) == 'role' and t.id in PROTECTED}
            if protected_after != protected_before:
                raise ValueError('Cambió un acceso protegido durante la actualización; se detiene el horario.')
            return current

        return await self.bot.changes.tracked('VOICE_QUIET_HOURS', 'Aplicar horario del canal de voz', operation,
            request_id=f'{CHANNEL_ID}:{mode}:{uuid4().hex}', snapshot=self.snapshot)

    async def disconnect(self, member):
        if not self.enabled() or not closed_at(self.now()):
            return
        if member.guild.id != GUILD_ID or not member.voice or not member.voice.channel or member.voice.channel.id != CHANNEL_ID:
            return

        async def snapshot():
            voice = member.voice
            return dict(member=member.id, channel=voice.channel.id if voice and voice.channel else None,
                reason='Horario privado del canal', local_time=self.now().astimezone(PR).isoformat())

        async def operation():
            if self.enabled() and closed_at(self.now()) and member.voice and member.voice.channel and member.voice.channel.id == CHANNEL_ID:
                await member.move_to(None, reason='Canal cerrado de 18:30 a 06:30, hora de Puerto Rico')
                return True
            return False

        moved = await self.bot.changes.tracked('VOICE_QUIET_HOURS', 'Desconectar del canal de voz fuera de horario', operation,
            request_id=f'{CHANNEL_ID}:disconnect:{member.id}:{uuid4().hex}', snapshot=snapshot)
        if moved:
            log.info('VOICE_HOURS disconnect_requested channel=%s member=%s', CHANNEL_ID, member.id)

    async def voice_update(self, member, before, after):
        if (self.bot.user.id != BOT_ID or member.guild.id != GUILD_ID or not after.channel
                or after.channel.id != CHANNEL_ID or not self.enabled() or not closed_at(self.now())):
            return
        async with self.lock:
            await self.disconnect(member)

    async def reconcile(self):
        if self.bot.user.id != BOT_ID:
            return
        async with self.lock:
            mode = 'disabled' if not self.enabled() else 'closed' if closed_at(self.now()) else 'open'
            channel = self.bot.get_channel(CHANNEL_ID)
            if self.mode != mode or clock.monotonic() - self.checked >= 300 or channel is None:
                try:
                    channel = await self.permissions(mode)
                    self.checked = clock.monotonic()
                except Exception:
                    log.exception('VOICE_HOURS permissions_pending channel=%s mode=%s', CHANNEL_ID, mode)
                    channel = self.bot.get_channel(CHANNEL_ID)
                    if channel is None:
                        raise
                else:
                    self.mode = mode
                    log.info('VOICE_HOURS permissions_verified channel=%s name=%s mode=%s timezone=America/Puerto_Rico open=06:30 close=18:30 everyone=%s citizens=%s managed_targets=%s scope=everyone,citizens everyone_always_blocked=True protected_roles_unchanged=True',
                        CHANNEL_ID, channel.name, mode, flags(channel.overwrites_for(channel.guild.default_role)),
                        flags(channel.overwrites_for(channel.guild.get_role(CITIZENS_ID))) if channel.guild.get_role(CITIZENS_ID) else None,
                        len(await asyncio.to_thread(self.store.rows)))
                    log.info('VOICE_HOURS effective_access channel=%s audit=%s', CHANNEL_ID,
                        json.dumps(access_audit(channel), ensure_ascii=False))
            if channel.guild.id != GUILD_ID or not isinstance(channel, discord.VoiceChannel):
                raise ValueError('El horario solo corresponde al canal autorizado.')
            if mode == 'closed':
                for uid in self.occupants(channel.guild):
                    if not self.enabled() or not closed_at(self.now()):
                        break
                    try:
                        member = channel.guild.get_member(uid) or await channel.guild.fetch_member(uid)
                        await self.disconnect(member)
                    except discord.NotFound:
                        continue
                    except Exception:
                        log.exception('VOICE_HOURS disconnect_pending channel=%s member=%s', CHANNEL_ID, uid)
                remaining = self.occupants(channel.guild)
                if remaining != self.last_occupants:
                    log.info('VOICE_HOURS occupants_checked channel=%s mode=closed remaining=%s', CHANNEL_ID, remaining)
                    self.last_occupants = remaining
            else:
                self.last_occupants = None

    async def loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            if self.bot.is_ready():
                try:
                    await self.reconcile()
                except Exception:
                    log.exception('VOICE_HOURS pending_retry channel=%s', CHANNEL_ID)
            delay = min(15, max(0.2, (next_change(self.now()) - self.now().astimezone(PR)).total_seconds()))
            await asyncio.sleep(delay)
