#!/usr/bin/env python3
"""Read the invert card's three rounds and name which of the four outcomes it is.

    python3 tools/check_invert.py <card dir> --curves 82,16
    python3 tools/check_invert.py --self-test

The card (camera/build_invert_card.py) inverts one or more curves in the
452-entry `GAM_TOP GAMMA TABLE` registry, then has the operator toggle the
colour mode to force the firmware's upload.  It dumps every window three times:

    V1nn.BIN  baseline, before anything is written
    V2nn.BIN  after the inversion, before the toggle
    V3nn.BIN  after the toggle

Window nn is 00..(k-1) for the k inverted curves, then the DRAM selector, then
the ISP shadow bank.  This tool decides:

  1. did the write land?          round 2 table == max - round 1 table
  2. did the firmware keep it?    round 3 table == round 2 table
  3. did the upload happen?       the ISP bank moved across the toggle

**It cannot see the picture.** The operator's observation is the fourth input,
and this tool narrows the answer to the outcomes that observation separates.

ON 0x30210594.  results/isprobe_1/ measured it as 65 x u16, 0 -> 2048 in steps
of 32 -- a UNITY ramp, which reads as a knot axis rather than as output values.
So this tool does not predict what it should become.  It diffs the whole bank
across the rounds and prints that word's neighbourhood, which is evidence either
way; claiming to know what value to expect there would be inventing a control.
"""
import argparse, pathlib, sys
import numpy as np

BANK, STRIDE, N = 0xC0971F34, 0x1000, 2048
NCURVES = 452
MODES = {82: 'Off', 16: 'Teal & Orange'}
RAMP_OFF, RAMP_N = 0x594, 65          # 0x30210594, 65 x u16 (results/isprobe_1/)
ROUNDS = ('1', '2', '3')


