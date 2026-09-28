#!/usr/bin/env python3
"""Find the code that builds a given address, in an ARM image.

    python3 tools/xref.py <dump> 0xC0971118
    python3 tools/xref.py <dump> 0xC0971118 --disasm 24
    python3 tools/xref.py <dump> --string "CinemaDngFile.c"

Why this exists: `results/isprobe2/FINDINGS.md` recorded that "no movt in the
image builds a 0x3021xxxx address, so grep will not find the driver". That was
true and it is only half the problem -- nothing in this repository could find
the code behind ANY address, so every data structure found in the dump stayed
disconnected from the code that uses it.

Three ways an ARM image names an address, all covered here:

  1. movw/movt pair      mov Rd,#lo ; movt Rd,#hi        -- the common case
  2. literal pool        ldr Rd,[pc,#n] with .word ADDR  -- also very common
  3. a plain .word       a pointer in a table            -- what grep finds

A movw and its movt need not be adjacent, so the pair is matched by register
within a window rather than by position.

  --self-test   assemble all three forms into noise and require exact recovery
"""
import argparse, pathlib, re, struct, sys

WINDOW = 64          # bytes a movt may trail its movw by


def _movw_enc(rd, imm16):
    return 0xE3000000 | ((imm16 >> 12) << 16) | (rd << 12) | (imm16 & 0xFFF)


def _movt_enc(rd, imm16):
    return 0xE3400000 | ((imm16 >> 12) << 16) | (rd << 12) | (imm16 & 0xFFF)


def find_movw_movt(buf, base, addr):
    """Every movw/movt pair, same register, within WINDOW, that builds addr."""
    lo, hi = addr & 0xFFFF, (addr >> 16) & 0xFFFF
    out = []
    for rd in range(13):
        w = struct.pack('<I', _movw_enc(rd, lo))
        t = struct.pack('<I', _movt_enc(rd, hi))
        tpos = {m.start() for m in re.finditer(re.escape(t), buf)}
        if not tpos:
            continue
        for m in re.finditer(re.escape(w), buf):
            p = m.start()
            near = [q for q in tpos if 0 < q - p <= WINDOW or 0 < p - q <= WINDOW]
            if near:
                out.append((base + p, rd, base + min(near, key=lambda q: abs(q - p))))
    return out


def find_literal_pool(buf, base, addr):
    """`.word addr` that some ldr rd,[pc,#imm] within 4 KiB points at."""
    out = []
    for m in re.finditer(re.escape(struct.pack('<I', addr)), buf):
        w = m.start()
        if w % 4:
            continue
        for p in range(max(0, w - 4096), w, 4):
            ins = struct.unpack_from('<I', buf, p)[0]
            # ldr Rd,[pc,#imm12]  cond 010 (P=1,U=1,B=0,W=0,L=1) 1111 Rd imm12
            if (ins & 0x0F7F0000) == 0x051F0000:
                if p + 8 + (ins & 0xFFF) == w:
                    out.append((base + p, (ins >> 12) & 0xF, base + w))
    return out


def find_word(buf, base, addr):
    return [base + m.start() for m in re.finditer(re.escape(struct.pack('<I', addr)), buf)
            if m.start() % 4 == 0]


def disasm(buf, base, at, count):
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    except ImportError:
        return ["  (capstone not installed)"]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    off = at - base
    return ["    %08X  %-8s %s" % (i.address, i.mnemonic, i.op_str)
            for i in md.disasm(buf[off:off + count * 4], at)]


def report(buf, base, addr, ndis=0):
    mm = find_movw_movt(buf, base, addr)
    lp = find_literal_pool(buf, base, addr)
    wd = find_word(buf, base, addr)
    print("0x%08X" % addr)
    print("  movw/movt pairs : %d" % len(mm))
    for a, rd, t in mm[:20]:
        print("    code @%08X   r%-2d (movt @%08X)" % (a, rd, t))
        if ndis:
            for l in disasm(buf, base, a, ndis):
                print(l)
    print("  literal-pool ldr: %d" % len(lp))
    for a, rd, w in lp[:20]:
        print("    code @%08X   r%-2d (.word @%08X)" % (a, rd, w))
        if ndis:
            for l in disasm(buf, base, a, ndis):
                print(l)
    print("  plain .word     : %d %s" % (len(wd), [hex(x) for x in wd[:8]]))
    return mm, lp, wd


