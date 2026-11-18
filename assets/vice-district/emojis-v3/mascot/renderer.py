"""Six original coqui vector animations; no reference raster pixels are used.

Draw scalable paths at 4x, rasterize to 128px, and encode a shared GIF palette.
Run from any directory: python renderer.py
"""
from pathlib import Path
import hashlib
import json
import math
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
FONT = OUT.parents[2] / 'esschino' / 'fonts' / 'NotoSans-Bold.ttf'
S, N, MS = 4, 24, 100
PLUM = '#291036'
PINK = '#FF2995'
MINT = '#75F3BA'
JADE = '#35C99A'
IVORY = '#FFF4DB'
CYAN = '#3DE9F4'
CORAL = '#FF786E'
PURPLE = '#A36BEE'


def wave(t):
    return math.sin(t)


def bezier(start, *segments):
    result = [start]
    for a, b, end in segments:
        x, y = result[-1]
        for i in range(1, 15):
            u = i / 14
            v = 1 - u
            result.append((v*v*v*x + 3*v*v*u*a[0] + 3*v*u*u*b[0] + u*u*u*end[0],
                           v*v*v*y + 3*v*v*u*a[1] + 3*v*u*u*b[1] + u*u*u*end[1]))
    return result


class Canvas:
    def __init__(self, sx=1, sy=1, dx=0, dy=0, angle=0):
        self.im = Image.new('RGBA', (128*S, 128*S))
        self.d = ImageDraw.Draw(self.im)
        self.sx, self.sy, self.dx, self.dy, self.angle = sx, sy, dx, dy, angle

    def point(self, p):
        x, y = (p[0]-64)*self.sx, (p[1]-67)*self.sy
        a = self.angle
        return (round((64+self.dx+x*math.cos(a)-y*math.sin(a))*S),
                round((67+self.dy+x*math.sin(a)+y*math.cos(a))*S))

    def poly(self, pts, fill, stroke=None, width=3):
        p = [self.point(v) for v in pts]
        self.d.polygon(p, fill=fill)
        if stroke:
            self.d.line(p+[p[0]], fill=stroke, width=round(width*S), joint='curve')

    def line(self, pts, fill=PLUM, width=4):
        p = [self.point(v) for v in pts]
        w = round(width*S)
        self.d.line(p, fill=fill, width=w, joint='curve')
        for q in [p[0], p[-1]]:
            self.d.ellipse((q[0]-w/2, q[1]-w/2, q[0]+w/2, q[1]+w/2), fill=fill)

    def ellipse(self, box, fill, stroke=None, width=3):
        x, y, r, b = box
        pts = [((x+r)/2+(r-x)/2*math.cos(i*math.tau/64),
                (y+b)/2+(b-y)/2*math.sin(i*math.tau/64)) for i in range(64)]
        self.poly(pts, fill, stroke, width)

    def arc(self, box, start, end, fill=PLUM, width=4):
        x, y, r, b = box
        self.line([((x+r)/2+(r-x)/2*math.cos(math.radians(start+(end-start)*i/32)),
                    (y+b)/2+(b-y)/2*math.sin(math.radians(start+(end-start)*i/32)))
                   for i in range(33)], fill, width)

    def finish(self):
        return self.im.resize((128, 128), Image.Resampling.LANCZOS)


HEAD = bezier((11, 61),
    ((4, 43), (8, 24), (22, 16)),
    ((37, 8), (51, 19), (54, 38)),
    ((61, 36), (67, 36), (74, 38)),
    ((78, 19), (91, 8), (106, 16)),
    ((121, 25), (124, 45), (116, 61)),
    ((125, 75), (121, 96), (108, 108)),
    ((88, 125), (39, 125), (20, 108)),
    ((6, 96), (2, 76), (11, 61)))


def head(c, cheeks=True):
    c.poly(HEAD, PINK, PINK, 7)
    c.poly(HEAD, MINT, PLUM, 3.3)
    c.arc((12, 49, 116, 118), 30, 150, JADE, 7)
    c.line(bezier((18, 37), ((20, 24), (33, 18), (40, 26))), IVORY, 3.5)
    c.line(bezier((87, 26), ((94, 20), (105, 25), (109, 36))), IVORY, 3.5)
    if cheeks:
        c.ellipse((13, 66, 32, 79), CORAL)
        c.ellipse((96, 66, 115, 79), CORAL)
    c.ellipse((54, 57, 59, 61), PLUM)
    c.ellipse((69, 57, 74, 61), PLUM)


