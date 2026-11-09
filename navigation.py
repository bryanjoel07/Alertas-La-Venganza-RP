"""One-shot position-only navigation changes with a durable rollback inventory."""
import json
import logging
import os
from pathlib import Path
import re

import discord
from profiles_hub import normalized

log = logging.getLogger('LaVenganzaRP.navegacion')
CATEGORY_ORDER = ('llegando','informacion','lavenganzarp','tickets','soporte','exclusivo',
                  'reclutamientostaff','negocios','policias','gangas','vistaalegre','vistahermosa',
                  'elcalenton','lasmonjas','staff','pagosjugadores','server','logs')
CHANNEL_ORDER = {
    'llegando': ('bienvenidas','despedidas'),
    'informacion': ('infoservidor','connect','serverup','alertasservidor','anuncios','updateserver','partners','serverboosters','sanciones'),
    'lavenganzarp': ('guiadelbot','general','perfiles','eventos','tiendaexclusive','pedirrol','sugerencias',
                    'fotos','clips','solicitarstreamer','streamers','lloraera','pedirmusica'),
    'tickets': ('tickets',),
    'soporte': ('ayuda','reportes','feedback','saladeespera','soporte1','soporte2','soporte3','soporte4','soporte5','ocupado'),
    'reclutamientostaff': ('informacionstaff','aplicarstaff','solicitudesstaff','entrevistasstaff','salaentrevista'),
}


def key(name):
    # Decompose accents after converting Discord's styled letters to plain text.
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD',normalized(name)) if not unicodedata.combining(c))


def plan(channels):
    categories = sorted((c for c in channels if c['type']=='category'),key=lambda c:(c['position'],c['id']))
    ranks = {name:n for n,name in enumerate(CATEGORY_ORDER)}
    categories.sort(key=lambda c:(ranks.get(key(c['name']),len(ranks)),c['position'],c['id']))
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


async def arrange_navigation(bot,guild_id,path):
    request = os.getenv('NAVIGATION_REQUEST_ID','').strip()
    if not request or getattr(bot,'_navigation_request',None)==request:
        return
    if not re.fullmatch('[A-Za-z0-9_-]{1,100}',request):
        raise ValueError('Identificador de ordenación no válido')
    guild = bot.get_guild(guild_id)
    fresh = await guild.fetch_channels()
    before = inventory(fresh)
    positions = plan(before)
    folder = Path(path).resolve().parent/'navigation'
    folder.mkdir(exist_ok=True)
    snapshot = folder/f'{request}-before.json'
    if not snapshot.exists():
        temp = snapshot.with_suffix('.tmp')
        temp.write_text(json.dumps(before,ensure_ascii=False,indent=2))
        temp.replace(snapshot)
    # The same request may run again after a restart; do not overwrite its rollback snapshot.
    target = {item['id']:item['position'] for item in positions}
    if any(c['position']!=target[c['id']] for c in before):
        await bot.http.bulk_channel_update(guild.id,positions,
            reason='Orden de navegación solicitado: entrada, información, comunidad y soporte; conservar permisos')
    after = inventory(await guild.fetch_channels())
    if protected_state(before)!=protected_state(after):
        raise RuntimeError('Cambió la estructura o los permisos durante la ordenación; revisar antes de continuar')
    for bucket in {c['bucket'] for c in before}:
        expected = sorted((c for c in before if c['bucket']==bucket),key=lambda c:target[c['id']])
        actual = sorted((c for c in after if c['bucket']==bucket),key=lambda c:(c['position'],c['id']))
        if [c['id'] for c in expected]!=[c['id'] for c in actual]:
            raise RuntimeError('Discord no confirmó el orden de canales solicitado')
    bot._navigation_request = request
    for c in sorted((c for c in after if c['type']=='category'),key=lambda c:c['position']):
        children = sorted((v for v in after if v['parent']==c['id']),key=lambda v:(v['bucket'],v['position']))
        log.info('NAVIGATION %s category=%s position=%s channels=%s',request,c['name'],c['position'],
                 json.dumps([v['name'] for v in children],ensure_ascii=False))
    log.info('NAVIGATION %s verified channels=%s permissions_unchanged=True snapshot=%s',request,len(after),snapshot.name)
