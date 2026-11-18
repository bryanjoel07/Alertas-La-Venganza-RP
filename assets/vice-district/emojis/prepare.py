from PIL import Image
import json,pathlib
p=pathlib.Path(__file__).with_name('manifest.json')
m=json.loads(p.read_text(encoding='utf-8'))
for a in m['assets']:
 im=Image.open(a['source']).convert('RGBA').resize((128,128),Image.Resampling.LANCZOS)
 im.save(a['path'],format='PNG',optimize=True)
 a['bytes']=pathlib.Path(a['path']).stat().st_size
 a['alpha_range']=list(im.getchannel('A').getextrema())
 assert a['bytes']<=256*1024 and im.size==(128,128) and a['alpha_range']==[0,255],a
 print(json.dumps({k:a[k] for k in ('name','path','bytes','alpha_range')}))
p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
