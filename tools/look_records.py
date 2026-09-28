#!/usr/bin/env python3
"""Print the look-record bank with its VERIFIED field layout.

    python3 tools/look_records.py results/dram_21_09_2026/dram_C0000000.bin

This exists because the layout in the first version of docs/LOOK_CURVE.md was
wrong, and every card built against it aimed 0x90 bytes past the record start.
The layout below is not asserted -- it is checked, and the script fails if the
check fails:

    a record is 0x124 bytes
      +0x000   24 x u16   knots  A
      +0x030   24 x u16   gains  A
      +0x060   24 x u16   slopes A
      +0x090   24 x u16   knots  B
      +0x0C0    1 x u16   record id
      +0x0C2    1 x u16   zero
      +0x0C4   24 x u16   gains  B
      +0x0F4   24 x u16   slopes B

The test that pins it: on this grid, and on no other alignment, +0x0C0 reads a
small distinct id and +0x0C2 reads zero for 36 consecutive records.

  --self-test   synthesise a bank, recover it, and require an exact match
"""
import argparse, pathlib, struct, sys

BANK = 0xC0B3AB80          # first record
NREC = 36
STRIDE = 0x124
NKNOT = 24
IDENT = tuple(round(i * 65536 / NKNOT) for i in range(NKNOT))

FIELDS = (('knots A', 0x000), ('gains A', 0x030), ('slopes A', 0x060),
          ('knots B', 0x090), ('gains B', 0x0C4), ('slopes B', 0x0F4))
ID_OFF, ZERO_OFF = 0x0C0, 0x0C2


def arr(buf, off, n=NKNOT):
    return struct.unpack_from('<%dH' % n, buf, off)


def u16(buf, off):
    return struct.unpack_from('<H', buf, off)[0]


def check_layout(buf, bank_off):
    """The id/zero test. Returns the ids, or raises."""
    ids, bad = [], []
    for n in range(NREC):
        s = bank_off + n * STRIDE
        i, z = u16(buf, s + ID_OFF), u16(buf, s + ZERO_OFF)
        if i > 63 or z != 0:
            bad.append((n, i, z))
        ids.append(i)
    if bad:
        raise SystemExit(
            'layout check FAILED: %d of %d records have no small id / zero '
            'at +0x%03X/+0x%03X -- first %r' % (len(bad), NREC, ID_OFF,
                                                ZERO_OFF, bad[0]))
    return ids


def describe(v):
    if v == IDENT:
        return 'identity'
    if len(set(v)) == 1:
        return '%04X' % v[0]
    return 'shaped'


def report(buf, base, bank=BANK):
    off = bank - base
    ids = check_layout(buf, off)
    print('layout check PASSED: %d records at 0x%08X, stride 0x%X, '
          'small id at +0x%03X\n' % (NREC, bank, STRIDE, ID_OFF))
    hdr = ['rec', 'start', 'id'] + [n for n, _ in FIELDS]
    print('  %-4s %-10s %-4s %s' % (hdr[0], hdr[1], hdr[2],
                                    ' '.join('%-9s' % h for h in hdr[3:])))
    for n in range(NREC):
        s = off + n * STRIDE
        cells = ' '.join('%-9s' % describe(arr(buf, s + o)) for _, o in FIELDS)
        print('  %-4d 0x%08X %-4d %s' % (n, base + s, ids[n], cells))
    print('\nknots B of record n -- the array every card in this repository '
          'has written --\nis at record_start + 0x090, NOT at a record start.')
    return ids


def self_test():
    """Plant a bank in noise, recover it, require an exact match."""
    import random
    random.seed(7)
    buf = bytearray(random.getrandbits(8) for _ in range(0x20000))
    base, bank = 0xC0000000, 0xC0000000 + 0x1000
    want = []
    for n in range(NREC):
        s = bank - base + n * STRIDE
        for _, o in FIELDS:
            vals = IDENT if o in (0x000, 0x090) else tuple([0x200] * NKNOT)
            struct.pack_into('<%dH' % NKNOT, buf, s + o, *vals)
        struct.pack_into('<HH', buf, s + ID_OFF, n, 0)
        want.append(n)
    got = check_layout(buf, bank - base)
    assert got == want, (got, want)
    # and it must REJECT the off-by-0x90 alignment the old docs used
    try:
        check_layout(buf, bank - base + 0x90)
    except SystemExit:
        pass
    else:
        raise SystemExit('self-test FAILED: the +0x90 alignment was accepted')
    print('self-test PASSED: bank recovered exactly, +0x90 alignment rejected')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?', type=pathlib.Path)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('--bank', type=lambda s: int(s, 0), default=BANK)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.dump:
        raise SystemExit('give a dump, or --self-test')
    report(a.dump.read_bytes(), a.base, a.bank)
    return 0


if __name__ == '__main__':
    sys.exit(main())
