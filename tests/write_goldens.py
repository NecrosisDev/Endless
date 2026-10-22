"""Write golden areas from the Python reference for the Lua golden test."""
import os
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'generator'))
sys.path.insert(0, os.environ.get('EXANIMATE_TOOLS') or str(HERE.parents[3] / 'tools' / 'exanimate'))
import endless_gen as eg  # noqa: E402
out = HERE.parent / 'out'
tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes() if (out / 'endless-dress.bin').exists() else b'')
golden = out / 'golden-lua'
golden.mkdir(exist_ok=True)
n = 0
for seed in (1, 3, 7, 42, 123456789, 4294967295):
    for area in (1, 2, 5, 12, 30, 99):
        data, lay = eg.build_floor(tp, seed, area)
        assert not eg.decode_check(eg.level.grid(eg.level.parse(data)).layers, lay)
        (golden / f'golden_s{seed}_a{area}.rfc').write_bytes(data)
        (golden / f'golden_s{seed}_a{area}.rft').write_bytes(lay.terrain)
        n += 1
print('goldens', n)
