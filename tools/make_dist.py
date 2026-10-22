"""Copy the ready-to-ship mod into dist/mods/com.necrosis.endless/ (what the installer and the
packager copy from). The four game-data-derived files under assets/ must have been built first."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_ID = 'com.necrosis.endless'
SHIP = ['manifest.toml', 'scripts/main.lua', 'scripts/gen.lua', 'scripts/build_worker.lua',
        'assets/endless-template.rfc', 'assets/endless-template.ini', 'assets/endless-template.rft', 'assets/charroles.rdb', 'assets/endless-dress.bin',
        'companions/DIALOGUE.md', 'README.md']


def main() -> int:
    missing = [f for f in SHIP if not (ROOT / f).is_file()]
    if missing:
        print('build first; missing: ' + ', '.join(missing))
        return 1
    dest = ROOT / 'dist' / 'mods' / MOD_ID
    if dest.exists():
        shutil.rmtree(dest)
    for f in SHIP:
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / f, dest / f)
    total = sum((dest / f).stat().st_size for f in SHIP)
    print(f'dist: {dest} ({len(SHIP)} files, {total} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
