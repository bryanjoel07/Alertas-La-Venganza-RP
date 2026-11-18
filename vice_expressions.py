"""Additional original coquí memes and animated district expressions."""
import logging

from vice_design import ASSETS, BOT_ID, GUILD_ID

log = logging.getLogger('ViceDistrict.expressions')
EXPRESSIONS_VERSION = 'vice-expressions-expanded-v2'
STATIC_EMOJIS = ('vd_coqui_risa', 'vd_coqui_llora', 'vd_coqui_sus',
                 'vd_coqui_shock', 'vd_coqui_facepalm', 'vd_coqui_chill')
ANIMATED_EMOJIS = ('vd_vi_neon', 'vd_wepa', 'vd_alerta', 'vd_cargando', 'vd_hype', 'vd_rip')
MASCOT_ANIMATED_EMOJIS = ('vd_coqui_fiesta', 'vd_coqui_carcajada', 'vd_coqui_llanto',
                         'vd_coqui_rabia', 'vd_coqui_amor', 'vd_coqui_saludo')
HYPE_ANIMATED_EMOJIS = ('vd_pr_onda', 'vd_duro', 'vd_gg_brillo',
                       'vd_corona', 'vd_drift', 'vd_boom')
ALL_ANIMATED_EMOJIS = ANIMATED_EMOJIS + MASCOT_ANIMATED_EMOJIS + HYPE_ANIMATED_EMOJIS
EMOJI_PACKS = ((False, STATIC_EMOJIS, 'emojis-v2/static', '.png'),
               (True, ANIMATED_EMOJIS, 'emojis-v2/animated', '.gif'),
               (True, MASCOT_ANIMATED_EMOJIS, 'emojis-v3/mascot', '.gif'),
               (True, HYPE_ANIMATED_EMOJIS, 'emojis-v3/hype', '.gif'))


async def install_expansion(system):
    guild = system.bot.get_guild(GUILD_ID)
    system.validate_guild(guild)
    if system.store.get('emoji_expansion_release') == EXPRESSIONS_VERSION:
        return
    existing = list(await guild.fetch_emojis())
    assets = []
    pending = {False: 0, True: 0}
    for animated, names, folder, extension in EMOJI_PACKS:
        for name in names:
            emoji = next((e for e in existing if e.id == system.store.get('emoji:' + name)
                or (e.name == name and e.user and e.user.id == BOT_ID)), None)
            if emoji and emoji.animated != animated:
                raise ValueError('El formato del emoji registrado necesita revisión: ' + name)
            data = (ASSETS / folder / (name + extension)).read_bytes()
            if len(data) > 256 * 1024 or (animated and not data.startswith((b'GIF87a', b'GIF89a'))):
                raise ValueError('Formato o tamaño de emoji no válido: ' + name)
            if not animated and not data.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('El emoji estático debe ser PNG: ' + name)
            assets.append((name, data, emoji))
            pending[animated] += emoji is None
    for animated, count in pending.items():
        if sum(e.animated == animated for e in existing) + count > guild.emoji_limit:
            raise ValueError('No hay suficientes espacios de emojis para esta ampliación.')
    async def snapshot():
        return dict(guild=guild.id, emojis=[dict(id=e.id, name=e.name, animated=e.animated,
            roles=[role.id for role in e.roles]) for e in await guild.fetch_emojis()])
    async def apply():
        for name, data, emoji in assets:
            if emoji is None:
                emoji = await guild.create_custom_emoji(name=name, image=data, roles=[],
                    reason='Más emojis exclusivos, memes y animaciones solicitados por el propietario')
            await system.call('put', 'emoji:' + name, emoji.id)
    await system.track('EXPRESSIONS_EXPAND', 'Añadir memes de coquí y emojis animados',
                       apply, EXPRESSIONS_VERSION, snapshot=snapshot)
    await system.call('put', 'emoji_expansion_release', EXPRESSIONS_VERSION)
    log.info('VICE_EXPRESSIONS_EXPANDED static=%s animated=%s added=%s',
             len(STATIC_EMOJIS), len(ALL_ANIMATED_EMOJIS), sum(pending.values()))
