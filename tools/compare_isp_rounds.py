#!/usr/bin/env python3
"""Read the live ISP probe's two rounds and say what the colour mode changed.

    tools/compare_isp_rounds.py <card dir>

Windows, in the order camera/isp_live_probe.S dumps them:
  0 0x300C0000  RFC readout          3 0x301B0000  the DSP recording uses
  1 0x300D0000  lossless JPEG        4 0x30210000  shadow config (control)
  2 0x300E0000  third dead block     5 0xC3414000  DRAM tone-curve selector
"""
import argparse, pathlib, struct, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from find_curves import scan

WIN = [(0xC3414000, 'DRAM selector (control)')] + \
      [(0x30210000 + _k * 0x1000, f'ISP config +0x{_k * 0x1000:04X}')
       for _k in range(16)]

BANK, STRIDE, NC = 0xC0971F34, 0x1000, 89
DEAD = (0x00000000, 0xFFFFFFFF)


def words(b):
    return np.frombuffer(b, dtype='<u4', count=len(b) // 4)


def curves_in(b, base):
    return [r for r in scan(b, base) if r['n'] >= 64]


def selector(b, base):
    out = []
    for i, v in enumerate(words(b)):
        v = int(v)
        if BANK <= v < BANK + NC * STRIDE and (v - BANK) % STRIDE == 0:
            out.append((base + i * 4, (v - BANK) // STRIDE))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', type=pathlib.Path)
    a = ap.parse_args()

    print(f'{"win":3s} {"address":>10} {"round 1":>22} {"round 2":>22}  block')
    have = {}
    for i, (base, why) in enumerate(WIN):
        row = []
        for r in (1, 2):
            p = a.card / f'L{r}{i:02d}.BIN'
            if not p.exists():
                row.append(None); continue
            b = p.read_bytes()
            have[(r, i)] = (b, base)
            w = words(b)
            live = int(np.sum(~np.isin(w, DEAD)))
            row.append((len(b), live, len(w)))
        def fmt(x):
            return 'MISSING' if x is None else (
                'dead' if x[1] == 0 else f'live {x[1]}/{x[2]} words')
        print(f'{i:3d} 0x{base:08X} {fmt(row[0]):>22} {fmt(row[1]):>22}  {why}')

    print('\n--- which curve was selected in each round (window 0) ---')
    for r in (1, 2):
        if (r, 0) in have:
            b, base = have[(r, 0)]
            s = selector(b, base)
            print(f'  round {r}: ' + (', '.join(f'0x{a_:08X} -> curve #{c}'
                                                for a_, c in s) if s
                                      else 'no curve pointer in this window'))

    print('\n--- what the colour mode changed, per window ---')
    found = False
    for i, (base, why) in enumerate(WIN):
        if (1, i) not in have or (2, i) not in have:
            continue
        b1, b2 = have[(1, i)][0], have[(2, i)][0]
        if len(b1) != len(b2):
            print(f'  win {i}: sizes differ, skipped'); continue
        w1, w2 = words(b1), words(b2)
        d = np.flatnonzero(w1 != w2)
        if d.size == 0:
            print(f'  win {i} 0x{base:08X}: identical')
            continue
        found = True
        print(f'  win {i} 0x{base:08X}: {d.size} of {w1.size} words differ'
              f'   (first 0x{base + int(d[0]) * 4:08X})')
        runs = np.split(d, np.flatnonzero(np.diff(d) != 1) + 1)
        big = [r for r in runs if r.size >= 64]
        for r in big[:4]:
            print(f'      contiguous run of {r.size} words at '
                  f'0x{base + int(r[0]) * 4:08X}   <-- LUT-SIZED' if r.size >= 512
                  else f'      contiguous run of {r.size} words at '
                       f'0x{base + int(r[0]) * 4:08X}')

    print('\n--- monotonic tables inside the live register windows ---')
    for r in (1, 2):
        for i in range(1, len(WIN)):
            if (r, i) not in have:
                continue
            b, base = have[(r, i)]
            c = curves_in(b, base)
            if c:
                print(f'  round {r} win {i} 0x{base:08X}: {len(c)} candidate(s)')
                for x in c[:3]:
                    print(f'      0x{x["addr"]:08X}  {x["n"]} x u{x["width"] * 8}'
                          f'  {int(x["lo"])}..{int(x["hi"])}  {x["shape"]}')
    if not found:
        print('\nNothing changed between the rounds. Either the colour mode was not')
        print('changed in time, the camera slept, or the blocks are still gated.')
        print('Check the "round 1 / round 2" columns above: if they read "dead",')
        print('the imaging domain was still powered down and the timing needs work.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
