"""Original code-native VIce District animated emoji pack.

Rebuild with Python + Pillow. All artwork is drawn from vector/canvas primitives
and the bundled Noto Sans font; no source raster artwork is edited.
"""
from pathlib import Path
import hashlib
import json
import math
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

OUT = Path(__file__).resolve().parent
FONT = OUT.parents[2] / 'esschino' / 'fonts' / 'NotoSans-Bold.ttf'
S, N, MS = 4, 24, 80
PLUM = '#24102F'
PINK = '#FF258D'
CORAL = '#FF785E'
CYAN = '#33E5E9'
IVORY = '#FFF4DB'
GOLD = '#FFD25E'
PURPLE = '#8C4DE7'


class Canvas:
    def __init__(self):
        self.im = Image.new('RGBA', (128*S, 128*S))
        self.d = ImageDraw.Draw(self.im)

    def poly(self, points, fill, stroke=PLUM, width=4):
        p = [(round(x*S), round(y*S)) for x,y in points]
        self.d.polygon(p, fill=fill)
        if stroke:
            self.d.line(p + [p[0]], fill=stroke, width=round(width*S), joint='curve')

    def line(self, points, fill, width):
        self.d.line([(round(x*S),round(y*S)) for x,y in points], fill=fill,
                    width=max(1,round(width*S)), joint='curve')

    def ellipse(self, box, fill, stroke=None, width=1):
        self.d.ellipse(tuple(round(v*S) for v in box), fill=fill,
                       outline=stroke, width=round(width*S))

    def rect(self, box, radius, fill, stroke=PLUM, width=4):
        self.d.rounded_rectangle(tuple(round(v*S) for v in box), radius=round(radius*S),
                                fill=fill, outline=stroke, width=round(width*S))

    def text(self, xy, word, size, fill=IVORY, width=4):
        font = ImageFont.truetype(str(FONT), round(size*S))
        # A second, narrow same-color stroke makes the bundled Bold extra chunky.
        p = (round(xy[0]*S),round(xy[1]*S))
        self.d.text(p, word, font=font, anchor='mm', fill=fill,
                    stroke_width=round((width+0.65)*S), stroke_fill=PLUM)
        self.d.text(p, word, font=font, anchor='mm', fill=fill,
                    stroke_width=round(.65*S), stroke_fill=fill)

    def finish(self):
        # Retain the original canvas resolution through whole-object motion.
        return self.im


def star(c,x,y,r,fill=IVORY,phase=0,points=5,inner=.43,stroke=PLUM,width=2):
    pts=[]
    for i in range(points*2):
        a=phase-math.pi/2+i*math.pi/points
        rr=r if i%2==0 else r*inner
        pts.append((x+math.cos(a)*rr,y+math.sin(a)*rr))
    c.poly(pts,fill,stroke,width)


def pr_onda(t):
    c=Canvas()
    # Five horizontal stripes, the blue hoist triangle and exactly one white star.
    # Every original vector point follows the same sine-wave fabric deformation.
    def p(x,y):
        u=(x-7)/114
        return (64+(x-64)*(.90+.04*math.cos(t))+4*math.sin(t),
                64+(y-64)*.80+24*math.sin(t-u*math.tau)*(.55+.45*u))
    for k in range(5):
        y0=25+k*15.6;y1=y0+15.6
        pts=[p(7+i*114/38,y0) for i in range(39)]
        pts += [p(7+i*114/38,y1) for i in reversed(range(39))]
        c.poly(pts, '#F2264A' if k%2==0 else IVORY, None)
    tri=[]
    for a,b in [((7,25),(68,64)),((68,64),(7,103)),((7,103),(7,25))]:
        tri += [p(a[0]+(b[0]-a[0])*j/20,a[1]+(b[1]-a[1])*j/20) for j in range(20)]
    c.poly(tri,'#0758B9',None)
    points=[]
    for i in range(10):
        a=-math.pi/2+i*math.pi/5;r=14 if i%2==0 else 6
        points.append(p(28+math.cos(a)*r,64+math.sin(a)*r))
    c.poly(points,IVORY,None)
    border=[p(7+i*114/38,25) for i in range(39)]
    border += [p(121,103)]
    border += [p(7+i*114/38,103) for i in reversed(range(39))]
    c.line(border+[border[0]],PLUM,4.5)
    c.line([p(9,27),p(9,101)],CYAN,1.1)
    return c.finish()


