"""The owner's GTA VI community design; never used by the Studio storefront."""
from pathlib import Path
from vice_role_catalog import OPTIONAL_ROLES, OPTIONAL_GROUPS

GUILD_ID = 1572462544302383164
BOT_ID = 1571639486591402174
OWNER_ID = 1509288420852109383
VERSION = 'vice-district-community-v4-pr'
STAFF_VERSION = 'vice-staff-departures-v2-admin-only'
DECORATION_VERSION = 'vice-decorated-channels-v1'
CLOSED_CATEGORY = '━━ 🔒 ARCHIVO ━━'
TICKET_OPEN_PREFIX = '┊・🎫│ticket-'
TICKET_CLOSED_PREFIX = '┊・🔒│cerrado-'
ASSETS = Path(__file__).parent / 'assets' / 'vice-district'
FONTS = Path(__file__).parent / 'assets' / 'esschino' / 'fonts'
PINK, CYAN, CORAL = 0xFF168A, 0x00D9E8, 0xFF795D
DESCRIPTION = ('Desde Puerto Rico para toda Latinoamérica. Tu corillo de GTA VI: noticias con fuentes, '
               'teorías, clips, ayuda y crews. Identidad boricua, ambiente latino y pasión por Vice City. '
               'Encuentra gente con quien jugar. Comunidad de fans no oficial.')

# Keys, display names, color, permission flags, display separately, old name.
STAFF_CHAT = dict(view_channel=True, read_message_history=True, send_messages=True,
                 embed_links=True, attach_files=True, add_reactions=True,
                 connect=True, speak=True, use_application_commands=True)
