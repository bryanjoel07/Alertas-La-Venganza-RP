from pathlib import Path
import json
from PIL import Image

manifest = Path(__file__).with_name('manifest.json')
data = json.loads(manifest.read_text(encoding='utf-8'))
for asset in data['assets']:
    image = Image.open(asset['source']).convert('RGBA')
    image.thumbnail((128, 128), Image.Resampling.LANCZOS)
    target = manifest.parent / (asset['name'] + '.png')
    image.save(target, optimize=True)
    asset.update(width=image.width, height=image.height, bytes=target.stat().st_size,
                 alpha_range=list(image.getchannel('A').getextrema()))
    assert image.size == (128, 128) and asset['alpha_range'] == [0, 255]
    assert asset['bytes'] <= 256 * 1024
    print(asset['name'], asset['bytes'])
manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