def eye_whites(c):
    c.ellipse((18, 29, 49, 61), IVORY, PLUM, 3)
    c.ellipse((79, 29, 110, 61), IVORY, PLUM, 3)


def eyes_open(c, look=0, blink=0):
    if blink > .5:
        c.arc((19, 36, 49, 59), 200, 340, width=4.5)
        c.arc((79, 36, 109, 59), 200, 340, width=4.5)
    else:
        eye_whites(c)
        for x in (34+look, 94+look):
            c.ellipse((x-7, 34, x+7, 55), PLUM)
            c.ellipse((x-3, 37, x+1.5, 43), IVORY)


def eyes_laugh(c):
    eye_whites(c)
    c.line(bezier((21, 51), ((30, 38), (39, 38), (46, 51))), width=5)
    c.line(bezier((82, 51), ((89, 38), (99, 38), (107, 51))), width=5)


def mouth(c, height=35):
    top = 70
    c.poly(bezier((34, top), ((48, top+6), (80, top+6), (94, top)),
                  ((91, top+height), (37, top+height), (34, top))), PLUM)
    c.poly(bezier((43, top+4), ((56, top+7), (72, top+7), (85, top+4)),
                  ((78, top+14), (49, top+14), (43, top+4))), IVORY)
    c.ellipse((50, top+height*.56, 78, top+height*.82), CORAL)


def heart(c, x, y, r, fill=PINK, outline=PLUM):
    pts = bezier((x, y+r),
        ((x-r*1.8, y), (x-r*.9, y-r*1.5), (x, y-r*.5)),
        ((x+r*.9, y-r*1.5), (x+r*1.8, y), (x, y+r)))
    c.poly(pts, fill, outline, 2.5)


def drop(c, x, y, size=9):
    pts = bezier((x, y-size),
        ((x-size*.5, y-size*.3), (x-size, y+size*.3), (x-size*.55, y+size*.65)),
        ((x, y+size*1.1), (x+size*.8, y+size*.6), (x+size*.65, y+size*.2)),
        ((x+size*.5, y-size*.3), (x+size*.2, y-size*.5), (x, y-size)))
    c.poly(pts, CYAN, PLUM, 2.3)
    c.line([(x-size*.22, y), (x-size*.15, y+size*.3)], IVORY, 2)


def star(c, x, y, r, fill=IVORY):
    c.poly([(x, y-r), (x+r*.3, y-r*.3), (x+r, y), (x+r*.3, y+r*.3),
            (x, y+r), (x-r*.3, y+r*.3), (x-r, y), (x-r*.3, y-r*.3)], fill, PLUM, 1.5)


def fiesta(t):
    c = Canvas(sx=.84+.035*math.cos(2*t), sy=.84-.045*math.cos(2*t),
               dx=4*math.sin(t), dy=3*math.cos(2*t), angle=.115*math.sin(t))
    # Tiny hands swing from the main silhouette; confetti travels in loops.
    c.ellipse((-1, 78+5*math.sin(t), 19, 97+5*math.sin(t)), MINT, PLUM, 3)
    c.ellipse((110, 78-5*math.sin(t), 129, 97-5*math.sin(t)), MINT, PLUM, 3)
    head(c); eyes_laugh(c); mouth(c, 37+6*math.cos(2*t))
    # Puerto Rican inspired party hat: coral and ivory stripes, cyan pompom.
    c.poly([(46, 24), (58, -5), (79, 23)], CORAL, PLUM, 3)
    c.poly([(52, 12), (57, 2), (68, 12)], IVORY)
    c.ellipse((53, -8, 64, 3), CYAN, PLUM, 2)
    c.sx=c.sy=1; c.dx=c.dy=c.angle=0
    for j, (x, y, color) in enumerate([(10,25,CYAN),(117,18,PINK),(13,113,IVORY),(114,108,CORAL)]):
        a=t+j*1.2
        c.line([(x+3*math.sin(a),y+4*math.cos(a)),
                (x+3*math.sin(a)+4*math.cos(a),y+4*math.cos(a)+4*math.sin(a))], color, 3.5)
    return c.finish()


def carcajada(t):
    c = Canvas(sx=.93+.025*math.cos(2*t), sy=.91-.04*math.cos(2*t),
               dy=1.5*math.sin(t), angle=.035*math.sin(t))
    head(c); eyes_laugh(c); mouth(c, 45+11*math.sin(2*t))
    # Tears rock far enough to read clearly at reaction size.
    drop(c, 12-4*math.sin(t), 60+8*math.cos(t), 10)
    drop(c, 116+4*math.sin(t), 60-8*math.cos(t), 10)
    c.line([(9,93),(4,99)], CORAL, 3)
    c.line([(118,93),(124,99)], CORAL, 3)
    return c.finish()


