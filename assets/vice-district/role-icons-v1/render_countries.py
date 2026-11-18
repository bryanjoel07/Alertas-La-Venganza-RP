"""Original small flag subjects for the shared VIce District role badges.

The caller supplies a supersampled 128-unit Canvas with poly/line/ellipse/rect
methods. Only the flag subject is drawn; the common badge and VI branding belong
to the parent renderer. No raster files, fonts, remote assets or Canvas clones.

National stripe layouts, canton positions and star counts remain recognizable.
Coats of arms are deliberately simplified original pictograms for tiny role
icons, not official reproductions. Colors are a flat RGB screen palette.

Pattern references checked against primary sources:
https://bvirtualogp.pr.gov/ogp/Bvirtual/leyesreferencia/PDF/1-1952.pdf
https://www.tsc.gob.hn/index.php/2024/09/01/en-acto-solemne-el-tsc-rindio-tributo-a-la-bandera-nacional-en-su-dia/
https://uruguayeduca.anep.edu.uy/sites/default/files/exelearning/06-2026/15088/bandera_del_uruguay.html
https://mppre.gob.ve/publicacion/679-0
"""
import math


PLUM = '#24102F'
WHITE = '#FFFFFF'
GOLD = '#F6B40E'
GREEN = '#287A39'
BOX = (23, 28, 105, 82)
COUNTRY_KEYS = frozenset({
    'pr', 'argentina', 'bolivia', 'chile', 'colombia', 'costa_rica', 'cuba',
    'ecuador', 'el_salvador', 'guatemala', 'honduras', 'mexico', 'nicaragua',
    'panama', 'paraguay', 'peru', 'dominican_republic', 'uruguay', 'venezuela',
})


def _rect(c, box, color):
    c.rect(box, 0, color, None, 0)


def _horizontal(c, colors, weights=None):
    x0, y0, x1, y1 = BOX
    weights = weights or [1] * len(colors)
    unit = (y1 - y0) / sum(weights)
    y = y0
    for color, weight in zip(colors, weights):
        bottom = y + unit * weight
        _rect(c, (x0, y, x1, bottom), color)
        y = bottom


def _vertical(c, colors):
    x0, y0, x1, y1 = BOX
    step = (x1 - x0) / len(colors)
    for i, color in enumerate(colors):
        _rect(c, (x0 + i * step, y0, x0 + (i + 1) * step, y1), color)


def _star(c, x, y, radius, color=WHITE):
    points = []
    for i in range(10):
        angle = -math.pi / 2 + math.pi * i / 5
        r = radius if i % 2 == 0 else radius * .40
        points.append((x + math.cos(angle) * r, y + math.sin(angle) * r))
    c.poly(points, color, None)


def _sun(c, x, y, radius, rays):
    # Alternating long/short golden rays stay visible without a tiny facial mask.
    for i in range(rays):
        angle = i * math.tau / rays
        r = radius if i % 2 == 0 else radius * .86
        c.line([(x + math.cos(angle) * radius * .42,
                 y + math.sin(angle) * radius * .42),
                (x + math.cos(angle) * r, y + math.sin(angle) * r)], GOLD, .95)
    c.ellipse((x-radius*.48, y-radius*.48, x+radius*.48, y+radius*.48), GOLD)
    c.ellipse((x-radius*.20, y-radius*.20, x+radius*.20, y+radius*.20), '#FFC82E')


def _wreath(c, x, y, radius, color=GREEN):
    for side in (-1, 1):
        points = [(x + side * radius * .30, y + radius * .78),
                  (x + side * radius * .84, y + radius * .35),
                  (x + side * radius, y - radius * .26)]
        c.line(points, color, 1.6)
        for dx, dy in [(.50, .64), (.78, .25), (.90, -.12)]:
            px, py = x + side * radius * dx, y + radius * dy
            c.poly([(px, py+1), (px+side*2.4, py-2.4), (px-side*.6, py-2.1)], color, None)


