"""One-shot category organization with a durable rollback inventory."""
import json
import logging
import os
from pathlib import Path
import re

import discord
from profiles_hub import normalized

log = logging.getLogger('LaVenganzaRP.navegacion')
CATEGORY_ORDER = ('server','llegando','informacion','lavenganzarp','multimedia','tickets','soporte','exclusivo',
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
    'multimedia': ('fotos','clips','solicitarstreamer','streamers','pedirmusica','musica'),
}

# Keep Perfiles and Tienda in La Venganza RP as explicitly requested.
REGROUP = {
    '1513422142014754976': 'lavenganzarp',   # Fotos stays in the original community category
    '1569173002200027136': 'llegando',       # Guía del bot
    '1528925322362228787': 'llegando',       # Información para entrar
    '1513421828415164546': 'llegando',       # Conexión
    '1513654622193979612': 'llegando',       # Pedir rol
    '1544076673392050256': 'logs',           # Despedidas (private)
    '1569084826324046028': 'logs',           # Registro de economía (private)
    '1539416259307774002': 'staff',          # Sanciones (private)
}
MEDIA_CHANNELS = {
    '1567382176121487421': 'multimedia',     # Clips
    '1568403146219454586': 'multimedia',     # Solicitar Streamer
    '1513653533340073994': 'multimedia',     # Streamers
    '1567661643129954344': 'multimedia',     # Pedir música
    '1567661450032451624': 'multimedia',     # Música (voz)
}
MEDIA_NAME = '│・ 🎬┊ 𝐌𝐮𝐥𝐭𝐢𝐦𝐞𝐝𝐢𝐚'


def regroup(channels,include_media=False):
    rules = {**REGROUP,**MEDIA_CHANNELS} if include_media else REGROUP
    categories = {key(c['name']):c['id'] for c in channels if c['type']=='category'}
    present = {c['id'] for c in channels}
    if not set(rules).issubset(present) or not set(rules.values()).issubset(categories):
        raise ValueError('Falta un canal o categoría requerido para agrupar; no se aplicaron cambios')
    projected = []
    moves = {}
    for channel in channels:
        item = dict(channel)
        if channel['id'] in rules:
            target = categories[rules[channel['id']]]
            if channel['parent']!=target:
                moves[channel['id']] = target
                item['parent'] = target
        projected.append(item)
    return projected,moves


def styled_channel_name(channel):
    import unicodedata
    if str(channel.type)=='category' or '┊' not in channel.name:
        return channel.name
    emoji,label = channel.name.split('┊',1)
    overrides = {'1425183472150118631':'Updates-EFLS','1300621178523619339':'Game-Rules'}
    label = overrides.get(str(channel.id),unicodedata.normalize('NFKC',label.strip()))
    result = []
    for c in unicodedata.normalize('NFD',label):
        if 'A'<=c<='Z':
            c = chr(0x1D400+ord(c)-ord('A'))
        elif 'a'<=c<='z':
            c = chr(0x1D41A+ord(c)-ord('a'))
        elif '0'<=c<='9':
            c = chr(0x1D7CE+ord(c)-ord('0'))
        result.append(c)
    name = emoji.strip()+'┊'+''.join(result)
    return name if len(name)<=100 else channel.name


async def prepare_full_organization(bot,guild,channels,request):
    me = await guild.fetch_member(bot.user.id)
    log.info('ORGANIZATION %s administrator=%s',request,me.guild_permissions.administrator)
    if not me.guild_permissions.administrator:
        raise ValueError('Discord todavía no refleja Administrador en el bot; no se cambiaron categorías')
    main_id = bot.economy.store.config('category')
    main = next((c for c in channels if str(c.id)==main_id),None)
    candidates = [c for c in channels if isinstance(c,discord.CategoryChannel) and key(c.name)=='multimedia']
    if main is None or len(candidates)>1:
        raise ValueError('No encuentro un destino único para la organización')
    media = candidates[0] if candidates else await guild.create_category(
        MEDIA_NAME,overwrites=main.overwrites,reason='Agrupar Clips, Streamers y Música; Fotos conserva su categoría original')
    bot.economy.store.runtime_config('multimedia_category',media.id)
    log.info('ORGANIZATION %s multimedia_category=%s name=%s',request,media.id,media.name)
    for channel in channels:
        name = styled_channel_name(channel)
        if name!=channel.name:
            await channel.edit(name=name,reason='Uniformar emoji, separador y letras sin cambiar permisos')
            log.info('ORGANIZATION %s renamed=%s old=%s new=%s',request,channel.id,channel.name,name)
    return await guild.fetch_channels()


async def review_repeated_channels(channels,request):
    groups = {}
    for channel in channels:
        if isinstance(channel,discord.CategoryChannel):
            continue
        groups.setdefault((channel.category_id,key(channel.name),channel._sorting_bucket),[]).append(str(channel.id))
        if key(channel.name) in ('comandos','admincommands','adcommandsnew'):
            try:
                messages = [m async for m in channel.history(limit=20)]
                log.info('ORGANIZATION %s command_review=%s id=%s sample=%s latest=%s oldest_sample=%s',
                    request,channel.name,channel.id,len(messages),
                    messages[0].created_at.isoformat() if messages else None,
                    messages[-1].created_at.isoformat() if messages else None)
            except discord.Forbidden:
                log.warning('ORGANIZATION %s command_review_blocked=%s',request,channel.id)
    duplicates = [dict(category=str(k[0]),name=k[1],ids=ids) for k,ids in groups.items() if len(ids)>1]
    log.info('ORGANIZATION %s same_category_duplicates=%s',request,json.dumps(duplicates))


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
                 overwrites=sorted((str(value.id),value.type,value.allow,value.deny)
                                   for value in c._overwrites)) for c in channels]


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
    full = os.getenv('NAVIGATION_FULL_ORGANIZE')=='1'
    original = before
    if full:
        fresh = await prepare_full_organization(bot,guild,fresh,request)
        before = inventory(fresh)
    grouping = os.getenv('NAVIGATION_REGROUP')=='1' or full
    projected,moves = regroup(before,include_media=full) if grouping else (before,{})
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
    after_by_id = {c['id']:c for c in after}
    if any(c['id'] not in after_by_id or c['overwrites']!=after_by_id[c['id']]['overwrites'] for c in original):
        raise RuntimeError('No se conservaron los permisos de todos los canales originales')
    for bucket in {c['bucket'] for c in before}:
        expected = sorted((c for c in before if c['bucket']==bucket),key=lambda c:target[c['id']])
        actual = sorted((c for c in after if c['bucket']==bucket),key=lambda c:(c['position'],c['id']))
        if [c['id'] for c in expected]!=[c['id'] for c in actual]:
            raise RuntimeError('Discord no confirmó el orden de canales solicitado')
    bot._navigation_request = request
    if grouping:
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
        if channel['id'] in (REGROUP.keys() | (MEDIA_CHANNELS.keys() if full else set())) and grouping:
            log.info('NAVIGATION %s assignment=%s parent=%s blocked=%s',request,channel['name'],channel['parent'],channel['id'] in blocked)
    log.info('NAVIGATION %s verified channels=%s permissions_unchanged=True blocked=%s snapshot=%s',request,len(after),blocked,snapshot.name)
    if full:
        await review_repeated_channels(await guild.fetch_channels(),request)