def llanto(t):
    c = Canvas(sx=.92, sy=.92, dy=2.5*math.sin(2*t), angle=.035*math.sin(t))
    head(c, False)
    eye_whites(c)
    c.line(bezier((20,43), ((29,51), (38,51), (47,42))), width=5)
    c.line(bezier((81,42), ((91,51), (100,51), (109,43))), width=5)
    c.line([(24,26),(42,31)], PLUM,4)
    c.line([(85,31),(104,26)], PLUM,4)
    # Broad constant streams, with visibly travelling ivory highlights.
    for j, x in enumerate((24, 104)):
        pts = bezier((x-6,51), ((x-9,70), (x-6,88), (x-12,112)),
                     ((x-6,121), (x+7,121), (x+12,112)),
                     ((x+5,89), (x+9,70), (x+6,51)))
        c.poly(pts,CYAN,PLUM,2)
        for k in range(2):
            yy=57+((t/math.tau*49+k*25+j*8)%49)
            c.line([(x-2, yy),(x-1,yy+9)], IVORY,3.2)
    h = 9+4*math.sin(2*t)
    c.ellipse((48,83-h,80,96+h), PLUM)
    c.ellipse((55,93,73,100+h), CORAL)
    return c.finish()


def steam(c, x, t, phase):
    # Curl moves up and sideways through a continuous vapor cycle.
    a=t+phase
    y=29+6*math.cos(a)
    c.line(bezier((x,y+10), ((x-10,y+1),(x+8,y-7),(x,y-17))), IVORY,6)
    c.line(bezier((x,y+10), ((x-10,y+1),(x+8,y-7),(x,y-17))), PLUM,1.6)


def rabia(t):
    c = Canvas(sx=.91+.022*math.cos(2*t), sy=.90, dx=2.2*math.sin(3*t), dy=4)
    head(c, False)
    eye_whites(c)
    for x in (34,94):
        c.ellipse((x-5,42,x+6,58),PLUM)
    c.poly([(15,28),(51,43),(49,50),(18,39)], MINT)
    c.poly([(77,43),(113,28),(110,39),(79,50)], MINT)
    c.line([(19,35),(49,47)],PLUM,6)
    c.line([(79,47),(109,35)],PLUM,6)
    c.ellipse((12,66,37,84),CORAL)
    c.ellipse((91,66,116,84),CORAL)
    c.poly(bezier((37,87),((47,75),(81,75),(91,87)),((81,99),(47,99),(37,87))), IVORY,PLUM,4)
    c.line([(40,87),(89,87)],PLUM,2)
    for x in (51,64,77): c.line([(x,80),(x,94)],PLUM,2)
    c.line([(62,29),(62,36),(68,36),(68,43)],PINK,3)
    c.line([(57,33),(62,33)],PINK,3)
    c.sx=c.sy=1;c.dx=c.dy=c.angle=0
    steam(c,12+2*math.sin(t),t,0)
    steam(c,116+2*math.cos(t),t,math.pi)
    return c.finish()


def amor(t):
    c=Canvas(sx=.91,sy=.91,dy=1.8*math.sin(t),angle=.045*math.sin(t))
    head(c)
    heart(c,34,44,14+1.6*math.sin(2*t),PINK)
    heart(c,94,44,14+1.6*math.sin(2*t),PINK)
    c.arc((43,62,85,91),0,180,width=4)
    # Hands hold a big heartbeat; a small orbiting heart reinforces motion.
    beat=1+.11*math.sin(2*t)+.035*math.sin(4*t)
    heart(c,64,103,19*beat,CORAL)
    c.ellipse((26,94,46,110),MINT,PLUM,3)
    c.ellipse((82,94,102,110),MINT,PLUM,3)
    heart(c,64+10*math.sin(t),15+3*math.cos(t),7,PINK)
    return c.finish()


def salute_hand(c, angle):
    # A chunky three-finger waving hand rotates around its wrist.
    pts=bezier((96,101),((90,88),(88,79),(92,75)),
        ((95,72),(97,77),(100,81)),((97,68),(95,58),(99,57)),
        ((103,55),(105,66),(106,72)),((104,57),(105,49),(109,49)),
        ((113,50),(113,66),(114,73)),((115,59),(117,57),(120,59)),
        ((123,62),(119,78),(120,83)),((122,94),(113,104),(105,106)))
    pivot=(104,102)
    def rotate(p):
        x,y=p[0]-pivot[0],p[1]-pivot[1]
        return (pivot[0]+x*math.cos(angle)-y*math.sin(angle),
                pivot[1]+x*math.sin(angle)+y*math.cos(angle))
    c.poly([rotate(p) for p in pts], PINK, PINK,6)
    c.poly([rotate(p) for p in pts], MINT,PLUM,3)
    c.line([rotate(p) for p in [(100,83),(106,87),(110,83)]],JADE,3)