def duro(t):
    c=Canvas()
    # Continuous bob + squash gives a weighty impact without blinking.
    q=(1+math.cos(t))/2
    by=-9*math.sin(t)
    w=4+5*q
    for a,b in [((9,28),(3,18)),((116,31),(123,23)),((10,95),(3,106)),((117,93),(124,106))]:
        c.line([a,b],PLUM,7)
        c.line([a,b],CYAN,3.5)
    c.ellipse((19-w,113-q*3,109+w,122),PINK,PLUM,3)
    c.text((64,39+by),'DU',63,IVORY,4.7)
    c.text((64,89+by*.75),'RO',62,CORAL,4.7)
    c.line([(20,14+by/3),(42,14+by/3)],CYAN,3)
    return c.finish()


def gg_brillo(t):
    c=Canvas();bob=5*math.sin(t)
    # Thick sloping badge makes the letters readable on dark/light Discord themes.
    c.poly([(11,29+bob),(107,20+bob),(122,94+bob),(20,108+bob)],PINK,PLUM,5)
    c.poly([(15,32+bob),(104,24+bob),(110,37+bob),(19,46+bob)],CORAL,None)
    c.text((64,66+bob),'GG',67,IVORY,4)
    # Moving small native vector diamonds travel across the large GG.
    x=64+43*math.sin(t)
    star(c,x,31+bob,10,CYAN,phase=t*.22,points=4,inner=.3,width=2.3)
    star(c,110-x*.13,98+bob,6+1.5*math.sin(t+.8),IVORY,points=4,inner=.3,width=1.8)
    c.line([(27,99+bob),(83,94+bob)],CYAN,3)
    return c.finish()


def corona(t):
    c=Canvas();bob=7*math.sin(t);angle=.11*math.sin(t)
    def p(x,y):
        dx=x-64;dy=y-66
        return (64+dx*math.cos(angle)-dy*math.sin(angle),66+bob+dx*math.sin(angle)+dy*math.cos(angle))
    def poly(ps,col,stroke=PLUM,width=4):c.poly([p(*v) for v in ps],col,stroke,width)
    poly([(14,32),(39,52),(63,17),(87,52),(114,32),(102,99),(26,99)],GOLD,width=5)
    poly([(16,34),(39,54),(64,22),(64,89),(28,89)],'#FFE9A0',None)
    poly([(26,79),(103,79),(102,101),(27,101)],CORAL,width=4.5)
    poly([(30,91),(99,91),(98,97),(31,97)],PINK,None)
    for x,y,r in [(14,30,6),(63,15,6),(114,30,6)]:
        xx,yy=p(x,y);c.ellipse((xx-r,yy-r,xx+r,yy+r),GOLD,PLUM,3)
    poly([(64,47),(76,62),(64,77),(52,62)],CYAN,width=3)
    poly([(64,51),(64,71),(57,62)],IVORY,None)
    for x in [39,89]:
        xx,yy=p(x,64);c.ellipse((xx-4,yy-4,xx+4,yy+4),PINK,PLUM,2)
    star(c,10,83-bob*.7,7,IVORY,t*.15,4,.3,width=2)
    star(c,117,103-bob,6,CYAN,-t*.15,4,.3,width=2)
    return c.finish()


def drift(t):
    c=Canvas();dx=5*math.sin(t);dy=2*math.cos(t*2)
    # Repeating, overlapping smoke lobes roll backward; no visual reset/pop.
    for j in range(3):
        a=t+j*math.tau/3
        x=22+11*math.cos(a);y=73-16*math.sin(a)
        r=11+3*math.cos(a+.6)
        c.ellipse((x-r,y-r,x+r,y+r),IVORY,PLUM,3)
    def p(x,y):return(x+dx,y+dy)
    def poly(ps,col,stroke=PLUM,width=4):c.poly([p(*v) for v in ps],col,stroke,width)
    # Original anonymous coupe: large wheels, angled windshield, short nose.
    poly([(14,71),(29,69),(42,47),(76,45),(92,63),(112,69),(118,89),(12,89)],CORAL,width=4.5)
    poly([(40,65),(47,50),(73,49),(85,64)],CYAN,width=3)
    poly([(46,61),(50,52),(61,51),(58,62)],IVORY,None)
    c.line([p(65,50),p(66,66)],PLUM,3)
    poly([(13,78),(111,77),(115,88),(13,88)],PINK,None)
    poly([(92,68),(111,72),(113,77),(93,76)],GOLD,width=2)
    c.line([p(49,71),p(68,71)],PLUM,2.5)
    c.line([p(48,75),p(48,84)],PLUM,2)
    poly([(11,68),(28,66),(27,71),(12,73)],PLUM,None)
    c.line([p(14,91),p(115,91)],PLUM,5)
    for x in [35,96]:
        x,y=p(x,89)
        c.ellipse((x-14,y-14,x+14,y+14),PLUM)
        c.ellipse((x-8.5,y-8.5,x+8.5,y+8.5),CYAN,IVORY,2)
        for k in range(3):
            a=-3*t+k*math.tau/3
            c.line([(x,y),(x+7*math.cos(a),y+7*math.sin(a))],PLUM,2.5)
        c.ellipse((x-2,y-2,x+2,y+2),IVORY)
    for y,phase in [(45,0),(37,1.8)]:
        x=14+4*math.sin(t+phase)
        c.line([(x,y),(x+19,y)],PLUM,5)
        c.line([(x,y),(x+19,y)],CYAN,2.5)
    return c.finish()


