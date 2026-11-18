"""Original code-native symbols for the VIce District role badge set.

Draw on the shared 128-unit Canvas. Background, edge trim and the VI wordmark
belong to the caller; these silhouettes occupy the upper 23..105 / 20..89 zone.
Only polygon, line, ellipse, rounded rectangle and text primitives are used.
"""
import math

PLUM = '#24102F'
IVORY = '#FFF4DB'
CYAN = '#33E5E9'
PINK = '#FF258D'
CORAL = '#FF785E'
GOLD = '#FFD25E'


def _star(c, x, y, radius, fill=IVORY, points=5, inner=.44, width=3):
    vertices = []
    for index in range(points * 2):
        angle = -math.pi / 2 + index * math.pi / points
        length = radius if index % 2 == 0 else radius * inner
        vertices.append((x + math.cos(angle) * length, y + math.sin(angle) * length))
    c.poly(vertices, fill, PLUM, width)


def _palm(c, x=62, y=45, scale=1, accent=CYAN):
    p = lambda vertices: [(x + dx * scale, y + dy * scale) for dx, dy in vertices]
    c.poly(p([(-2, 0), (5, 1), (2, 17), (-1, 35), (-12, 35), (-7, 16)]),
           CORAL, PLUM, 3.5)
    for leaf in [
        [(0, 0), (-17, -15), (-34, -12), (-18, -6)],
        [(0, 0), (-22, -3), (-34, 11), (-16, 5)],
        [(0, 0), (-6, -22), (5, -29), (3, -10)],
        [(0, 0), (18, -17), (34, -12), (17, -5)],
        [(0, 0), (22, -1), (33, 14), (16, 5)],
    ]:
        c.poly(p(leaf), accent, PLUM, 3)
    c.ellipse((x-4*scale, y-3*scale, x+5*scale, y+5*scale), GOLD, PLUM, 2)


def _controller(c, x=64, y=61, scale=1, accent=CYAN):
    p = lambda vertices: [(x + dx * scale, y + dy * scale) for dx, dy in vertices]
    c.poly(p([(-26, -15), (-14, -17), (-7, -12), (7, -12), (14, -17),
              (26, -15), (34, 5), (31, 18), (23, 20), (11, 8), (-11, 8),
              (-23, 20), (-31, 18), (-34, 5)]), accent, PLUM, 4)
    c.line(p([(-20, -7), (-20, 7)]), PLUM, 4.5 * scale)
    c.line(p([(-27, 0), (-13, 0)]), PLUM, 4.5 * scale)
    for dx, dy, color in [(17, -5, IVORY), (24, 2, PINK)]:
        cx, cy = x + dx * scale, y + dy * scale
        r = 3.6 * scale
        c.ellipse((cx-r, cy-r, cx+r, cy+r), color, PLUM, 1.6)
    c.line(p([(-4, 0), (4, 0)]), IVORY, 2.5 * scale)


def _shield(c, accent, motif='check'):
    c.poly([(64, 24), (94, 34), (91, 59), (80, 76), (64, 86),
            (48, 76), (37, 59), (34, 34)], accent, PLUM, 4)
    c.poly([(64, 31), (64, 77), (51, 69), (43, 56), (41, 39)], IVORY, None)
    if motif == 'check':
        c.line([(49, 52), (60, 63), (80, 41)], PLUM, 10)
        c.line([(49, 52), (60, 63), (80, 41)], GOLD, 5.5)
    else:
        _star(c, 64, 52, 18, GOLD, width=3.5)


def _founder(c, accent):
    c.poly([(30, 36), (46, 49), (64, 25), (82, 49), (99, 36),
            (91, 77), (38, 77)], accent, PLUM, 4)
    c.poly([(33, 39), (46, 51), (64, 30), (64, 69), (40, 69)], IVORY, None)
    c.rect((38, 69, 91, 82), 3, CORAL, PLUM, 3.5)
    c.line([(43, 77), (85, 77)], PINK, 3)
    c.poly([(64, 45), (73, 56), (64, 67), (55, 56)], CYAN, PLUM, 3)
    for x, y in [(30, 34), (64, 24), (99, 34)]:
        c.ellipse((x-4, y-4, x+4, y+4), GOLD, PLUM, 2.5)


