"""Original vector/canvas emoji animations; no source raster artwork is edited.

Rebuild: python assets/vice-district/emojis-v2/animated/render.py
Requires Pillow. Geometry is drawn at 4x and encoded with one shared palette per GIF.
"""
from pathlib import Path
import json
import math
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
FONT = OUT.parents[2] / 'esschino' / 'fonts' / 'NotoSans-Bold.ttf'
S, N = 4, 20
PLUM = '#24102F'
PINK = '#FF258D'
CORAL = '#FF785E'
CYAN = '#33E5E9'
IVORY = '#FFF4DB'
PURPLE = '#8C4DE7'


class Canvas:
    def __init__(self):
        self.im = Image.new('RGBA', (128*S, 128*S))
        self.d = ImageDraw.Draw(self.im)

    def poly(self, points, fill, stroke=PLUM, width=3):
        p = [(round(x*S), round(y*S)) for x,y in points]
        self.d.polygon(p, fill=fill)
        if stroke:
            self.d.line(p + [p[0]], fill=stroke, width=round(width*S), joint='curve')

    def line(self, points, fill, width):
        self.d.line([(round(x*S),round(y*S)) for x,y in points], fill=fill, width=round(width*S), joint='curve')

    def ellipse(self, box, fill, stroke=None, width=1):
        self.d.ellipse(tuple(round(v*S) for v in box), fill=fill, outline=stroke, width=round(width*S))

    def roundrect(self, box, radius, fill, stroke=PLUM, width=3):
        self.d.rounded_rectangle(tuple(round(v*S) for v in box), radius=round(radius*S), fill=fill, outline=stroke, width=round(width*S))

    def text(self, xy, text, size, fill=IVORY, stroke=PLUM, width=3):
        font=ImageFont.truetype(str(FONT), round(size*S))
        self.d.text((round(xy[0]*S),round(xy[1]*S)), text, font=font, anchor='mm', fill=fill,
                    stroke_width=round(width*S), stroke_fill=stroke)

    def arc(self, box, start, end, color, width):
        self.d.arc(tuple(round(v*S) for v in box), start, end, fill=color, width=round(width*S))

    def finish(self):
        return self.im.resize((128,128), Image.Resampling.LANCZOS)


def star(c,x,y,r,fill=IVORY,phase=0):
    pts=[]
    for i in range(10):
        a=phase - math.pi/2 + i*math.pi/5
        rr=r if i%2==0 else r*.43
        pts.append((x+math.cos(a)*rr,y+math.sin(a)*rr))
    c.poly(pts,fill,PLUM,1.5)


def palm(c,x,y,scale=1,sway=0):
    # Compact native vector silhouette: curved trunk and five arching fronds.
    def p(px,py): return (x+px*scale,y+py*scale)
    c.poly([p(-5,33),p(5,34),p(3,18),p(0,4),p(-4,4),p(-1,20)],CORAL,PLUM,2.5*scale)
    fronds=[[(0,3),(-8,-14),(-26,-12),(-15,-6)],
            [(0,2),(-13,-2),(-31,7),(-14,5)],
            [(0,1),(6,-18),(23,-20),(13,-10)],
            [(1,2),(19,-11),(34,1),(15,-1)],
            [(1,2),(13,6),(18,21),(7,10)]]
    for points in fronds:
        c.poly([p(px+sway*(1-min(abs(py),30)/40),py) for px,py in points],CYAN,PLUM,2.2*scale)
    c.ellipse((x-3*scale,y-1*scale,x+5*scale,y+7*scale),PINK,PLUM,1.5*scale)


def vi(t):
    c=Canvas(); q=(math.sin(t)+1)/2
    c.ellipse((8,12,120,123),PLUM)
    c.ellipse((12,16,116,119),PINK)
    c.ellipse((17,21,111,114),PLUM)
    c.arc((17,21,111,114),205,320,CYAN,5)
    c.arc((17,21,111,114),25,140,CORAL,5)
    palm(c,88,29,.72,2*math.sin(t))
    c.text((58,77),'VI',59,IVORY,PLUM,5)
    c.line([(33,104),(86,104)],PINK,3+q*2)
    star(c,19,33,7+q,CYAN)
    return c.finish()


