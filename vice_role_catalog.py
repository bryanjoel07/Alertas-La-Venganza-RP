"""Optional identity roles for VIce District; no Discord mutations or privileges.

The owner's corrected scope is the 18 Spanish-speaking Latin American states
plus Puerto Rico. The country selector includes Puerto Rico as explicitly
requested; this community catalog makes no sovereignty claims.

Regions below are optional community identity tags, not a partition of M49.
Their overlap is intentional. Platform options include Rockstar's confirmed
GTA VI console options, checked 2026-11-18, plus PC at the owner's explicit
request. PC retains its existing role ID and is labeled as waiting for GTA VI,
never as a confirmed release. All role specifications have zero permissions.
"""

CATALOG_VERSION = 'vice-optional-role-catalog-v4-owner-curated'
COUNTRY_SOURCE = 'https://unstats.un.org/unsd/methodology/m49/'
PLATFORM_SOURCE = ('https://support.rockstargames.com/articles/'
                   '4QfG4FmZCf5W1gS8jy4UVT/grand-theft-auto-vi-platform-editions-and-versions')
PLATFORM_SEPARATOR_KEY = 'preferences_separator'

# Frozen retirement scope explicitly requested by the owner when narrowing the
# previous Latin America + whole Caribbean catalog. Never infer further keys
# from name, geography or a future catalog difference.
RETIRED_KEYS = frozenset({
    'anguilla', 'antigua_barbuda', 'aruba', 'bahamas', 'barbados', 'belize',
    'bonaire_saba_eustatius', 'brazil', 'curacao', 'dominica', 'grenada',
    'guadeloupe', 'french_guiana', 'guyana', 'haiti', 'cayman_islands',
    'falkland_islands', 'turks_caicos', 'british_virgin_islands',
    'us_virgin_islands', 'jamaica', 'martinique', 'montserrat',
    'saint_barthelemy', 'saint_kitts_nevis', 'saint_martin',
    'saint_vincent_grenadines', 'saint_lucia', 'sint_maarten', 'suriname',
    'trinidad_tobago', 'lesser_antilles', 'guianas', 'europe',
    'nintendo', 'steam_deck', 'android', 'ios', 'macos', 'linux', 'vr',
    # The owner removed these five roles manually; retire the now-empty divider
    # as well rather than recreating their earlier catalog entries.
    'andean', 'southern_cone', 'amazon', 'news', 'events', 'interests_separator',
})


def _flag(code):
    return ''.join(chr(0x1F1E6 + ord(char) - ord('A')) for char in code)


def _role(key, name, color):
    # Matches vice_design.ROLES: key, label, color, permissions, hoist, old name.
    return key, name, color, {}, False, None


# Puerto Rico first; then Spanish alphabetical order. Preserve legacy pr/mexico
# keys so existing members keep exactly the same role IDs and assignments.
COUNTRY_DATA = (
    ('pr', 'PR', 'Puerto Rico', 0xFF4866),
    ('argentina', 'AR', 'Argentina', 0x69C9F5),
    ('bolivia', 'BO', 'Bolivia', 0x68D68B),
    ('chile', 'CL', 'Chile', 0xED647E),
    ('colombia', 'CO', 'Colombia', 0xF2CC59),
    ('costa_rica', 'CR', 'Costa Rica', 0x5D9CFF),
    ('cuba', 'CU', 'Cuba', 0x55B4F2),
    ('ecuador', 'EC', 'Ecuador', 0xEFC357),
    ('el_salvador', 'SV', 'El Salvador', 0x67AEFA),
    ('guatemala', 'GT', 'Guatemala', 0x7ACDF7),
    ('honduras', 'HN', 'Honduras', 0x5DD2E5),
    ('mexico', 'MX', 'México', 0x54BCAB),
    ('nicaragua', 'NI', 'Nicaragua', 0x69B7F2),
    ('panama', 'PA', 'Panamá', 0xF17C8C),
    ('paraguay', 'PY', 'Paraguay', 0xE987A1),
    ('peru', 'PE', 'Perú', 0xF1687E),
    ('dominican_republic', 'DO', 'República Dominicana', 0x758FF4),
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
]
REGION_KEYS = tuple(role[0] for role in REGION_ROLES)

PLATFORM_ROLES = [
    _role('ps', '🎮 PlayStation 5', 0x6C9FFF),
    _role('xbox', '🎮 Xbox Series X|S', 0x58C66A),
    _role('xbox_one_cloud', '☁️ Xbox One · Nube', 0x6AC6E5),
    _role('pc', '⌛ PC · Esperando GTA VI', 0xAC90F5),
]
PLATFORM_KEYS = tuple(role[0] for role in PLATFORM_ROLES)

# Crew already belongs to the original community block, so it needs no new
# optional role or extra divider after the owner's manual removals.
INTEREST_ROLES = []

OPTIONAL_ROLES = [
    _role('country_separator', '━━ 🌎 PAÍSES ━━', 0xFF6D9F),
    *COUNTRY_ROLES,
    _role('region_separator', '━━ 🧭 REGIONES ━━', 0x24D8CB),
    *REGION_ROLES,
    _role(PLATFORM_SEPARATOR_KEY, '━━ 🎮 PLATAFORMAS ━━', 0x829EFF),
    *PLATFORM_ROLES,
]

# Discord permits 25 options per select and five select rows per message.
# One selector covers the corrected Hispanic catalog; no old country pages
# remain registered. A new choice replaces the member's previous country role.
COUNTRY_GROUPS = {
    'country': ('País · Hispanoamérica y Puerto Rico', list(COUNTRY_KEYS), 1),
}
OPTIONAL_GROUPS = {
    **COUNTRY_GROUPS,
    'region': ('Tus regiones · puedes elegir varias', list(REGION_KEYS), len(REGION_KEYS)),
    'platform': ('Plataformas de GTA VI · PC en espera', list(PLATFORM_KEYS), len(PLATFORM_KEYS)),
    'interests': ('Tu crew · encuentra con quién jugar', ['crew'], 1),
}
GROUP_SCOPES = {
    group: COUNTRY_KEYS if group in COUNTRY_GROUPS else tuple(keys)
    for group, (_, keys, _) in OPTIONAL_GROUPS.items()
}
