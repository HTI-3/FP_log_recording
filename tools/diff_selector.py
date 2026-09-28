#!/usr/bin/env python3
"""Diff two selector captures and name the live tone curve.

    tools/diff_selector.py camera/sel_A camera/sel_B
    tools/diff_selector.py --self-test

Each directory holds SELx0.BIN (the descriptor array -- a control that must NOT
change) and SELx1.BIN (live state, where the selection lives).

The answer you want is the line marked SELECTOR: a word that changed between
the two colour modes AND points at a curve table start.
"""
import argparse, pathlib, re, struct, sys

DESC_BASE, LIVE_BASE = 0xC0971000, 0xC3400000
BANK, STRIDE, NCURVES = 0xC0971F34, 0x1000, 89
BANK_END = BANK + NCURVES * STRIDE


def load(d, which):
    hits = [p for p in pathlib.Path(d).iterdir()
            if re.fullmatch(rf'SEL.{which}\.BIN', p.name, re.I)]
    if len(hits) != 1:
        raise SystemExit(f'{d}: expected exactly one SEL?{which}.BIN, found {len(hits)}')
    return hits[0].read_bytes(), hits[0].name


def words(b, base):
    return base, struct.unpack(f'<{len(b) // 4}I', b[:len(b) // 4 * 4])


def curve_of(v):
    if not (BANK <= v < BANK_END):
        return None
    n, off = divmod(v - BANK, STRIDE)
    return n, off


def compare(a_dir, b_dir):
    ok = True
    da, na = load(a_dir, 0)
    db, nb = load(b_dir, 0)
    print(f'control  {na} vs {nb}: '
          f'{"IDENTICAL — good" if da == db else "DIFFERS — see note below"}')
    if da != db:
        ok = False
        print('  The descriptor array is static firmware data. If it changed, either')
        print('  the two runs were not the same firmware, or something is rewriting it.')
        print('  Treat everything below as unreliable until that is explained.')

    la, _ = load(a_dir, 1)
    lb, _ = load(b_dir, 1)
    if len(la) != len(lb):
        raise SystemExit('live windows are different sizes')
    _, wa = words(la, LIVE_BASE)
    _, wb = words(lb, LIVE_BASE)

    changed = [(LIVE_BASE + i * 4, x, y) for i, (x, y) in enumerate(zip(wa, wb)) if x != y]
    print(f'\nlive window: {len(changed):,} of {len(wa):,} words differ')

    sel = [(a, x, y) for a, x, y in changed
           if curve_of(x) and curve_of(y) and curve_of(x)[1] == 0 and curve_of(y)[1] == 0]
    into = [(a, x, y) for a, x, y in changed if curve_of(x) or curve_of(y)]

    if sel:
        print(f'\n*** SELECTOR: {len(sel)} word(s) changed from one curve table start '
              f'to another ***')
        for a, x, y in sel:
            print(f'  0x{a:08X}:  curve #{curve_of(x)[0]} (0x{x:08X})'
                  f'  ->  curve #{curve_of(y)[0]} (0x{y:08X})')
        picked = {curve_of(x)[0] for _, x, _ in sel}, {curve_of(y)[0] for _, _, y in sel}
        print(f'\n  run A selects curve {sorted(picked[0])}, '
              f'run B selects curve {sorted(picked[1])}')
    elif into:
        print(f'\n  {len(into)} changed word(s) touch the curve bank but not at a table '
              f'start — mid-table pointers or coincidence:')
        for a, x, y in into[:10]:
            print(f'    0x{a:08X}: 0x{x:08X} -> 0x{y:08X}')
    else:
        print('\n  No changed word points into the curve bank.')
        print('  Either the two runs used the same colour mode, or the selection is')
        print('  held as an INDEX rather than a pointer, or it lives outside')
        print(f'  0x{LIVE_BASE:08X}..0x{LIVE_BASE + len(la):08X}. If the colour modes really')
        print('  differed, widen the window in camera/build_selector_card.py and')
        print('  look for a small integer 0..88 that changed.')
        ok = False
    return ok


def self_test():
    import tempfile, os
    print('SELF-TEST\n')
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        desc = bytes(0x2000)
        for tag, curve in (('A', 82), ('B', 57)):
            d = t / tag
            d.mkdir()
            (d / f'SEL{tag}0.BIN').write_bytes(desc)
            live = bytearray(0x40000)
            struct.pack_into('<I', live, 0x14510, BANK + curve * STRIDE)
            struct.pack_into('<I', live, 0x14D4C, BANK + curve * STRIDE)
            struct.pack_into('<I', live, 0x20000, 0xDEADBEEF ^ (curve << 8))  # decoy
            (d / f'SEL{tag}1.BIN').write_bytes(bytes(live))
        ok = compare(t / 'A', t / 'B')
    print(f'\nSELF-TEST {"PASSED" if ok else "FAILED"}')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dirs', nargs='*')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if len(a.dirs) != 2:
        ap.error('give two directories, or --self-test')
    return 0 if compare(*a.dirs) else 1


if __name__ == '__main__':
    sys.exit(main())
