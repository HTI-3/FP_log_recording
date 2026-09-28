#!/usr/bin/env python3
"""Compare the three address views of the curve table from one boot.

    tools/compare_views.py <card dir>

VC.BIN = 0xC0981F34 (cached CPU view), V4.BIN = 0x40981F34, V0.BIN = 0x00981F34.
"""
import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent.parent
CURVES = HERE / 'results/dram_21_09_2026/curves/all_curves.npy'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', type=pathlib.Path)
    ap.add_argument('--curve', type=int, default=16)
    ap.add_argument('--from', dest='lo', type=int, default=800)
    ap.add_argument('--to', dest='hi', type=int, default=1200)
    a = ap.parse_args()

    orig = np.load(CURVES)[a.curve]
    want = orig.copy(); want[a.lo:a.hi] = orig[a.lo]

    got = {}
    for n in ('VC', 'V4', 'V0'):
        p = a.card / f'{n}.BIN'
        if not p.exists():
            print(f'{n}.BIN  MISSING — the camera stopped at or before this view')
            continue
        b = p.read_bytes()
        if len(b) != orig.size * 2:
            print(f'{n}.BIN  wrong size {len(b)}'); continue
        got[n] = np.frombuffer(b, dtype='<u2')

    print(f'{"view":5s} {"file":9s} {"matches":22s} note')
    for n, v in got.items():
        if np.array_equal(v, want):
            what, note = 'the WRITTEN table', 'sees our write'
        elif np.array_equal(v, orig):
            what, note = 'the ORIGINAL table', 'does NOT see our write'
        else:
            what, note = 'neither', f'{int((v != want).sum())} entries differ from written'
        print(f'{n:5s} {n + ".BIN":9s} {what:22s} {note}')

    if not got:
        return 1
    print()
    vals = {n: v.tobytes() for n, v in got.items()}
    if len(set(vals.values())) == 1:
        print('ALL VIEWS IDENTICAL.')
        if np.array_equal(next(iter(got.values())), want):
            print('  DRAM really is updated, and the write is visible everywhere.')
            print('  So cache coherency is NOT the explanation, and this curve bank')
            print('  is not what the video path renders from. Different problem —')
            print('  do not keep writing to it.')
        else:
            print('  Nothing sees the write. Check the card actually ran.')
    else:
        print('VIEWS DISAGREE — this is the cache-coherency result.')
        print('  The CPU view and DRAM hold different bytes, so `mem save` was')
        print('  confirming a write that never reached memory the ISP can see.')
        print('  Fix: clean the D-cache after writing (fp_sup uses F_CACHE')
        print('  0xC000E91C / F_ICACHE 0xC000EABC). That needs a payload, not a')
        print('  bare AutoRun — camera/build_probe_card.py shows the --boot-call')
        print('  pattern.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