def _central_triangle(c, wreath=False):
    # Original miniature shorthand: triangle, blue sea, five green volcanoes,
    # sunrise and cap. Nicaragua gets a gold seal ring, El Salvador a wreath.
    if wreath:
        _wreath(c, 64, 55, 11)
    else:
        c.ellipse((53, 44, 75, 66), WHITE, '#B38E2F', 1.2)
    c.poly([(64, 46), (55, 63), (73, 63)], '#D9F2FB', GOLD, 1.1)
    c.poly([(56, 60), (72, 60), (73, 63), (55, 63)], '#3BA7DA', None)
    for i in range(5):
        x = 57 + i * 3.5
        c.poly([(x-1.6, 60), (x, 56.3-i%2), (x+1.8, 60)], '#4B8C44', None)
    c.line([(60, 53), (62, 51.8), (66, 51.8), (68, 53)], '#F2B33E', 1)
    c.ellipse((62.7, 52.2, 65.3, 54.6), '#D52B36')


def _mexican_emblem(c):
    # Eagle-and-serpent silhouette over a cactus and laurel, kept deliberately
    # broader than the official fine heraldic detail for a 32px badge preview.
    _wreath(c, 64, 58, 10)
    c.line([(64, 62), (64, 57), (60, 57), (60, 54)], GREEN, 2.2)
    c.poly([(62, 55), (57, 50), (57, 45), (61, 46), (65, 51),
            (69, 49), (70, 53), (66, 58)], '#8E5B2E', None)
    c.ellipse((64, 46, 69, 51), '#8E5B2E')
    c.poly([(68, 48), (72, 49), (68, 50.6)], GOLD, None)
    c.line([(71, 49), (73, 52), (70, 54), (72, 57)], '#4C9A51', 1.5)
    c.line([(61, 53), (58, 48)], '#B67C35', 1)
    c.ellipse((66.5, 47.4, 67.5, 48.4), WHITE)


def _quetzal_emblem(c):
    _wreath(c, 64, 56, 12)
    c.line([(55, 63), (72, 47)], '#A18253', 1.2)
    c.line([(56, 48), (73, 62)], '#A18253', 1.2)
    c.rect((58, 51, 70, 61), 1, '#FFF0BC', '#B59C56', .8)
    c.line([(60, 54), (68, 54)], '#B59C56', .8)
    c.line([(60, 57), (67, 57)], '#B59C56', .8)
    c.line([(64, 48), (68, 49), (69, 52), (67, 64), (64, 68)], '#218C52', 2.8)
    c.ellipse((60, 45, 67, 50), '#218C52')
    c.poly([(61, 47), (58, 48), (61, 49)], GOLD, None)
    c.ellipse((62, 46.6, 63.1, 47.7), WHITE)


def _ecuador_emblem(c):
    # Condor above the oval shield distinguishes this from plain Colombia.
    c.poly([(54, 45), (62, 47), (64, 44), (66, 47), (74, 45),
            (69, 51), (64, 50), (59, 51)], '#3C2B25', None)
    for side in (-1, 1):
        c.poly([(64+side*6, 51), (64+side*11, 65), (64+side*7, 64)], '#D52B36', None)
        c.line([(64+side*8, 52), (64+side*11, 63)], GOLD, 1.2)
    c.ellipse((57, 49, 71, 67), '#67BBE4', '#C79D37', 1.8)
    c.poly([(58.8, 59), (63, 53), (67, 59)], WHITE, None)
    c.poly([(58, 61), (62, 57), (66, 61), (69, 58), (70, 65), (59, 65)], '#4C9B5A', None)
    c.line([(60, 64), (68, 64)], '#4B8BC9', 1.4)