def _bot(c, accent):
    c.line([(64, 26), (64, 37)], PLUM, 7)
    c.ellipse((59, 21, 69, 31), PINK, PLUM, 2.5)
    c.rect((27, 48, 38, 68), 4, CORAL, PLUM, 3)
    c.rect((90, 48, 101, 68), 4, CORAL, PLUM, 3)
    c.rect((35, 35, 93, 81), 10, accent, PLUM, 4)
    c.rect((43, 44, 85, 65), 6, PLUM, None)
    c.ellipse((48, 49, 58, 59), IVORY)
    c.ellipse((70, 49, 80, 59), IVORY)
    c.line([(52, 73), (76, 73)], PLUM, 4)
    c.line([(59, 69), (59, 76)], IVORY, 2)
    c.line([(69, 69), (69, 76)], IVORY, 2)


def _team(c, accent):
    c.line([(31, 28), (95, 82)], PLUM, 9)
    c.line([(97, 28), (33, 82)], PLUM, 9)
    c.line([(31, 28), (95, 82)], CORAL, 4)
    c.line([(97, 28), (33, 82)], CORAL, 4)
    _shield(c, accent, 'star')


def _admin(c, accent):
    points = []
    for index in range(40):
        angle = -math.pi / 2 + index * math.tau / 40
        radius = 32 if index % 5 in (1, 2, 3) else 25
        points.append((64 + math.cos(angle) * radius, 55 + math.sin(angle) * radius))
    c.poly(points, accent, PLUM, 4)
    c.ellipse((45, 36, 83, 74), PLUM, IVORY, 3)
    c.poly([(66, 36), (52, 57), (62, 57), (59, 75), (77, 50), (66, 50)],
           GOLD, PLUM, 2.7)


def _moderator(c, accent):
    _shield(c, accent)


def _support(c, accent):
    c.ellipse((32, 23, 96, 87), accent, PLUM, 4)
    for band in [
        [(43, 28), (53, 24), (60, 42), (49, 47)],
        [(75, 24), (85, 29), (78, 47), (68, 42)],
        [(35, 68), (40, 78), (57, 70), (51, 60)],
        [(88, 78), (94, 68), (77, 60), (71, 70)],
    ]:
        c.poly(band, IVORY, None)
    c.ellipse((49, 40, 79, 70), PLUM, PLUM, 3)
    c.rect((60, 45, 68, 65), 2, CORAL, None)
    c.rect((54, 51, 74, 59), 2, CORAL, None)


def _creator(c, accent):
    c.poly([(28, 43), (43, 43), (49, 32), (74, 32), (82, 43), (98, 43),
            (98, 79), (28, 79)], accent, PLUM, 4)
    c.rect((35, 36, 43, 44), 2, GOLD, PLUM, 2)
    c.ellipse((47, 43, 82, 78), PLUM, IVORY, 3)
    c.ellipse((54, 50, 75, 71), CYAN, PLUM, 2)
    c.ellipse((58, 52, 65, 59), IVORY)
    c.line([(86, 50), (92, 50)], PINK, 3)


def _community(c, accent):
    c.ellipse((43, 23, 88, 68), CORAL, PLUM, 3)
    for box, col in [((28, 51, 47, 84), accent), ((50, 36, 72, 84), IVORY),
                     ((77, 45, 98, 84), accent)]:
        c.rect(box, 2, col, PLUM, 3.5)
    c.line([(61, 26), (61, 36)], PLUM, 4)
    for x, y in [(35, 59), (35, 71), (58, 45), (58, 57), (58, 69), (85, 55), (85, 68)]:
        c.rect((x, y, x+7, y+5), 1, PINK, None)


