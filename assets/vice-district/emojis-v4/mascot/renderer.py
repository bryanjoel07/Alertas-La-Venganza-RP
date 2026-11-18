"""Six original coqui vector animations; no reference raster pixels are used.

Draw scalable paths at 4x, rasterize to 128px, and encode a shared GIF palette.
Run from any directory: python renderer.py
"""
from pathlib import Path
import hashlib
import json
import math
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageStat

OUT = Path(__file__).resolve().parent
FONT = OUT.parents[2] / 'esschino' / 'fonts' / 'NotoSans-Bold.ttf'
S, N, MS = 4, 24, 80
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
    c.ellipse((50, top+height*.50, 78, top+height*.71), CORAL)


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
    c = Canvas(sx=.74+.07*math.cos(2*t), sy=.73-.07*math.cos(2*t),
               dx=7*math.sin(t), dy=4+8*math.cos(2*t), angle=math.radians(18)*math.sin(t))
    head(c); eyes_laugh(c); mouth(c, 38+13*math.cos(2*t))
    # Hands are in front, so the alternating arm dance remains obvious at 32px.
    for x, phase in [(-1,t),(110,t+math.pi)]:
        yy=69+20*math.sin(phase)
        c.line([(x+12,85),(x+7,yy+8)],PLUM,12)
        c.line([(x+12,85),(x+7,yy+8)],MINT,7)
        c.ellipse((x-3,yy-5,x+19,yy+17),MINT,PLUM,3)
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
    c = Canvas(sx=.79+.07*math.cos(2*t), sy=.78-.08*math.cos(2*t),
               dy=5*math.sin(2*t), angle=.20*math.sin(t))
    head(c); eyes_laugh(c)
    opening=(1+math.sin(2*t))/2
    if opening<.13:
        c.arc((34,64,94,86),0,180,PLUM,5)
    else:
        mouth(c, 12+58*opening)
    # Tears rock far enough to read clearly at reaction size.
    drop(c, 12-6*math.sin(t), 60+16*math.cos(t), 12)
    drop(c, 116+6*math.sin(t), 60-16*math.cos(t), 12)
    c.line([(9,93),(4,99)], CORAL, 3)
    c.line([(118,93),(124,99)], CORAL, 3)
    return c.finish()


def llanto(t):
    c = Canvas(sx=.79+.045*math.cos(2*t), sy=.73-.06*math.cos(2*t),
               dy=-7+6*math.sin(2*t), angle=.07*math.sin(t))
    head(c, False)
    eye_whites(c)
    c.line(bezier((20,43), ((29,51), (38,51), (47,42))), width=5)
    c.line(bezier((81,42), ((91,51), (100,51), (109,43))), width=5)
    c.line([(24,26),(42,31)], PLUM,4)
    c.line([(85,31),(104,26)], PLUM,4)
    # Short streams feed large drops which fall clear of the head and splash.
    for j, x in enumerate((24, 104)):
        pts = bezier((x-6,51), ((x-9,61), (x-6,71), (x-8,78)),
                     ((x-5,85), (x+7,85), (x+8,78)),
                     ((x+5,70), (x+9,61), (x+6,51)))
        c.poly(pts,CYAN,PLUM,2)
        c.line([(x-2,57),(x-1,72)],IVORY,3.2)
    h = 9+8*math.sin(2*t)
    c.ellipse((48,83-h,80,96+h), PLUM)
    c.ellipse((55,93,73,100+h), CORAL)
    c.sx=c.sy=1;c.dx=c.dy=c.angle=0
    for j,x in enumerate((31,97)):
        u=(t/math.tau*2+j*.5)%1
        if u<.72:
            q=u/.72
            drop(c,x,73+35*q*q,9+2*q)
        else:
            q=(u-.72)/.28
            c.ellipse((x-4-16*q,117-3*(1-q),x+4+16*q,121),CYAN,PLUM,1.5)
            for sign in (-1,1):
                xx=x+sign*(5+15*q)
                yy=116-12*math.sin(q*math.pi)
                c.ellipse((xx-2,yy-3,xx+2,yy+2),CYAN)
    return c.finish()


