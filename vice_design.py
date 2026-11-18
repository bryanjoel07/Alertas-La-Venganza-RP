"""The owner's GTA VI community design; never used by the Studio storefront."""
from pathlib import Path

GUILD_ID = 1572462544302383164
BOT_ID = 1571639486591402174
OWNER_ID = 1509288420852109383
VERSION = 'vice-district-community-v1'
ASSETS = Path(__file__).parent / 'assets' / 'vice-district'
FONTS = Path(__file__).parent / 'assets' / 'esschino' / 'fonts'
PINK, CYAN, CORAL = 0xFF168A, 0x00D9E8, 0xFF795D
DESCRIPTION = ('Tu punto de encuentro latino para GTA VI. Noticias con fuentes, teorías, clips, '
               'ayuda y crews de toda Latinoamérica. Comparte tu pasión por Vice City y encuentra '
               'gente con quien jugar. Comunidad de fans no oficial.')

# Keys, display names, color, permission flags, display separately, old name.
ROLES = [
    ('mod', '🛡️ Moderación', PINK, dict(manage_messages=True, manage_threads=True,
        moderate_members=True, kick_members=True, mute_members=True, deafen_members=True,
        move_members=True, view_audit_log=True), True, 'Moderación'),
    ('support', '🛟 Soporte', 0x38CFAE, {}, True, None),
    ('creator', '🎬 Creadores', 0xB87AFF, {}, True, 'Creadores'),
    ('crew', '🤝 Crew', CYAN, {}, False, 'Crew'),
    ('member', '🌴 Comunidad', 0xFFFBEA, {}, True, 'Comunidad'),
    ('ps', '🎮 PlayStation', 0x6C9FFF, {}, False, None),
    ('xbox', '🎮 Xbox', 0x58C66A, {}, False, None),
    ('pc', '💻 PC', 0xAC90F5, {}, False, None),
    ('mexico', '🇲🇽 México', 0x54BCAB, {}, False, None),
    ('central', '🌋 Centroamérica', 0x54BCAB, {}, False, None),
    ('caribbean', '🌴 Caribe', 0x54BCAB, {}, False, None),
    ('south', '🌎 Sudamérica', 0x54BCAB, {}, False, None),
    ('north', '🌎 Norteamérica', 0x54BCAB, {}, False, None),
    ('europe', '🌍 España / Europa', 0x54BCAB, {}, False, None),
    ('news', '📰 Avisos de GTA VI', 0xFFB36A, {}, False, None),
    ('events', '🎉 Avisos de eventos', 0xFF8EBE, {}, False, None),
]
GROUPS = {
    'platform': ('Tus plataformas', ['ps', 'xbox', 'pc'], 3),
    'region': ('Tu región · opcional', ['mexico', 'central', 'caribbean', 'south', 'north', 'europe'], 1),
    'interests': ('Tus avisos y tu crew', ['news', 'events', 'crew'], 3),
}
SELF_ROLES = frozenset(key for _, keys, _ in GROUPS.values() for key in keys)
CATEGORIES = [
    ('info', '🌴 EMPIEZA AQUÍ', 'read'),
    ('community', '🌆 COMUNIDAD', 'chat'),
    ('game', '🎮 UNIVERSO GTA VI', 'chat'),
    ('voice', '🔊 VICE RADIO', 'chat'),
    ('help', '🛟 SOPORTE', 'read'),
    ('team', '🛠 EQUIPO', 'staff'),
]
# key, category, name, topic, policy, voice, slowmode/user limit
CHANNELS = [
    ('welcome','info','👋・bienvenida','Tu llegada a VIce District. Lee las normas, elige tus roles y conoce a la comunidad.','read',False,0),
    ('rules','info','📜・normas','Convivencia, privacidad, spoilers y juego limpio.','read',False,0),
    ('roles','info','🎭・elige-tus-roles','Personaliza tu perfil: plataformas, región y avisos. Puedes cambiar tus elecciones cuando quieras.','read',False,0),
    ('announcements','info','📢・anuncios','Comunicados de la comunidad y novedades del servidor.','read',False,0),
    ('general','community','💬・general','La avenida principal: charla con la comunidad, comparte ideas y disfruta del ambiente.','chat',False,5),
    ('introductions','community','🙌・presentaciones','Cuéntanos tu apodo, región, plataformas y tu GTA favorito. No publiques datos personales.','chat',False,10),
    ('clips','community','📸・clips-y-capturas','Tus mejores momentos de GTA. Da crédito, marca spoilers y evita contenido gráfico.','chat',False,15),
    ('memes','community','😂・memes','Humor y memes de GTA con respeto. Sin spam ni ataques personales.','chat',False,10),
    ('suggestions','community','💡・sugerencias','Una idea por mensaje: propuesta, beneficio y ejemplo. Opina con respeto.','chat',False,30),
    ('news','game','📰・noticias','Noticias con fuentes verificables. Los rumores se comentan en teorías.','read',False,0),
    ('theories','game','🔎・teorías','Analiza pistas y comparte teorías. Distingue especulación de hechos y oculta spoilers.','chat',False,10),
    ('guides','game','🧭・guías-y-ayuda','Dudas sobre GTA y ayuda entre jugadores. Explica tu plataforma y lo que ya probaste.','chat',False,5),
    ('crew','game','🤝・busca-crew','Encuentra gente afín: plataforma, zona horaria, horario y estilo de juego.','chat',False,30),
    ('events','game','🎉・eventos','Quedadas, retos y actividades de la comunidad. Horarios y requisitos en cada convocatoria.','read',False,0),
    ('lobby','voice','🌴 Lobby',None,'chat',True,0),
    ('voice1','voice','🚗 Crew 01',None,'chat',True,6),
    ('voice2','voice','🌇 Crew 02',None,'chat',True,6),
    ('support','help','🎫・soporte','Abre un ticket privado para ayuda del servidor o reportes al equipo.','read',False,0),
    ('staff','team','👥・chat-staff','Coordinación privada de Fundador, Moderación y Soporte.','staff',False,0),
    ('log','team','📋・registro-staff','Resumen privado de la instalación y actividad de soporte.','staffread',False,0),
    ('staffvoice','team','🛠 Sala del equipo',None,'staff',True,0),
]