def _u16(b):
    return np.frombuffer(b, dtype='<u2', count=len(b) // 2).astype(np.int64)


def _u32(b):
    return np.frombuffer(b, dtype='<u4', count=len(b) // 4)


def load(card, rnd, idx):
    p = card / f'V{rnd}{idx:02d}.BIN'
    return p.read_bytes() if p.exists() else None


def selector_hits(b, base=0xC3414000):
    """Offsets in the window whose word points at a curve table start."""
    out = []
    for i, v in enumerate(_u32(b)):
        v = int(v)
        if BANK <= v < BANK + NCURVES * STRIDE and (v - BANK) % STRIDE == 0:
            out.append((base + i * 4, (v - BANK) // STRIDE))
    return out


def check_curve(idx, cid, rounds):
    """Return (write_landed, held, note) for one curve's three dumps."""
    r1, r2, r3 = (_u16(rounds[k]) if rounds[k] else None for k in ROUNDS)
    name = f'curve #{cid} "{MODES.get(cid, "?")}"'
    if r1 is None or r2 is None:
        return None, None, f'{name}: missing V1{idx:02d}.BIN or V2{idx:02d}.BIN'

    mx = int(r1.max())
    want = mx - r1
    landed = bool(len(r1) == len(r2) and (r2 == want).all())
    lines = [f'{name} @ 0x{BANK + cid * STRIDE:08X}',
             f'    round 1  {r1[0]:5d} .. {r1[-1]:5d}   max {mx}'
             f'   {"non-decreasing" if (np.diff(r1) >= 0).all() else "NOT MONOTONIC"}',
             f'    round 2  {r2[0]:5d} .. {r2[-1]:5d}'
             f'   {"non-increasing" if (np.diff(r2) <= 0).all() else "NOT MONOTONIC"}'
             f'   {"== inverted round 1" if landed else "!= inverted round 1"}']
    if not landed:
        n = int((r2 != want).sum()) if len(r1) == len(r2) else -1
        lines.append(f'    {n} of {len(r1)} entries differ from the inversion')
        if (r2 == r1).all():
            lines.append('    round 2 is byte-identical to round 1: '
                         'the write did not land at all')
    held = None
    if r3 is not None:
        held = bool(len(r3) == len(r2) and (r3 == r2).all())
        lines.append(f'    round 3  {r3[0]:5d} .. {r3[-1]:5d}'
                     f'   {"unchanged since round 2" if held else "CHANGED since round 2"}')
        if held is False and (r3 == r1).all():
            lines.append('    round 3 is the STOCK table: the firmware put it back')
    return landed, held, '\n'.join(lines)


def isp_report(rounds, base=0x30210000):
    """Diff the shadow bank across rounds; the toggle sits between 2 and 3."""
    have = {k: rounds[k] for k in ROUNDS if rounds[k]}
    if len(have) < 2:
        return None, 'ISP bank: fewer than two rounds captured'
    out, moved = [], None
    ks = sorted(have)
    for a, b in zip(ks, ks[1:]):
        wa, wb = _u32(have[a]), _u32(have[b])
        n = int((wa != wb).sum()) if len(wa) == len(wb) else -1
        tag = 'the mode toggle' if (a, b) == ('2', '3') else 'the inversion'
        out.append(f'    round {a} -> {b}  ({tag}): {n} of {len(wa)} words differ')
        if (a, b) == ('2', '3'):
            moved = n > 0
    for k in ks:
        r = _u16(have[k])[RAMP_OFF // 2: RAMP_OFF // 2 + RAMP_N]
        head = ' '.join(str(int(v)) for v in r[:6])
        out.append(f'    round {k}  0x{base + RAMP_OFF:08X}: {head} ...'
                   f'  (min {int(r.min())}, max {int(r.max())})')
    return moved, f'ISP shadow bank 0x{base:08X}\n' + '\n'.join(out)


def verdict(landed, held, uploaded):
    """The four outcomes of docs/CURVE_TARGETS.md target 1, narrowed."""
    if landed is False:
        return ('OUTCOME 4 -- the table does not hold our bytes.\n'
                '  Either the write never happened or the firmware composes this\n'
                '  table from somewhere else. Find what writes it before anything\n'
                '  else; nothing below this line is interpretable.')
    if held is False:
        return ('OUTCOME 4 -- the write landed and the firmware REWROTE it.\n'
                '  The table is composed, not static. That is a real finding: the\n'
                '  composer is the thing to find, and it runs on a mode change.')
    if uploaded is False:
        return ('OUTCOME 2 -- written, held, but the ISP bank did not move.\n'
                '  The upload trigger is something other than a colour-mode change.\n'
                '  Before concluding: check the selector below actually changed\n'
                '  between rounds. If it did not, the operator did not toggle and\n'
                '  this run says nothing -- re-run it.')
    if uploaded:
        return ('The table holds our inverted bytes AND the ISP bank moved across\n'
                '  the toggle, so the upload happened. THE PICTURE DECIDES:\n'
                '    negative picture  -> OUTCOME 1. The transfer function is\n'
                '                         reachable. Everything after is curve\n'
                '                         fitting. This is the result the project\n'
                '                         has been trying to reach.\n'
                '    picture unchanged -> OUTCOME 3. This bank feeds a path that\n'
                '                         is not the video render.')
    return 'Not enough rounds captured to decide. Read the files by hand.'


def self_test():
    ok = True
    stock = np.clip(np.arange(N) * 4, 0, 8190).astype(np.int64)
    inv = int(stock.max()) - stock

    def pack(a):
        return a.astype('<u2').tobytes()

    # landed and held
    l, h, _ = check_curve(0, 82, {'1': pack(stock), '2': pack(inv), '3': pack(inv)})
    ok &= (l, h) == (True, True)
    # write did not land
    l, h, _ = check_curve(0, 82, {'1': pack(stock), '2': pack(stock), '3': pack(stock)})
    ok &= (l, h) == (False, True)
    # landed then rewritten
    l, h, _ = check_curve(0, 82, {'1': pack(stock), '2': pack(inv), '3': pack(stock)})
    ok &= (l, h) == (True, False)
    print(f'  curve checks                      {"PASS" if ok else "FAIL"}')

    # a uint16 view would wrap every fall to +65000; the check must not
    d = bool((np.diff(inv) <= 0).all())
    print(f'  inverted curve reads non-increasing  {"PASS" if d else "FAIL"}')
    ok &= d

    # selector: a word pointing at curve 82's table must resolve to 82
    buf = np.zeros(0x400, dtype='<u4'); buf[3] = BANK + 82 * STRIDE
    hits = selector_hits(buf.tobytes())
    s = hits == [(0xC3414000 + 12, 82)]
    print(f'  selector resolves 0x{BANK + 82 * STRIDE:08X} -> 82   {"PASS" if s else "FAIL"}')
    ok &= s

    # a word one byte off a table start must NOT resolve -- the decoy
    buf = np.zeros(0x400, dtype='<u4'); buf[3] = BANK + 82 * STRIDE + 4
    d2 = selector_hits(buf.tobytes()) == []
    print(f'  misaligned pointer is not a hit      {"PASS" if d2 else "FAIL"}')
    ok &= d2

    # ISP diff: identical rounds -> not moved, differing -> moved
    a = np.zeros(0x400, dtype='<u4').tobytes()
    b = np.ones(0x400, dtype='<u4').tobytes()
    m1, _ = isp_report({'1': a, '2': a, '3': a})
    m2, _ = isp_report({'1': a, '2': a, '3': b})
    i = (m1 is False) and (m2 is True)
    print(f'  ISP bank movement across the toggle  {"PASS" if i else "FAIL"}')
    ok &= i

    # the four outcomes must each be reachable from the right inputs
    v = all([
        'OUTCOME 4' in verdict(False, None, None),      # write never landed
        'REWROTE'   in verdict(True, False, None),      # landed, then rewritten
        'OUTCOME 2' in verdict(True, True, False),      # held, no upload
        'OUTCOME 1' in verdict(True, True, True),       # held, uploaded
    ])
    print(f'  all four outcomes reachable          {"PASS" if v else "FAIL"}')
    ok &= v

    print('\nSELF-TEST ' + ('PASSED' if ok else 'FAILED'))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', nargs='?', type=pathlib.Path)
    ap.add_argument('--curves', default='82,16')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.card is None:
        ap.error('give a card directory, or --self-test')

    curves = [int(x) for x in a.curves.split(',') if x.strip()]
    nwin = len(curves) + 2                      # curves, selector, ISP bank
    missing = [f'V{r}{i:02d}.BIN' for r in ROUNDS for i in range(nwin)
               if not (a.card / f'V{r}{i:02d}.BIN').exists()]
    if missing:
        print(f'MISSING {len(missing)} of {nwin * 3} files: {" ".join(missing)}')
        print('The payload writes each file as soon as it is read, so the first')
        print('missing one is where it stopped. Read the rest anyway.\n')

    print(f'{a.card}  -- {len(curves)} curve(s), {nwin} windows, 3 rounds\n')

    landed_all, held_all = [], []
    for i, cid in enumerate(curves):
        l, h, note = check_curve(i, cid, {r: load(a.card, r, i) for r in ROUNDS})
        print(note + '\n')
        landed_all.append(l)
        held_all.append(h)

    sel_i = len(curves)
    for r in ROUNDS:
        b = load(a.card, r, sel_i)
        if b:
            hits = selector_hits(b)
            which = sorted({c for _, c in hits})
            print(f'selector round {r}: {len(hits)} pointer(s) -> curve(s) {which}')
    print()

    moved, note = isp_report({r: load(a.card, r, sel_i + 1) for r in ROUNDS})
    print(note + '\n')

    def agg(xs):
        xs = [x for x in xs if x is not None]
        if not xs:
            return None
        return all(xs) if all(x is not None for x in xs) else None

    print('=' * 72)
    print(verdict(agg(landed_all), agg(held_all), moved))
    print('=' * 72)
    if len(curves) > 1 and len(set(x for x in landed_all if x is not None)) > 1:
        print('\nNOTE: the curves did not behave the same way. That asymmetry is')
        print('the finding -- record which curve did what, per colour mode.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
