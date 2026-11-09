"""One-shot category organization with a durable rollback inventory."""
import json
import logging
import os
from pathlib import Path
import re

import discord
from profiles_hub import normalized

log = logging.getLogger('LaVenganzaRP.navegacion')
CATEGORY_ORDER = ('server','llegando','informacion','lavenganzarp','tickets','soporte','exclusivo',
                  'reclutamientostaff','negocios','policias','gangas','vistaalegre','vistahermosa',
                  'elcalenton','lasmonjas','staff','pagosjugadores','logs')
CHANNEL_ORDER = {
    'llegando': ('bienvenidas','guiadelbot','infoservidor','connect','pedirrol','despedidas'),
    'informacion': ('infoservidor','connect','serverup','alertasservidor','anuncios','updateserver','partners','serverboosters','sanciones'),
    'lavenganzarp': ('guiadelbot','general','perfiles','eventos','tiendaexclusive','pedirrol','sugerencias',
                    'fotos','clips','solicitarstreamer','streamers','lloraera','pedirmusica'),
    'tickets': ('tickets',),
    'soporte': ('ayuda','reportes','feedback','saladeespera','soporte1','soporte2','soporte3','soporte4','soporte5','ocupado'),
    'reclutamientostaff': ('informacionstaff','aplicarstaff','solicitudesstaff','entrevistasstaff','salaentrevista'),
    'staff': ('generalstaff','sanciones','ideas','comandos','admincommands','adcommandsnew','pedidosluyyo','pagoslogs'),
    'logs': ('logsdc','joinleavelogs','despedidas','registroexclusive'),
}

# Keep Perfiles and Tienda in La Venganza RP as explicitly requested.
REGROUP = {
    '1569173002200027136': 'llegando',       # Guía del bot
    '1528925322362228787': 'llegando',       # Información para entrar
    '1513421828415164546': 'llegando',       # Conexión
    '1513654622193979612': 'llegando',       # Pedir rol
    '1544076673392050256': 'logs',           # Despedidas (private)
    '1569084826324046028': 'logs',           # Registro de economía (private)
    '1539416259307774002': 'staff',          # Sanciones (private)
}


def regroup(channels):
    categories = {key(c['name']):c['id'] for c in channels if c['type']=='category'}
    present = {c['id'] for c in channels}
    if not set(REGROUP).issubset(present) or not set(REGROUP.values()).issubset(categories):
        raise ValueError('Falta un canal o categoría requerido para agrupar; no se aplicaron cambios')
    projected = []
    moves = {}
    for channel in channels:
        item = dict(channel)
        if channel['id'] in REGROUP:
            target = categories[REGROUP[channel['id']]]
            if channel['parent']!=target:
                moves[channel['id']] = target
                item['parent'] = target
        projected.append(item)
    return projected,moves


def key(name):
    # Decompose accents after converting Discord's styled letters to plain text.
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD',normalized(name)) if not unicodedata.combining(c))


def plan(channels):
    categories = sorted((c for c in channels if c['type']=='category'),key=lambda c:(c['position'],c['id']))
    ranks = {name:n for n,name in enumerate(CATEGORY_ORDER)}
    categories.sort(key=lambda c:(key(c['name'])=='logs',ranks.get(key(c['name']),len(ranks)),c['position'],c['id']))
    category_ranks = {c['id']:n for n,c in enumerate(categories)}
    category_names = {c['id']:key(c['name']) for c in categories}
    payload = [dict(id=c['id'],position=n) for n,c in enumerate(categories)]
    buckets = sorted({c['bucket'] for c in channels if c['type']!='category'})
    for bucket in buckets:
        group = [c for c in channels if c['type']!='category' and c['bucket']==bucket]
        def order(c):
            names = CHANNEL_ORDER.get(category_names.get(c['parent'],''),())
            rank = names.index(key(c['name'])) if key(c['name']) in names else len(names)
            return category_ranks.get(c['parent'],-1),rank,c['position'],c['id']
        group.sort(key=order)
        payload.extend(dict(id=c['id'],position=n) for n,c in enumerate(group))
    return payload


def inventory(channels):
    return [dict(id=str(c.id),name=c.name,type=str(c.type),parent=str(c.category_id) if c.category_id else None,
                 position=c.position,bucket=c._sorting_bucket,
                 overwrites=sorted((str(target.id),value.pair()[0].value,value.pair()[1].value)
                                   for target,value in c.overwrites.items())) for c in channels]


