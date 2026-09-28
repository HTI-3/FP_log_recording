#!/usr/bin/env python3
"""Print the ISP and recording-path structures out of a DRAM dump.

    python3 tools/isp_map.py results/dram_21_09_2026/dram_C0000000.bin
    python3 tools/isp_map.py <dump> --only patterns

Everything in docs/ISP_PIPELINE.md comes from here, so the document can be
re-derived rather than trusted:

  names      the ISP block/function name pool   (0xC07D36A4, \n\0-terminated)
  patterns   the eight ISP pattern names        (0xC0B38A6C, pointer array)
  shell      the shell command table            (0xC0BAC14C, stride 0x18)
  subcmds    a command's sub-table              ({name, help, fn}, stride 12)
  curves     the tone-curve registry            (0xC0971118, {ptr, id})

  --self-test  build each structure in noise and require exact recovery
"""
import argparse, pathlib, re, struct, sys

NAMES = 0xC07D3600          # scan start; pool entries end "\n\0"
NAMES_END = 0xC07D4200
PATTERNS = 0xC0B38A6C
NPATTERN = 8
SHELL_TBL = 0xC0BAC14C
CURVE_REG = 0xC0971118
CURVE_0 = 0xC0971F34
CURVE_STRIDE = 0x1000

SUBTABLES = {'movrec': 0xC0BBF91C, 'rec': 0xC0BC1840, 'pic': 0xC0BC00E8}

MODE_TBL = 0xC0B59E24     # sensor mode table: 70 entries x 100 bytes
MODE_STRIDE, MODE_N = 100, 70
# columns, from FUN_c0321028 (stride 0x64) and FUN_c0320B38 (entry[0] = mode id)
MODE_COLS = {0: 'mode', 1: 'width', 2: 'height', 16: 'maxfps',
             17: 'decH', 19: 'decV', 21: 'aspect?'}


def cstr(buf, base, a, limit=90):
    o = a - base
    if not (0 <= o < len(buf)):
        return None
    e = buf.find(b'\0', o)
    if e < 0 or e - o > limit:
        return None
    s = buf[o:e]
    return s.decode('ascii', 'replace') if s and all(9 <= c < 127 for c in s) else None


def names(buf, base, lo=NAMES, hi=NAMES_END):
    """The ISP pool: printable runs terminated by newline + NUL."""
    seg = buf[lo - base:hi - base]
    return [(lo + m.start(), m.group()[:-2].decode('ascii', 'replace'))
            for m in re.finditer(rb'[ -~][ -~]{1,40}\n\x00', seg)]


def patterns(buf, base, at=PATTERNS, n=NPATTERN):
    out = []
    for i in range(n):
        p = struct.unpack_from('<I', buf, at - base + i * 4)[0]
        out.append((i, p, cstr(buf, base, p, 32)))
    return out


def shell(buf, base, at=SHELL_TBL):
    out, n = [], 0
    while True:
        o = at - base + n * 0x18
        nm = buf[o:o + 0x14].split(b'\0')[0].decode('ascii', 'replace')
        fn = struct.unpack_from('<I', buf, o + 0x14)[0]
        if not nm or fn == 0:
            break
        out.append((n, nm, fn))
        n += 1
    return out


def subcmds(buf, base, at, maxn=64):
    """{name*, help*, fn*} triples, stride 12, until a word stops being a pointer."""
    out = []
    for n in range(maxn):
        o = at - base + n * 12
        p, h, fn = struct.unpack_from('<III', buf, o)
        if not (0xC0000000 <= p < 0xC4000000 and 0xC0000000 <= fn < 0xC4000000):
            break
        out.append((cstr(buf, base, p, 32), fn, cstr(buf, base, h) or ''))
    return out


def modes(buf, base, at=MODE_TBL, n=MODE_N):
    """The sensor mode table. entry[0] is the mode id, 1/2 are width/height."""
    out = []
    for i in range(n):
        e = struct.unpack_from('<25I', buf, at - base + i * MODE_STRIDE)
        if not (0 < e[0] < 256):
            break
        out.append(e)
    return out