def saludo(t):
    c=Canvas(sx=.79,sy=.83,dx=-10,dy=4,angle=.025*math.sin(t))
    head(c)
    blink = max(0, math.cos(t-1.7))**24
    eyes_open(c,2*math.sin(t),blink)
    mouth(c,29)
    c.sx=c.sy=1;c.dx=c.dy=c.angle=0
    salute_hand(c,.23*math.sin(2*t)-.05)
    c.line([(102,32),(104,25+2*math.sin(t))],IVORY,3)
    c.line([(115,36),(121,32+2*math.cos(t))],CYAN,3)
    return c.finish()


ASSETS=[
 ('vd_coqui_fiesta',fiesta,'Coqui del corillo bailando con gorrito y confeti; inclinacion y squash/stretch'),
 ('vd_coqui_carcajada',carcajada,'Coqui atacado de risa, boca que se abre y lagrimas rebotando'),
 ('vd_coqui_llanto',llanto,'Coqui llorando dramaticamente, rios de lagrimas y sollozo'),
 ('vd_coqui_rabia',rabia,'Coqui furioso con mejillas coral, dientes apretados y vapor en movimiento'),
 ('vd_coqui_amor',amor,'Coqui enamorado con ojos de corazon y un gran corazon que late entre sus manos'),
 ('vd_coqui_saludo',saludo,'Coqui sonriente saludando con una mano que gira y parpadeo'),
]


def encode(frames,path):
    sample=Image.new('RGB',(128*N,128))
    for i,im in enumerate(frames): sample.paste(im.convert('RGB'),(128*i,0))
    base=sample.quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    palette=Image.new('P',(1,1));palette.putpalette([0,0,0]+base.getpalette()[:765])
    indexed=[]
    for im in frames:
        f=im.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE)
        f.paste(0,mask=im.getchannel('A').point(lambda a:255 if a<128 else 0))
        f.info['transparency']=0;indexed.append(f)
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=MS,loop=0,
                    transparency=0,disposal=2,optimize=False)


def main():
    font=ImageFont.truetype(str(FONT),14)
    manifest={'mode':'original vector animation','renderer':'renderer.py',
              'style':'VIce District coqui; mint, plum, fuchsia, coral, cyan and ivory',
              'frame_count':N,'frame_duration_ms':MS,'loop':'infinite','assets':[]}
    sheet=Image.new('RGB',(720,6*180),'#313338');draw=ImageDraw.Draw(sheet)
    for row,(name,func,description) in enumerate(ASSETS):
        frames=[func(math.tau*i/N) for i in range(N)]
        path=OUT/(name+'.gif');encode(frames,path)
        frames[6].save(OUT/(name+'-preview.png'))
        im=Image.open(path);actual=[];durations=[]
        assert im.size==(128,128) and im.n_frames==N and im.info['loop']==0
        for k in range(im.n_frames):
            im.seek(k);rgba=im.convert('RGBA');actual.append(rgba.copy())
            durations.append(im.info['duration'])
            assert rgba.getchannel('A').getextrema()==(0,255)
        unique=len({i.tobytes() for i in actual})
        assert unique>=20 and path.stat().st_size<=256*1024
        bounding=actual[0].getbbox()
        manifest['assets'].append(dict(name=name,path='assets/vice-district/emojis-v3/mascot/'+name+'.gif',
            description=description,bytes=path.stat().st_size,width=128,height=128,frames=N,
            distinct_frames=unique,duration_ms=sum(durations),transparent=True,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            prompt='Original scalable vector coqui mascot: '+description+'. Large silhouette; smooth 2.4-second loop.'))
        draw.text((10,row*180+3),name,fill=IVORY,font=font)
        for col,k in enumerate((0,3,9,15)):
            x=10+col*175;y=row*180+25
            sheet.paste(actual[k],(x,y),actual[k])
            small=actual[k].resize((32,32),Image.Resampling.LANCZOS)
            sheet.paste(small,(x+132,y+45),small)
        print(name,path.stat().st_size,'bytes;',unique,'unique frames; bbox',bounding)
    sheet.save(OUT/'contact-sheet-128-and-32.png')
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
