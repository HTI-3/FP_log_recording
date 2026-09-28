#!/usr/bin/env python3
"""Which curve is actually in the camera?  Reads LOGC82.BIN back off the card.

    python3 tools/check_logc.py /Volumes/<card>/LOGC82.BIN
    python3 tools/check_logc.py --self-test

The Log C card ends with `mem save \\LOGC82.BIN`, so every run leaves the table
the camera was really holding on the card. This identifies it against every form
the project has built, and against the stock curve.

**Why it exists.** A frame was reported as still showing the highlight artefact
after the roll-off was reverted. The frame's own histogram said otherwise -- it
had no ceiling pile-up, which spec-exact cannot avoid -- and the argument took
several measurements to make. `LOGC82.BIN` answers it in one command, with no
inference at all.
"""
import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import logc

DUMP = HERE.parent / 'results/dram_21_09_2026/dram_C0000000.bin'


def candidates(ei=800):
    out = {
        'spec-exact Log C  (SHIPS)': logc.camera_table(ei),
        'Log C + roll-off  (rejected, results/logc3/)':
            logc.camera_table(ei, rolloff=True),
        'Log C --fit-range (rejected, results/logc2/)':
            logc.camera_table(ei, fit_range=True),
        'Log C --stretch   (black..white onto 0..255)':
            logc.camera_table(ei, stretch=True),
    }
    if DUMP.exists():
        with DUMP.open('rb') as f:
            f.seek(0xC0971F34 - 0xC0000000 + 82 * 0x1000)
            out['stock sRGB (camera is unmodified)'] = list(
                np.frombuffer(f.read(4096), dtype='<u2'))
    return out


def identify(table, ei=800):
    got = np.asarray(table, np.int64)
    rows = []
    for name, ref in candidates(ei).items():
        ref = np.asarray(ref, np.int64)
        if len(ref) != len(got):
            continue
        d = np.abs(got - ref)
        rows.append((int(d.max()), float(d.mean()), name))
    rows.sort()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path', nargs='?', type=pathlib.Path)
    ap.add_argument('--ei', type=int, default=800, choices=sorted(logc.EXPOSURE))
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        ok = True
        for want, kw in (('spec-exact', {}), ('roll-off', dict(rolloff=True)),
                         ('fit-range', dict(fit_range=True)),
                         ('stretch', dict(stretch=True))):
            rows = identify(logc.camera_table(800, **kw))
            good = rows[0][0] == 0 and want.replace('-', '-') in rows[0][2]
            print(f'  identifies {want:<12} as "{rows[0][2][:34]}"  '
                  f'max diff {rows[0][0]}   {"PASS" if good else "FAIL"}')
            ok &= good
        # a table that is none of them must not be claimed as an exact match
        odd = [min(v + 37, 8190) for v in logc.camera_table(800)]
        rows = identify(odd)
        good = rows[0][0] > 0
        print(f'  an unknown table is not claimed exact       max diff '
              f'{rows[0][0]}   {"PASS" if good else "FAIL"}')
        ok &= good
        print('\nSELF-TEST ' + ('PASSED' if ok else 'FAILED'))
        return 0 if ok else 1

    if a.path is None:
        ap.error('give the path to LOGC82.BIN, or --self-test')
    b = a.path.read_bytes()
    if len(b) != 4096:
        print(f'{a.path} is {len(b)} bytes, expected 4096 -- is this the right file?')
        return 1
    got = np.frombuffer(b, dtype='<u2').astype(np.int64)

    print(f'{a.path}\n')
    print(f'  first 4 entries {list(got[:4])}   last 4 {list(got[-4:])}')
    print(f'  range {got.min()}..{got.max()} of 8190'
          f'   (8-bit {round(int(got.min()) / 8190 * 255)}'
          f'..{round(int(got.max()) / 8190 * 255)})')
    print(f'  monotonic: {bool((np.diff(got) >= 0).all())}\n')
    print(f'  {"candidate":<46}{"max diff":>9}{"mean":>9}')
    for mx, mean, name in identify(got, a.ei):
        print(f'  {name:<46}{mx:9d}{mean:9.2f}')
    mx, _, name = identify(got, a.ei)[0]
    print()
    if mx == 0:
        print(f'  EXACT MATCH: {name}')
    elif mx <= 2:
        print(f'  matches {name} to within {mx} codes -- almost certainly it')
    else:
        print(f'  Closest is {name}, but off by {mx} codes.')
        print('  That is not one of the tables this project builds. Either the')
        print('  card did not run, the firmware rewrote it, or the build differs.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