def protected_state(items):
    return {c['id']:(c['name'],c['type'],c['parent'],c['overwrites']) for c in items}


async def apply_layout(http,guild_id,positions):
    reason = 'Organizar categorías y canales: SERVER abre, Logs cierra; conservar permisos sin sincronizar'
    order = [dict(id=item['id'],position=item['position']) for item in positions]
    # Discord allows only one parent_id change per bulk request (error 40009).
    await http.bulk_channel_update(guild_id,order,reason=reason)
    moves = [item for item in positions if 'parent_id' in item]
    blocked = []
    for item in moves:
        try:
            await http.bulk_channel_update(guild_id,[item],reason=reason)
        except discord.Forbidden:
            blocked.append(item['id'])
            log.warning('NAVIGATION blocked_channel=%s destination=%s reason=MissingAccess',item['id'],item['parent_id'])
    if moves:
        await http.bulk_channel_update(guild_id,order,reason=reason)
    return blocked


async def arrange_navigation(bot,guild_id,path):
    request = os.getenv('NAVIGATION_REQUEST_ID','').strip()
    if not request or getattr(bot,'_navigation_request',None)==request:
        return
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):
        raise ValueError('Identificador de ordenación no válido')
    guild = bot.get_guild(guild_id)
    fresh = await guild.fetch_channels()
    before = inventory(fresh)
    folder = Path(path).resolve().parent/'navigation'
    folder.mkdir(exist_ok=True)
    snapshot = folder/f'{request}-before.json'
    if not snapshot.exists():
        temp = snapshot.with_suffix('.tmp')
        temp.write_text(json.dumps(before,ensure_ascii=False,indent=2))
        temp.replace(snapshot)
    projected,moves = regroup(before) if os.getenv('NAVIGATION_REGROUP')=='1' else (before,{})
    positions = plan(projected)
    for item in positions:
        if item['id'] in moves:
            item.update(parent_id=moves[item['id']],lock_permissions=False)
    # The same request may run again after a restart; do not overwrite its rollback snapshot.
    target = {item['id']:item['position'] for item in positions}
    blocked = []
    if moves or any(c['position']!=target[c['id']] for c in before):
        blocked = await apply_layout(bot.http,guild.id,positions)
        if blocked:
            old_parents = {c['id']:c['parent'] for c in before}
            for channel in projected:
                if channel['id'] in blocked:
                    channel['parent'] = old_parents[channel['id']]
                    moves.pop(channel['id'],None)
            positions = plan(projected)
            target = {item['id']:item['position'] for item in positions}
            await apply_layout(bot.http,guild.id,positions)
    after = inventory(await guild.fetch_channels())
    if protected_state(projected)!=protected_state(after):
        raise RuntimeError('Cambió la estructura o los permisos durante la ordenación; revisar antes de continuar')
    for bucket in {c['bucket'] for c in before}:
        expected = sorted((c for c in before if c['bucket']==bucket),key=lambda c:target[c['id']])
        actual = sorted((c for c in after if c['bucket']==bucket),key=lambda c:(c['position'],c['id']))
        if [c['id'] for c in expected]!=[c['id'] for c in actual]:
            raise RuntimeError('Discord no confirmó el orden de canales solicitado')
    bot._navigation_request = request
    if os.getenv('NAVIGATION_REGROUP')=='1':
        parents = {c['id']:c['parent'] for c in after}
        bot.economy.store.runtime_config('guide_category',parents['1569173002200027136'])
        bot.economy.store.runtime_config('audit_category',parents['1569084826324046028'])
    for channel in before:
        if channel['id'] in moves:
            log.info('NAVIGATION %s moved=%s from=%s to=%s permissions_unchanged=True',
                     request,channel['name'],channel['parent'],moves[channel['id']])
    for c in sorted((c for c in after if c['type']=='category'),key=lambda c:c['position']):
        children = sorted((v for v in after if v['parent']==c['id']),key=lambda v:(v['bucket'],v['position']))
        log.info('NAVIGATION %s category=%s position=%s channels=%s',request,c['name'],c['position'],
                 json.dumps([v['name'] for v in children],ensure_ascii=False))
    for channel in after:
        if channel['id'] in REGROUP and os.getenv('NAVIGATION_REGROUP')=='1':
            log.info('NAVIGATION %s assignment=%s parent=%s blocked=%s',request,channel['name'],channel['parent'],channel['id'] in blocked)
    log.info('NAVIGATION %s verified channels=%s permissions_unchanged=True blocked=%s snapshot=%s',request,len(after),blocked,snapshot.name)
