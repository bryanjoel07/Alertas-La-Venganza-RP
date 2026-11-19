"""Staff-requested reopen of the same private ticket, with restart recovery."""
from copy import deepcopy
import asyncio
from datetime import datetime, timezone
import logging
import uuid

import discord

from vice_design import BOT_ID, GUILD_ID, OWNER_ID, TICKET_OPEN_PREFIX
from vice_channel_style import format_name
from vice_ticket_delete import (ARCHIVE_TITLE, REOPEN_CUSTOM_ID, REOPEN_TITLE,
                                has_control, panel_footer, record_key as delete_key)
from vice_tickets import assignment_key

VERSION = 'vice-ticket-reopen-v1'
log = logging.getLogger('ViceDistrict.ticket_reopen')


def record_key(channel_id):
    return 'ticket_reopen:' + str(channel_id)


def rules_state(rules):
    return sorted([dict(id=str(target.id), allow=str(rule.pair()[0].value),
                        deny=str(rule.pair()[1].value)) for target, rule in rules.items()],
                  key=lambda value: int(value['id']))


class TicketReopen:
    def __init__(self, system):
        self.system = system
        self.task = None

    async def context(self, actor_id):
        guild = self.system.tickets.guild()
        actual = await self.system.bot.fetch_guild(GUILD_ID)
        self.system.validate_guild(actual)
        if actual.id != GUILD_ID or actual.owner_id != OWNER_ID:
            raise ValueError('No se pudo verificar el servidor del ticket.')
        member = await self.system.tickets.fresh_staff(guild, actor_id)
        return guild, member

    def bound(self, record, row):
        if (not row or record.get('version') != VERSION or not self.system.tickets.bound(record, row)
                or record.get('created') != row['created'] or record.get('kind') != row['kind']
                or record.get('state') not in ('pending', 'completed') or not record.get('revision')
                or not record.get('actor') or not record.get('panel_id')):
            raise ValueError('La reapertura registrada necesita revisión del equipo.')

    async def save(self, record):
        await self.system.call('put', record_key(record['channel']), record)
        await self.system.call('put', f'ticket_reopen:history:{record["channel"]}:{record["revision"]}', record)

    def private(self, channel, row):
        allowed = {GUILD_ID, BOT_ID, OWNER_ID, int(row['owner'])}
        allowed.update(int(self.system.store.get('role:' + key) or 0)
                       for key in ('founder', 'admin', 'mod', 'support'))
        rules = {target.id: rule for target, rule in channel.overwrites.items()}
        if (rules.get(GUILD_ID) is None or rules[GUILD_ID].view_channel is not False
                or any(rule.view_channel is True and target not in allowed for target, rule in rules.items())):
            raise ValueError('El ticket debe seguir siendo privado para su autor y el equipo.')

    async def source(self, channel, row, panel_id):
        record = await self.system.ticket_deletion.record(channel.id)
        if (record.get('state') != 'ready' or record.get('guild') != GUILD_ID
                or str(record.get('channel')) != str(row['channel'])
                or str(record.get('owner')) != str(row['owner'])
                or int(record.get('panel_id') or 0) != int(panel_id)):
            raise ValueError('Usa Reabrir en el panel actual del ticket cerrado.')
        panel = await channel.fetch_message(int(panel_id))
        if (panel.channel.id != channel.id or panel.id != int(panel_id)
                or not self.system.ticket_deletion.archive_matches(panel, channel.id)):
            raise ValueError('El panel del ticket necesita revisión del equipo.')
        return record, panel

    async def request(self, interaction):
        self.system.tickets.check_interaction(interaction)
        await interaction.response.defer(ephemeral=True)
        async with self.system.ticket_lock:
            guild, actor = await self.context(interaction.user.id)
            row = await self.system.call('ticket', interaction.channel_id)
            channel = await guild.fetch_channel(interaction.channel_id)
            if not row or channel.id != int(row['channel']):
                raise ValueError('Este canal no es un ticket registrado.')
            receipt = await self.system.call('get', record_key(channel.id))
            if receipt and receipt.get('state') == 'pending':
                self.bound(receipt, row)
                if interaction.message is None or interaction.message.id != receipt['panel_id']:
                    raise ValueError('Usa el panel registrado de este ticket.')
                async def recovery_snapshot():
                    return dict(ticket=await self.system.call('ticket', row['channel']), receipt=receipt)
                await self.system.track('TICKET_REOPEN_RECOVERY', 'Completar reapertura privada ya solicitada',
                    lambda: self.resume(receipt), receipt['revision'], snapshot=recovery_snapshot)
            else:
                if row['state'] == 'open':
                    raise ValueError('Este ticket ya está abierto.')
                self.system.tickets.valid_channel(channel, row, closed=True)
                self.private(channel, row)
                source = interaction.message
                if source is None or source.author.id != BOT_ID or source.channel.id != channel.id:
                    raise ValueError('Usa Reabrir en el panel del ticket cerrado.')
                deletion, panel = await self.source(channel, row, source.id)
                if panel.embeds[0].title != ARCHIVE_TITLE or not has_control(panel, REOPEN_CUSTOM_ID):
                    raise ValueError('Usa el botón Reabrir actual de este ticket.')
                owner, category, rules = await self.target(guild, row)
                assignment = await self.system.tickets.assignment(row)
                before = self.system.ticket_deletion.channel_snapshot(channel, row, deletion, panels=[panel])
                receipt = dict(version=VERSION, guild=GUILD_ID, channel=str(channel.id), owner=str(row['owner']),
                    created=row['created'], kind=row['kind'], state='pending', revision=uuid.uuid4().hex,
                    actor=actor.id, request_id=str(interaction.id), panel_id=panel.id,
                    reopened_at=datetime.now(timezone.utc).isoformat(), before=before,
                    assignment=assignment, target=dict(name=format_name(TICKET_OPEN_PREFIX + str(row['owner'])[-6:]),
                        category=category.id, topic='VIce ticket owner=' + str(row['owner']), rules=rules_state(rules)))
                async def snapshot():
                    return dict(before=before, assignment=assignment,
                        previous_reopen=await self.system.call('get', record_key(channel.id)),
                        reminder=await self.system.call('get', 'ticket_reminder:state:' + str(channel.id)))
                async def begin():
                    await self.save(receipt)
                    return await self.resume(receipt)
                await self.system.track('TICKET_REOPEN', 'Reabrir el mismo ticket privado conservando su historial',
                                        begin, receipt['revision'], snapshot=snapshot)
        await interaction.followup.send('🔓 Ticket reabierto. Se conservan el canal, el historial y la asignación vigente.',
            ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        try:
            await self.system.ticket_dashboard.tick()
        except Exception as error:
            log.warning('VICE_TICKET_REOPEN_DASHBOARD_PENDING error=%s', type(error).__name__)

    async def target(self, guild, row):
        try:
            owner = await guild.fetch_member(int(row['owner']))
        except discord.NotFound:
            raise ValueError('El autor ya no está en el servidor. Su historial cerrado se conserva.') from None
        if owner.id != int(row['owner']) or owner.guild.id != GUILD_ID or owner.bot:
            raise ValueError('No se pudo verificar al autor del ticket.')
        for other in await self.system.call('tickets', row['owner']):
            if str(other['channel']) != str(row['channel']) and other['state'] == 'open':
                raise ValueError('Este usuario ya tiene otro ticket abierto. Resuélvelo antes de reabrir este caso.')
        category = await guild.fetch_channel(int(self.system.store.get('category:help') or 0))
        if not isinstance(category, discord.CategoryChannel) or category.guild.id != GUILD_ID:
            raise ValueError('La categoría de ayuda necesita revisión del equipo.')
        if guild.me is None or guild.me.id != BOT_ID:
            raise ValueError('No se pudo verificar el bot del servidor.')
        for key in ('founder', 'admin', 'mod', 'support'):
            if guild.get_role(int(self.system.store.get('role:' + key) or 0)) is None:
                raise ValueError('Falta un rol del equipo; el ticket se conserva cerrado.')
        return owner, category, self.system.overwrites(guild, 'ticket', owner)

    async def resume(self, receipt):
        """Caller holds ticket_lock. Only a saved intent can recover an interrupted edit."""
        row = await self.system.call('ticket', receipt['channel'])
        self.bound(receipt, row)
        if receipt['state'] == 'completed':
            return
        guild, unused = await self.context(receipt['actor'])
        channel = await guild.fetch_channel(int(row['channel']))
        owner, category, rules = await self.target(guild, row)
        target = receipt['target']
        if (target['category'] != category.id or target['rules'] != rules_state(rules)
                or target['name'] != format_name(TICKET_OPEN_PREFIX + str(row['owner'])[-6:])
                or target['topic'] != 'VIce ticket owner=' + str(row['owner'])):
            raise ValueError('Los accesos del ticket cambiaron durante la reapertura.')
        desired = (channel.name == target['name'] and channel.category_id == target['category']
                   and channel.topic == target['topic'] and rules_state(channel.overwrites) == target['rules'])
        if not desired:
            self.system.tickets.valid_channel(channel, row, closed=True)
            self.private(channel, row)
            old = receipt['before']
            old_rules = sorted([dict(id=x['id'], allow=x['allow'], deny=x['deny']) for x in old['overwrites']],
                               key=lambda value: int(value['id']))
            if (channel.name != old['name'] or channel.category_id != old['category']
                    or channel.topic != old['topic'] or rules_state(channel.overwrites) != old_rules):
                raise ValueError('El ticket cambió manualmente; se conserva para revisión.')
            deletion, panel = await self.source(channel, row, receipt['panel_id'])
            if not has_control(panel, REOPEN_CUSTOM_ID):
                raise ValueError('El botón de reapertura cambió.')
            # Invalidate already-open delete confirmations before changing the channel.
            deletion['reopen_revision'] = receipt['revision']
            await self.system.call('put', delete_key(channel.id), deletion)
            receipt['attempted_at'] = datetime.now(timezone.utc).isoformat()
            # A verified still-closed channel starts its wait at this attempt,
            # not at a possibly much older request that never reached Discord.
            receipt['reopened_at'] = receipt['attempted_at']
            await self.save(receipt)
            await channel.edit(name=target['name'], category=category, topic=target['topic'], overwrites=rules,
                               reason=f'Ticket reabierto por {receipt["actor"]} • {receipt["revision"]}')
            channel = await guild.fetch_channel(channel.id)
            if (channel.name != target['name'] or channel.category_id != target['category']
                    or channel.topic != target['topic'] or rules_state(channel.overwrites) != target['rules']):
                raise ValueError('Discord no confirmó la reapertura; se verificará de nuevo.')
        elif row['state'] not in ('closed', 'open') or not receipt.get('attempted_at'):
            raise ValueError('La reapertura no tiene un intento verificable.')
        await self.system.call('ticket_state', row['channel'], 'open')
        row = await self.system.call('ticket', row['channel'])
        self.system.tickets.notice_scope(channel, row)
        assignment = await self.system.tickets.assignment(row)
        if assignment.get('staff_id'):
            try:
                staff = await self.system.tickets.fresh_staff(guild, assignment['staff_id'])
                if not channel.permissions_for(staff).view_channel:
                    raise ValueError('Sin acceso')
            except (discord.NotFound, ValueError):
                previous = deepcopy(assignment)
                assignment.update(staff_id=None, staff_name=None, released_by=receipt['actor'],
                    released_at=receipt['reopened_at'], release_reason='Responsable anterior ya no disponible')
                await self.system.call('put', f'ticket_reopen:assignment:{channel.id}:{receipt["revision"]}', previous)
                await self.system.call('put', assignment_key(channel.id), assignment)
        await self.system.ticket_reminders.reopened(channel, row, receipt['reopened_at'], receipt['revision'])
        await self.system.ticket_feedback.reopened(row, receipt['revision'])
        channel = await guild.fetch_channel(channel.id)
        self.system.tickets.notice_scope(channel, row)
        await self.system.tickets.fresh_staff(guild, receipt['actor'])
        if (channel.name != target['name'] or channel.category_id != target['category']
                or channel.topic != target['topic'] or rules_state(channel.overwrites) != target['rules']):
            raise ValueError('El ticket cambió antes de completar la reapertura.')
        await self.system.tickets.ensure_open_panel(channel, row)
        deletion, panel = await self.source(channel, row, receipt['panel_id'])
        responsible = f'<@{assignment["staff_id"]}>' if assignment.get('staff_id') else 'Sin asignar · usa Atender'
        embed = self.system.embed(REOPEN_TITLE, 'Este caso vuelve a estar abierto. El historial se conserva aquí.\n'
                                 f'**Responsable:** {responsible}')
        embed.set_footer(text=panel_footer(channel.id))
        if panel.embeds[0].to_dict() != embed.to_dict() or panel.components:
            await panel.edit(embed=embed, view=None, allowed_mentions=discord.AllowedMentions.none())
        receipt.update(state='completed', completed_at=datetime.now(timezone.utc).isoformat())
        await self.save(receipt)
        log.info('VICE_TICKET_REOPENED channel=%s revision=%s', channel.id, receipt['revision'])

    async def ready(self, *, quiet=False):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.worker(), name='vice-ticket-reopen-recovery')
        recovered = pending = 0
        for row in await self.system.call('tickets'):
            receipt = await self.system.call('get', record_key(row['channel']))
            if not receipt or receipt.get('state') != 'pending':
                continue
            async with self.system.ticket_lock:
                try:
                    self.bound(receipt, row)
                    async def snapshot():
                        return dict(ticket=await self.system.call('ticket', row['channel']), receipt=receipt)
                    await self.system.track('TICKET_REOPEN_RECOVERY', 'Completar reapertura privada ya solicitada',
                        lambda: self.resume(receipt), receipt['revision'], snapshot=snapshot)
                    recovered += 1
                except Exception as error:
                    pending += 1
                    log.warning('VICE_TICKET_REOPEN_PENDING channel=%s error=%s', row['channel'], type(error).__name__)
        if not quiet or recovered or pending:
            log.info('VICE_TICKET_REOPEN_READY recovered=%s pending=%s', recovered, pending)
        return recovered

    async def worker(self):
        await self.system.ready_event.wait()
        while True:
            await asyncio.sleep(60)
            try:
                await self.ready(quiet=True)
            except Exception as error:
                log.warning('VICE_TICKET_REOPEN_WORKER error=%s', type(error).__name__)

    async def close(self):
        task, self.task = self.task, None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