def steam(c, x, t, phase):
    # Curl moves up and sideways through a continuous vapor cycle.
    a=t+phase
    y=29+6*math.cos(a)
    c.line(bezier((x,y+10), ((x-10,y+1),(x+8,y-7),(x,y-17))), IVORY,6)
    c.line(bezier((x,y+10), ((x-10,y+1),(x+8,y-7),(x,y-17))), PLUM,1.6)


def rabia(t):
    c = Canvas(sx=.76+.03*math.cos(2*t), sy=.78, dx=10*math.sin(3*t), dy=8,
               angle=.08*math.sin(3*t))
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
    for j,x in enumerate((19,109)):
        u=(t/math.tau+j*.5)%1
        if u<.88:
            scale=math.sin(u/.88*math.pi)
            rr=2+8*scale; yy=43-29*u
            c.ellipse((x-rr,yy-rr,x+rr,yy+rr),IVORY,PLUM,1.5)
            c.ellipse((x-rr-3,yy-rr*.3,x+rr*.3,yy+rr*.7),IVORY)
            c.ellipse((x-rr*.3,yy-rr-3,x+rr*.7,yy+rr*.3),IVORY)
    return c.finish()


def amor(t):
    c=Canvas(sx=.77,sy=.77,dy=-3+4*math.sin(t),angle=.10*math.sin(t))
    head(c)
    heart(c,34,44,11+6*math.sin(t),PINK)
    heart(c,94,44,11-6*math.sin(t),PINK)
    c.arc((43,62,85,91),0,180,width=4)
    # Hands hold a big heartbeat; a small orbiting heart reinforces motion.
    beat=1+.37*math.sin(2*t)
    c.sx=c.sy=1;c.dx=c.dy=c.angle=0
    heart(c,64,98,19*beat,CORAL)
    c.ellipse((33-7*beat,92,48-4*beat,107),MINT,PLUM,3)
    c.ellipse((80+4*beat,92,95+7*beat,107),MINT,PLUM,3)
    heart(c,64+19*math.sin(t),17+4*math.cos(t),6,PINK)
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
    c=Canvas(sx=.70,sy=.73,dx=-13,dy=6,angle=.13*math.sin(t))
    head(c)
    blink = max(0, math.cos(t-1.7))**24
    eyes_open(c,2*math.sin(t),blink)
    mouth(c,29)
    c.sx=c.sy=1;c.dx=c.dy=c.angle=0
    # 60-degree sweep; wrist is shifted inward to leave generous margins.
    c.dx=-10;c.dy=-2
    salute_hand(c,math.radians(30)*math.sin(2*t)-.22)
    c.line([(102,32),(104,25+2*math.sin(t))],IVORY,3)
    c.line([(115,36),(121,32+2*math.cos(t))],CYAN,3)
    return c.finish()


ASSETS=[
 ('vd_coqui_fiesta_max',fiesta,'Saltos de 16 px, baile de 36 grados, brazos alternos y squash/stretch'),
 ('vd_coqui_carcajada_max',carcajada,'Carcajada abierta-cerrada, balanceo amplio y lagrimas rebotando'),
 ('vd_coqui_llanto_max',llanto,'Grandes lagrimas que caen y salpican con cuerpo sollozando'),
 ('vd_coqui_rabia_max',rabia,'Sacudida de cabeza de 20 px con nubes de vapor que crecen y desaparecen'),
 ('vd_coqui_amor_max',amor,'Corazon grande que se expande y contrae, ojos de corazon alternos'),
 ('vd_coqui_saludo_max',saludo,'Saludo amplio de 60 grados con mano grande, inclinacion y parpadeo'),
]


