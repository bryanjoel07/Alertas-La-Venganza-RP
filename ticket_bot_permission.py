"""Owner-requested Manage Channels grant, restricted to this bot's managed role."""
import logging

import discord

from tickets_store import PROTECTED

GUILD=1244988345327550565
BOT=1567658433497399408
MARKER='bot-delete-permission-request-v37'
log=logging.getLogger('LaVenganzaRP.tickets')


async def ensure_bot_delete_permission(system):
    if system.guild_id!=GUILD or system.bot.user.id!=BOT:return None
    guild=system.bot.get_guild(GUILD)
    if guild is None:raise ValueError('El bot todavía no está conectado al servidor.')

    async def inspect():
        roles=await guild.fetch_roles()
        member=await guild.fetch_member(BOT)
        assigned={role.id for role in member.roles}
        matches=[role for role in roles if role.managed and getattr(role.tags,'bot_id',None)==BOT and role.id in assigned]
        if len(matches)!=1:raise ValueError('No se pudo identificar el rol propio del bot con seguridad.')
        role=matches[0]
        if role.id in PROTECTED or role.id==GUILD:raise ValueError('El rol identificado está protegido; no se modifica.')
        value=0
        for item in roles:
            if item.id in assigned or item.id==GUILD:value|=item.permissions.value
        effective=discord.Permissions(value)
        return role,dict(bot=BOT,role=role.id,role_name=role.name,permissions=role.permissions.value,
            role_manage_channels=role.permissions.manage_channels,role_administrator=role.permissions.administrator,
            effective_manage_channels=effective.administrator or effective.manage_channels)

    role,before=await inspect()
    if await system.call('config',MARKER)=='verified':
        after=before;granted=False
    else:
        async def snapshot():return (await inspect())[1]
        async def grant():
            target,current=await inspect()
            if not current['effective_manage_channels']:
                permissions=discord.Permissions(current['permissions']);permissions.manage_channels=True
                await target.edit(permissions=permissions,reason='Permiso de eliminar canales de tickets solicitado por el propietario')
            _,result=await inspect()
            if not result['effective_manage_channels']:
                raise ValueError('Discord no confirmó Gestionar canales para el bot.')
            return result
        try:
            after=await system.bot.changes.tracked('TICKET_BOT_DELETE_PERMISSION','Verificar permiso de eliminar canales para el rol propio del bot',
                grant,request_id=f'{role.id}:manage-channels-v37',snapshot=snapshot)
            _,after=await inspect()
        except (discord.HTTPException,ValueError) as error:
            log.warning('TICKETS bot_delete_permission_pending bot=%s role=%s role_name=%s error=%s; no_other_roles_changed=True',
                BOT,role.id,role.name,type(error).__name__)
            return dict(before,verified=False,error_type=type(error).__name__)
        await system.call('config',MARKER,'verified')
        granted=not (before['role_manage_channels'] or before['role_administrator']) and after['role_manage_channels']
    verified=bool(after['effective_manage_channels'])
    log.log(logging.INFO if verified else logging.WARNING,
        'TICKETS bot_delete_permission_verified bot=%s role=%s role_name=%s manage_channels=%s administrator=%s granted=%s verified=%s',
        BOT,after['role'],after['role_name'],after['effective_manage_channels'],after['role_administrator'],granted,verified)
    return dict(after,verified=verified)