def _legend(c, accent):
    c.poly([(43, 29), (85, 29), (101, 48), (64, 85), (27, 48)], accent, PLUM, 4)
    c.poly([(43, 29), (53, 49), (27, 48)], IVORY, PLUM, 2.5)
    c.poly([(43, 29), (64, 29), (53, 49)], CYAN, PLUM, 2.5)
    c.poly([(64, 29), (85, 29), (76, 49), (53, 49)], IVORY, PLUM, 2.5)
    c.poly([(85, 29), (101, 48), (76, 49)], CORAL, PLUM, 2.5)
    c.poly([(53, 49), (76, 49), (64, 85)], accent, PLUM, 2.5)
    _star(c, 94, 26, 6, IVORY, points=4, inner=.25, width=1.5)


def _booster(c, accent):
    # A tall neon crystal with an upward charge, distinct from Legend's wide gem.
    c.poly([(64, 23), (81, 36), (81, 65), (64, 81), (47, 65), (47, 36)],
           accent, PLUM, 4)
    c.poly([(64, 23), (55, 39), (55, 63), (64, 81), (47, 65), (47, 36)],
           IVORY, PLUM, 2.5)
    c.poly([(64, 23), (81, 36), (81, 65), (64, 81), (73, 62), (73, 39)],
           PINK, PLUM, 2.5)
    c.poly([(64, 35), (74, 47), (68, 47), (68, 64), (60, 64),
            (60, 47), (54, 47)], CYAN, PLUM, 2.5)
    _star(c, 33, 47, 8, CYAN, points=4, inner=.28, width=2)
    _star(c, 96, 34, 7, IVORY, points=4, inner=.28, width=2)
    c.line([(34, 78), (34, 65)], PINK, 3)
    c.line([(94, 76), (94, 63)], CYAN, 3)
    c.line([(52, 86), (76, 86)], accent, 3)


def _veteran(c, accent):
    _star(c, 64, 34, 12, GOLD, width=3)
    for y, fill in [(47, IVORY), (61, accent), (74, CORAL)]:
        c.poly([(35, y-6), (64, y+3), (93, y-6), (93, y+4),
                (64, y+13), (35, y+4)], fill, PLUM, 3)


def _citizen(c, accent):
    c.ellipse((68, 29, 99, 60), GOLD, PLUM, 3)
    _palm(c, 61, 49, .91, accent)
    c.line([(32, 84), (94, 84)], CYAN, 3)


def _crew(c, accent):
    c.poly([(28, 45), (42, 39), (55, 44), (68, 42), (90, 58), (84, 76),
            (72, 82), (54, 73), (40, 61), (28, 62)], accent, PLUM, 4)
    c.poly([(99, 43), (86, 36), (73, 39), (61, 38), (47, 52), (53, 59),
            (63, 51), (75, 62), (89, 68), (99, 63)], IVORY, PLUM, 4)
    c.line([(62, 63), (77, 75)], PLUM, 3)
    c.line([(56, 68), (68, 79)], PLUM, 3)
    c.rect((25, 42, 37, 66), 2, CORAL, PLUM, 3)
    c.rect((91, 40, 103, 66), 2, CYAN, PLUM, 3)


def _entry(c, accent):
    for a, b in [((64, 23), (64, 33)), ((40, 31), (46, 39)),
                 ((88, 31), (82, 39)), ((29, 50), (40, 52)), ((99, 50), (88, 52))]:
        c.line([a, b], PLUM, 6)
        c.line([a, b], GOLD, 3)
    c.poly([(42, 64), (43, 51), (50, 42), (61, 38), (72, 40), (82, 49), (86, 64)],
           accent, PLUM, 4)
    c.line([(28, 65), (100, 65)], IVORY, 3)
    c.poly([(58, 68), (70, 68), (83, 87), (45, 87)], PLUM, CYAN, 2)
    c.line([(64, 71), (64, 76)], GOLD, 3)
    c.line([(64, 80), (64, 85)], GOLD, 3)


def _member(c, accent):
    c.ellipse((49, 25, 79, 56), IVORY, PLUM, 4)
    c.poly([(31, 85), (33, 73), (42, 65), (53, 61), (64, 67), (75, 61),
            (86, 65), (95, 73), (97, 85)], accent, PLUM, 4)
    c.line([(64, 69), (64, 82)], PLUM, 3)
    c.line([(50, 69), (56, 75)], IVORY, 3)


