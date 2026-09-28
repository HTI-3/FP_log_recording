#!/usr/bin/env python3
"""Annotated ARM disassembly of a DRAM dump.

    python3 tools/disasm.py <dump> 0xC02B8E38 -n 40
    python3 tools/disasm.py <dump> 0xC0404590 --func      # to the end of the function
    python3 tools/disasm.py <dump> 0xC02B8E38 --back      # find the function start first

Capstone alone is not enough to read this firmware: every interesting constant
is built by a movw/movt pair, a literal pool load, or a pc-relative add, and
what matters is the value, not the encoding. This resolves all three and looks
up whatever the value points at.

Annotations:
    ; =0xADDR "string"      a resolved constant that points at text
    ; =0xADDR               a resolved constant
    ; -> 0xADDR             a branch target
    ; [0xADDR] = 0xVALUE    a literal-pool load, with what is there

`tools/re/dis.py` is a different thing: a one-off for the OpenGate VBIN
payloads. This one works on the dump.

  --self-test   assemble the three constant forms and require exact recovery
"""
import argparse, pathlib, re, struct, sys

try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
except ImportError:
    Cs = None

LO, HI = 0xC0000000, 0xC4000000


def cstr(buf, base, a, limit=80):
    o = a - base
    if not (0 <= o < len(buf)):
        return None
    e = buf.find(b'\0', o)
    if e < 0 or e - o > limit or e == o:
        return None
    s = buf[o:e]
    return s.decode('ascii', 'replace') if all(9 <= c < 127 for c in s) else None


def word(buf, base, a):
    o = a - base
    return struct.unpack_from('<I', buf, o)[0] if 0 <= o < len(buf) - 3 else None


def _rot(imm, rot):
    rot &= 31
    return ((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF


def annotate(buf, base, ins, regs):
    """Return an annotation string, updating `regs` with movw/movt state."""
    m = ins.mnemonic
    ops = ins.op_str

    if m == 'movw':
        r, v = ops.split(',', 1)
        try:
            regs[r.strip()] = int(v.split('#')[1], 0)
        except (IndexError, ValueError):
            pass
        return ''

    if m == 'movt':
        r, v = ops.split(',', 1)
        r = r.strip()
        try:
            hi = int(v.split('#')[1], 0)
        except (IndexError, ValueError):
            return ''
        if r in regs:
            full = (hi << 16) | regs[r]
            regs.pop(r, None)
            s = cstr(buf, base, full)
            return '  ; =0x%08X%s' % (full, ' "%s"' % s.replace('\n', '\\n') if s else '')
        return ''

    # add rX, pc, #imm  (optionally with a rotate: "#96, #30")
    mm = re.match(r'(\w+), pc, #(\d+)(?:, #(\d+))?$', ops)
    if m == 'add' and mm:
        imm = int(mm.group(2))
        if mm.group(3):
            imm = _rot(imm, int(mm.group(3)))
        t = ins.address + 8 + imm
        s = cstr(buf, base, t)
        return '  ; =0x%08X%s' % (t, ' "%s"' % s.replace('\n', '\\n') if s else '')

    # ldr rX, [pc, #imm]  -- capstone renders the target for us sometimes
    mm = re.match(r'(\w+), \[pc, #(-?)(0x[0-9a-f]+|\d+)\]$', ops)
    if m == 'ldr' and mm:
        off = int(mm.group(3), 0) * (-1 if mm.group(2) else 1)
        at = ins.address + 8 + off
        v = word(buf, base, at)
        if v is None:
            return ''
        s = cstr(buf, base, v) if LO <= v < HI else None
        return '  ; [0x%08X] = 0x%08X%s' % (at, v, ' "%s"' % s.replace('\n', '\\n') if s else '')

    if m in ('bl', 'b', 'blx', 'bx') and ops.startswith('#'):
        return '  ; -> %s' % ops[1:]

    return ''


def func_start(buf, base, addr, limit=0x600):
    """Scan back for a `push {..., lr}` -- encoding 0xE92D4xxx / 0xE52DE004."""
    for a in range(addr & ~3, max(base, addr - limit), -4):
        w = word(buf, base, a)
        if w is None:
            continue
        if (w & 0xFFFF0000) == 0xE92D0000 and (w & 0x4000):
            return a
        if w == 0xE52DE004:
            return a
    return None


def disasm(buf, base, at, n=40, stop_at_return=False):
    if Cs is None:
        raise SystemExit('capstone not installed: pip3 install capstone')
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    o = at - base
    out, regs = [], {}
    for ins in md.disasm(buf[o:o + n * 4 * 4], at):
        out.append("  %08X  %-8s %-30s%s"
                   % (ins.address, ins.mnemonic, ins.op_str,
                      annotate(buf, base, ins, regs)))
        if stop_at_return and (
                (ins.mnemonic.startswith('pop') and 'pc' in ins.op_str)
                or ins.mnemonic == 'bx' and ins.op_str.strip() == 'lr'):
            break
        if len(out) >= n:
            break
    return out


def self_test():
    import random
    random.seed(5)
    base = 0xC0000000
    buf = bytearray(random.getrandbits(8) for _ in range(0x4000))
    s_at = 0x800
    buf[s_at:s_at + 12] = b'GAM_TOP\0\0\0\0\0'
    target = base + s_at
    # movw r0,#lo ; movt r0,#hi
    struct.pack_into('<I', buf, 0, 0xE3000000 | ((target & 0xF000) << 4) | (target & 0xFFF))
    struct.pack_into('<I', buf, 4, 0xE3400000 | (((target >> 28) & 0xF) << 16) | ((target >> 16) & 0xFFF))
    # ldr r1,[pc,#4] with the word 8 bytes on
    struct.pack_into('<I', buf, 8, 0xE59F1004)
    struct.pack_into('<I', buf, 0x14, target)
    # add r2, pc, #4  -> 0x10 + 8 + 4 = 0x1C
    struct.pack_into('<I', buf, 0x10, 0xE28F2004)
    buf[0x1C:0x1C + 6] = b'YCMAT\0'
    # a push {r4,lr} at 0x100, so func_start from 0x110 finds it
    struct.pack_into('<I', buf, 0x100, 0xE92D4010)

    lines = disasm(buf, base, base, n=6)
    body = '\n'.join(lines)
    assert '=0x%08X "GAM_TOP"' % target in body, body
    assert '[0x%08X] = 0x%08X "GAM_TOP"' % (base + 0x14, target) in body, body
    assert '=0x%08X "YCMAT"' % (base + 0x1C) in body, body
    assert func_start(buf, base, base + 0x110) == base + 0x100
    assert func_start(buf, base, base + 0x08, limit=4) is None
    print('self-test PASSED: movw/movt, literal pool, pc-relative add and '
          'function-start scan all recovered')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?', type=pathlib.Path)
    ap.add_argument('addr', nargs='?')
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('-n', type=int, default=40)
    ap.add_argument('--func', action='store_true', help='stop at the return')
    ap.add_argument('--back', action='store_true', help='scan back to the function start')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not (a.dump and a.addr):
        raise SystemExit('give a dump and an address, or --self-test')
    buf, at = a.dump.read_bytes(), int(a.addr, 0)
    if a.back:
        s = func_start(buf, a.base, at)
        if s:
            print('function starts 0x%08X (%d bytes back)\n' % (s, at - s))
            at = s
        else:
            print('no push{...,lr} found within range; starting at 0x%08X\n' % at)
    for l in disasm(buf, a.base, at, a.n, a.func):
        print(l)
    return 0


if __name__ == '__main__':
    sys.exit(main())
