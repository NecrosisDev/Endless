"""Orientation check (read-only): generated areas against the shipped levels of the same stone, measured the
same way on both, since the models' own forward axes are not known.

1. Wall-hung pieces (above HUNG_Y over the floor, not decals): each must sit within NEAR of a wall side of
   its cell, and its turn relative to that wall (the angle of its matrix's first row against the wall's
   inward normal, to the nearest 90 degrees) must be one the shipped levels use for that model.
2. Tipped pieces (|yy| < 0.7): the model must be one the shipped levels also place tipped.
3. Seats: the share of chairs and stools whose third matrix row points within 60 degrees of the nearest
   table within 2 m, against the shipped levels' share (a statistic, not a pass/fail per seat).
Prints counts and the failing models; exit 1 when 1 or 2 fail.

    python -X utf8 -B tests/check_orientation.py [--areas 12]
"""
import argparse
import collections
import math
import os
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'generator'))
sys.path.insert(0, os.environ.get('EXANIMATE_TOOLS') or str(HERE.parents[3] / 'tools' / 'exanimate'))
import endless_gen as eg  # noqa: E402
from exanimate import level, rpk  # noqa: E402

BUILT, CELL = 0x80000, 600.0
SIDE = [(0, -1), (-1, 0), (0, 1), (1, 0)]
HUNG_Y, NEAR = 80.0, 0.3 * 600.0
STAGE1 = ('exanima01.rfc', 'exanima02.rfc', 'exanima03.rfc')


def rows(o):
    m = getattr(o, 'rot', None) or getattr(o, 'matrix', None)
    return list(m)


def scan(lv):
    g = level.grid(lv)
    w, h, L0 = g.w, g.h, g.layers[0]

    def word(c, r):
        return L0[r * w + c] if 0 <= c < w and 0 <= r < h else 0
    ys = sorted(o.pos[1] for o in lv.objects if o.name.startswith('decal')) or sorted(o.pos[1] for o in lv.objects)
    floor = ys[len(ys) // 2] if ys else 0.0
    hung, tipped, seats, tables = [], [], [], []
    for o in lv.objects:
        if o.name.startswith('decal'):
            continue
        m = rows(o)
        x, y, z = o.pos
        c, r = int(x / CELL + w // 2), int(z / CELL + h // 2)
        if not (word(c, r) & BUILT):
            continue
        fx, fz = x / CELL + w // 2 - c, z / CELL + h // 2 - r
        low = o.name.lower()
        if 'table' in low:
            tables.append((x, z))
        if ('chair' in low or 'stool' in low) and 'brok' not in low and abs(m[4]) >= 0.7:
            seats.append((x, z, m[6], m[8], o.name))
        if abs(m[4]) < 0.7:
            tipped.append(o.name)
        if y - floor > HUNG_Y:
            dist = [fz * CELL, fx * CELL, (1 - fz) * CELL, (1 - fx) * CELL]  # to the N, W, S, E sides
            walls = [q for q in range(4) if (word(c, r) >> (4 * q)) & 0xF == 7 and dist[q] < NEAR]
            if not walls:
                hung.append((o.name, None))
                continue
            q = min(walls, key=lambda k: dist[k])
            nx, nz = -SIDE[q][0], -SIDE[q][1]  # the wall's inward normal
            rel = (math.degrees(math.atan2(m[2], m[0])) - math.degrees(math.atan2(nz, nx))) % 360.0
            hung.append((o.name, int(round(rel / 90.0)) % 4))
    facing = 0
    counted = 0
    for x, z, ax, az, _n in seats:
        near = [(tx, tz) for tx, tz in tables if (tx - x) ** 2 + (tz - z) ** 2 < 200.0 ** 2]
        if not near or (ax == 0 and az == 0):
            continue
        tx, tz = min(near, key=lambda p: (p[0] - x) ** 2 + (p[1] - z) ** 2)
        dx, dz = tx - x, tz - z
        cos = (ax * dx + az * dz) / (math.hypot(ax, az) * math.hypot(dx, dz) or 1.0)
        counted += 1
        facing += cos >= math.cos(math.radians(60))
    return hung, tipped, (facing, counted)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--areas', type=int, default=12)
    a = ap.parse_args()
    van_turns = collections.defaultdict(set)
    van_tipped = set()
    van_face = [0, 0]
    van_off_wall = 0
    van_hung = 0
    for name in STAGE1:
        hung, tipped, (f, n) = scan(level.parse(rpk.read(a.game / 'Resource.rpk', name)))
        for model, turn in hung:
            van_hung += 1
            if turn is None:
                van_off_wall += 1
            else:
                van_turns[model].add(turn)
        van_tipped.update(tipped)
        van_face[0] += f
        van_face[1] += n
    out = HERE.parent / 'out'
    tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
    eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
    eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes())
    gen_hung = off_wall = bad_turn = 0
    bad_turn_models, off_wall_models, bad_tip = collections.Counter(), collections.Counter(), collections.Counter()
    face = [0, 0]
    gen_models = collections.Counter()
    n = 0
    seed = 1
    while n < a.areas:
        for area in (1, 2, 3):
            data, _lay = eg.build_floor(tp, seed, area)
            hung, tipped, (f, c) = scan(level.parse(data))
            for model, turn in hung:
                gen_hung += 1
                gen_models[model] += 1
                if turn is None:
                    off_wall += 1
                    off_wall_models[model] += 1
                elif model in van_turns and turn not in van_turns[model]:
                    bad_turn += 1
                    bad_turn_models[model] += 1
            for model in tipped:
                if model not in van_tipped:
                    bad_tip[model] += 1
            face[0] += f
            face[1] += c
            n += 1
        seed += 1
    print(f'wall-hung pieces: Endless {gen_hung}, off any wall {off_wall} ({100 * off_wall / max(1, gen_hung):.1f} %; vanilla {100 * van_off_wall / max(1, van_hung):.1f} %), '
          f'turned unlike vanilla {bad_turn}')
    if bad_turn_models:
        print('  turned unlike vanilla:', dict(bad_turn_models.most_common(10)))
    if off_wall_models:
        # per model: Endless's share off a wall against vanilla's (a hook off any wall is wrong; a hoop or a
        # stacked barrel is not)
        van_off = collections.Counter(); van_all = collections.Counter()
        for name in STAGE1:
            hung_v, _t, _f = scan(level.parse(rpk.read(a.game / 'Resource.rpk', name)))
            for model, turn in hung_v:
                van_all[model] += 1
                van_off[model] += turn is None
        gen_all = collections.Counter(m for m in off_wall_models.elements())
        print('  off any wall, Endless count / vanilla share off wall:')
        for model, k in off_wall_models.most_common(14):
            share = van_off[model] / van_all[model] if van_all[model] else float('nan')
            print(f'    {model:22} Endless {100 * k / gen_models[model]:5.1f} % of {gen_models[model]:5d}   vanilla {100 * share:5.1f} % of {van_all[model]}')
    print(f'tipped pieces of models vanilla never tips: {sum(bad_tip.values())}', dict(bad_tip.most_common(10)) if bad_tip else '')
    print(f'seats facing the nearest table (within 60 degrees): Endless {100 * face[0] / max(1, face[1]):.0f} % of {face[1]}, '
          f'vanilla {100 * van_face[0] / max(1, van_face[1]):.0f} % of {van_face[1]}')
    return 1 if bad_turn or sum(bad_tip.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
