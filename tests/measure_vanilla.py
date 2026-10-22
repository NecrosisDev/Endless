"""Measures the shipped levels' floor plans (read-only) and, for comparison, generated areas: room
sizes, corridor share, doors per room, loops and dead ends. A cell side nibble of 0 is open floor,
7 a wall, anything else between two built cells a doorway (0xB a door; vanilla uses others too).
Spaces are the floor cells joined through open sides; a space is a corridor when it is one cell
wide everywhere (no 2x2 block of its cells). Prints one table; writes nothing.

    python -X utf8 -B tests/measure_vanilla.py [--game D:\\...\\Exanima] [--areas 20]
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

BUILT = 0x80000
SIDE = [(0, -1), (-1, 0), (0, 1), (1, 0)]


def plan_stats(layer0, w, h):
    def word(c, r):
        return layer0[r * w + c] if 0 <= c < w and 0 <= r < h else 0

    def built(c, r):
        return bool(word(c, r) & BUILT) and word(c, r) != 0xFFFF

    cells = [(c, r) for r in range(h) for c in range(w) if built(c, r)]
    comp = {}
    spaces = []
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
        spaces.append(members)
    doors = set()
    raw = collections.Counter()  # doorway edges per space, each counted (two doors into one corridor are two)
    kinds = collections.Counter()
    for c, r in cells:
        for q, (dx, dz) in enumerate(SIDE):
            n = (c + dx, r + dz)
            v = (word(c, r) >> (4 * q)) & 0xF
            if v not in (0, 7) and built(*n) and comp[(c, r)] != comp[n]:
                raw[comp[(c, r)]] += 1
                e = frozenset((comp[(c, r)], comp[n]))
                if e not in doors:
                    kinds[v] += 1
                doors.add(e)
    corridor = []
    for members in spaces:
        s = set(members)
        corridor.append(not any((c + 1, r) in s and (c, r + 1) in s and (c + 1, r + 1) in s for c, r in s))
    degree = collections.Counter()
    for e in doors:
        for k in e:
            degree[k] += 1
    rooms = [i for i in range(len(spaces)) if not corridor[i]]
    corr = [i for i in range(len(spaces)) if corridor[i]]
    # loops of the space graph: edges - nodes + connected parts
    parent = list(range(len(spaces)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in doors:
        a, b = tuple(e) if len(e) == 2 else (next(iter(e)),) * 2
        parent[find(a)] = find(b)
    parts = len({find(i) for i in range(len(spaces))})
    return {
        'cells': len(cells),
        'rooms': len(rooms),
        'room_cells_median': statistics.median(len(spaces[i]) for i in rooms) if rooms else 0,
        'room_cells_max': max((len(spaces[i]) for i in rooms), default=0),
        'corridor_share': sum(len(spaces[i]) for i in corr) / max(1, len(cells)),
        'doors_per_room': statistics.mean(degree[i] for i in rooms) if rooms else 0,
        'doorways_per_room': statistics.mean(raw[i] for i in rooms) if rooms else 0,
        'corridor_spaces': len(corr),
        'loops': len(doors) - len(spaces) + parts,
        'dead_end_rooms': sum(1 for i in rooms if degree[i] == 1) / max(1, len(rooms)),
        'door_kinds': dict(kinds),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--game', type=Path, default=Path(r'D:\SteamLibrary\steamapps\common\Exanima'))
    ap.add_argument('--areas', type=int, default=20)
    a = ap.parse_args()
    rows = []
    names = sorted({m.name.rsplit('/', 1)[-1] for m in rpk.members(a.game / 'Resource.rpk') if m.name.lower().rsplit('/', 1)[-1].startswith('exanima') and m.name.lower().endswith('.rfc')})
    for name in names:
        try:
            lv = level.parse(rpk.read(a.game / 'Resource.rpk', name))
            g = level.grid(lv)
        except Exception as e:  # noqa: BLE001 - a level the reader does not take is listed, not fatal
            print(f'{name}: not read ({e})')
            continue
        rows.append((name, plan_stats(g.layers[0], g.w, g.h)))
    out = HERE.parent / 'out'
    tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
    eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
    eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes())
    gen = []
    for k in range(a.areas):
        seed, area = 1 + k, 1 + (k * 7) % 60
        data, _lay = eg.build_floor(tp, seed, area)
        g = level.grid(level.parse(data))
        gen.append(plan_stats(g.layers[0], g.w, g.h))
    keys = ['cells', 'rooms', 'room_cells_median', 'corridor_share', 'corridor_spaces', 'doors_per_room', 'doorways_per_room', 'loops', 'dead_end_rooms']
    print('level'.ljust(18) + ''.join(k[:14].rjust(15) for k in keys) + '  door kinds')
    for name, st in rows:
        print(name.ljust(18) + ''.join(f'{st[k]:15.2f}' if isinstance(st[k], float) else f'{st[k]:15d}' for k in keys) + f'  {st["door_kinds"]}')
    for label, group in (('vanilla median', [st for _n, st in rows]), (f'generated ({a.areas})', gen)):
        print(label.ljust(18) + ''.join(f'{statistics.median(st[k] for st in group):15.2f}' for k in keys))
    return 0


if __name__ == '__main__':
    sys.exit(main())