def wepa(t):
    c=Canvas(); y=4*math.sin(t)
    # Star pennant uses the Puerto Rican red/white/blue visual vocabulary.
    c.poly([(17,32+y),(99,21+y),(113,95+y),(29,110+y)],PLUM,PLUM,4)
    c.poly([(13,28+y),(96,17+y),(110,91+y),(25,105+y)],PINK,PLUM,4)
    c.line([(21,37+y),(96,27+y)],IVORY,5)
    c.line([(29,95+y),(104,82+y)],CYAN,5)
    c.ellipse((40,6+y,71,37+y),'#246BC9',PLUM,3)
    star(c,55.5,21.5+y,11)
    c.text((62,60+y),'WEPA',33,IVORY,PLUM,3)
    star(c,113,40-y,8,CYAN,math.sin(t)*.13)
    star(c,12,87-y,7,CORAL)
    return c.finish()


def alerta(t):
    c=Canvas(); x=64+20*math.sin(t)
    c.ellipse((22,103,107,119),PLUM)
    # Smooth traveling highlight, no hard flash.
    c.poly([(34,94),(34,51),(42,33),(54,26),(76,26),(89,36),(97,54),(97,94)],PINK,PLUM,5)
    c.poly([(38,85),(38,52),(45,37),(54,31),(64,30),(64,87)],CORAL,None)
    c.roundrect((x-7,40,x+4,79),5,IVORY,None)
    c.roundrect((23,88,106,108),8,PLUM,None)
    c.roundrect((27,91,102,103),4,CYAN,None)
    for ray in [[(25,24),(17,18)],[(64,16),(64,7)],[(103,24),(111,18)]]:
        c.line(ray,PLUM,8)
        c.line(ray,CYAN,4)
    return c.finish()


def cargando(t):
    c=Canvas()
    c.ellipse((5,5,123,123),PLUM)
    c.ellipse((13,13,115,115),PURPLE)
    c.ellipse((20,20,108,108),PLUM)
    phase=t*180/math.pi
    c.arc((10,10,118,118),phase,phase+125,CYAN,7)
    c.arc((10,10,118,118),phase+150,phase+275,PINK,7)
    palm(c,62,54,1.05,2*math.sin(t))
    c.line([(43,95),(80,95)],IVORY,4)
    return c.finish()


def hype(t):
    c=Canvas(); sway=5*math.sin(t); squeeze=2*math.cos(t)
    # Flame is a full canvas vector polygon with smooth looped movement.
    outer=[(64+sway,7),(72+sway,31),(66,45),(89+squeeze,34),(84,59),
           (103,72),(108,91),(100,107),(83,118),(56,121),(34,116),(20,101),
           (18,82),(28,63),(29,44),(42,57),(47,36)]
    c.poly(outer,PINK,PLUM,5)
    inner=[(62+sway/2,34),(65,59),(78,53),(74,76),(90,89),(88,102),
           (76,111),(58,114),(41,105),(35,92),(40,76),(50,85),(51,60)]
    c.poly(inner,CORAL,None)
    c.poly([(61,68),(66,88),(74,84),(77,98),(69,108),(56,108),(49,98),(54,88)],IVORY,None)
    # Cheeky little excited face remains readable at emoji size.
    c.ellipse((38,79,45,89),PLUM);c.ellipse((77,79,84,89),PLUM)
    c.arc((48,82,75,103),0,180,PLUM,4)
    star(c,17,25,6,CYAN,math.sin(t)*.2)
    star(c,107,48,6,CYAN)
    return c.finish()


def rip(t):
    c=Canvas(); bob=4*math.sin(t)
    c.ellipse((14,106,114,124),PLUM)
    c.roundrect((19,22,92,114),29,PLUM,None)
    c.roundrect((24,27,87,110),25,PURPLE,PLUM,3)
    c.line([(31,104),(80,104)],PINK,5)
    c.text((55,75),'RIP',34,IVORY,PLUM,2)
    # A rounded ghost with three scallops, constructed from vector points.
    ghost=[(79,20+bob),(82,10+bob),(92,5+bob),(105,7+bob),(113,17+bob),
           (115,47+bob),(106,42+bob),(99,49+bob),(91,42+bob),(82,48+bob)]
    c.poly(ghost,IVORY,PLUM,3)
    c.ellipse((88,20+bob,93,28+bob),PLUM)
    c.ellipse((102,20+bob,107,28+bob),PLUM)
    c.ellipse((95,31+bob,100,37+bob),PLUM)
    star(c,15,25-bob,7,CYAN)
    return c.finish()


