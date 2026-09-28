#!/usr/bin/env python3
"""Build `share/` -- the distributable card -- from the canonical sources.

    python3 tools/make_share.py            # regenerate share/
    python3 tools/make_share.py --check    # fail if share/ is stale

`share/` is committed so it can be browsed and zipped straight out of the repo.
That means the same code exists twice, which is exactly the drift this project
keeps everything else free of -- `tools/logc.py` emits the camera table, the
.cube and the DCTL precisely so they cannot disagree.

So every derived file in `share/` is generated here and **`--check` is what
closes the loop**: it rebuilds into a temporary directory and compares byte for
byte. Run it before committing. `share/README.md` is hand-written and is the one
file this does not own.
"""
import argparse, filecmp, pathlib, shutil, subprocess, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SHARE = REPO / 'share'

# (source, destination, path-rewrite needed)
COPIES = [
    (REPO / 'tools/logc.py',              'logc.py',       False),
    (REPO / 'camera/build_logc_card.py',  'build_card.py', True),
    (REPO / 'tools/check_logc.py',        'check_card.py', True),
]
# what build_logc_card.py emits, and where it lands in share/
FROM_CARD = [('AutoRun.txt', 'AutoRun.txt'), ('expected.csv', 'expected.csv'),
             ('curve.txt', 'curve.txt'),
             ('fplog_decode.cube', 'decode/fplog_decode.cube'),
             ('fplog_decode.dctl', 'decode/fplog_decode.dctl')]

REWRITES = {
    # the share folder is flat, so siblings import from beside themselves
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'tools'))":
        "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))",
    "sys.path.insert(0, str(HERE))":
        "sys.path.insert(0, str(HERE))",
    # the 64 MB dump is not shipped, so the stock comparison is skipped
    "DUMP = HERE.parent / 'results/dram_21_09_2026/dram_C0000000.bin'":
        "DUMP = HERE / 'stock_curve.bin'    # not shipped; stock comparison skipped",
    # and the tools are renamed on the way in
    "python3 tools/check_logc.py /Volumes/<card>/LOGC82.BIN":
        "python3 check_card.py /Volumes/<card>/LOGC82.BIN",
    "python3 tools/check_logc.py --self-test":
        "python3 check_card.py --self-test",
    "python3 camera/build_logc_card.py --out camera/cards/logc":
        "python3 build_card.py --out ./card",
}


def build(dest: pathlib.Path):
    """Write every derived file of the share folder into `dest`."""
    (dest / 'decode').mkdir(parents=True, exist_ok=True)
    for src, name, rewrite in COPIES:
        text = src.read_text()
        if rewrite:
            for a, b in REWRITES.items():
                text = text.replace(a, b)
        out = dest / name
        out.write_text(text)
        out.chmod(0o755)

    with tempfile.TemporaryDirectory() as td:
        card = pathlib.Path(td) / 'card'
        subprocess.run([sys.executable, str(REPO / 'camera/build_logc_card.py'),
                        '--out', str(card)], check=True,
                       stdout=subprocess.DEVNULL)
        for a, b in FROM_CARD:
            shutil.copy2(card / a, dest / b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='exit non-zero if share/ differs from a fresh build')
    a = ap.parse_args()

    if a.check:
        if not SHARE.exists():
            print('share/ does not exist'); return 1
        with tempfile.TemporaryDirectory() as td:
            ref = pathlib.Path(td) / 'share'
            build(ref)
            bad = []
            for p in sorted(ref.rglob('*')):
                if p.is_dir():
                    continue
                rel = p.relative_to(ref)
                cur = SHARE / rel
                if not cur.exists():
                    bad.append(f'missing: {rel}')
                elif not filecmp.cmp(p, cur, shallow=False):
                    bad.append(f'stale:   {rel}')
            for line in bad:
                print(' ', line)
            if bad:
                print(f'\nshare/ is out of date -- run: python3 tools/make_share.py')
                return 1
            print(f'share/ is current ({sum(1 for _ in ref.rglob("*") if _.is_file())} '
                  f'generated files match)')
            return 0

    build(SHARE)
    files = sorted(p.relative_to(SHARE) for p in SHARE.rglob('*') if p.is_file())
    total = sum((SHARE / f).stat().st_size for f in files)
    print(f'wrote {SHARE}  ({len(files)} files, {total / 1024:.0f} KB)')
    for f in files:
        print(f'  {f}')
    print('\nshare/README.md is hand-written and not generated.')
    print('Verify with: python3 tools/make_share.py --check')
    return 0


if __name__ == '__main__':
    sys.exit(main())