def _countries(c, accent):
    c.ellipse((37, 28, 99, 88), accent, PLUM, 4)
    c.ellipse((52, 29, 84, 87), None, IVORY, 2.5)
    c.line([(39, 58), (97, 58)], IVORY, 2.5)
    c.line([(45, 42), (91, 42)], IVORY, 2.5)
    c.line([(45, 74), (91, 74)], IVORY, 2.5)
    c.line([(29, 25), (29, 70)], PLUM, 7)
    c.line([(29, 25), (29, 70)], GOLD, 3)
    c.poly([(29, 25), (42, 22), (58, 28), (55, 44), (41, 39), (29, 42)],
           CORAL, PLUM, 3)
    _star(c, 41, 32, 5, IVORY, width=1)


def _regions(c, accent):
    c.poly([(28, 42), (47, 36), (73, 44), (99, 36), (99, 78),
            (74, 86), (48, 78), (28, 85)], accent, PLUM, 4)
    c.poly([(48, 37), (73, 44), (74, 86), (48, 78)], IVORY, PLUM, 3)
    c.line([(35, 66), (44, 61), (56, 72), (84, 58), (92, 62)], PINK, 3)
    c.poly([(64, 66), (48, 47), (47, 36), (52, 26), (64, 22),
            (76, 26), (81, 36), (80, 47)], CORAL, PLUM, 3.5)
    c.ellipse((56, 30, 72, 46), IVORY, PLUM, 2.5)


def _platforms(c, accent):
    _star(c, 64, 31, 10, GOLD, width=2.5)
    _controller(c, 64, 64, 1.03, accent)


def _caribbean(c, accent):
    c.ellipse((73, 27, 99, 53), GOLD, PLUM, 3)
    _palm(c, 49, 43, .67, accent)
    c.poly([(30, 74), (45, 67), (63, 69), (76, 75)], CORAL, PLUM, 2.5)
    for y, offset in [(77, 0), (85, 5)]:
        c.line([(28+offset, y), (39+offset, y-3), (52+offset, y),
                (65+offset, y-3), (78+offset, y), (96, y-3)], CYAN, 3)


def _central(c, accent):
    c.ellipse((54, 24, 67, 38), IVORY, PLUM, 2.5)
    c.ellipse((62, 20, 78, 33), IVORY, PLUM, 2.5)
    c.poly([(27, 85), (49, 52), (55, 43), (73, 43), (80, 55), (101, 85)],
           accent, PLUM, 4)
    c.poly([(55, 43), (73, 43), (80, 55), (69, 53), (65, 67),
            (58, 54), (49, 55)], CORAL, PLUM, 2.5)
    c.line([(55, 43), (73, 43)], GOLD, 4)
    c.poly([(38, 82), (51, 62), (55, 82)], IVORY, None)


def _south(c, accent):
    # Deliberately bold, original geographic silhouette rather than tiny borders.
    c.poly([(40, 27), (54, 24), (65, 30), (81, 34), (90, 44), (86, 57),
            (76, 66), (72, 77), (63, 87), (56, 78), (57, 62), (48, 54),
            (41, 42), (34, 36)], accent, PLUM, 4)
    c.line([(46, 34), (49, 47), (59, 61), (61, 75)], IVORY, 3)
    _star(c, 74, 44, 7, GOLD, width=2)


def _north(c, accent):
    c.poly([(28, 32), (41, 25), (50, 31), (59, 24), (68, 30), (83, 25),
            (95, 35), (89, 44), (99, 48), (88, 56), (78, 56), (72, 65),
            (80, 74), (85, 83), (74, 80), (65, 72), (58, 60), (47, 55),
            (42, 43), (30, 44)], accent, PLUM, 4)
    c.line([(46, 39), (57, 43), (73, 42)], IVORY, 3)
    _star(c, 65, 50, 7, GOLD, width=2)