def panel_copy(key, c):
    ref = lambda k: f'<#{c(k)}>'
    panels = {
        'welcome': ('🌴 BIENVENIDO A VICE DISTRICT',
            '**GTA VI Latino · Tu próxima crew empieza aquí.**\n\n'
            'Atardeceres, motores y una comunidad con la que compartir la pasión por GTA. '
            'Ponte cómodo: ya estás en el distrito.\n\n'
            f'**01 · Conoce el barrio**\nLee {ref("rules")} y pulsa **Unirme a la comunidad**.\n\n'
            f'**02 · Dale tu estilo**\nElige plataformas, región y avisos en {ref("roles")}.\n\n'
            f'**03 · Encuentra tu gente**\nPreséntate en {ref("introductions")} y pásate por {ref("general")}.', PINK),
        'rules': ('📜 EL CÓDIGO DEL DISTRITO',
            '**Un buen ambiente lo construimos entre todos.**\n\n'
            '**1 · Respeto primero.** Sin acoso, discriminación, amenazas ni ataques personales.\n'
            '**2 · Cero spam y estafas.** Publicidad solo con permiso del equipo. No piratería, trampas ni enlaces engañosos.\n'
            '**3 · Cuida la privacidad.** No publiques datos personales, conversaciones privadas o imágenes ajenas sin permiso.\n'
            '**4 · Comparte con criterio.** Nada de contenido sexual explícito o violencia gráfica.\n'
            '**5 · Respeta los spoilers.** Usa `||texto||` y marca los archivos con spoilers. Señala claramente los rumores.\n'
            '**6 · Cada cosa en su canal.** Evita menciones masivas, discusiones repetidas y ruido excesivo en voz.\n'
            '**7 · Juego limpio y moderación.** Sigue las normas de Discord y las indicaciones del equipo. '
            'El equipo puede retirar contenido, aplicar tiempos de espera o expulsar según la gravedad.\n\n'
            f'**¿Necesitas reportar algo?** Abre un ticket en {ref("support")}; evita confrontaciones públicas.', CORAL),
        'roles': ('🎭 TU IDENTIDAD EN EL DISTRITO',
            '**Tu comunidad, a tu manera.**\n\n'
            '🎮 **Plataformas:** elige todas las que usas.\n'
            '🌎 **Región:** una opción, totalmente voluntaria.\n'
            '🔔 **Intereses:** avisos de GTA VI, eventos y búsqueda de crew.\n\n'
            'Cada menú reemplaza solo las opciones de su grupo. Déjalo vacío para retirarlas. '
            'Puedes volver cuando quieras.\n\n'
            '**Equipo:** Fundador, Moderación y Soporte.\n'
            '**Comunidad:** Creadores, Crew y Comunidad. Los roles del equipo y Creadores los asigna la administración.', CYAN),
        'announcements': ('📢 LA VOZ DEL DISTRITO',
            'Aquí encontrarás los comunicados de **GTA VI Latino | VIce District**: cambios, novedades y avisos importantes.\n\n'
            f'Activa solo los avisos que te interesen en {ref("roles")}. Las sugerencias van en {ref("suggestions")}.', PINK),
        'introductions': ('🙌 PRESENTA TU ESTILO',
            '**Rompe el hielo con esta pequeña ficha:**\n\n'
            '🌴 **Apodo:**\n🌎 **Región / zona horaria:** (opcional)\n🎮 **Plataformas:**\n'
            '🚗 **Mi GTA favorito:**\n🤝 **Busco:** charla, clips, crew o conocer gente.\n\n'
            'Comparte solo lo que te haga sentir cómodo. ¡Bienvenido al barrio!', CYAN),
        'news': ('📰 EL RADAR DE GTA VI',
            '**Información con contexto y fuentes.**\n\n'
            'Cada noticia debe incluir la fuente original y su fecha. Las novedades confirmadas se distinguirán '
            f'de la especulación. Para rumores, pistas y debates visita {ref("theories")}.\n\n'
            'No publicamos filtraciones de datos privados ni enlaces a descargas ilegales.', CORAL),
        'crew': ('🤝 ENCUENTRA TU CREW',
            '**Copia esta ficha y conecta con gente de tu estilo:**\n\n'
            '🎮 **Plataforma / juego:**\n🕒 **Zona horaria y horario:**\n🎯 **Plan:**\n'
            '👥 **Personas que buscas:**\n🎙️ **Voz:** sí / no\n\n'
            f'Activa el rol **Crew** en {ref("roles")} y usa las salas de **VICE RADIO** para reunirte. '
            'Sin cobros por acceso, spam ni promesas falsas.', CYAN),
        'events': ('🎉 NOS VEMOS EN VICE DISTRICT',
            'Este es el punto de encuentro para quedadas, retos y actividades de la comunidad.\n\n'
            'Cada convocatoria indicará **fecha, hora con zona horaria, plataforma, cupos y reglas**.\n\n'
            f'Activa **Avisos de eventos** en {ref("roles")} para enterarte cuando el equipo publique una actividad.', PINK),
        'support': ('🎫 TU EQUIPO, A UN CLIC',
            '**¿Necesitas ayuda con el servidor o quieres hacer un reporte?**\n\n'
            'Pulsa **Abrir ticket** para hablar en un canal privado contigo y el equipo. '
            'Explica el problema y añade enlaces o pruebas útiles.\n\n'
            'Nunca compartas contraseñas, tokens o datos de pago. Un ticket abierto por persona. '
            'Al cerrarlo, la conversación se conserva en privado.', CYAN),
        'suggestions': ('💡 DISEÑEMOS EL BARRIO JUNTOS',
            '**Tu idea puede mejorar la comunidad.**\n\n'
            'Publica una propuesta por mensaje con **qué cambiarías**, **a quién ayuda** y **un ejemplo**. '
            'Puedes apoyar otras ideas con una reacción y debatirlas con respeto.\n\n'
            'El equipo revisará las propuestas; publicar una idea no garantiza su aprobación.', CORAL),
    }
    return panels.get(key)