ROLES = [
    ('team_separator', '━━ 🛡️ EQUIPO ━━', PINK, {}, False, None),
    ('admin', '⚙️ Administrador', 0xFF4866, dict(administrator=True), True, None),
    ('mod', '🛡️ Moderación', PINK, dict(**STAFF_CHAT, manage_messages=True, pin_messages=True, manage_threads=True,
        moderate_members=True, kick_members=True, ban_members=True, manage_nicknames=True, mute_members=True, deafen_members=True,
        move_members=True, view_audit_log=True), True, 'Moderación'),
    ('support', '🛟 Soporte', 0x38CFAE, dict(STAFF_CHAT), True, None),
    ('creator', '🎬 Creadores', 0xB87AFF, {}, True, 'Creadores'),
    ('community_separator', '━━ 🌆 COMUNIDAD ━━', CYAN, {}, False, None),
    ('legend', '💎 Leyenda de Vice', 0xFFD36A, {}, True, None),
    ('veteran', '🌆 Veterano', 0xB47CFF, {}, True, None),
    ('citizen', '🌴 Ciudadano', 0x22DCB4, {}, True, '🌴 Comunidad'),
    ('crew', '🤝 Crew', CYAN, {}, False, 'Crew'),
    *OPTIONAL_ROLES,
    ('entry_separator', '━━ 🌅 RECIÉN LLEGADOS ━━', 0x58B7FF, {}, False, None),
    ('member', '👤 Miembro', 0x58B7FF, {}, True, None),
]
GROUPS = OPTIONAL_GROUPS
SELF_ROLES = frozenset(key for _, keys, _ in GROUPS.values() for key in keys)
CATEGORIES = [
    ('info', '━━ 🌴 EMPIEZA AQUÍ ━━', 'read'),
    ('community', '━━ 🇵🇷 CORILLO LATINO ━━', 'chat'),
    ('game', '━━ 🎮 UNIVERSO GTA VI ━━', 'chat'),
    ('voice', '━━ 🔊 VICE RADIO ━━', 'chat'),
    ('help', '━━ 🎫 AYUDA Y TICKETS ━━', 'read'),
    ('team', '━━ 🛡️ EQUIPO ━━', 'staff'),
]
# key, category, name, topic, policy, voice, slowmode/user limit
CHANNELS = [
    ('welcome','info','╭・👋│bienvenida','Tu llegada a VIce District. Lee las normas, elige tus roles y conoce a la comunidad.','read',False,0),
    ('rules','info','├・📜│normas','Convivencia, privacidad, spoilers y juego limpio.','read',False,0),
    ('roles','info','├・🎭│elige-tus-roles','Personaliza tu perfil: país, regiones, plataformas y crew. Todo es opcional y puedes cambiarlo cuando quieras.','read',False,0),
    ('announcements','info','╰・📢│anuncios','Comunicados de la comunidad y novedades del servidor.','read',False,0),
    ('general','community','╭・💬│general','El punto de encuentro del corillo boricua y latinoamericano. Charla, comparte y disfruta del ambiente.','chat',False,5),
    ('introductions','community','├・🙌│presentaciones','Cuéntanos tu apodo, región, plataformas y tu GTA favorito. No publiques datos personales.','chat',False,10),
    ('clips','community','├・📸│clips-y-capturas','Tus mejores momentos de GTA. Da crédito, marca spoilers y evita contenido gráfico.','chat',False,15),
    ('memes','community','├・😂│memes','Humor y memes de GTA con respeto. Sin spam ni ataques personales.','chat',False,10),
    ('suggestions','community','╰・💡│sugerencias','Una idea por mensaje: propuesta, beneficio y ejemplo. Opina con respeto.','chat',False,30),
    ('news','game','╭・📰│noticias','Noticias con fuentes verificables. Los rumores se comentan en teorías.','read',False,0),
    ('theories','game','├・🔎│teorías','Analiza pistas y comparte teorías. Distingue especulación de hechos y oculta spoilers.','chat',False,10),
    ('guides','game','├・🧭│guías-y-ayuda','Dudas sobre GTA y ayuda entre jugadores. Explica tu plataforma y lo que ya probaste.','chat',False,5),
    ('crew','game','├・🤝│busca-crew','Encuentra gente afín: plataforma, zona horaria, horario y estilo de juego.','chat',False,30),
    ('events','game','╰・🎉│eventos','Quedadas, retos y actividades de la comunidad. Horarios y requisitos en cada convocatoria.','read',False,0),
    ('lobby','voice','╭・🌴│Lobby',None,'chat',True,0),
    ('voice1','voice','├・🚗│Crew 01',None,'chat',True,6),
    ('voice2','voice','╰・🌇│Crew 02',None,'chat',True,6),
    ('support','help','╰・🎫│abrir-ticket','Abre un ticket privado para ayuda del servidor o reportes al equipo.','read',False,0),
    ('staff','team','╭・👥│chat-staff','Coordinación privada de Fundador, Administrador, Moderación y Soporte.','staff',False,0),
    ('log','team','├・📋│registro-staff','Auditoría y actividad del distrito: miembros, voz y cambios administrativos. Registro privado del equipo.','staffread',False,0),
    ('goodbye','team','├・🚪│despedidas','Registro privado de salidas, expulsiones y baneos. Acceso exclusivo de Fundador y Administrador.','adminread',False,0),
    ('staffvoice','team','╰・🛠│Sala del equipo',None,'staff',True,0),
]

