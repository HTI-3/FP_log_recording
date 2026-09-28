#!/usr/bin/env python3
"""Build a READ-ONLY AutoRun that captures which tone curve is selected.

    camera/build_selector_card.py --tag A --out camera/sel_A
    camera/build_selector_card.py --tag B --out camera/sel_B

Run card A with the camera in one colour mode, card B in another, then:

    python3 tools/diff_selector.py <cardA files> <cardB files>

WHY NOT THE DESCRIPTOR ARRAY
  An earlier note in this project said to diff the descriptor array. **That was
  wrong.** 0xC0971118 is static data inside the decompressed firmware image:
  entry n is {pointer to curve n, n+1}, an index, and it does not change with
  camera state. It is dumped here only as a control -- if it ever differs
  between two runs, something else is going on and the rest is untrustworthy.

  The selection lives in the live-state region ABOVE the firmware image. In the
  2026-09-21 dump, three words there pointed at curve #82's table start:
  0xC3414510, 0xC3414D4C, 0xC3414D84. Those are what change.

READ-ONLY: every line is `mem save`, `display`, or a comment. No `mem set`, no
`prom`, no NAND, no payload. Delete AutoRun.txt, power-cycle, camera is stock.
Firmware Ver.5.02 only.
"""
import argparse, pathlib, sys

# (name, start, size, why)
WINDOWS = [
    ('0', 0xC0971000, 0x2000,
     'descriptor array 0xC0971118 + context -- the CONTROL, must not change'),
    ('1', 0xC3400000, 0x40000,
     'live state around the three selector words seen at 0xC34145xx/0xC3414Dxx'),
]
BANK, STRIDE, NCURVES = 0xC0971F34, 0x1000, 89


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True, help='one letter, A or B')
    ap.add_argument('--out', type=pathlib.Path, required=True)
    a = ap.parse_args()
    if len(a.tag) != 1 or not a.tag.isalnum():
        ap.error('--tag must be a single alphanumeric character')
    tag = a.tag.upper()

    a.out.mkdir(parents=True, exist_ok=True)
    total = sum(w[2] for w in WINDOWS)
    L = []
    W = L.append
    W('# ' + '=' * 72)
    W(f'# fpLog -- tone-curve SELECTOR capture, run "{tag}".  READ-ONLY.')
    W('#')
    W('# Run this card with the camera in ONE colour mode.  Then build a card')
    W('# with a different --tag, set a DIFFERENT colour mode, and run that.')
    W('# Diff the two with tools/diff_selector.py: the word that changes and')
    W('# points into the curve bank is the live selector.')
    W('#')
    for n, s, sz, why in WINDOWS:
        W(f'#   SEL{tag}{n}.BIN  0x{s:08X}..0x{s + sz:08X}  {sz // 1024:>4} KiB  -- {why}')
    W('#')
    W(f'# {total // 1024} KiB total. Nothing is written to NAND, EEPROM or any other')
    W('# non-volatile store -- every line below is `mem save` or `display`.')
    W('# Firmware Ver.5.02 only.  Delete the old SEL*.BIN before re-running:')
    W('# `mem save` may fail rather than overwrite.')
    W('# ' + '=' * 72)
    W('')
    W('display monitor 0 1')
    W('display osd 1 0xFFFFFFFF')
    W(f'display text SEL{tag}[..]000')
    W('display osd 1')
    W('')
    for i, (n, s, sz, why) in enumerate(WINDOWS):
        W(f'# {why}')
        W(f'mem save \\SEL{tag}{n}.BIN 0x{s:08X},,0x{sz:X}')
        W(f'display text SEL{tag}[{"#" * (i + 1)}{"." * (len(WINDOWS) - i - 1)}]'
          f'{int(100 * (i + 1) / len(WINDOWS)):03d}')
        W('display osd 1')
        W('')
    W(f'display text SEL{tag} DONE')
    W('display osd 1')

    dest = a.out / 'AutoRun.txt'
    dest.write_text('\n'.join(L) + '\n')
    print(f'wrote {dest}')
    print(f'  run "{tag}": files SEL{tag}0.BIN, SEL{tag}1.BIN  ({total // 1024} KiB)')
    print(f'  check {sum(1 for l in L if l.startswith("mem save"))} mem save, '
          f'{sum(1 for l in L if l.startswith("mem set"))} mem set (must be 0)')
    print('\n  Card A in colour mode 1, card B in colour mode 2, then:')
    print('    python3 tools/diff_selector.py <dirA> <dirB>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
