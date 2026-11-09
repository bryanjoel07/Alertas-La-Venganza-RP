"""Apply requested high-priority channel fixes without changing player writing."""
import json
import logging
import os

import discord
from profiles_hub import normalized

log = logging.getLogger('LaVenganzaRP.fixes')


def citizen_overwrite(current, shop=False):
    overwrite = discord.PermissionOverwrite.from_pair(*current.pair())
    if shop:
        overwrite.view_channel = True
        overwrite.read_message_history = True
        overwrite.use_application_commands = True
    else:
        overwrite.mention_everyone = False
    return overwrite


async def fix_high_priorities(bot, guild_id):
    request = os.getenv('SERVER_FIX_REQUEST_ID', '').strip()
    if not request or getattr(bot, '_fixed_request', None) == request:
        return
    pending = False
    guild = bot.get_guild(guild_id)
    roles = await guild.fetch_roles()
    citizens = [r for r in roles if normalized(r.name).endswith('ciudadanos')]
    if len(citizens) != 1:
        raise ValueError('No encuentro un único rol Ciudadanos')
    citizens = citizens[0]
    me = await guild.fetch_member(bot.user.id)
    channels = await guild.fetch_channels()
    shop_id = bot.economy.store.config('shop_channel')
    for channel in channels:
        shop = str(channel.id) == shop_id
        mentions = normalized(channel.name) in ('anuncios', 'ayuda')
        if not shop and not mentions:
            continue
        before = channel.overwrites_for(citizens)
        after = citizen_overwrite(before, shop)
        try:
            if after != before:
                await channel.set_permissions(citizens, overwrite=after,
                    reason='Ajustes de prioridad alta autorizados; conservar escritura de Ciudadanos')
            refreshed = await bot.fetch_channel(channel.id)
            actual = refreshed.overwrites_for(citizens)
            log.info('SERVER_FIX %s %s', request, json.dumps(dict(
                channel=channel.name, id=str(channel.id), shop=shop, status='verified',
                send_before=before.send_messages,send_after=actual.send_messages,
                view=actual.view_channel,commands=actual.use_application_commands,
                everyone=actual.mention_everyone), ensure_ascii=False))
        except discord.Forbidden:
            pending = True
            log.warning('SERVER_FIX %s %s', request, json.dumps(dict(channel=channel.name,
                id=str(channel.id), status='blocked', reason='Missing channel Manage Permissions',
                bot_manage_roles=channel.permissions_for(me).manage_roles), ensure_ascii=False))
    log.info('SERVER_FIX %s %s', request, json.dumps(dict(
        capability='role_hierarchy', bot_role=me.top_role.name, bot_position=me.top_role.position,
        citizen_position=citizens.position, ready=me.top_role>citizens,
        reason='Discord prevents a bot from moving its highest role above itself'), ensure_ascii=False))
    log.info('SERVER_FIX %s %s', request, json.dumps(dict(
        capability='manage_nicknames', ready=me.guild_permissions.manage_nicknames,
        reason='An administrator must grant guild permissions the bot does not hold'), ensure_ascii=False))
    if me.top_role <= citizens or not me.guild_permissions.manage_nicknames:
        pending = True
    if not pending:
        bot._fixed_request = request
    log.info('SERVER_FIX %s %s', request, 'pending_admin_changes' if pending else 'complete')
