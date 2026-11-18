"""Original VIce District role badges, extending the server's code-native art.

No reference raster is modified. All art is drawn from canvas primitives.
Run with the repository Python environment; exports 64px PNGs and 256px masters.
"""
from pathlib import Path
import hashlib
import json
import math
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
from vice_design import ROLES
from vice_role_catalog import COUNTRY_KEYS
from render_countries import draw_country
from render_symbols import draw_symbol

FONT = ROOT / 'assets/esschino/fonts/NotoSans-Bold.ttf'
S = 4
PLUM, PINK, CYAN, IVORY = '#24102F', '#FF258D', '#33E5E9', '#FFF4DB'


class Canvas:
    def __init__(self):
        self.im = Image.new('RGBA', (128*S, 128*S))
        self.d = ImageDraw.Draw(self.im)

    def poly(self, points, fill, stroke=PLUM, width=4):
        points = [(round(x*S), round(y*S)) for x,y in points]
        self.d.polygon(points, fill=fill)
        if stroke:
            self.d.line(points+[points[0]], fill=stroke, width=max(1,round(width*S)), joint='curve')

    def line(self, points, fill, width):
        self.d.line([(round(x*S),round(y*S)) for x,y in points], fill=fill,
                    width=max(1,round(width*S)), joint='curve')

    def ellipse(self, box, fill, stroke=None, width=1):
        self.d.ellipse(tuple(round(v*S) for v in box), fill=fill, outline=stroke,
                       width=max(1,round(width*S)))

    def rect(self, box, radius, fill, stroke=PLUM, width=4):
        self.d.rounded_rectangle(tuple(round(v*S) for v in box), radius=round(radius*S),
                                 fill=fill, outline=stroke, width=max(1,round(width*S)))

    def text(self, xy, word, size, fill=IVORY, width=2):
        self.d.text((round(xy[0]*S),round(xy[1]*S)), word,
                    font=ImageFont.truetype(str(FONT), round(size*S)), anchor='mm', fill=fill,
                    stroke_width=round(width*S), stroke_fill=PLUM)


def badge(accent):
    c = Canvas()
    c.rect((8,8,120,120),24,PLUM,accent,3)
    c.rect((12,12,116,116),20,'#34183F',None)
    # Sunset disc and boulevard accents echo the server's Miami/VI art.
    c.ellipse((24,15,104,95),'#673255')
    c.line([(24,64),(104,64)],'#9B426D',2)
    c.line([(27,72),(101,72)],'#9B426D',2)
    c.line([(33,80),(95,80)],'#9B426D',2)
    c.line([(14,28),(14,78)],CYAN,2)
    c.line([(114,43),(114,96)],PINK,2)
    # A small palm mark is part of every badge's frame, outside the main symbol.
    c.line([(22,113),(24,100),(29,91)],CYAN,3)
    for pts in [[(29,91),(20,89),(15,93)],[(29,91),(25,85),(18,84)],
                [(29,91),(36,87),(42,89)],[(29,91),(35,93),(39,99)]]:
        c.line(pts,CYAN,2)
    return c


def render():
    roles = json.loads((OUT/'live-roles.json').read_text(encoding='utf-8'))
    by_name = {r['name']:r for r in roles}
    specs = [('founder','👑 Fundador',0xFF6B6A),('bot','🤖 EssChino Studio Bot',0x3498DB),
             ('booster','Server Booster',16023551)]
    specs += [(key,name,color) for key,name,color,*_ in ROLES]
    assert len(specs)==46 and len(roles)==46
    assert {name for _,name,_ in specs}==set(by_name)
    (OUT/'png').mkdir(exist_ok=True)
    (OUT/'masters').mkdir(exist_ok=True)
    manifest = dict(version='vice-role-icons-v1',guild_id='1572462544302383164',
        status='prepared_not_installed',capability='ROLE_ICONS',checked_boost_level=1,
        design='Original code-native VI sunset badges; plum, magenta, cyan, ivory; existing role symbols.',
        roles=[])
    columns, cw, ch = 5, 250, 156
    sheet = Image.new('RGB',(columns*cw,math.ceil(len(specs)/columns)*ch+100),'#17121F')
    d=ImageDraw.Draw(sheet)
    d.text((28,18),'VICE DISTRICT / ROLE ICONS',font=ImageFont.truetype(str(FONT),30),fill=IVORY)
    d.text((28,62),'46 insignias · GTA VI Latino · Puerto Rico',font=ImageFont.truetype(str(FONT),17),fill=CYAN)
    for index,(key,name,color) in enumerate(specs):
        accent=f'#{color:06X}'
        c=badge(accent)
        if key in COUNTRY_KEYS:
            assert draw_country(c,key) is not False,key
        else:
            assert draw_symbol(c,key,accent) is not False,key
        c.rect((44,91,99,118),8,PLUM,None)
        c.text((71,103),'VI',29,IVORY,0)
        c.line([(48,118),(95,118)],PINK,2)
        master=c.im.resize((256,256),Image.Resampling.LANCZOS)
        small=c.im.resize((64,64),Image.Resampling.LANCZOS)
        master.save(OUT/'masters'/f'{key}.png',optimize=True)
        dest=OUT/'png'/f'{key}.png'
        small.save(dest,optimize=True)
        raw=dest.read_bytes()
        assert len(raw)<256*1024
        assert small.getchannel('A').getextrema()==(0,255)
        assert small.getchannel('A').getbbox()[0]>0
        role=by_name[name]
        manifest['roles'].append(dict(key=key,id=role['id'],name=name,path=f'png/{key}.png',
            master=f'masters/{key}.png',color=accent,sha256=hashlib.sha256(raw).hexdigest(),
            bytes=len(raw),width=64,height=64,
            application='owner_session' if key in {'founder','bot','booster'} else 'bot_when_unlocked'))
        x,y=(index%columns)*cw,(index//columns)*ch+100
        sheet.paste(master.resize((96,96),Image.Resampling.LANCZOS),(x+18,y+6),
                    master.resize((96,96),Image.Resampling.LANCZOS))
        sheet.paste(small,(x+131,y+8),small)
        tiny=small.resize((24,24),Image.Resampling.LANCZOS)
        sheet.paste(tiny,(x+151,y+78),tiny)
        clean=name.replace('━━','').strip()
        if not clean[0].isalnum():
            clean=' '.join(clean.split()[1:])
        font=ImageFont.truetype(str(FONT),14)
        while font.getlength(clean)>cw-24:
            font=ImageFont.truetype(str(FONT),font.size-1)
        d.text((x+12,y+119),clean,font=font,fill=IVORY)
    assert len({r['sha256'] for r in manifest['roles']})==46,'Icons must be individually distinct'
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sheet.save(OUT/'preview.png')
    with zipfile.ZipFile(OUT/'VIce-District-iconos-roles.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT.rglob('*')):
            if path.is_file() and path.suffix in {'.png','.json','.py','.md'} and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(OUT).as_posix())
    print(json.dumps(dict(icons=len(specs),max_png_bytes=max(r['bytes'] for r in manifest['roles']),
                         preview=str(OUT/'preview.png'),zip=str(OUT/'VIce-District-iconos-roles.zip'))))


if __name__=='__main__':
    render()
