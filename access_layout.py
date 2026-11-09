"""Explicit, one-shot faction access and role organization requested by the owner."""
import json
import logging
import os
from pathlib import Path
import re
import discord
from navigation import key

log = logging.getLogger('LaVenganzaRP.access')
STAFF = {1245008186440683530,1245010156576833536,1300619682486947931,
         1300627506801541230,1300627732954349619,1300631163362218054,1567253212937846935}
PROTECTED = {1245008186440683530,1300627506801541230,1300619682486947931,1245010156576833536}
ADMINS = STAFF - {1300627732954349619,1300631163362218054}
CITIZENS = 1245009164070158409
GANGS = {1370507359935266967,1371545781768814793,1567016508805357778,1569198736889085962}
LEADERS = {1370558759155404810,1540462927507619991}
POLICE = {1300628784457977988,1300628979660750871}
BUSINESSES = {1300629493526040626,1370560414877745274,1541186725114814475,
              1541211430445908049,1547361036926197862,1567253732868227082,
              1567263381701005402,1567270078712520724}
# Categories that are shared remain shared; each gang's own category stays private.
CATEGORY_ROLES = {
    1567257821911720027:{1370507359935266967},
    1567225971306926090:{1569198736889085962},
    1561151256670511267:{1371545781768814793},
    1567081958180261949:{1567016508805357778},
    1541628457216249918:POLICE,
    1528921046827274371:GANGS|LEADERS,
    1528921493067796670:BUSINESSES,
}
COMMANDS = {
    1544188640907759646:('🔵┊𝐂𝐨𝐦𝐚𝐧𝐝𝐨𝐬-𝐒𝐭𝐚𝐟𝐟',False,
        'Comandos de trabajo para Staff: Soporte, Moderadores y Administración. Cada comando conserva sus requisitos de autorización.'),
    1300622843435941969:('🔱┊𝐂𝐨𝐦𝐚𝐧𝐝𝐨𝐬-𝐀𝐝𝐦𝐢𝐧',True,
        'Comandos de Administración. Uso: Admin, Súper Admin, Jefe de Staff, Programador y Owner. Soporte y Moderadores pueden consultar el canal.'),
    1512502018760114397:('🔱┊𝐂𝐨𝐦𝐚𝐧𝐝𝐨𝐬-𝐀𝐝𝐦𝐢𝐧-𝐍𝐮𝐞𝐯𝐨',True,
        'Comandos nuevos de Administración. Uso: Admin, Súper Admin, Jefe de Staff, Programador y Owner. Se conserva el historial de este canal.'),
}
# Bottom to top, within existing editable slots. No staff or managed role moves.
ROLE_ORDER = [CITIZENS,1568399564887826486,1300630661400625214,
    1567253732868227082,1541211430445908049,1541186725114814475,
    1300629493526040626,1547361036926197862,1567263381701005402,
    1567270078712520724,1370560414877745274,
    1567253062945607791,1300629269570912327,1360296810484203704,
    1300628979660750871,1300628784457977988,
    1567016508805357778,1371545781768814793,1569198736889085962,1370507359935266967,
    1540462927507619991,1370558759155404810,
    1300628492446208123,1300627810582528122]


def merged_raw(channel, changes):
    """Retain member exceptions, unresolved targets and every unrelated permission bit."""
    raw = {(o.type,o.id):dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny))
           for o in channel._overwrites}
    for role_id,fields in changes.items():
        previous=raw.get((0,role_id),dict(id=str(role_id),type=0,allow='0',deny='0'))
        ow=discord.PermissionOverwrite.from_pair(discord.Permissions(int(previous['allow'])),
                                                  discord.Permissions(int(previous['deny'])))
        for field,value in fields.items():
            setattr(ow,field,value)
        allow,deny=ow.pair()
        raw[(0,role_id)]=dict(id=str(role_id),type=0,allow=str(allow.value),deny=str(deny.value))
    return list(raw.values())


def access_changes(channel, guild_id):
    cat=channel.id if channel.id in CATEGORY_ROLES else channel.category_id
    if cat not in CATEGORY_ROLES and channel.id not in COMMANDS:
        return {}
    changes={guild_id:dict(view_channel=False),CITIZENS:dict(view_channel=False)}
    changes.update({r:dict(view_channel=True,read_message_history=True) for r in STAFF-PROTECTED})
    if channel.id in COMMANDS:
        pass  # Names clarify purpose; existing Staff command permissions are preserved.
    else:
        own=CATEGORY_ROLES[cat]
        changes.update({r:dict(view_channel=True,read_message_history=True) for r in own})
        if cat in {1567257821911720027,1567225971306926090,1561151256670511267,1567081958180261949,1541628457216249918}:
            # Global gang leadership grants already present are retained. Other faction identities are isolated.
            changes.update({r:dict(view_channel=False) for r in (GANGS|POLICE)-own})
    return changes


