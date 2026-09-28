#!/usr/bin/env python3
"""Check that the curve write actually landed.

    tools/verify_curve_write.py <card>/CURVE16.BIN --curve 16 --from 800 --to 1200

On this camera a write is only real once it has been read back. The test card
saves the whole table after writing it; this compares that readback against both
the original table and the intended result.
"""
import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent.parent
CURVES = HERE / 'results/dram_21_09_2026/curves/all_curves.npy'
BANK, STRIDE, N = 0xC0971F34, 0x1000, 2048


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('readback', type=pathlib.Path)
    ap.add_argument('--curve', type=int, default=16)
    ap.add_argument('--from', dest='lo', type=int, default=800)
    ap.add_argument('--to', dest='hi', type=int, default=1200)
    a = ap.parse_args()

    b = a.readback.read_bytes()
    if len(b) != N * 2:
        raise SystemExit(f'{a.readback} is {len(b)} bytes, expected {N * 2}')
    got = np.frombuffer(b, dtype='<u2')
    orig = np.load(CURVES)[a.curve]
    want = orig.copy()
    want[a.lo:a.hi] = orig[a.lo]

    print(f'curve #{a.curve} @ 0x{BANK + a.curve * STRIDE:08X}, '
          f'read back {len(b)} bytes\n')
    if np.array_equal(got, want):
        print('  MATCHES the intended result exactly.')
        print(f'  entries {a.lo}..{a.hi - 1} are flat at {int(orig[a.lo])}, '
              f'everything else untouched.')
        print('\n  The write landed. If the picture did not change, the DRAM table')
        print('  is not what the ISP renders from directly -- try a colour-mode')
        print('  toggle, and if that fails too, say so rather than poking further.')
        return 0
    if np.array_equal(got, orig):
        print('  IDENTICAL TO THE ORIGINAL -- the write did not land at all.')
        print('  Check: right firmware version? AutoRun.txt actually ran '
              '(did the banner show)? correct addresses?')
        return 1
    d = np.flatnonzero(got != want)
    inside = d[(d >= a.lo) & (d < a.hi)]
    outside = d[(d < a.lo) | (d >= a.hi)]
    print(f'  PARTIAL / UNEXPECTED: {len(d)} of {N} entries differ from intended')
    print(f'    inside the target span:  {len(inside)}')
    print(f'    OUTSIDE the target span: {len(outside)}'
          f'{"   <-- something else wrote here" if len(outside) else ""}')
    for i in d[:8]:
        print(f'    [{i}] got {got[i]}  want {want[i]}  orig {orig[i]}')
    if len(outside):
        print('\n  Entries changing outside the span means the firmware rewrote the')
        print('  table, or the addresses are wrong. Do not proceed on this result.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
