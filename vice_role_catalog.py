"""Optional identity roles for VIce District; no Discord mutations or privileges.

Country coverage follows the inhabited countries/areas of UN M49 Latin America
and the Caribbean, checked 2026-11-18: 33 sovereign states and 17 territories.
https://unstats.un.org/unsd/methodology/m49/
Bouvet Island and South Georgia/South Sandwich Islands are omitted because they
have no permanent population. The label is deliberately countries *and
territories*: this community catalog makes no sovereignty claims.

Regions below are optional community identity tags, not a partition of M49.
Their overlap is intentional; existing North America and Europe roles remain
available for the diaspora. Platforms describe where members play generally,
not GTA VI availability. All role specifications have zero permissions.
"""

CATALOG_VERSION = 'vice-optional-role-catalog-v1'
COUNTRY_SOURCE = 'https://unstats.un.org/unsd/methodology/m49/'
PLATFORM_SEPARATOR_KEY = 'preferences_separator'


def _flag(code):
    return ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)


def _role(key, name, color):
    # Matches vice_design.ROLES: key, label, color, permissions, hoist, old name.
    return key, name, color, {}, False, None


# Puerto Rico first; then Spanish alphabetical order. Preserve legacy pr/mexico
# keys so existing members keep exactly the same role IDs and assignments.
COUNTRY_DATA = (
    ('pr', 'PR', 'Puerto Rico', 0xFF4866),
    ('anguilla', 'AI', 'Anguila', 0x56B9F2),
    ('antigua_barbuda', 'AG', 'Antigua y Barbuda', 0xFF875E),
    ('argentina', 'AR', 'Argentina', 0x69C9F5),
    ('aruba', 'AW', 'Aruba', 0x39C5D9),
    ('bahamas', 'BS', 'Bahamas', 0x32D4BE),
    ('barbados', 'BB', 'Barbados', 0x6F94FF),
    ('belize', 'BZ', 'Belice', 0x548EF7),
    ('bolivia', 'BO', 'Bolivia', 0x68D68B),
    ('bonaire_saba_eustatius', 'BQ', 'Bonaire, San Eustaquio y Saba', 0xF5C85E),
    ('brazil', 'BR', 'Brasil', 0x4CD98A),
    ('chile', 'CL', 'Chile', 0xED647E),
    ('colombia', 'CO', 'Colombia', 0xF2CC59),
    ('costa_rica', 'CR', 'Costa Rica', 0x5D9CFF),
    ('cuba', 'CU', 'Cuba', 0x55B4F2),
    ('curacao', 'CW', 'Curazao', 0x38BCCE),
    ('dominica', 'DM', 'Dominica', 0x56CF9D),
    ('ecuador', 'EC', 'Ecuador', 0xEFC357),
    ('el_salvador', 'SV', 'El Salvador', 0x67AEFA),
    ('grenada', 'GD', 'Granada', 0xF18D64),
    ('guadeloupe', 'GP', 'Guadalupe', 0xF6B963),
    ('guatemala', 'GT', 'Guatemala', 0x7ACDF7),
    ('french_guiana', 'GF', 'Guayana Francesa', 0x7DCD6D),
    ('guyana', 'GY', 'Guyana', 0x49C697),
    ('haiti', 'HT', 'Haití', 0xA18BF2),
    ('honduras', 'HN', 'Honduras', 0x5DD2E5),
    ('cayman_islands', 'KY', 'Islas Caimán', 0x58B8E8),
    ('falkland_islands', 'FK', 'Islas Malvinas (Falkland)', 0x7FA6F2),
    ('turks_caicos', 'TC', 'Islas Turcas y Caicos', 0x42C9C7),
    ('british_virgin_islands', 'VG', 'Islas Vírgenes Británicas', 0x77C97B),
    ('us_virgin_islands', 'VI', 'Islas Vírgenes de EE. UU.', 0xF3C86C),
    ('jamaica', 'JM', 'Jamaica', 0x64D66E),
    ('martinique', 'MQ', 'Martinica', 0xEE718D),
    ('mexico', 'MX', 'México', 0x54BCAB),
    ('montserrat', 'MS', 'Montserrat', 0x6DBFA8),
    ('nicaragua', 'NI', 'Nicaragua', 0x69B7F2),
    ('panama', 'PA', 'Panamá', 0xF17C8C),
    ('paraguay', 'PY', 'Paraguay', 0xE987A1),
    ('peru', 'PE', 'Perú', 0xF1687E),
    ('dominican_republic', 'DO', 'República Dominicana', 0x758FF4),
    ('saint_barthelemy', 'BL', 'San Bartolomé', 0xA893EB),
    ('saint_kitts_nevis', 'KN', 'San Cristóbal y Nieves', 0x5CCE96),
    ('saint_martin', 'MF', 'San Martín (parte francesa)', 0xC38CEE),
    ('saint_vincent_grenadines', 'VC', 'San Vicente y las Granadinas', 0x70CFB3),
    ('saint_lucia', 'LC', 'Santa Lucía', 0x68C9EF),
    ('sint_maarten', 'SX', 'Sint Maarten (parte neerlandesa)', 0xEB8A94),
    ('suriname', 'SR', 'Surinam', 0x60C88A),
    ('trinidad_tobago', 'TT', 'Trinidad y Tobago', 0xF47779),
    ('uruguay', 'UY', 'Uruguay', 0x87C3F5),
    ('venezuela', 'VE', 'Venezuela', 0xF6BE63),
)
COUNTRY_ROLES = [_role(key, f'{_flag(code)} {name}', color)
                 for key, code, name, color in COUNTRY_DATA]
