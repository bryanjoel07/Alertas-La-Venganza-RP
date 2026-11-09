"""Opt-in read-only server audit; logs metadata, never message contents or secrets."""
import asyncio
from contextlib import closing
import json
import logging
import os
from pathlib import Path
import sqlite3

import discord
from backup_meta import read_backup
from diagnostics import read_database, task_state
from navigation import key

log = logging.getLogger('LaVenganzaRP.audit')


def database_summary(path):
    result = read_database(path)
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {}
        for table in ('events', 'registrations', 'meetings', 'streamer_profiles', 'streamer_requests',
                      'eco_accounts', 'eco_purchases', 'eco_products', 'eco_sync', 'eco_rewards'):
            if table in tables:
                counts[table] = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        result['counts'] = counts
        for table in ('events', 'meetings', 'eco_purchases'):
            if table in tables:
                result[table + '_status'] = dict(db.execute(f'SELECT status,COUNT(*) FROM {table} GROUP BY status'))
        if 'eco_accounts' in tables:
            result['economy_totals'] = db.execute('SELECT COALESCE(SUM(balance),0),COALESCE(MAX(balance),0) FROM eco_accounts').fetchone()
        if 'eco_products' in tables:
            result['products'] = dict(db.execute('SELECT kind,COUNT(*) FROM eco_products WHERE active=1 GROUP BY kind'))
    return result


def emit(request, section, value):
    log.info('SERVER_AUDIT %s %s %s', request, section, json.dumps(value, ensure_ascii=False, default=str))


async def audit_server(bot, guild_id, path):
    request = os.getenv('SERVER_AUDIT_REQUEST_ID', '').strip()
    if not request or getattr(bot, '_audited_request', None) == request:
        return
    bot._audited_request = request
    await asyncio.sleep(5)
    guild = bot.get_guild(guild_id)
    if guild is None:
        raise ValueError('No encuentro el servidor solicitado')
    channels = await guild.fetch_channels()
    roles = await guild.fetch_roles()
    citizens = next((r for r in roles if key(r.name)=='ciudadanos'),None)
    if citizens:
        essentials = {'bienvenidas','infoservidor','connect','guiadelbot','general','perfiles',
                      'tiendaexclusive','ayuda','tickets','solicitarstreamer','eventos'}
        for channel in channels:
            if key(channel.name) in essentials and not isinstance(channel,discord.CategoryChannel):
                permissions = channel.permissions_for(citizens)
                emit(request,'new_player',dict(channel=channel.name,id=str(channel.id),
                     category=getattr(channel.category,'name',None),position=channel.position,
                     view=permissions.view_channel,history=permissions.read_message_history,
                     write=permissions.send_messages,commands=permissions.use_application_commands))
        guide_id = bot.economy.store.config('guide_channel')
        guide_message = bot.economy.store.config('guide_message')
        guide = next((c for c in channels if str(c.id)==guide_id),None)
        if guide and guide_message:
            message = await guide.fetch_message(int(guide_message))
            for row in message.components:
                for button in row.children:
                    url = getattr(button,'url',None)
                    target = next((c for c in channels if url and url.rstrip('/').endswith('/'+str(c.id))),None)
                    emit(request,'new_player_link',dict(label=getattr(button,'label',None),url=url,
                         target_exists=target is not None,
                         target_visible=target.permissions_for(citizens).view_channel if target else False))
    me = await guild.fetch_member(bot.user.id)
    emit(request, 'guild', dict(name=guild.name, members=guild.member_count,
         cached_members=len(guild.members), verification=str(guild.verification_level),
         content_filter=str(guild.explicit_content_filter), mfa_level=guild.mfa_level,
         features=guild.features, bot_permissions=[k for k,v in me.guild_permissions if v],
         highest_bot_role=me.top_role.name, role_count=len(roles), channel_count=len(channels)))
    for channel in sorted(channels, key=lambda c:(getattr(c,'category_id',0) or 0,c.position)):
        permissions = channel.permissions_for(me)
        public = channel.permissions_for(guild.default_role)
        selected = ('view_channel','send_messages','use_application_commands','manage_channels',
                    'manage_roles','manage_messages','embed_links','attach_files','read_message_history',
                    'mention_everyone','connect','speak','send_messages_in_threads')
        role_exceptions = [dict(role=target.name, send=value.send_messages, view=value.view_channel,
                               everyone=value.mention_everyone, commands=value.use_application_commands)
                           for target,value in channel.overwrites.items() if isinstance(target,discord.Role)]
        emit(request, 'channel', dict(id=channel.id,name=channel.name,type=str(channel.type),
             category=getattr(channel.category,'name',None),category_id=getattr(channel,'category_id',None),
             bot={k:getattr(permissions,k) for k in selected},
             public={k:getattr(public,k) for k in ('view_channel','send_messages','use_application_commands','mention_everyone','send_messages_in_threads')},
             role_overwrites=role_exceptions))
    for role in roles:
        elevated = [p for p in ('administrator','manage_guild','manage_roles','manage_channels','ban_members','kick_members','mention_everyone') if getattr(role.permissions,p)]
        if elevated or role.managed:
            emit(request,'role',dict(name=role.name,managed=role.managed,position=role.position,
                                    above_bot=role>=me.top_role,permissions=elevated))
    commands = await bot.tree.fetch_commands(guild=discord.Object(id=guild_id))
    emit(request,'commands',[dict(name=c.name,default_permissions=c.default_member_permissions.value if c.default_member_permissions else None) for c in commands])
    try:
        rules = await guild.fetch_automod_rules()
        emit(request,'automod',[dict(name=r.name,enabled=r.enabled,trigger=str(r.trigger.type),actions=[str(a.type) for a in r.actions]) for r in rules])
    except discord.Forbidden:
        emit(request,'automod',dict(error='No permission to inspect rules'))
    emit(request,'database',await asyncio.to_thread(database_summary,path))
    emit(request,'backup',await asyncio.to_thread(read_backup,path))
    emit(request,'backup_automation',await bot.backups.describe())
    emit(request,'tasks',dict(monitor=task_state(bot.monitor_task),meetings=task_state(bot.meetings.task),
         events=task_state(bot.event_features.task),economy=task_state(bot.economy.task),
         sources=getattr(bot,'monitor_sources',None),economy_error=bot.economy.last_error))
    emit(request,'economy_config',{k:bot.economy.store.config(k) for k in ('category','voice_category','shop_channel','audit_channel','profiles_channel','admin_role')})
    emit(request,'complete',True)
