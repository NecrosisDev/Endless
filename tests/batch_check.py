"""Generate many areas and run the consistency checks: grid rules, one exit doorway,
everything reachable, determinism. Prints a one-line summary (exit code 1 on problems)."""
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'generator'))
sys.path.insert(0, os.environ.get('EXANIMATE_TOOLS') or str(HERE.parents[3] / 'tools' / 'exanimate'))
import endless_gen as eg  # noqa: E402
from exanimate import level  # noqa: E402


def main() -> int:
    out = HERE.parent / 'out'
    tp = eg.load_template((out / 'endless-template.rfc').read_bytes(), (out / 'endless-template.ini').read_text(encoding='ascii'))
    eg.load_terrain_template(tp, (out / 'endless-template.rft').read_bytes())
    eg.load_dress(tp, (out / 'endless-dress.bin').read_bytes() if (out / 'endless-dress.bin').exists() else b'')
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    areas = (1, 2, 3, 4, 6, 9, 13, 20, 33, 100)
    bad = n = 0
    counts, sizes = [], []
    t = time.time()
    for seed in range(1, seeds + 1):
        for area in areas:
            data, lay = eg.build_floor(tp, seed, area)
            n += 1
            back = level.parse(data)
            problems = eg.decode_check(level.grid(back).layers, lay)
            if eg.build_floor(tp, seed, area)[0] != data:
                problems.append('not deterministic')
            if problems:
                bad += 1
                print('problems', seed, area, problems[:3])
            counts.append(len(back.spawns))
            sizes.append(len(data))
    print(f'areas {n}, with problems {bad}, avg {(time.time() - t) / n:.3f} s/area, spawns {min(counts)}..{max(counts)}, bytes {min(sizes)}..{max(sizes)}, tiers {[len(tp.enemy_ids)] + [len(x) for x in tp.enemy_tiers]} bosses {[len(x) for x in tp.boss_tiers]}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
