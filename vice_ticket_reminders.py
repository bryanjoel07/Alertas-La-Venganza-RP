"""Private, durable reminders for tickets waiting for a human staff response."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import uuid

import discord

from vice_design import BOT_ID, CYAN, GUILD_ID


log = logging.getLogger('ViceDistrict.ticket_reminders')
VERSION = 'vice-ticket-reminders-v1'
INITIAL_DELAY = timedelta(hours=2)
FOLLOWUP_DELAY = timedelta(hours=24)
REPEAT_DELAY = timedelta(hours=24)
POLL_SECONDS = 60
HISTORY_LIMIT = 1000
TICK_LIMIT = 20
TITLE = '⏰ Ticket pendiente de respuesta'
FOOTER = 'VIce District • Seguimiento de tickets'


def utcnow():
    return datetime.now(timezone.utc)


def state_key(channel_id):
    return 'ticket_reminder:state:' + str(channel_id)


def receipt_key(nonce):
    return 'ticket_reminder:receipt:' + str(nonce)


def as_time(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('El seguimiento necesita una fecha válida.')
    return value.astimezone(timezone.utc)


class TicketReminders:
    def __init__(self, system):
        self.system = system
        self.task = None
        self.cursor = 0

    async def start(self):
        # StudioStore is already initialized by ViceDistrict.start().
        pass

    def enabled(self):
        event = getattr(self.system, 'ready_event', None)
        return (bool(self.system.configured) and isinstance(event, asyncio.Event)
                and event.is_set())

    def guild(self):
        return self.system.tickets.guild()

    async def message(self, message):
        # Polling, rather than gateway ordering, is authoritative. Never copy a
        # message's text, attachments or embeds into reminder storage.
        if (getattr(getattr(message, 'guild', None), 'id', None) != GUILD_ID
                or getattr(getattr(message, 'author', None), 'bot', False)
                or getattr(message, 'webhook_id', None) is not None):
            return False
        return True

    async def load(self, row):
        value = await self.system.call('get', state_key(row['channel']))
        binding = dict(guild=GUILD_ID, channel=str(row['channel']), owner=str(row['owner']),
                       created=int(row['created']), version=VERSION)
        if value:
            if any(value.get(key) != item for key, item in binding.items()):
                raise ValueError('El seguimiento no pertenece al ticket registrado.')
            return dict(value)
        opened = datetime.fromtimestamp(int(row['created']), timezone.utc)
        return dict(binding, cursor=0, ever_replied=False, awaiting_since=opened.isoformat(),
                    episode='open:' + str(row['created']), owner_message=None,
                    last_sent=None, pending=None)

    async def save(self, state):
        await self.system.call('put', state_key(state['channel']), state)

    def scope(self, channel, row):
        self.system.tickets.notice_scope(channel, row)
        if channel.id != int(row['channel']):
            raise ValueError('El canal del seguimiento cambió.')
        permissions = channel.permissions_for(channel.guild.me)
        if not all(getattr(permissions, name, False) for name in
                   ('view_channel', 'read_message_history', 'send_messages', 'embed_links')):
            raise ValueError('Faltan permisos para el recordatorio privado.')

    async def reconcile(self, channel, row, state):
        """Read a bounded ordered page; incomplete pages never permit a send."""
        candidate = deepcopy(state)
        cursor = int(candidate['cursor'])
        kwargs = dict(limit=HISTORY_LIMIT + 1, oldest_first=True)
        if cursor:
            kwargs['after'] = discord.Object(id=cursor)
        messages = [message async for message in channel.history(**kwargs)]
        complete = len(messages) <= HISTORY_LIMIT
        members = {}
        for message in messages[:HISTORY_LIMIT]:
            if (message.channel.id != channel.id or message.guild.id != GUILD_ID
                    or int(message.id) <= cursor):
                raise ValueError('El historial del ticket no conserva su orden e identidad.')
            cursor = int(message.id)
            candidate['cursor'] = cursor
            author = message.author
            if (author.id == BOT_ID or getattr(author, 'bot', False)
                    or getattr(message, 'webhook_id', None) is not None
                    or getattr(message, 'type', discord.MessageType.default) not in
                        (discord.MessageType.default, discord.MessageType.reply)):
                continue
            when = as_time(message.created_at)
            if when > utcnow() + timedelta(minutes=5):
                raise ValueError('El historial del ticket contiene una fecha incoherente.')
            # A staff member can open a ticket too; their own messages remain
            # customer messages and must never satisfy the response deadline.
            if author.id == int(row['owner']):
                if candidate['awaiting_since'] is None:
                    candidate.update(awaiting_since=when.isoformat(), episode='message:' + str(message.id),
                                     owner_message=str(message.id))
                elif candidate['owner_message'] is None:
                    candidate['owner_message'] = str(message.id)
                continue
            if author.id not in members:
                member = await channel.guild.fetch_member(author.id)
                if member.id != author.id or member.guild.id != GUILD_ID or member.bot:
                    raise ValueError('No se pudo comprobar al participante del ticket.')
                members[author.id] = member
            if not self.system.is_staff(members[author.id]):
                # This private channel admits only its author and staff. An old
                # reply from somebody whose role was removed is ambiguous; do
                # not mislabel the ticket as unanswered or guess their old role.
                raise ValueError('No se pudo comprobar una respuesta anterior del equipo.')
            candidate.update(ever_replied=True, awaiting_since=None, episode=None,
                             owner_message=None)
        await self.save(candidate)
        return candidate, complete

    @staticmethod
    def due(state, now):
        if state['awaiting_since'] is None:
            return False
        delay = FOLLOWUP_DELAY if state['ever_replied'] else INITIAL_DELAY
        deadline = as_time(state['awaiting_since']) + delay
        if state.get('last_sent'):
            deadline = max(deadline, as_time(state['last_sent']) + REPEAT_DELAY)
        return now >= deadline

    async def recipient(self, channel, row):
        assignment = await self.system.tickets.assignment(row)
        staff_id = assignment.get('staff_id')
        if staff_id is not None:
            if int(staff_id) == int(row['owner']):
                raise ValueError('El autor del ticket no puede recibir su propio aviso de equipo.')
            target = await self.system.tickets.fresh_staff(channel.guild, staff_id)
            permissions = channel.permissions_for(target)
            if not permissions.view_channel or not permissions.read_message_history:
                raise ValueError('El responsable ya no puede consultar este ticket.')
            return dict(kind='user', id=int(target.id), revision=assignment.get('notice_revision'),
                        claimed_at=assignment.get('claimed_at'))
        role_id = int(self.system.store.get('role:support') or 0)
        roles = await channel.guild.fetch_roles()
        role = next((role for role in roles if role.id == role_id), None)
        if role is None or role.guild.id != GUILD_ID or role.id == GUILD_ID:
            raise ValueError('No se pudo comprobar el rol de Soporte.')
        permissions = channel.permissions_for(role)
        if (not permissions.view_channel or not permissions.read_message_history
                or not (role.mentionable or channel.permissions_for(channel.guild.me).mention_everyone)):
            raise ValueError('Soporte no puede recibir el aviso privado de este ticket.')
        return dict(kind='role', id=role_id, revision=assignment.get('notice_revision'),
                    claimed_at=assignment.get('claimed_at'))

    @staticmethod
    def mention(receipt):
        return ('<@&' if receipt['target']['kind'] == 'role' else '<@') + str(receipt['target']['id']) + '>'

    def embed(self, receipt):
        waiting = int(as_time(receipt['awaiting_since']).timestamp())
        first = receipt['phase'] == 'initial'
        # Discord serializes embed timestamps at millisecond precision. Keep
        # retries and exact receipt comparisons independent of Python microseconds.
        created = as_time(receipt['created_at'])
        created -= timedelta(microseconds=created.microsecond % 1000)
        description = ('Este ticket aún no tiene responsable. Usa **Atender** para tomarlo.'
                       if receipt['target']['kind'] == 'role' else
                       'Este caso sigue esperando una respuesta del equipo.')
        result = discord.Embed(title=TITLE, description=description, color=CYAN,
            timestamp=created,
            url=f'https://discord.com/channels/{GUILD_ID}/{receipt["channel"]}?reminder={receipt["nonce"]}')
        result.add_field(name='Pendiente desde', value=f'<t:{waiting}:R>', inline=True)
        result.add_field(name='Plazo', value='Primera respuesta · 2 h' if first else 'Seguimiento · 24 h', inline=True)
        if receipt.get('owner_message'):
            link = f'https://discord.com/channels/{GUILD_ID}/{receipt["channel"]}/{receipt["owner_message"]}'
            result.add_field(name='Consulta pendiente', value=f'[Ver mensaje]({link})', inline=False)
        return result.set_footer(text=FOOTER)

    def matches(self, message, receipt):
        if (message.author.id != BOT_ID or message.channel.id != int(receipt['channel'])
                or message.content != self.mention(receipt) or message.attachments
                or message.components or len(message.embeds) != 1):
            return False
        actual, desired = message.embeds[0], self.embed(receipt)
        return (actual.title == desired.title and actual.description == desired.description
                and actual.url == desired.url and actual.timestamp == desired.timestamp
                and actual.footer.text == desired.footer.text
                and [dict(name=f.name, value=f.value, inline=f.inline) for f in actual.fields]
                    == [dict(name=f.name, value=f.value, inline=f.inline) for f in desired.fields])

    async def finish(self, state, receipt, message=None):
        receipt = dict(receipt)
        if message is not None:
            sent = as_time(message.created_at)
            receipt.update(state='sent', message_id=int(message.id), sent_at=sent.isoformat())
            previous = as_time(state['last_sent']) if state.get('last_sent') else sent
            state['last_sent'] = max(sent, previous).isoformat()
        else:
            receipt.update(state='cancelled', cancelled_at=utcnow().isoformat())
        await self.system.call('put', receipt_key(receipt['nonce']), receipt)
        state['pending'] = None
        await self.save(state)

    async def recover(self, channel, receipt):
        if not receipt.get('attempted_at'):
            return None
        attempted = as_time(receipt['attempted_at'])
        count = 0
        async for message in channel.history(limit=HISTORY_LIMIT + 1,
                after=attempted - timedelta(seconds=5), oldest_first=True):
            count += 1
            if self.matches(message, receipt):
                return message
        if count > HISTORY_LIMIT or utcnow() - attempted < timedelta(seconds=10):
            raise ValueError('La entrega anterior todavía necesita verificarse.')
        return None

    async def process(self, channel_id):
        """Caller holds ticket_lock, shared with claims, release and closure."""
        guild = self.guild()
        row = await self.system.call('ticket', channel_id)
        if not row or row['state'] != 'open':
            return 0
        channel = await guild.fetch_channel(int(channel_id))
        self.scope(channel, row)
        state = await self.load(row)
        state, complete = await self.reconcile(channel, row, state)
        if not complete:
            return 0
        pending = state.get('pending')
        if pending:
            expected = dict(guild=GUILD_ID, channel=str(row['channel']), owner=str(row['owner']))
            if any(pending.get(key) != value for key, value in expected.items()):
                raise ValueError('La entrega pendiente no pertenece a este ticket.')
            saved = await self.system.call('get', receipt_key(pending['nonce']))
            if saved and saved.get('state') == 'sent':
                state['last_sent'] = saved['sent_at']
                state['pending'] = None
                await self.save(state)
                return 0
            found = await self.recover(channel, pending)
            if found is not None:
                await self.finish(state, pending, found)
                return 0
        if not self.due(state, utcnow()):
            if pending:
                await self.finish(state, pending)
            return 0
        target = await self.recipient(channel, row)
        if pending and (pending['episode'] != state['episode'] or pending['target'] != target):
            await self.finish(state, pending)
            pending = None
        if pending is None:
            pending = dict(guild=GUILD_ID, channel=str(row['channel']), owner=str(row['owner']),
                target=target, episode=state['episode'], nonce=uuid.uuid4().hex,
                phase='followup' if state['ever_replied'] else 'initial',
                awaiting_since=state['awaiting_since'], owner_message=state['owner_message'],
                created_at=utcnow().isoformat(), state='pending', attempted_at=None)
        before = deepcopy(state)

        async def snapshot():
            return dict(guild=GUILD_ID, channel=channel.id, before=before,
                current=await self.system.call('get', state_key(channel.id)),
                receipt=await self.system.call('get', receipt_key(pending['nonce'])))

        async def publish():
            nonlocal channel, row, state
            # Final checks run after the durable journal snapshot, immediately
            # before publication. A missed human reply suppresses the reminder.
            channel = await guild.fetch_channel(int(channel_id))
            row = await self.system.call('ticket', channel_id)
            if not row or row['state'] != 'open':
                return 0
            self.scope(channel, row)
            if str(row['owner']) != pending['owner']:
                raise ValueError('El autor del ticket cambió.')
            current_target = await self.recipient(channel, row)
            # Recipient lookup can take a REST round trip. Read history after it
            # so a response posted during that check suppresses this reminder.
            state, complete = await self.reconcile(channel, row, await self.load(row))
            if (not complete or not self.due(state, utcnow()) or state['episode'] != pending['episode']
                    or current_target != pending['target']):
                if state.get('pending'):
                    await self.finish(state, state['pending'])
                return 0
            pending.update(state='pending', attempted_at=utcnow().isoformat())
            state['pending'] = deepcopy(pending)
            await self.save(state)
            await self.system.call('put', receipt_key(pending['nonce']), pending)
            target_id = discord.Object(id=pending['target']['id'])
            allowed = discord.AllowedMentions(everyone=False, replied_user=False,
                users=[target_id] if pending['target']['kind'] == 'user' else False,
                roles=[target_id] if pending['target']['kind'] == 'role' else False)
            message = await channel.send(content=self.mention(pending), embed=self.embed(pending),
                nonce=str(int(pending['nonce'][:16], 16)), allowed_mentions=allowed)
            if not self.matches(message, pending):
                raise ValueError('Discord no confirmó el recordatorio registrado.')
            await self.finish(state, pending, message)
            log.info('VICE_TICKET_REMINDER_SENT channel=%s message=%s phase=%s',
                     channel.id, message.id, pending['phase'])
            return 1

        return await self.system.track('TICKET_REMINDER', 'Recordar respuesta pendiente en ticket privado',
            publish, pending['nonce'], snapshot=snapshot)

    async def tick(self):
        if not self.enabled():
            return 0
        self.guild()
        rows = sorted((row for row in await self.system.call('tickets') if row['state'] == 'open'),
                      key=lambda row: int(row['channel']))
        rows = [row for row in rows if int(row['channel']) > self.cursor] + [
            row for row in rows if int(row['channel']) <= self.cursor]
        sent = 0
        for row in rows[:TICK_LIMIT]:
            self.cursor = int(row['channel'])
            try:
                async with self.system.ticket_lock:
                    if not self.enabled():
                        break
                    sent += await self.process(int(row['channel']))
            except Exception as error:
                log.warning('VICE_TICKET_REMINDER_PENDING channel=%s error=%s',
                            row['channel'], type(error).__name__)
        return sent

    async def ready(self):
        self.guild()
        rows = await self.system.call('tickets')
        open_count = sum(row['state'] == 'open' for row in rows)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.worker(), name='vice-ticket-reminders')
        log.info('VICE_TICKET_REMINDERS_READY initial_hours=2 followup_hours=24 repeat_hours=24 open_count=%s',
                 open_count)
        return open_count

    async def worker(self):
        await self.system.ready_event.wait()
        while True:
            try:
                await self.tick()
            except Exception as error:
                log.warning('VICE_TICKET_REMINDER_WORKER error=%s', type(error).__name__)
            await asyncio.sleep(POLL_SECONDS)

    async def close(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