def _antilles(c, accent):
    c.poly([(28, 34), (40, 29), (51, 35), (61, 36), (72, 46), (66, 50),
            (53, 43), (43, 42), (34, 37)], accent, PLUM, 3)
    c.poly([(66, 53), (77, 49), (90, 56), (87, 64), (77, 63), (68, 61)],
           CORAL, PLUM, 3)
    c.poly([(44, 57), (58, 56), (65, 61), (53, 65), (44, 63)], IVORY, PLUM, 2.5)
    c.rect((92, 57, 103, 64), 2, GOLD, PLUM, 2)
    c.line([(31, 76), (43, 73), (55, 76), (67, 73), (79, 76), (96, 73)], CYAN, 3)
    c.line([(43, 85), (56, 82), (70, 85), (85, 82)], accent, 3)


def _playstation(c, accent):
    c.poly([(34, 26), (49, 29), (54, 78), (44, 83), (36, 75)], IVORY, PLUM, 3.5)
    c.poly([(49, 29), (55, 25), (59, 75), (54, 79)], accent, PLUM, 3)
    c.line([(48, 36), (51, 73)], PLUM, 3)
    c.rect((30, 81, 62, 86), 2, PLUM, None)
    c.text((81, 43), 'PS5', 19, IVORY, 2.3)
    _controller(c, 80, 71, .58, accent)


def _xbox(c, accent):
    c.rect((31, 26, 60, 84), 3, PLUM, accent, 3.5)
    c.line([(37, 31), (53, 31)], accent, 3)
    c.line([(40, 43), (51, 54)], IVORY, 3)
    c.line([(51, 43), (40, 54)], IVORY, 3)
    c.rect((66, 45, 99, 84), 3, IVORY, PLUM, 3.5)
    c.ellipse((71, 50, 94, 73), PLUM, accent, 2.5)
    c.ellipse((90, 78, 93, 81), PLUM)


def _xbox_cloud(c, accent):
    c.poly([(37, 60), (29, 56), (26, 48), (29, 39), (38, 35), (44, 35),
            (47, 26), (56, 22), (65, 25), (71, 34), (82, 31), (93, 37),
            (99, 46), (96, 55), (89, 60)], IVORY, PLUM, 4)
    c.line([(51, 40), (60, 49)], accent, 3)
    c.line([(60, 40), (51, 49)], accent, 3)
    _controller(c, 65, 69, .85, accent)


def _pc(c, accent):
    c.rect((29, 27, 99, 73), 5, accent, PLUM, 4)
    c.rect((36, 34, 92, 66), 2, PLUM, None)
    c.rect((58, 74, 70, 81), 1, IVORY, PLUM, 3)
    c.rect((45, 82, 83, 87), 2, IVORY, PLUM, 2.5)
    c.poly([(55, 37), (74, 37), (73, 44), (67, 50), (73, 57),
            (74, 63), (55, 63), (56, 57), (61, 50), (56, 44)], IVORY, None)
    c.poly([(58, 39), (71, 39), (65, 47)], CORAL, None)
    c.poly([(58, 61), (65, 54), (71, 61)], PINK, None)
    c.line([(53, 36), (76, 36)], GOLD, 3)
    c.line([(53, 64), (76, 64)], GOLD, 3)


_DRAWERS = {
    'founder': _founder, 'bot': _bot, 'team_separator': _team,
    'admin': _admin, 'mod': _moderator, 'support': _support, 'creator': _creator,
    'community_separator': _community, 'legend': _legend, 'booster': _booster,
    'veteran': _veteran,
    'citizen': _citizen, 'crew': _crew, 'entry_separator': _entry, 'member': _member,
    'country_separator': _countries, 'region_separator': _regions,
    'preferences_separator': _platforms, 'caribbean': _caribbean,
    'central': _central, 'south': _south, 'north': _north,
    'greater_antilles': _antilles, 'ps': _playstation, 'xbox': _xbox,
    'xbox_one_cloud': _xbox_cloud, 'pc': _pc,
}
SYMBOL_KEYS = tuple(_DRAWERS)


def draw_symbol(c, key, accent=CYAN):
    """Render one named symbol into the caller's Canvas; never write files."""
    if isinstance(accent, int):
        accent = f'#{accent:06X}'
    try:
        painter = _DRAWERS[key]
    except KeyError:
        raise ValueError('Unknown VIce District role symbol: ' + str(key)) from None
    painter(c, accent)
