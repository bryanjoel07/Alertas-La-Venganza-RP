"""One authorized channel overwrite for Ciudadanos; leave every other bit intact."""
import logging
import time

import discord

CHANNEL_ID = 1539014594348064939
CITIZEN_ID = 1245009164070158409
ACCESS_KEY = 'citizen_panel_access_v1'
FIELDS = ('view_channel', 'read_message_history', 'use_application_commands')
MASK = discord.Permissions(**dict.fromkeys(FIELDS, True)).value
log = logging.getLogger('LaVenganzaRP.feedback')


def access_state(channel, role):
    allow, deny = channel.overwrites_for(role).pair()
    return dict(channel=channel.id, category=channel.category_id, synced=channel.permissions_synced,
        role=role.id, role_name=role.name, guild_permissions=str(role.permissions.value),
        target=dict(allow=str(allow.value), deny=str(deny.value)),
        overwrites=[dict(id=o.id, type=o.type, allow=str(o.allow), deny=str(o.deny)) for o in channel._overwrites])


def other_overwrites(state):
    return {(o['id'],o['type']):(o['allow'],o['deny']) for o in state['overwrites']
        if (o['id'],o['type']) != (CITIZEN_ID,0)}


async def enable_citizen_panel(system):
    if await system.call('config', ACCESS_KEY) == 'complete':
        return
    before = None
    verified = None

    async def current():
        channel = await system.channel()
        if channel.id != CHANNEL_ID or channel.guild.id != system.guild_id:
            raise ValueError('El permiso solicitado es solo para el canal de Feedback de La Venganza RP.')
        role = channel.guild.get_role(CITIZEN_ID)
        if role is None:
            raise ValueError('No encuentro el rol Ciudadanos esperado; no se cambiarán otros roles.')
        return channel, role

    async def snapshot():
        nonlocal before
        channel, role = await current()
        state = access_state(channel, role)
        if before is None:
            before = state
        return state

    async def apply():
        nonlocal verified
        channel, role = await current()
        if access_state(channel, role)['target'] != before['target']:
            raise ValueError('Los permisos de Ciudadanos cambiaron durante la revisión. Se revisarán otra vez antes de guardar.')
        overwrite = channel.overwrites_for(role)
        for name in FIELDS:
            setattr(overwrite, name, True)
        if overwrite.pair() != channel.overwrites_for(role).pair():
            await channel.set_permissions(role, overwrite=overwrite,
                reason='Solicitud del dueño: permitir a Ciudadanos ver y usar el panel de Feedback')
        channel, role = await current()
        after = access_state(channel, role)
        actual = channel.overwrites_for(role)
        effective = channel.permissions_for(role)
        if not all(getattr(actual, name) is True and getattr(effective, name) for name in FIELDS):
            raise RuntimeError('Discord no confirmó el acceso de Ciudadanos al panel de Feedback.')
        if any(int(before['target'][key]) & ~MASK != int(after['target'][key]) & ~MASK for key in ('allow','deny')):
            raise RuntimeError('Cambió un permiso de Ciudadanos ajeno al acceso solicitado.')
        if other_overwrites(before) != other_overwrites(after) or before['guild_permissions'] != after['guild_permissions']:
            raise RuntimeError('Otros permisos cambiaron durante la configuración; se conserva el respaldo para revisión.')
        verified = channel, role, actual, effective

    await system.bot.changes.tracked('FEEDBACK_CITIZEN_ACCESS', 'Dar a Ciudadanos acceso al panel de Feedback', apply,
        request_id=f'{CHANNEL_ID}:{CITIZEN_ID}:{time.time_ns()}', snapshot=snapshot)
    await system.call('config', ACCESS_KEY, 'complete')
    channel, role, actual, effective = verified
    log.info('FEEDBACK citizen_access_verified channel=%s role=%s view_channel=%s read_message_history=%s use_application_commands=%s writing_overwrite=%s effective_write=%s other_overwrites_preserved=True guild_permissions_unchanged=True one_shot=True',
        channel.id,role.id,effective.view_channel,effective.read_message_history,effective.use_application_commands,
        actual.send_messages,effective.send_messages)