COUNTRY_KEYS = tuple(role[0] for role in COUNTRY_ROLES)

REGION_ROLES = [
    _role('caribbean', '🌴 Caribe', 0x27D8C4),
    _role('central', '🌋 Centroamérica', 0xFF9E65),
    _role('south', '🌎 Sudamérica', 0x65C98A),
    _role('north', '🌎 Norteamérica', 0x70ACF7),
    _role('greater_antilles', '🏝️ Antillas Mayores', 0x50D3EA),
    _role('lesser_antilles', '🌺 Antillas Menores', 0xF58CBD),
    _role('andean', '⛰️ Región Andina', 0xBC97F5),
    _role('southern_cone', '🧉 Cono Sur', 0xF0BD76),
    _role('amazon', '🌳 Amazonía', 0x4AD29F),
    _role('guianas', '🌊 Guayanas', 0x66BCCB),
    _role('europe', '🌍 España / Europa', 0x8F9EF5),
]
REGION_KEYS = tuple(role[0] for role in REGION_ROLES)

PLATFORM_ROLES = [
    _role('ps', '🎮 PlayStation', 0x6C9FFF),
    _role('xbox', '🎮 Xbox', 0x58C66A),
    _role('pc', '💻 PC', 0xAC90F5),
    _role('nintendo', '🕹️ Nintendo', 0xFF657C),
    _role('steam_deck', '🎮 Steam Deck', 0x6AC6E5),
    _role('android', '🤖 Android', 0x63DB9C),
    _role('ios', '📱 iPhone / iPad', 0xF2ABC9),
    _role('macos', '🍎 macOS', 0xB5B9F3),
    _role('linux', '🐧 Linux', 0xF4CD67),
    _role('vr', '🥽 Realidad virtual', 0xDA85ED),
]
PLATFORM_KEYS = tuple(role[0] for role in PLATFORM_ROLES)

INTEREST_ROLES = [
    _role('news', '📰 Avisos de GTA VI', 0xFFB36A),
    _role('events', '🎉 Avisos de eventos', 0xFF8EBE),
]

OPTIONAL_ROLES = [
    _role('country_separator', '━━ 🌎 PAÍSES Y TERRITORIOS ━━', 0xFF6D9F),
    *COUNTRY_ROLES,
    _role('region_separator', '━━ 🧭 REGIONES ━━', 0x24D8CB),
    *REGION_ROLES,
    _role(PLATFORM_SEPARATOR_KEY, '━━ 🎮 PLATAFORMAS ━━', 0x829EFF),
    *PLATFORM_ROLES,
    _role('interests_separator', '━━ 🔔 AVISOS ━━', 0xFFB36A),
    *INTEREST_ROLES,
]

# Discord permits 25 options per select and five select rows per message.
# The two country selectors have ONE shared replacement scope, so choosing in
# the second menu removes an older choice in the first (and vice versa).
COUNTRY_GROUPS = {
    'country_a': ('País / territorio · Puerto Rico y A–Haití', list(COUNTRY_KEYS[:25]), 1),
    'country_b': ('País / territorio · Honduras–Venezuela', list(COUNTRY_KEYS[25:]), 1),
}
OPTIONAL_GROUPS = {
    **COUNTRY_GROUPS,
    'region': ('Tus regiones · puedes elegir varias', list(REGION_KEYS), len(REGION_KEYS)),
    'platform': ('Tus plataformas · elige las que usas', list(PLATFORM_KEYS), len(PLATFORM_KEYS)),
    'interests': ('Tus avisos y tu crew', ['news', 'events', 'crew'], 3),
}
GROUP_SCOPES = {
    group: COUNTRY_KEYS if group in COUNTRY_GROUPS else tuple(keys)
    for group, (_, keys, _) in OPTIONAL_GROUPS.items()
}