def boom(t):
    c=Canvas();scale=.91+.065*math.sin(t);rot=.075*math.cos(t)
    pts=[]
    for i in range(24):
        a=-math.pi/2+i*math.pi/12+rot
        r=(62 if i%2==0 else 43)*scale
        pts.append((64+math.cos(a)*r,64+math.sin(a)*r))
    c.poly(pts,CORAL,PLUM,5)
    inner=[(64+(x-64)*.81,64+(y-64)*.81) for x,y in pts]
    c.poly(inner,GOLD,None)
    # Stacked giant letters keep BOOM readable at ordinary 32px emoji size.
    c.text((63,42-3*math.sin(t)),'BO',49,IVORY,3.5)
    c.text((64,83+3*math.sin(t)),'OM',47,IVORY,3.5)
    star(c,112,16+3*math.sin(t),8,CYAN,rot,4,.35,width=2)
    star(c,13,110-3*math.sin(t),7,PINK,-rot,4,.35,width=2)
    return c.finish()


def ease_keys(u, keys):
    for a,b in zip(keys,keys[1:]):
        if a[0] <= u <= b[0]:
            f=(u-a[0])/(b[0]-a[0]);f=f*f*(3-2*f)
            return tuple(x+(y-x)*f for x,y in zip(a[1:],b[1:]))
    return keys[-1][1:]


def transformed(im, sx=1, sy=None, angle=0, x=64, y=64, canvas=None):
    """Transform freshly drawn native geometry, never existing raster artwork."""
    sy=sx if sy is None else sy
    im=im.crop(im.getbbox())
    im=im.resize((max(1,round(im.width*sx)),max(1,round(im.height*sy))),Image.Resampling.BICUBIC)
    im=im.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True)
    # Retain a three-pixel transparent margin throughout turns and wide travel.
    fit=min(1,2*min(x-3,125-x)*S/im.width,2*min(y-3,125-y)*S/im.height)
    if fit<1:im=im.resize((round(im.width*fit),round(im.height*fit)),Image.Resampling.BICUBIC)
    target=Image.new('RGBA',(128*S,128*S)) if canvas is None else canvas
    target.alpha_composite(im,(round(x*S-im.width/2),round(y*S-im.height/2)))
    return target


def pr_onda_max(t):
    return pr_onda(t).resize((128,128),Image.Resampling.LANCZOS)


def duro_max(t):
    u=t/math.tau
    sx,sy,y=ease_keys(u,[(0,.76,.76,45),(.18,.68,.90,64),(.30,1.02,.40,91),
                           (.43,.68,.95,61),(.60,.78,.76,44),(.75,.94,.59,80),
                           (.87,.73,.86,52),(1,.76,.76,45)])
    c=Canvas()
    impact=max(0,1-abs(u-.30)/.14)
    c.ellipse((25-12*impact,111,103+12*impact,120),PINK,PLUM,3)
    for sign in [-1,1]:
        xx=64+sign*(42+6*impact)
        c.line([(xx,105),(xx+sign*7,96-10*impact)],PLUM,7)
        c.line([(xx,105),(xx+sign*7,96-10*impact)],CYAN,3.5)
    body=Canvas();body.text((64,38),'DU',63,IVORY,4.7);body.text((64,88),'RO',62,CORAL,4.7)
    im=transformed(body.im,sx,sy,angle=3*math.sin(t),y=y,canvas=c.im)
    return im.resize((128,128),Image.Resampling.LANCZOS)