def positions_for(roles, top):
    selected=[r for r in roles if r.id in ROLE_ORDER]
    if len(selected)!=len(ROLE_ORDER):
        raise ValueError('Falta un rol conocido; no se modifica la jerarquía')
    if any(r.managed or r>=top for r in selected):
        raise ValueError('Un rol está protegido por la jerarquía del bot')
    by_id={r.id:r for r in selected}
    slots=sorted(r.position for r in selected)
    return {by_id[rid]:position for rid,position in zip(ROLE_ORDER,slots)}


async def organize_access(bot,guild_id,path):
    request=os.getenv('ACCESS_LAYOUT_REQUEST_ID','').strip()
    if not request or getattr(bot,'_access_layout_request',None)==request:
        return
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):
        raise ValueError('Identificador inválido')
    guild=bot.get_guild(guild_id)
    channels=await guild.fetch_channels()
    roles=await guild.fetch_roles()
    me=await guild.fetch_member(bot.user.id)
    if not me.guild_permissions.administrator:
        raise ValueError('El bot necesita los permisos administrativos ya autorizados')
    by_id={r.id:r for r in roles}
    if not (STAFF|GANGS|LEADERS|POLICE|BUSINESSES|{CITIZENS}).issubset(by_id):
        raise ValueError('Falta un rol requerido; no se aplicaron cambios')
    if not (set(CATEGORY_ROLES)|set(COMMANDS)).issubset({c.id for c in channels}):
        raise ValueError('Falta una categoría o canal requerido')
    positions=positions_for(roles,me.top_role)
    plans={c.id:merged_raw(c,access_changes(c,guild_id)) for c in channels if access_changes(c,guild_id)}
    folder=Path(path).resolve().parent/'navigation'
    folder.mkdir(exist_ok=True)
    snapshot=folder/f'{request}-access-layout-before.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps(dict(roles=[dict(id=str(r.id),name=r.name,position=r.position,
            permissions=r.permissions.value,color=r.color.value,hoist=r.hoist) for r in roles],
            channels=[dict(id=str(c.id),name=c.name,parent=str(c.category_id),topic=getattr(c,'topic',None),
            overwrites=[dict(id=str(o.id),type=o.type,allow=str(o.allow),deny=str(o.deny)) for o in c._overwrites])
            for c in channels]),ensure_ascii=False,indent=2))
    for c in channels:
        if c.id not in plans:
            continue
        fields=dict(permission_overwrites=plans[c.id])
        if c.id in COMMANDS:
            fields.update(name=COMMANDS[c.id][0],topic=COMMANDS[c.id][2])
        await bot.http.edit_channel(c.id,reason='Organización de accesos y comandos solicitada por el propietario',**fields)
        log.info('ACCESS_LAYOUT %s applied channel=%s id=%s',request,c.name,c.id)
    await guild.edit_role_positions(positions=positions,reason='Agrupar roles conservando Staff y bot por encima')
    for role in roles:
        if role.id in GANGS|POLICE|BUSINESSES|{CITIZENS}:
            if not role.hoist:
                await role.edit(hoist=True,reason='Separar visualmente facciones y Ciudadanos')
        elif role.id in {1300627810582528122,1300628492446208123} or role.name.startswith('LV · '):
            if role<me.top_role and not role.managed and role.hoist:
                await role.edit(hoist=False,reason='Mantener cosméticos fuera de los grupos de facciones')
    fresh_channels=await guild.fetch_channels()
    original_channels={c.id:c for c in channels}
    if set(original_channels)!={c.id for c in fresh_channels} or any(
            c.category_id!=original_channels[c.id].category_id for c in fresh_channels):
        raise RuntimeError('El inventario o la ubicación de canales cambió durante la revisión')
    def raw_values(values):
        return {(int(v['type']),str(v['id']),int(v['allow']),int(v['deny'])) for v in values}
    for c in fresh_channels:
        if c.id in plans:
            actual=[dict(id=str(o.id),type=o.type,allow=o.allow,deny=o.deny) for o in c._overwrites]
            if raw_values(actual)!=raw_values(plans[c.id]):
                raise RuntimeError(f'Permisos no confirmados en {c.id}')
            for role_id in (STAFF-PROTECTED)|CATEGORY_ROLES.get(c.id if c.id in CATEGORY_ROLES else c.category_id,set()):
                if not c.permissions_for(by_id[role_id]).view_channel:
                    raise RuntimeError(f'Acceso no confirmado para {role_id} en {c.id}')
            if c.id in COMMANDS and (c.name!=COMMANDS[c.id][0] or c.topic!=COMMANDS[c.id][2]):
                raise RuntimeError('Nombre de comandos no confirmado')
    fresh_roles={r.id:r for r in await guild.fetch_roles()}
    ordered=[fresh_roles[rid].position for rid in ROLE_ORDER]
    if ordered!=sorted(ordered) or len(set(ordered))!=len(ordered):
        raise RuntimeError('Discord no confirmó el orden de roles')
    for role in roles:
        new=fresh_roles[role.id]
        if new.permissions!=role.permissions or new.color!=role.color:
            raise RuntimeError('Permisos o color de rol cambiaron inesperadamente')
        if role.id in GANGS|POLICE|BUSINESSES|{CITIZENS} and not new.hoist:
            raise RuntimeError('Discord no confirmó los grupos visuales de roles')
        if (role.managed or role>=me.top_role) and new.position!=role.position:
            raise RuntimeError('Cambió una posición protegida')
    bot._access_layout_request=request
    log.info('ACCESS_LAYOUT %s complete channels=%s roles=%s staff_preserved=True bot_hierarchy_preserved=True photos_parent=%s',
        request,len(plans),len(positions),next(c.category_id for c in fresh_channels if c.id==1513422142014754976))


