#!/usr/bin/env python3
"""Build the curve-write test card.  THIS ONE WRITES TO THE CAMERA.

*** RUN, AND CLOSED.  The write landed and the picture did not change;
*** the 89-curve bank was later shown inert.  results/curve_1_res/, results/selector/

    camera/build_curvetest_card.py --out camera/curvetest

Flattens a block of entries in the middle of ONE tone curve to a constant, so
that colour mode maps a whole band of input to a single output. On any gradual
tone -- sky, a wall, a grey card -- that is an unmistakable flat band.

  If the band shows   -> the DRAM table IS what the ISP renders from, the
                         mechanism is proven, and the rest of fpLog is packaging.
  If nothing changes  -> toggle the colour mode away and back to force a reload
                         before concluding. `GAM_TOP SBUS GAMMA` in the ISP stage
                         map hints the table may be uploaded to hardware once
                         rather than read per frame.
  If still nothing    -> the DRAM table is not the live source. Say so and stop;
                         do not start poking registers to make it work.

DEFAULT TARGET: curve #16 = colour mode **Teal & Orange** (confirmed on hardware,
results/res_A/FINDINGS.md). NOT curve #82, which is colour mode *Off* -- the
neutral mode, the one worth keeping intact.

WHAT IT WRITES
  `mem set` into DRAM only: a few hundred bytes inside one tone-curve table.
  No `prom`, no `fwup`, no NAND, nothing non-volatile, no payload, no hook.
  Remove AutoRun.txt, take the BATTERY OUT, power on -- the table is whatever
  the boot loader decompresses, i.e. stock. A warm restart does NOT clear RAM.

  It then `mem save`s the table back to the card, because on this camera a write
  is only real once it has been read back.

Firmware Ver.5.02 only.
"""
import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent.parent
CURVES = HERE / 'results/dram_21_09_2026/curves/all_curves.npy'
BANK, STRIDE, NCURVES, N = 0xC0971F34, 0x1000, 89, 2048
MODES = {82: 'Off', 16: 'Teal & Orange'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--curve', type=int, default=16)
    ap.add_argument('--from', dest='lo', type=int, default=800)
    ap.add_argument('--to', dest='hi', type=int, default=1200)
    a = ap.parse_args()

    if not 0 <= a.curve < NCURVES:
        ap.error(f'--curve must be 0..{NCURVES - 1}')
    if a.curve == 82:
        print('WARNING: curve #82 is colour mode "Off", the neutral mode.\n'
              '         #16 (Teal & Orange) is the one to sacrifice.\n', file=sys.stderr)
    if not 0 <= a.lo < a.hi <= N:
        ap.error(f'--from/--to must satisfy 0 <= from < to <= {N}')
    if (a.hi - a.lo) % 2:
        ap.error('the flattened span must be an even number of entries '
                 '(`mem set` writes 32-bit words = 2 entries)')

    M = np.load(CURVES)
    orig = M[a.curve]
    base = BANK + a.curve * STRIDE
    if base % 4 or (base + a.lo * 2) % 4:
        ap.error('table or span start is not word-aligned')

    val = int(orig[a.lo])                      # plateau at the curve's own value
    word = (val << 16) | val                   # two identical u16 per 32-bit word
    nwords = (a.hi - a.lo) // 2
    mode = MODES.get(a.curve, f'unknown (curve #{a.curve})')

    L = []
    W = L.append
    W('# ' + '=' * 72)
    W('# fpLog -- CURVE WRITE TEST.  *** THIS CARD WRITES TO MEMORY ***')
    W('#')
    W(f'# Target: curve #{a.curve} at 0x{base:08X} = colour mode "{mode}".')
    W(f'# Flattens entries {a.lo}..{a.hi - 1} to a constant {val}, so that whole')
    W('# band of input maps to one output. On any gradual tone that is a hard,')
    W('# unmistakable flat band.')
    W('#')
    W(f'#   writes  {nwords} words = {nwords * 4} bytes at '
      f'0x{base + a.lo * 2:08X}..0x{base + a.hi * 2:08X}')
    W(f'#   reads   the whole {N * 2}-byte table back to \\CURVE{a.curve:02d}.BIN')
    W('#')
    W('# HOW TO RUN')
    W(f'#   1. Card in, power on, wait for "CURVE DONE".')
    W(f'#   2. Set colour mode to "{mode}".')
    W('#   3. Point at something with a smooth gradient and look.')
    W('#   4. If nothing: switch colour mode away and back, look again.')
    W('#   5. Copy CURVE%02d.BIN off the card and check the write landed:' % a.curve)
    W(f'#        python3 tools/verify_curve_write.py <card>/CURVE{a.curve:02d}.BIN '
      f'--curve {a.curve} --from {a.lo} --to {a.hi}')
    W('#')
    W('# SAFETY')
    W('#   RAM only. No prom, no fwup, no NAND, nothing non-volatile.')
    W('#   TO REVERT: delete AutoRun.txt, take the BATTERY OUT, power on.')
    W('#   A warm restart does NOT clear RAM.')
    W('#   Firmware Ver.5.02 only -- these addresses are that build\'s.')
    W('#   If the camera behaves oddly at any point: card out, battery out.')
    W('# ' + '=' * 72)
    W('')
    W('display monitor 0 1')
    W('display osd 1 0xFFFFFFFF')
    W('display text CURVE[....]000')
    W('display osd 1')
    W('')
    W(f'# flatten entries {a.lo}..{a.hi - 1} of curve #{a.curve} to {val}')
    for i in range(nwords):
        addr = base + a.lo * 2 + i * 4
        W(f'mem set 0x{addr:08X} 0x{word:08X}')
        if i and i % (max(1, nwords // 3)) == 0:
            f = i / nwords
            W(f'display text CURVE[{"#" * int(f * 4)}{"." * (4 - int(f * 4))}]'
              f'{int(f * 100):03d}')
            W('display osd 1')
    W('')
    W('# read it back -- a write is only real once it has been read back')
    W(f'mem save \\CURVE{a.curve:02d}.BIN 0x{base:08X},,0x{N * 2:X}')
    W('display text CURVE[####]100')
    W('display osd 1')
    W('display text CURVE DONE')
    W('display osd 1')

    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / 'AutoRun.txt'
    dest.write_text('\n'.join(L) + '\n')

    exp = orig.copy()
    exp[a.lo:a.hi] = val
    np.save(a.out / f'expected_curve_{a.curve:02d}.npy', exp)

    nset = sum(1 for l in L if l.startswith('mem set'))
    print(f'wrote {dest}')
    print(f'  target   curve #{a.curve} @ 0x{base:08X}  = colour mode "{mode}"')
    print(f'  flatten  entries {a.lo}..{a.hi - 1} -> {val}  '
          f'(orig {int(orig[a.lo])}..{int(orig[a.hi - 1])})')
    print(f'  writes   {nset} mem set ({nset * 4} bytes), 1 mem save, '
          f'{sum(1 for l in L if l.startswith("prom"))} prom (must be 0)')
    print(f'  expected result saved for verification')
    return 0


if __name__ == '__main__':
    sys.exit(main())