def draw_country(c, key):
    """Draw one of the current 19 flag subjects; return False for unknown keys."""
    if key not in COUNTRY_KEYS:
        return False

    if key in ('pr', 'cuba'):
        stripe, triangle = ('#ED0000', '#0050A4') if key == 'pr' else ('#002A8F', '#CF142B')
        _horizontal(c, [stripe, WHITE, stripe, WHITE, stripe])
        c.poly([(23, 28), (69.76, 55), (23, 82)], triangle, None)
        _star(c, 39, 55, 9)
    elif key == 'argentina':
        _horizontal(c, ['#75AADB', WHITE, '#75AADB'])
        _sun(c, 64, 55, 7.8, 32)
    elif key == 'bolivia':
        _horizontal(c, ['#D52B1E', '#F9E300', '#007934'])
    elif key == 'chile':
        _horizontal(c, [WHITE, '#D52B1E'])
        _rect(c, (23, 28, 50, 55), '#0039A6')
        _star(c, 36.5, 41.5, 8)
    elif key in ('colombia', 'ecuador'):
        _horizontal(c, ['#FCD116', '#003893', '#CE1126'], [2, 1, 1])
        if key == 'ecuador':
            _ecuador_emblem(c)
    elif key == 'costa_rica':
        _horizontal(c, ['#002B7F', WHITE, '#CE1126', WHITE, '#002B7F'], [1, 1, 2, 1, 1])
    elif key == 'el_salvador':
        _horizontal(c, ['#0047AB', WHITE, '#0047AB'])
        _central_triangle(c, wreath=True)
    elif key == 'guatemala':
        _vertical(c, ['#4997D0', WHITE, '#4997D0'])
        _quetzal_emblem(c)
    elif key == 'honduras':
        blue = '#00BCE4'
        _horizontal(c, [blue, WHITE, blue])
        for x, y in [(53, 50), (75, 50), (64, 55), (53, 60), (75, 60)]:
            _star(c, x, y, 3.2, blue)
    elif key == 'mexico':
        _vertical(c, ['#006847', WHITE, '#CE1126'])
        _mexican_emblem(c)
    elif key == 'nicaragua':
        _horizontal(c, ['#0067C6', WHITE, '#0067C6'])
        _central_triangle(c)
    elif key == 'panama':
        _rect(c, BOX, WHITE)
        _rect(c, (64, 28, 105, 55), '#DA121A')
        _rect(c, (23, 55, 64, 82), '#072357')
        _star(c, 43.5, 41.5, 8, '#072357')
        _star(c, 84.5, 68.5, 8, '#DA121A')
    elif key == 'paraguay':
        _horizontal(c, ['#D52B1E', WHITE, '#0038A8'])
        c.ellipse((55.5, 46.5, 72.5, 63.5), WHITE, '#C99D35', 1.5)
        _wreath(c, 64, 55, 5.8)
        _star(c, 64, 53.4, 3.6, GOLD)
    elif key == 'peru':
        _vertical(c, ['#D91023', WHITE, '#D91023'])
    elif key == 'dominican_republic':
        _rect(c, BOX, WHITE)
        _rect(c, (23, 28, 59.5, 50.5), '#002D62')
        _rect(c, (68.5, 28, 105, 50.5), '#CE1126')
        _rect(c, (23, 59.5, 59.5, 82), '#CE1126')
        _rect(c, (68.5, 59.5, 105, 82), '#002D62')
        _wreath(c, 64, 55, 7.5)
        c.poly([(60, 50), (68, 50), (68, 58), (64, 61), (60, 58)], '#CE1126', None)
        _rect(c, (60, 50, 64, 55), '#002D62')
        _rect(c, (64, 55, 68, 58), '#002D62')
        c.line([(64, 50), (64, 59)], WHITE, 1.8)
        c.line([(60, 54.5), (68, 54.5)], WHITE, 1.8)
    elif key == 'uruguay':
        _horizontal(c, [WHITE, '#0038A8', WHITE, '#0038A8', WHITE,
                        '#0038A8', WHITE, '#0038A8', WHITE])
        _rect(c, (23, 28, 53, 58), WHITE)
        _sun(c, 38, 43, 10, 16)
    elif key == 'venezuela':
        _horizontal(c, ['#FCE300', '#003DA5', '#EF3340'])
        for i in range(8):
            angle = math.radians(205 + i * 130 / 7)
            _star(c, 64 + math.cos(angle) * 23, 64 + math.sin(angle) * 15, 2.55)

    # One consistent heavy edge joins every subject to the plum VIce badge.
    c.line([(23, 28), (105, 28), (105, 82), (23, 82), (23, 28)], PLUM, 4)
    return True