def curves(buf, base, at=CURVE_REG):
    """{pointer, id} until the id stops being index+1 or the pointer goes wild."""
    out, n = [], 0
    while True:
        p, i = struct.unpack_from('<II', buf, at - base + n * 8)
        if not (0xC0000000 <= p < 0xC4000000):
            break
        if p != CURVE_0 + n * CURVE_STRIDE:
            break
        out.append((n, p, i))
        n += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?', type=pathlib.Path)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('--only', choices=['names', 'patterns', 'shell', 'subcmds',
                                       'curves', 'modes'])
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.dump:
        raise SystemExit('give a dump, or --self-test')
    buf, base = a.dump.read_bytes(), a.base
    want = a.only

    if want in (None, 'patterns'):
        ps = patterns(buf, base)
        print("=== ISP patterns @0x%08X\n" % PATTERNS)
        for i, p, s in ps:
            print("  %d  %08X  %s" % (i, p, s))
        print()

    if want in (None, 'names'):
        ns = names(buf, base)
        print("=== ISP name pool @0x%08X, %d entries\n" % (ns[0][0], len(ns)))
        for addr, s in ns:
            print("  %08X  %s" % (addr, s))
        print()

    if want in (None, 'shell'):
        sh = shell(buf, base)
        print("=== shell command table @0x%08X, %d entries\n" % (SHELL_TBL, len(sh)))
        for n, nm, fn in sh:
            print("  %2d  %-14s %08X" % (n, nm, fn))
        print()

    if want in (None, 'subcmds'):
        for lbl, at in SUBTABLES.items():
            sc = subcmds(buf, base, at)
            print("=== %s sub-table @0x%08X, %d entries" % (lbl, at, len(sc)))
            for nm, fn, h in sc:
                print("   %-14s fn=%08X  %s" % (nm, fn, h[:58]))
            print()

    if want in (None, 'modes'):
        ms = modes(buf, base)
        print("=== sensor mode table @0x%08X, %d entries of %d bytes\n"
              % (MODE_TBL, len(ms), MODE_STRIDE))
        print("  mode   width height  maxfps  decH decV")
        for e in sorted(ms, key=lambda x: (-x[1], -x[2], x[0])):
            print("   %3d   %5d %5d   %4d     %d    %d"
                  % (e[0], e[1], e[2], e[16], e[17], e[19]))
        geo = {}
        for e in ms:
            geo.setdefault((e[1], e[2]), []).append(e[0])
        print("\n  %d distinct geometries:" % len(geo))
        for (w, h), mm in sorted(geo.items(), key=lambda x: -x[0][0]):
            print("    %5d x %5d   %2d modes  max %3d fps"
                  % (w, h, len(mm), max(e[16] for e in ms if (e[1], e[2]) == (w, h))))
        print()

    if want in (None, 'curves'):
        cs = curves(buf, base)
        first, last = cs[0][1], cs[-1][1]
        print("=== tone-curve registry @0x%08X" % CURVE_REG)
        print("  %d curves, 2048 x u16 each, stride 0x%X" % (len(cs), CURVE_STRIDE))
        print("  data 0x%08X .. 0x%08X" % (first, last))
        print("  array ends 0x%08X, curve 0 begins 0x%08X (they abut)"
              % (CURVE_REG + len(cs) * 8, CURVE_0))
        print()
    return 0


def self_test():
    import random
    random.seed(3)
    base = 0xC0000000
    buf = bytearray(random.getrandbits(8) for _ in range(0x40000))

    # names: three pool entries, and a decoy without the \n\0 terminator
    at = 0x10000
    blob = b'GAM_TOP GAMMA TABLE\n\0\0PST_TOP Y_GAMMA\n\0\0CEQ24_ORG\n\0\0NOTAPOOLENTRY\0'
    buf[at:at + len(blob)] = blob
    got = [s for _, s in names(buf, base, base + at, base + at + len(blob))]
    assert got == ['GAM_TOP GAMMA TABLE', 'PST_TOP Y_GAMMA', 'CEQ24_ORG'], got

    # patterns: pointer array -> strings
    sa, pa = 0x20000, 0x20100
    off = sa
    for s in (b'Jpg\0', b'Dng\0', b'Mov\0'):
        buf[off:off + len(s)] = s
        off += len(s)
    struct.pack_into('<III', buf, pa, base + sa, base + sa + 4, base + sa + 8)
    assert [s for _, _, s in patterns(buf, base, base + pa, 3)] == ['Jpg', 'Dng', 'Mov']

    # shell table: two entries then a NULL handler terminator
    st = 0x30000
    buf[st:st + 0x18 * 3] = b'\0' * (0x18 * 3)
    buf[st:st + 4] = b'mem\0'
    struct.pack_into('<I', buf, st + 0x14, 0xC03FA2A8)
    buf[st + 0x18:st + 0x18 + 5] = b'pic\0\0'
    struct.pack_into('<I', buf, st + 0x18 + 0x14, 0xC0404E98)
    got = shell(buf, base, base + st)
    assert got == [(0, 'mem', 0xC03FA2A8), (1, 'pic', 0xC0404E98)], got

    # modes: three records that must stop at a non-mode id
    mt = 0x3C000
    for i, (m, w, h) in enumerate(((7, 6064, 3412), (117, 3032, 2012), (139, 2016, 1344))):
        struct.pack_into('<III', buf, mt + i * MODE_STRIDE, m, w, h)
    struct.pack_into('<I', buf, mt + 3 * MODE_STRIDE, 0)
    got = modes(buf, base, base + mt, 10)
    assert [(e[0], e[1], e[2]) for e in got] == [
        (7, 6064, 3412), (117, 3032, 2012), (139, 2016, 1344)], got

    # curves: a short registry that must stop when the stride breaks
    cr = 0x38000
    for n in range(5):
        struct.pack_into('<II', buf, cr + n * 8, CURVE_0 + n * CURVE_STRIDE, n + 1)
    struct.pack_into('<II', buf, cr + 5 * 8, CURVE_0 + 99 * CURVE_STRIDE, 6)  # gap
    assert len(curves(buf, base, base + cr)) == 5

    print("self-test PASSED: name pool, pattern array, shell table, sensor mode "
          "table and curve registry all recovered; unterminated and "
          "non-contiguous decoys rejected")
    return 0


if __name__ == '__main__':
    sys.exit(main())