def string_start(buf, pos):
    """Where the string containing buf[pos] begins.

    Walks back over printable ASCII only. Walking back to the previous NUL, as
    this used to, runs into whatever binary precedes a string that is not
    NUL-preceded -- a pointer, an instruction -- and returns a start address
    that is neither the string's nor anything the code references, then crashes
    decoding it (`MovSigProcess.cpp` is preceded by 0xE4).
    """
    while pos > 0 and 0x20 <= buf[pos - 1] < 0x7F:
        pos -= 1
    return pos


def string_end(buf, pos):
    while pos < len(buf) and 0x20 <= buf[pos] < 0x7F:
        pos += 1
    return pos


def self_test():
    import random
    random.seed(11)
    buf = bytearray(random.getrandbits(8) for _ in range(0x8000))
    base, target = 0xC0000000, 0xC0B3B2E8
    # 1. movw/movt, r4, 8 bytes apart, with a filler instruction between
    struct.pack_into('<I', buf, 0x100, _movw_enc(4, target & 0xFFFF))
    struct.pack_into('<I', buf, 0x104, 0xE1A00000)               # nop (mov r0,r0)
    struct.pack_into('<I', buf, 0x108, _movt_enc(4, target >> 16))
    # 2. literal pool: ldr r5,[pc,#4] at 0x200 -> .word at 0x20C
    struct.pack_into('<I', buf, 0x200, 0x051F0000 | 0xE0000000 | (5 << 12) | 4)
    struct.pack_into('<I', buf, 0x20C, target)
    # 3. a plain pointer in a table
    struct.pack_into('<I', buf, 0x400, target)
    mm = find_movw_movt(buf, base, target)
    lp = find_literal_pool(buf, base, target)
    wd = find_word(buf, base, target)
    assert [a for a, _, _ in mm] == [base + 0x100], mm
    assert [a for a, _, _ in lp] == [base + 0x200], lp
    assert set(wd) >= {base + 0x20C, base + 0x400}, wd
    # a decoy: right halves, wrong register -- must NOT match
    buf2 = bytearray(buf)
    struct.pack_into('<I', buf2, 0x108, _movt_enc(7, target >> 16))
    assert not find_movw_movt(buf2, base, target), 'register mismatch accepted'
    # a decoy: right register, too far apart -- must NOT match
    buf3 = bytearray(buf)
    struct.pack_into('<I', buf3, 0x108, 0xE1A00000)
    struct.pack_into('<I', buf3, 0x100 + WINDOW + 8, _movt_enc(4, target >> 16))
    assert not find_movw_movt(buf3, base, target), 'out-of-window pair accepted'
    # --string: the start of a string, whatever precedes it
    sbuf = bytearray(b'\xff' * 64)
    one, two = b'\x00src/a/one.c', b'\xe4src/b/two.c'  # NUL- / binary-preceded
    sbuf[8:8 + len(one)] = one
    sbuf[30:30 + len(two)] = two
    assert len(sbuf) == 64
    assert string_start(sbuf, sbuf.index(b'one.c')) == 9, 'NUL-preceded start'
    assert string_start(sbuf, sbuf.index(b'two.c')) == 31, 'binary-preceded start'
    assert string_end(sbuf, 31) == 30 + len(two)
    print("self-test PASSED: movw/movt, literal pool and .word all recovered; "
          "wrong-register and out-of-window decoys rejected; string starts found "
          "after a NUL and after binary")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?', type=pathlib.Path)
    ap.add_argument('addr', nargs='*')
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('--string', help='find the address of this string, then xref it')
    ap.add_argument('--disasm', type=int, default=0, metavar='N',
                    help='disassemble N instructions at each hit')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.dump:
        raise SystemExit('give a dump, or --self-test')
    buf = a.dump.read_bytes()
    targets = [int(x, 0) for x in a.addr]
    if a.string:
        hits = [m.start() for m in re.finditer(re.escape(a.string.encode()), buf)]
        if not hits:
            raise SystemExit('string not found')
        starts = sorted({string_start(buf, h) for h in hits})
        for s in starts:
            text = buf[s:string_end(buf, s)].decode('ascii')
            print('string "%s" at 0x%08X' % (text, a.base + s))
            targets.append(a.base + s)
        print()
    for t in targets:
        report(buf, a.base, t, a.disasm)
        print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