def gg_brillo_max(t):
    u=t/math.tau
    angle,scale=ease_keys(u,[(0,-16,.78),(.13,18,.93),(.26,-9,.91),(.42,-25,.62),
                              (.67,-360,.63),(.82,-374,.91),(1,-376,.78)])
    # 360-degree turn lands on the identical initial orientation.
    im=transformed(gg_brillo(t),scale,angle=angle,y=64+7*math.sin(t))
    return im.resize((128,128),Image.Resampling.LANCZOS)


def corona_max(t):
    u=t/math.tau
    angle,scale,y=ease_keys(u,[(0,-13,.77,71),(.18,15,.76,46),(.30,-45,.62,48),
                             (.57,-350,.64,55),(.69,-373,.85,77),(.81,-353,.73,56),
                             (1,-373,.77,71)])
    c=Canvas();q=(y-44)/37
    c.ellipse((41-13*q,114,87+13*q,122),PURPLE,PLUM,2)
    im=transformed(corona(0),scale,angle=angle,y=y,canvas=c.im)
    return im.resize((128,128),Image.Resampling.LANCZOS)


def drift_max(t):
    # The car center travels 44px while pitching through a 40-degree arc.
    c=Canvas();x=64+22*math.sin(2*t)
    c.line([(6,108),(122,108)],PLUM,6);c.line([(6,108),(122,108)],CYAN,2.6)
    for j in range(3):
        a=t+j*math.tau/3
        xx=25+16*math.cos(a);yy=87-17*math.sin(a)
        r=7+3*math.cos(a)
        c.ellipse((xx-r,yy-r,xx+r,yy+r),IVORY,PLUM,2)
    im=transformed(drift(t*2),.68,.80,angle=25*math.cos(2*t),x=x,y=74-13*math.cos(2*t),canvas=c.im)
    return im.resize((128,128),Image.Resampling.LANCZOS)


def boom_max(t):
    u=t/math.tau
    scale,angle=ease_keys(u,[(0,.38,-15),(.16,.46,-9),(.32,.98,5),(.44,.72,-7),
                              (.58,.90,3),(.73,.77,-5),(1,.38,-15)])
    im=transformed(boom(0),scale,angle=angle)
    return im.resize((128,128),Image.Resampling.LANCZOS)


ASSETS=[
 ('vd_pr_onda_max',pr_onda_max,'Bandera de Puerto Rico con ondas de tela de 48 px y desplazamiento lateral'),
 ('vd_duro_max',duro_max,'DURO cae 46 px, se aplasta al 40 por ciento y rebota con impacto'),
 ('vd_gg_brillo_max',gg_brillo_max,'GG celebra con giro completo de 360 grados y zoom amplio'),
 ('vd_corona_max',corona_max,'Corona salta, da una vuelta completa y rebota al caer'),
 ('vd_drift_max',drift_max,'Coupé coral cruza 44 px dos veces con inclinación de 50 grados, ruedas y humo'),
 ('vd_boom_max',boom_max,'BOOM se expande del 38 al 98 por ciento y retrocede con rebote'),
]