def panel_copy(key, c):
    ref = lambda k: f'<#{c(k)}>'
    panels = {
        'welcome': ('🇵🇷 BIENVENIDO A VICE DISTRICT',
            '**Desde Puerto Rico para toda Latinoamérica.**\n\n'
            'Un corillo con identidad boricua y espacio para todo el mundo latino. '
            'Compartimos la pasión por GTA, las buenas conversaciones y las ganas de encontrar crew. '
            'Ponte cómodo: ya estás en el distrito.\n\n'
            f'**01 · Conoce el barrio**\nAl entrar recibes **👤 Miembro**. Lee {ref("rules")} y pulsa '
            '**Unirme a la comunidad** para aceptar las normas y ser **🌴 Ciudadano**.\n\n'
            f'**02 · Dale tu estilo**\nElige tu país, regiones, plataformas y el rol Crew en {ref("roles")}.\n\n'
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
            '🌎 **País:** los 18 países de Hispanoamérica y Puerto Rico, primero en la lista. Elige uno si quieres.\n'
            '🧭 **Regiones:** Caribe, Centroamérica, Sudamérica, Norteamérica y Antillas Mayores.\n'
            '🎮 **Plataformas:** PlayStation 5, Xbox Series X|S, Xbox One mediante juego en la nube y PC en espera.\n'
            '🤝 **Crew:** encuentra gente con quien jugar.\n\n'
            'Todo es opcional. Elige un país y tantas regiones o plataformas como quieras. Cada lista es independiente. '
            'Deja un menú vacío para retirar los roles de ese grupo.\n\n'
            '⌛ **PC** está incluida por petición de la comunidad, marcada **Esperando GTA VI**. Una versión de PC no figura como confirmada por Rockstar. '
            '[Plataformas oficiales](https://support.rockstargames.com/articles/4QfG4FmZCf5W1gS8jy4UVT/grand-theft-auto-vi-platform-editions-and-versions).\n\n'
            '**Equipo:** Fundador, Administrador, Moderación y Soporte.\n'
            '**Tu recorrido:** 👤 Miembro → 🌴 Ciudadano → 🌆 Veterano → 💎 Leyenda de Vice.\n'
            '**Miembro** se entrega al entrar; **Ciudadano**, al aceptar las normas. '
            'Veterano, Leyenda, Creadores y los roles del equipo los asigna la administración.', CYAN),
        'announcements': ('📢 LA VOZ DEL DISTRITO',
            'Aquí encontrarás los comunicados de **GTA VI Latino | VIce District**: cambios, novedades y avisos importantes.\n\n'
            f'Consulta aquí las novedades del equipo. Comparte tus ideas en {ref("suggestions")}.', PINK),
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
            'Cada convocatoria indicará **fecha, hora de Puerto Rico como referencia, zona horaria, plataforma, cupos y reglas**. '
            'Cuando corresponda, añadiremos equivalencias para el resto de Latinoamérica.\n\n'
            'Consulta las próximas actividades y pulsa **Me interesa** en el evento al que quieras unirte.', PINK),
        'support': ('🎫 TU EQUIPO, A UN CLIC',
            'Pulsa **Abrir ticket** y elige el motivo:\n'
            '💬 Ayuda general · 🚩 Reportar a un jugador\n'
            '⚖️ Apelación · 🛠️ Problema técnico\n\n'
            'Tu conversación será privada y recibirás un aviso cuando alguien la atienda. '
            'Un ticket abierto por persona.\n\n'
            'Al terminar podrás valorar la atención de **1 a 5 estrellas**, con comentario opcional. '
            'Solo Administración verá tu valoración.\n\n'
            'Al cerrarlo, el historial se conserva. Antes de eliminarlo se guarda una copia privada para el equipo. '
            'Nunca compartas contraseñas, tokens ni datos de pago.', CYAN),
        'goodbye': ('🚪 SALIDAS DEL DISTRITO',
            '**Solo para Fundador y Administrador.**\n\n'
            'Cada despedida incluye **banner, nombre y avatar**, hora de salida y fecha de entrada cuando esté disponible.\n\n'
            '**Expulsiones y baneos:** se muestra la razón y el responsable del registro de auditoría cuando Discord los proporciona.\n'
            '**Otras salidas:** se indica que no hay una acción administrativa confirmada; Discord no proporciona el motivo personal. '
            'Si la auditoría no está disponible, el panel lo indicará.', CORAL),
        'suggestions': ('💡 DISEÑEMOS EL BARRIO JUNTOS',
            '**Tu idea puede mejorar la comunidad.**\n\n'
            'Publica una propuesta por mensaje con **qué cambiarías**, **a quién ayuda** y **un ejemplo**. '
            'Puedes apoyar otras ideas con una reacción y debatirlas con respeto.\n\n'
            'El equipo revisará las propuestas; publicar una idea no garantiza su aprobación.', CORAL),
    }
    return panels.get(key)
