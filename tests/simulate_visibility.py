"""What the game draws from each spot (read-only), from the static decompile of its culling (141840 sectors,
143C20 active rooms, 5B170 per-state drawing): a sector is a run of built cells joined by any side that is
not a wall (7) or a doorway (11); the camera's sector is drawn whole, the sectors one doorway away are drawn
through that doorway, nothing further. With every built cell as the camera's cell, per level: sectors drawn,
objects drawn and lamps in the drawn sectors (an upper bound: the neighbours count whole, though the game
draws only what shows through each doorway; lamps light their own room and one hop on, 148450).

    python -X utf8 -B tests/simulate_visibility.py [--areas 9]
"""
import argparse
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
STAGE1 = ('exanima01.rfc', 'exanima02.rfc', 'exanima03.rfc')


def simulate(lv):
    g = level.grid(lv)
    w, h, L0 = g.w, g.h, g.layers[0]

    def word(c, r):
        return L0[r * w + c] if 0 <= c < w and 0 <= r < h else 0

    def built(c, r):
        return bool(word(c, r) & BUILT) and word(c, r) != 0xFFFF

    cells = [(c, r) for r in range(h) for c in range(w) if built(c, r)]
    sector = {}
    portals = []
    count = 0
    for start in cells:
        if start in sector:
            continue
        sector[start] = count
        stack = [start]
        while stack:
            c, r = stack.pop()
            for q, (dx, dz) in enumerate(SIDE):
                n = (c + dx, r + dz)
                if not built(*n):
                    continue
                v = (word(c, r) >> (4 * q)) & 0xF
                if v == 7:
                    continue
                if v == 11:
                    portals.append(((c, r), n))
                    continue
                if n not in sector:
                    sector[n] = count
                    stack.append(n)
        count += 1
    links = [set() for _ in range(count)]
    for a, b in portals:
        if b in sector and sector[a] != sector[b]:
            links[sector[a]].add(sector[b])
            links[sector[b]].add(sector[a])
    objs = [0] * count
    lamps = [0] * count

    def owner(x, z):
        return sector.get((int(x / CELL + w // 2), int(z / CELL + h // 2)))
    for o in lv.objects:
        s = owner(o.pos[0], o.pos[2])
        if s is not None:
            objs[s] += 1
    for lt in level.lights(lv):
        s = owner(lt['pos'][0], lt['pos'][2])
        if s is not None:
            lamps[s] += 1
    size = [0] * count
    for cell in cells:
        size[sector[cell]] += 1
    per_cell = []
    for cell in cells:
        s = sector[cell]
        drawn = {s} | links[s]
        per_cell.append((len(drawn), sum(objs[k] for k in drawn), sum(lamps[k] for k in drawn), size[s]))
    return per_cell, count, size


def summary(rows):
    def med(i):
        return statistics.median(r[i] for r in rows)

    def p90(i):
        return sorted(r[i] for r in rows)[int(len(rows) * 0.9)]
    return {'sectors drawn': (med(0), p90(0)), 'objects drawn': (med(1), p90(1)), 'lamps drawn': (med(2), p90(2)), 'own sector cells': (med(3), p90(3))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--areas', type=int, default=9)
    a = ap.parse_args()
    van, van_sectors = [], []
    for name in STAGE1:
        rows, n, size = simulate(level.parse(rpk.read(a.game / 'Resource.rpk', name)))
        van += rows
        van_sectors.append((n, max(size)))
    out = HERE.parent / 'out'
    tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
    eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
    eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes())
    gen, gen_sectors = [], []
    seed = 1
    while len(gen_sectors) < a.areas:
        for area in (1, 2, 3):
            data, _lay = eg.build_floor(tp, seed, area)
            rows, n, size = simulate(level.parse(data))
            gen += rows
            gen_sectors.append((n, max(size)))
        seed += 1
    sv, sg = summary(van), summary(gen)
    print(f'{"from every built cell":26}{"vanilla 1-3 median / p90":>28}{"Endless depth 1 median / p90":>32}')
    for key in sv:
        print(f'{key:26}{sv[key][0]:14.0f} /{sv[key][1]:7.0f}       {sg[key][0]:14.0f} /{sg[key][1]:7.0f}')
    print('sectors per level and the largest (cells):', 'vanilla', van_sectors, 'Endless', gen_sectors[:6])
    return 0


if __name__ == '__main__':
    sys.exit(main())