ASSETS=[
    ('vd_vi_neon',vi,'Insignia VI de neón con palmera y brillo suave'),
    ('vd_wepa',wepa,'WEPA boricua rebotando con estrella y acentos tropicales'),
    ('vd_alerta',alerta,'Sirena del distrito con reflejo móvil suave'),
    ('vd_cargando',cargando,'Palmera dentro de un aro de carga neón giratorio'),
    ('vd_hype',hype,'Fuego del corillo con expresión emocionada'),
    ('vd_rip',rip,'Lápida RIP con fantasmita flotante para los fails'),
]


def encode(frames,path):
    # Reserve palette index zero for transparency, shared across all frames.
    sample=Image.new('RGB',(128*N,128))
    for i,im in enumerate(frames): sample.paste(im.convert('RGB'),(128*i,0))
    base=sample.quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    palette=Image.new('P',(1,1))
    palette.putpalette([0,0,0]+base.getpalette()[:765])
    indexed=[]
    for im in frames:
        f=im.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE)
        f.paste(0,mask=im.getchannel('A').point(lambda a:255 if a<128 else 0))
        f.info['transparency']=0
        indexed.append(f)
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=120,loop=0,
                    transparency=0,disposal=2,optimize=False)


def main():
    manifest={'mode':'original vector animation','renderer':'render.py (Pillow high-resolution vector/canvas geometry)',
              'frame_count':N,'frame_duration_ms':120,'loop':'infinite','assets':[]}
    sheet=Image.new('RGB',(3*256,2*286),'#221B29')
    for j,(name,func,description) in enumerate(ASSETS):
        frames=[func(2*math.pi*i/N) for i in range(N)]
        dest=OUT/(name+'.gif'); encode(frames,dest)
        frames[N//4].save(OUT/(name+'-preview.png'))
        im=Image.open(dest)
        rgba=im.convert('RGBA')
        assert im.size==(128,128) and im.n_frames==N and im.info['loop']==0
        assert dest.stat().st_size<=256*1024 and rgba.getchannel('A').getextrema()==(0,255)
        unique=set()
        for k in range(N):im.seek(k);unique.add(im.convert('RGBA').tobytes())
        assert len(unique)>5,(name,len(unique))
        manifest['assets'].append(dict(name=name,path='assets/vice-district/emojis-v2/animated/'+name+'.gif',
            description=description,bytes=dest.stat().st_size,width=128,height=128,frames=N,
            distinct_frames=len(unique),duration_ms=N*120,transparent=True,
            prompt='Original vector design: '+description+'. Neon plum/coral/pink/cyan; no official game logo. Smooth 2.4-second loop.'))
        x=(j%3)*256;y=(j//3)*286
        sheet.paste(frames[N//4].resize((230,230),Image.Resampling.NEAREST),(x+13,y+6),frames[N//4].resize((230,230),Image.Resampling.NEAREST))
        d=ImageDraw.Draw(sheet);d.text((x+128,y+255),name,fill='white',anchor='mm',font=ImageFont.truetype(str(FONT),17))
        print(name,dest.stat().st_size,len(unique))
    sheet.save(OUT/'preview-sheet.png')
    actual=Image.new('RGB',(768,184),'#313338')
    for j,(name,_,_) in enumerate(ASSETS):
        encoded=Image.open(OUT/(name+'.gif'))
        encoded.seek(5)
        rgba=encoded.convert('RGBA')
        actual.paste(rgba,(j*128,0),rgba)
        small=rgba.resize((32,32),Image.Resampling.LANCZOS)
        actual.paste(small,(j*128+48,140),small)
    actual.save(OUT/'gif-actual-size-check.png')
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
