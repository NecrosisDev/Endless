"""Measures dressing density (read-only): objects per built cell in rooms and in corridors, how many stand
near a wall (within WALL_NEAR of a wall side of their cell), how many hang on walls (above WALL_HIGH),
floor decals per cell, and the most common models, for the shipped levels and for generated areas.
Rooms and corridors as in measure_vanilla.py (a corridor space is one cell wide everywhere).

    python -X utf8 -B tests/measure_dressing.py [--game D:\\...\\Exanima] [--areas 12]
"""
import argparse
import collections
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'generator'))
sys.path.insert(0, os.environ.get('EXANIMATE_TOOLS') or str(HERE.parents[3] / 'tools' / 'exanimate'))
import endless_gen as eg  # noqa: E402
from exanimate import level, rpk  # noqa: E402

BUILT, CELL = 0x80000, 600.0
SIDE = [(0, -1), (-1, 0), (0, 1), (1, 0)]
WALL_NEAR = 150.0   # cm from a wall side
WALL_HIGH = 80.0    # cm above the floor: hung on a wall or a shelf top, not standing
STAGE1 = ('exanima01.rfc', 'exanima02.rfc', 'exanima03.rfc')


def census(lv):
    g = level.grid(lv)
    w, h, L0 = g.w, g.h, g.layers[0]

    def word(c, r):
        return L0[r * w + c] if 0 <= c < w and 0 <= r < h else 0

    def built(c, r):
        return bool(word(c, r) & BUILT) and word(c, r) != 0xFFFF

    cells = [(c, r) for r in range(h) for c in range(w) if built(c, r)]
    comp, spaces = {}, []
    for start in cells:
        if start in comp:
            continue
        k = len(spaces)
        comp[start] = k
        stack, members = [start], []
        while stack:
            c, r = stack.pop()
            members.append((c, r))
            for q, (dx, dz) in enumerate(SIDE):
                n = (c + dx, r + dz)
                if (word(c, r) >> (4 * q)) & 0xF == 0 and built(*n) and n not in comp:
                    comp[n] = k
                    stack.append(n)
        spaces.append(set(members))
    corridor = [not any((c + 1, r) in s and (c, r + 1) in s and (c + 1, r + 1) in s for c, r in s) for s in spaces]
    ys = sorted(o.pos[1] for o in lv.objects if o.name.startswith('decal')) or sorted(o.pos[1] for o in lv.objects)
    floor = ys[len(ys) // 2] if ys else 0.0
    out = {'room_cells': 0, 'corr_cells': 0, 'room_objs': 0, 'corr_objs': 0, 'near_wall': 0, 'standing': 0,
           'hung': 0, 'decals': 0, 'wall_sides': 0}
    names = collections.Counter()
    for c, r in cells:
        if corridor[comp[(c, r)]]:
            out['corr_cells'] += 1
        else:
            out['room_cells'] += 1
            out['wall_sides'] += sum(1 for q in range(4) if (word(c, r) >> (4 * q)) & 0xF == 7)
    for o in lv.objects:
        x, y, z = o.pos
        c, r = int((x / CELL) + w // 2), int((z / CELL) + h // 2)
        if (c, r) not in comp:
            continue
        fx, fz = x / CELL + w // 2 - c, z / CELL + h // 2 - r  # 0..1 inside the cell
        if o.name.startswith('decal'):
            out['decals'] += 1
            continue
        if corridor[comp[(c, r)]]:
            out['corr_objs'] += 1
            continue
        out['room_objs'] += 1
        names[o.name] += 1
        if y - floor > WALL_HIGH:
            out['hung'] += 1
            continue
        out['standing'] += 1
        dist = [fz * CELL, fx * CELL, (1 - fz) * CELL, (1 - fx) * CELL]  # to the N, W, S, E sides
        if any((word(c, r) >> (4 * q)) & 0xF == 7 and dist[q] < WALL_NEAR for q in range(4)):
            out['near_wall'] += 1
    return out, names


def summary(rows):
    def per(a, b):
        return statistics.median(r[a] / max(1, r[b]) for r in rows)
    return {
        'room objects / cell': per('room_objs', 'room_cells'),
        'corridor objects / cell': per('corr_objs', 'corr_cells'),
        'standing near a wall': per('near_wall', 'standing'),
        'hung / room wall side': per('hung', 'wall_sides'),
        'decals / cell': statistics.median(r['decals'] / max(1, r['room_cells'] + r['corr_cells']) for r in rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--areas', type=int, default=12)
    a = ap.parse_args()
    van, van_names = [], collections.Counter()
    for name in STAGE1:
        row, names = census(level.parse(rpk.read(a.game / 'Resource.rpk', name)))
        van.append(row)
        van_names.update(names)
    out = HERE.parent / 'out'
    tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
    eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
    eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes())
    gen, gen_names = [], collections.Counter()
    k = 0
    seed = 1
    while len(gen) < a.areas:
        for area in (1, 2, 3):  # the catacombs' stone, as the vanilla levels above
            data, _lay = eg.build_floor(tp, seed, area)
            row, names = census(level.parse(data))
            gen.append(row)
            gen_names.update(names)
        seed += 1
    sv, sg = summary(van), summary(gen)
    print(f'{"":28}{"vanilla (levels 1-3)":>22}{"Endless (depth 1)":>20}')
    for key in sv:
        print(f'{key:28}{sv[key]:22.2f}{sg[key]:20.2f}')
    print('most common room models, vanilla:', ', '.join(f'{n} {c}' for n, c in van_names.most_common(12)))
    print('most common room models, Endless:', ', '.join(f'{n} {c}' for n, c in gen_names.most_common(12)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