COMMAND_PERMISSION_FIELDS=('send_messages','use_application_commands','send_messages_in_threads',
                           'create_public_threads','create_private_threads')
REPAIR_ROLES={1300627732954349619,1300631163362218054}


def restore_command_restrictions(channel, original):
    """Undo only newly introduced denials for Support/Moderator, never protected ranks."""
    saved={(int(o['type']),int(o['id'])):o for o in original['overwrites']}
    changes={}
    for rid in REPAIR_ROLES:
        previous=saved.get((0,rid),dict(allow=0,deny=0))
        before=discord.PermissionOverwrite.from_pair(discord.Permissions(int(previous['allow'])),
                                                    discord.Permissions(int(previous['deny'])))
        current=next((o for o in channel._overwrites if o.type==0 and o.id==rid),None)
        now=discord.PermissionOverwrite.from_pair(discord.Permissions(current.allow if current else 0),
                                                 discord.Permissions(current.deny if current else 0))
        fields={field:getattr(before,field) for field in COMMAND_PERMISSION_FIELDS
                if getattr(now,field) is False and getattr(before,field) is not False}
        if fields:
            changes[rid]=fields
    return changes


async def repair_staff_command_access(bot,guild_id,path):
    request=os.getenv('REPAIR_STAFF_ACCESS_REQUEST_ID','').strip()
    if not request or getattr(bot,'_repair_staff_access',None)==request:
        return
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):
        raise ValueError('Identificador inválido')
    folder=Path(path).resolve().parent/'navigation'
    original=json.loads((folder/'access-roles-20261109-access-layout-before.json').read_text())
    originals={int(c['id']):c for c in original['channels']}
    guild=bot.get_guild(guild_id)
    channels=await guild.fetch_channels()
    roles=await guild.fetch_roles()
    previous_roles={int(r['id']):r for r in original['roles']}
    # This comparison is read-only. No role permission, assignment, name or position is edited.
    for r in roles:
        if r.id in STAFF:
            saved=previous_roles[r.id]
            log.info('STAFF_REPAIR %s role=%s id=%s permissions_before=%s permissions_now=%s position_before=%s position_now=%s protected=%s',
                request,r.name,r.id,saved['permissions'],r.permissions.value,saved['position'],r.position,r.id in PROTECTED)
    backup=folder/f'{request}-before.json'
    if not backup.exists():
        backup.write_text(json.dumps([dict(id=str(c.id),overwrites=[dict(id=str(o.id),type=o.type,
            allow=str(o.allow),deny=str(o.deny)) for o in c._overwrites]) for c in channels if c.id in COMMANDS],indent=2))
    protected_before={c.id:{(o.type,o.id,o.allow,o.deny) for o in c._overwrites if o.id in PROTECTED and o.type==0}
                      for c in channels}
    repaired=0
    for c in channels:
        if c.id not in COMMANDS:
            continue
        changes=restore_command_restrictions(c,originals[c.id])
        if changes:
            await bot.http.edit_channel(c.id,permission_overwrites=merged_raw(c,changes),
                                       reason='Restaurar permisos previos de Soporte y Moderadores; rangos protegidos intactos')
            repaired+=1
            log.info('STAFF_REPAIR %s restored channel=%s roles=%s',request,c.id,sorted(changes))
    refreshed=await guild.fetch_channels()
    by_role={r.id:r for r in roles}
    for c in refreshed:
        protected_now={(o.type,o.id,o.allow,o.deny) for o in c._overwrites if o.id in PROTECTED and o.type==0}
        if protected_now!=protected_before[c.id]:
            raise RuntimeError('Cambió un permiso protegido durante la revisión')
        if c.id in COMMANDS and restore_command_restrictions(c,originals[c.id]):
            raise RuntimeError('Discord no confirmó la restauración')
    programmer=by_role[1300627506801541230]
    full=all(c.permissions_for(programmer).administrator and c.permissions_for(programmer).view_channel
             and c.permissions_for(programmer).send_messages for c in refreshed)
    log.info('STAFF_REPAIR %s complete restored_channels=%s protected_overwrites_unchanged=True programmer_admin=%s programmer_full_access=%s channels_checked=%s',
        request,repaired,programmer.permissions.administrator,full,len(refreshed))
    bot._repair_staff_access=request