def encode(frames,path):
    w,h=frames[0].size
    sample=Image.new('RGB',(w*len(frames),h))
    for i,im in enumerate(frames):sample.paste(im.convert('RGB'),(w*i,0))
    base=sample.quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    palette=Image.new('P',(1,1))
    palette.putpalette(base.getpalette())
    colors=[0,0,0]+base.getpalette()[:765]
    indexed=[]
    for im in frames:
        f=im.convert('RGB').quantize(palette=palette,dither=Image.Dither.NONE)
        f=f.point(lambda i:min(i+1,255));f.putpalette(colors)
        f.paste(0,mask=im.getchannel('A').point(lambda a:255 if a<128 else 0))
        f.info['transparency']=0
        indexed.append(f)
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=MS,loop=0,
                    transparency=0,disposal=2,optimize=False)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={'mode':'original vector animation','renderer':'render.py (Pillow supersampled canvas geometry)',
              'frame_count':N,'frame_duration_ms':MS,'loop':'infinite','assets':[]}
    sheet=Image.new('RGB',(6*160,220),'#313338')
    dark=Image.new('RGB',(6*160,220),'#FFFFFF')
    storyboard=Image.new('RGB',(8*128,6*128),'#313338')
    before_after=[]
    for j,(name,func,description) in enumerate(ASSETS):
        frames=[func(math.tau*i/N) for i in range(N)]
        dest=OUT/(name+'.gif');encode(frames,dest)
        gif=Image.open(dest)
        assert gif.size==(128,128) and gif.n_frames==N and gif.info['loop']==0
        assert dest.stat().st_size<=256*1024
        unique=set();alpha=True;dur=0;encoded=[];border_clear=True
        for k in range(N):
            gif.seek(k);im=gif.convert('RGBA');encoded.append(im)
            unique.add(im.tobytes());alpha &= im.getchannel('A').getextrema()==(0,255)
            dur+=gif.info['duration']
            bbox=im.getchannel('A').getbbox()
            border_clear &= bbox[0]>0 and bbox[1]>0 and bbox[2]<128 and bbox[3]<128
        assert len(unique)>12 and alpha and dur==N*MS
        assert border_clear, name+' touches canvas edge'
        im=encoded[N//4];im.save(OUT/(name+'-preview.png'))
        for target in [sheet,dark]:
            target.paste(im,(j*160+16,2),im)
            small=im.resize((32,32),Image.Resampling.LANCZOS)
            target.paste(small,(j*160+64,144),small)
            ImageDraw.Draw(target).text((j*160+80,198),name,anchor='mm',
                font=ImageFont.truetype(str(FONT),13),fill='white' if target is sheet else PLUM)
        for k in range(8):
            im=encoded[k*3];storyboard.paste(im,(k*128,j*128),im)
        previous=Image.open(OUT.parents[1]/'emojis-v3'/'hype'/(name.removesuffix('_max')+'.gif'))
        old=[]
        for k in range(previous.n_frames):
            previous.seek(k);old.append(previous.convert('RGBA'))
        before_after.append((name,old,encoded))
        motion={'before_32px':measure_motion(old),'after_32px':measure_motion(encoded)}
        raw=dest.read_bytes()
        sha=hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest()
        manifest['assets'].append(dict(name=name,path='assets/vice-district/emojis-v4/hype/'+name+'.gif',
            description=description,bytes=len(raw),width=128,height=128,frames=N,
            distinct_frames=len(unique),duration_ms=dur,transparent=alpha,border_clear=border_clear,
            motion_comparison=motion,git_blob_sha=sha,
            prompt='Original code-native vector design: '+description+'. Bold plum outline; coral, magenta, cyan and ivory. Pronounced 1.92-second motion.'))
        print(name,len(raw),len(unique),sha,json.dumps(motion))
    sheet.save(OUT/'gif-actual-size-check.png')
    dark.save(OUT/'gif-light-background-check.png')
    storyboard.save(OUT/'motion-storyboard.png')
    comparison=[]
    font=ImageFont.truetype(str(FONT),12)
    for k in range(120):
        panel=Image.new('RGBA',(300,400),'#313338')
        d=ImageDraw.Draw(panel);d.text((190,5),'V3',font=font,fill=IVORY);d.text((250,5),'MAX',font=font,fill=CYAN)
        for j,(name,old,new) in enumerate(before_after):
            y=37+j*59
            d.text((8,y+8),name.removesuffix('_max'),font=font,fill=IVORY)
            for x,im in [(186,old[int(k*MS/100)%24]),(250,new[k%N])]:
                small=im.resize((32,32),Image.Resampling.LANCZOS)
                panel.alpha_composite(small,(x,y))
        comparison.append(panel)
    encode(comparison,OUT/'before-after-32px.gif')
    comparison[6].convert('RGB').save(OUT/'before-after-32px-preview.png')
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def measure_motion(frames):
    small=[]
    for im in frames:
        im=im.resize((32,32),Image.Resampling.LANCZOS)
        bg=Image.new('RGBA',(32,32),'#313338');bg.alpha_composite(im)
        small.append(bg.convert('RGB'))
    delta=[];changed=[];largest=0
    for a,b in zip(small,small[1:]+small[:1]):
        d=ImageChops.difference(a,b)
        delta.append(sum(ImageStat.Stat(d).mean)/3)
        count=sum(1 for p in d.get_flattened_data() if max(p)>=20)
        changed.append(count);largest=max(largest,count)
    return {'mean_consecutive_rgb_delta_0_255':round(sum(delta)/len(delta),3),
            'mean_pixels_changed_ge20':round(sum(changed)/len(changed),2),
            'max_pixels_changed_ge20':largest,'total_pixels':1024}


if __name__=='__main__':main()
