"""Explicit one-shot, read-only inspection of the owner's reference forum."""
import json
import logging
import os

import discord
from discord.http import Route

CHANNEL = 1556488595131466000
REQUEST = 'reportes-design-20261110-v1'
log = logging.getLogger('LaVenganzaRP.design')


async def inspect_channel_design(bot, guild_id):
    if os.getenv('CHANNEL_DESIGN_REQUEST_ID', '') != REQUEST or getattr(bot, '_design_survey_done', False):
        return
    raw = await bot.http.get_channel(CHANNEL)
    if int(raw.get('guild_id', 0)) != guild_id or raw['type'] != 15:
        raise ValueError('El canal de referencia no es el foro de La Venganza RP esperado.')
    fields = ('id','name','type','topic','flags','available_tags','default_forum_layout',
              'default_sort_order','default_reaction_emoji','rate_limit_per_user',
              'default_thread_rate_limit_per_user','default_auto_archive_duration')
    log.info('CHANNEL_DESIGN settings %s', json.dumps({k:raw.get(k) for k in fields}, ensure_ascii=False))
    active = await bot.http.request(Route('GET','/guilds/{guild_id}/threads/active',guild_id=guild_id))
    archived = await bot.http.request(Route('GET','/channels/{channel_id}/threads/archived/public',channel_id=CHANNEL),params={'limit':12})
    threads = {t['id']:t for t in active['threads'] if int(t['parent_id']) == CHANNEL}
    threads.update({t['id']:t for t in archived['threads'] if int(t['parent_id']) == CHANNEL})
    ordered = sorted(threads.values(),key=lambda t:(bool(t.get('flags',0)&2),int(t['id'])),reverse=True)
    for thread in ordered[:8]:
        summary = {k:thread.get(k) for k in ('id','name','applied_tags','flags','message_count','thread_metadata')}
        try:
            first = await bot.http.get_message(int(thread['id']),int(thread['id']))
            summary['starter'] = dict(content=first.get('content','')[:3000],
                embeds=first.get('embeds',[]),components=first.get('components',[]),
                attachments=[{k:a.get(k) for k in ('filename','url','content_type','width','height')} for a in first.get('attachments',[])])
        except discord.NotFound:
            summary['starter'] = 'Original eliminado; no se leyó la conversación.'
        log.info('CHANNEL_DESIGN post %s',json.dumps(summary,ensure_ascii=False))
    bot._design_survey_done = True
    log.info('CHANNEL_DESIGN complete channel=%s sampled=%s archived_more=%s discord_mutations=0',CHANNEL,min(len(ordered),8),archived.get('has_more'))
