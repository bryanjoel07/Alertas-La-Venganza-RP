"""Provision the requested Vista Hermosa role without assigning members."""
import json
import logging
import os
from pathlib import Path
import re

import discord
from navigation import key

log = logging.getLogger('LaVenganzaRP.roles')
ROLE_NAME = '🔴┊𝐕𝐢𝐬𝐭𝐚 𝐇𝐞𝐫𝐦𝐨𝐬𝐚'
RED = 0xFF0000


def access_overwrite(current):
    overwrite = discord.PermissionOverwrite.from_pair(*current.pair())
    for field in ('view_channel','send_messages','read_message_history','use_application_commands','connect','speak'):
        setattr(overwrite,field,True)
    return overwrite


async def ensure_vista_hermosa(bot,guild_id,path):
    request = os.getenv('VISTA_HERMOSA_REQUEST_ID','').strip()
    if not request or getattr(bot,'_vista_hermosa_request',None)==request:
        return
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):
        raise ValueError('Identificador de rol inválido')
    guild = bot.get_guild(guild_id)
    channels = await guild.fetch_channels()
    categories = [c for c in channels if isinstance(c,discord.CategoryChannel) and key(c.name)=='vistahermosa']
    if len(categories)!=1:
        raise ValueError('No encuentro una categoría Vista Hermosa única')
    category = categories[0]
    roles = await guild.fetch_roles()
    matches = [r for r in roles if key(r.name)=='vistahermosa' and not r.managed]
    if len(matches)>1:
        raise ValueError('Hay varios roles Vista Hermosa; no se creó otro')
    if matches:
        role = matches[0]
    else:
        # One creator across overlapping deployments; never duplicate an uncertain POST.
        with bot.economy.store.db() as db:
            claimed = db.execute("INSERT OR IGNORE INTO eco_resources(key,resource_id,state) VALUES ('faction:vista-hermosa',NULL,'creating')").rowcount
        if not claimed:
            log.warning('VISTA_HERMOSA %s creation_pending: reconciling existing request; no duplicate role created',request)
            return
        role = await guild.create_role(name=ROLE_NAME,colour=discord.Colour(RED),
            permissions=discord.Permissions.none(),mentionable=False,reason='Rol Vista Hermosa rojo solicitado por administración')
    with bot.economy.store.db() as db:
        db.execute("INSERT INTO eco_resources(key,resource_id,state) VALUES ('faction:vista-hermosa',?,'ready') ON CONFLICT(key) DO UPDATE SET resource_id=excluded.resource_id,state='ready'",(role.id,))
    if role.name!=ROLE_NAME or role.colour.value!=RED:
        role = await role.edit(name=ROLE_NAME,colour=discord.Colour(RED),reason='Nombre y color rojo solicitados para Vista Hermosa')
    me = await guild.fetch_member(bot.user.id)
    citizens = next((r for r in roles if key(r.name)=='ciudadanos'),None)
    if citizens and role.position<=citizens.position:
        position = min(citizens.position+1,me.top_role.position-1)
        if position>role.position:
            await guild.edit_role_positions(positions={role:position},reason='Mostrar el rojo de Vista Hermosa por encima de Ciudadanos y debajo de Staff')
    targets = [category]+[c for c in channels if c.category_id==category.id]
    folder=Path(path).resolve().parent/'navigation'
    folder.mkdir(exist_ok=True)
    snapshot=folder/f'{request}-role-access-before.json'
    if not snapshot.exists():
        snapshot.write_text(json.dumps(dict(role_id=str(role.id),channels=[dict(id=str(c.id),
            overwrites=[dict(id=str(o.id),type=o.type,allow=o.allow,deny=o.deny) for o in c._overwrites])
            for c in targets]),ensure_ascii=False,indent=2))
    for channel in targets:
        before = channel.overwrites_for(role)
        overwrite = access_overwrite(before)
        if before!=overwrite:
            await channel.set_permissions(role,overwrite=overwrite,reason='Dar acceso a Vista Hermosa conservando los demás roles')
    refreshed = await guild.fetch_channels()
    checks = [c for c in refreshed if c.id==category.id or c.category_id==category.id]
    for channel in checks:
        permission = channel.overwrites_for(role)
        if not all(getattr(permission,p) is True for p in ('view_channel','send_messages','read_message_history','connect','speak')):
            raise RuntimeError('Discord no confirmó todo el acceso de Vista Hermosa')
        log.info('VISTA_HERMOSA %s access_verified=%s channel=%s',request,channel.name,channel.id)
    current_role = next(r for r in await guild.fetch_roles() if r.id==role.id)
    if current_role.colour.value!=RED:
        raise RuntimeError('Discord no confirmó el rojo del rol')
    bot._vista_hermosa_request=request
    log.info('VISTA_HERMOSA %s complete role=%s name=%s color=#FF0000 channels=%s position=%s',
             request,role.id,current_role.name,len(checks),current_role.position)
