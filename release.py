"""Builds the Endless release: dist/mods/com.necrosis.endless/ and dist/Endless-<version>.zip with a .sha256
beside it.

    python -X utf8 -B release.py [--zip-only | --without-private] [--tag v<version>]

The ZIP holds mods/com.necrosis.endless/ as EMTK loads it from the Exanima folder, without the files built from
the game's own data (PRIVATE), which are never published. Its entries carry a fixed timestamp, so the same files
always give the same SHA256. Before building, the previous mod folder is moved to dist/previous/, so the ZIP holds
only what this build wrote. --zip-only packages the mod folder as it stands. --without-private (CI) copies the
shipped files that need no game data into a scratch folder, so it builds from a clean checkout and never touches dist/mods/. --tag stops unless the tag is
v<manifest version>.
"""
import argparse
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'Endless'
MOD_ID = 'com.necrosis.endless'
DIST = ROOT / 'dist'
PRIVATE = {'assets/endless-template.rfc', 'assets/endless-template.rft', 'assets/endless-template.ini',
           'assets/charroles.rdb', 'assets/endless-dress.bin'}


def assemble(extra: list[str]) -> None:
    subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'tools/make_dist.py'), *extra], check=True)


def assemble_public(mod: Path) -> None:
    spec = importlib.util.spec_from_file_location('make_dist', ROOT / 'tools/make_dist.py')
    make_dist = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_dist)
    for name in make_dist.SHIP:
        if name not in PRIVATE:
            target = mod / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)


def version(mod: Path) -> str:
    match = re.search(r'^version = "([^"]+)"', (mod / 'manifest.toml').read_text(encoding='utf-8'), re.M)
    if not match:
        raise SystemExit(f'{mod / "manifest.toml"} has no version line')
    return match.group(1)


def set_aside(mod: Path) -> None:
    if mod.exists():
        target = DIST / 'previous' / f'{mod.name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}'
        target.parent.mkdir(parents=True, exist_ok=True)
        mod.rename(target)
        print(f'previous build moved to {target}')


def package(mod: Path, name: str) -> Path:
    files = sorted(p for p in mod.rglob('*') if p.is_file() and p.relative_to(mod).as_posix() not in PRIVATE)
    DIST.mkdir(exist_ok=True)
    archive = DIST / f'{name}-{version(mod)}.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for path in files:
            info = zipfile.ZipInfo(f'mods/{mod.name}/{path.relative_to(mod).as_posix()}', date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'RELEASE={archive} files={len(files)} sha256={digest}')
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--zip-only', action='store_true', help='package the mod folder already in dist/')
    parser.add_argument('--without-private', action='store_true', help='build only the files that need no game data')
    parser.add_argument('--tag', help='release tag; must be v<manifest version>')
    args, extra = parser.parse_known_args()
    if args.zip_only and extra:
        parser.error('builder options need a build, not --zip-only')
    if args.without_private:
        # The public files go to a scratch folder: dist/mods/ is the full, playable build the installer copies.
        with tempfile.TemporaryDirectory(prefix='endless-public-') as stage:
            mod = Path(stage) / MOD_ID
            assemble_public(mod)
            return release(mod, args.tag)
    mod = DIST / 'mods' / MOD_ID
    if not args.zip_only:
        set_aside(mod)
        assemble(extra)
    return release(mod, args.tag)


def release(mod: Path, tag: str | None) -> int:
    if not (mod / 'manifest.toml').is_file():
        raise SystemExit(f'no built mod in {mod}')
    if tag and tag != f'v{version(mod)}':
        raise SystemExit(f'tag {tag} does not match manifest version {version(mod)}')
    package(mod, NAME)
    return 0


if __name__ == '__main__':
    sys.exit(main())