def encode(frames,path):
    sample=Image.new('RGB',(128*N,128))
    for i,im in enumerate(frames): sample.paste(im.convert('RGB'),(128*i,0))
    base=sample.quantize(colors=127,method=Image.Quantize.MEDIANCUT)
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
    sheet=Image.new('RGB',(1312,6*180),'#313338');draw=ImageDraw.Draw(sheet)
    comparisons=[]
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
            bbox=rgba.getbbox()
            assert bbox[0]>=2 and bbox[1]>=2 and bbox[2]<=126 and bbox[3]<=126,(name,k,bbox)
        unique=len({i.tobytes() for i in actual})
        assert unique>=20 and path.stat().st_size<=256*1024
        bounding=actual[0].getbbox()
        oldpath=OUT.parents[1]/'emojis-v3'/'mascot'/(name.removesuffix('_max')+'.gif')
        oldgif=Image.open(oldpath);old=[]
        for k in range(oldgif.n_frames):
            oldgif.seek(k);old.append(oldgif.convert('RGBA').copy())
        def small_frames(frames):
            out=[]
            for frame in frames:
                f=Image.new('RGB',(32,32),'#313338')
                tiny=frame.resize((32,32),Image.Resampling.LANCZOS)
                f.paste(tiny,(0,0),tiny);out.append(f)
            return out
        def motion_metrics(frames):
            adj=[];maxchange=0;maxdistance=0
            for a,b in zip(frames,frames[1:]+frames[:1]):
                diff=ImageChops.difference(a,b)
                adj.append(sum(ImageStat.Stat(diff).mean)/3)
            for i,a in enumerate(frames):
                for b in frames[i+1:]:
                    pixels=list(ImageChops.difference(a,b).get_flattened_data())
                    maxchange=max(maxchange,sum(max(p)>30 for p in pixels)/1024)
                    maxdistance=max(maxdistance,sum(sum(p) for p in pixels)/(1024*3))
            return dict(mean_adjacent_rgb_distance=round(sum(adj)/len(adj),3),
                        max_pair_rgb_distance=round(maxdistance,3),
                        max_pair_changed_pixel_fraction=round(maxchange,3))
        oldsmall=small_frames(old);newsmall=small_frames(actual)
        oldmetric=motion_metrics(oldsmall);newmetric=motion_metrics(newsmall)
        comparisons.append((name,oldsmall,newsmall))
        manifest['assets'].append(dict(name=name,path='assets/vice-district/emojis-v4/mascot/'+name+'.gif',
            description=description,bytes=path.stat().st_size,width=128,height=128,frames=N,
            distinct_frames=unique,duration_ms=sum(durations),transparent=True,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            motion_at_32px={'v3':oldmetric,'v4':newmetric,
                'adjacent_motion_ratio':round(newmetric['mean_adjacent_rgb_distance']/oldmetric['mean_adjacent_rgb_distance'],3)},
            prompt='Original scalable vector coqui mascot: '+description+'. Broad action; smooth 1.92-second loop.'))
        draw.text((10,row*180+3),name,fill=IVORY,font=font)
        for col,k in enumerate(range(0,N,3)):
            x=4+col*164;y=row*180+25
            sheet.paste(actual[k],(x,y),actual[k])
            small=actual[k].resize((32,32),Image.Resampling.LANCZOS)
            sheet.paste(small,(x+132,y+45),small)
        print(name,path.stat().st_size,'bytes;',unique,'unique frames; motion',oldmetric,newmetric)
    sheet.save(OUT/'storyboard-8-keyframes-128-and-32.png')
    comparisonframes=[]
    for k in range(N):
        frame=Image.new('RGB',(430,60+6*58),'#313338');d=ImageDraw.Draw(frame)
        d.text((235,7),'ANTES',font=font,fill=IVORY)
        d.text((335,7),'AHORA',font=font,fill=IVORY)
        d.text((10,30),'Comparacion real a 32 px / misma fase',font=font,fill=IVORY)
        for row,(name,old,new) in enumerate(comparisons):
            y=63+row*58
            d.text((10,y+6),name.removeprefix('vd_coqui_').removesuffix('_max'),font=font,fill=IVORY)
            frame.paste(old[k],(251,y));frame.paste(new[k],(351,y))
        comparisonframes.append(frame)
    comparisonframes[0].save(OUT/'before-after-32px.gif',save_all=True,
        append_images=comparisonframes[1:],duration=MS,loop=0,optimize=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
