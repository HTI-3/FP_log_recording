#!/usr/bin/env python3
"""Label the ISP shadow bank: shadow word -> register -> ISP stage name.

    python3 tools/shadow_map.py results/dram_rec_23_09_2026/dram_C0000000.bin
    python3 tools/shadow_map.py --self-test

Two pieces of Thumb-2 code in the firmware image are read, not guessed:

  BUILDER  0xC019C810  the sequencer command list.  Each entry is a call to
           0xC019DF90 with r1 = the register, r2 = the word count and
           r3 = bank offset + the shadow address (movw/movt of 0x3021xxxx).
  DUMPER   0xC01597B8  the firmware's own ISP register dump.  Each block is a
           call to 0xC01F57F4 with r1 = its label (e.g. "YUV_PACK\\n"), then
           calls to 0xC015C1D8(start, end) for each register window, where
           r1 = end (movw/movt) and r0 = r1 - imm.

Joined on the register address, that names the stage behind every shadow word
the sequencer uploads.  results/code_10bit/FINDINGS.md has how both were found.
"""
import argparse, bisect, pathlib, struct, sys

BASE = 0xC0000000
BUILDER, BUILDER_ENTRY = 0xC019C810, 0xC019DF90
DUMPER, DUMP_LABEL, DUMP_RANGE = 0xC01597B8, 0xC01F57F4, 0xC015C1D8
SPAN = 0x3000           # bytes of each function to walk; both end well inside


def _disasm(buf, at, n):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    return md.disasm(buf[at - BASE:at - BASE + n], at)


def _imm(op):
    return int(op.split('#')[1], 0)


def _target(ins):
    return int(ins.op_str.lstrip('#'), 0) if ins.mnemonic in ('bl', 'blx') else None


def _cstr(buf, a):
    o = a - BASE
    if not 0 <= o < len(buf):
        return None
    e = buf.find(b'\0', o)
    s = buf[o:e]
    return s.decode('ascii').strip() if 0 < len(s) < 64 and all(9 <= c < 127 for c in s) else None


def _walk(buf, at, span, calls, zero=()):
    """Yield (call target, {reg: value}, address) for each bl/blx in `calls`.

    Tracks movw/movt, mov #imm, mov rd, rn, and add/sub with an immediate or a
    register.  Registers named in `zero` read as 0 -- the builder's bank offset
    r4, which is 0 for every movie pattern (0xC07D4360).  Any other instruction
    that writes a register drops it, so a value is never carried stale.
    """
    regs, lo = {}, {}

    def val(r):
        return 0 if r in zero else regs.get(r)

    for ins in _disasm(buf, at, span):
        m, ops = ins.mnemonic, [o.strip() for o in ins.op_str.split(',')]
        base = m.split('.')[0].rstrip('s') if m not in ('movs',) else 'mov'
        if m.startswith('movw'):
            lo[ops[0]] = _imm(ins.op_str)
            regs[ops[0]] = lo[ops[0]]
        elif m.startswith('movt'):
            regs[ops[0]] = (_imm(ins.op_str) << 16) | lo.get(ops[0], 0)
        elif base == 'mov' and len(ops) == 2:
            v = _imm(ins.op_str) if ops[1].startswith('#') else val(ops[1])
            if v is None:
                regs.pop(ops[0], None)
            else:
                regs[ops[0]] = v
        elif base in ('add', 'sub') and len(ops) in (2, 3) and not ops[-1].startswith('['):
            a, b = (ops[0], ops[1]) if len(ops) == 2 else (ops[1], ops[2])
            x = val(a)
            y = int(b[1:], 0) if b.startswith('#') else val(b)
            if x is None or y is None or 'sp' in (a, b) or 'pc' in (a, b):
                regs.pop(ops[0], None)
            else:
                regs[ops[0]] = (x + y if base == 'add' else x - y) & 0xFFFFFFFF
        elif ops and ops[0].startswith('r') and not m.startswith(('str', 'cmp', 'cmn', 'tst', 'b', 'push', 'pop', 'it', 'cb')):
            regs.pop(ops[0], None)
        t = _target(ins)
        if t in calls:
            yield t, dict(regs), ins.address
            for r in ('r0', 'r1', 'r2', 'r3', 'r12', 'ip'):
                regs.pop(r, None)       # caller-saved: gone after the call
        if m.startswith('pop') and 'pc' in ins.op_str:
            return


def builder_entries(buf):
    """[(shadow, register, words)] from the command-list builder."""
    out = []
    for _, r, _ in _walk(buf, BUILDER, SPAN, {BUILDER_ENTRY}, zero={'r4'}):
        # 0xC019DF90(slot, register, words, shadow): the shadow is r3 = r4 + imm
        sh, reg, n = r.get('r3'), r.get('r1'), r.get('r2')
        # a register lies below the shadow banks; anything else is a value the
        # walker could not follow, and is dropped rather than mislabelled
        if sh is not None and 0x30200000 <= sh < 0x30300000 and n \
                and reg is not None and 0x30000000 <= reg < 0x30200000:
            out.append((sh, reg, n))
    return out


def dumper_blocks(buf):
    """[(label, start, end)] register windows, end inclusive, from the dumper."""
    out, label = [], None
    for t, r, _ in _walk(buf, DUMPER, SPAN * 4, {DUMP_LABEL, DUMP_RANGE}):
        if t == DUMP_LABEL:
            label = _cstr(buf, r.get('r1', 0)) or label
        elif label and 'r0' in r and 'r1' in r:
            out.append((label, r['r0'], r['r1']))
    return out


def shadow_map(buf):
    """{shadow word address: (register, stage label or None)}."""
    blocks = sorted((s, e, lab) for lab, s, e in dumper_blocks(buf))
    starts = [b[0] for b in blocks]

    def stage(reg):
        i = bisect.bisect_right(starts, reg) - 1
        if i >= 0 and blocks[i][0] <= reg <= blocks[i][1]:
            return blocks[i][2]
        return None

    out = {}
    for sh, reg, n in builder_entries(buf):
        for k in range(n):
            out[sh + 4 * k] = (reg + 4 * k, stage(reg + 4 * k))
    return out


def load_image(path):
    buf = pathlib.Path(path).read_bytes()
    if len(buf) < 0x2F0D000:
        raise SystemExit(f'{path}: not a full DRAM dump from 0xC0000000')
    return buf


def self_test():
    """Assemble a builder and a dumper in Thumb-2, as the firmware writes them,
    into a zero image, and require the join to come out exactly."""
    def movw(rd, v):
        i, imm4, imm3, imm8 = (v >> 11) & 1, (v >> 12) & 0xF, (v >> 8) & 7, v & 0xFF
        return struct.pack('<HH', 0xF240 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)

    def movt(rd, v):
        i, imm4, imm3, imm8 = (v >> 11) & 1, (v >> 12) & 0xF, (v >> 8) & 7, v & 0xFF
        return struct.pack('<HH', 0xF2C0 | (i << 10) | imm4, (imm3 << 12) | (rd << 8) | imm8)

    def mov32(rd, v):
        return movw(rd, v & 0xFFFF) + movt(rd, v >> 16)

    def bl(frm, to):
        off = to - (frm + 4)
        s = (off >> 24) & 1
        i1, i2 = (off >> 23) & 1, (off >> 22) & 1
        j1, j2 = (~i1 ^ s) & 1, (~i2 ^ s) & 1
        return struct.pack('<HH', 0xF000 | (s << 10) | ((off >> 12) & 0x3FF),
                           0xD000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF))

    def movs(rd, v):
        return struct.pack('<H', 0x2000 | (rd << 8) | v)

    def subw(rd, rn, v):            # sub.w rd, rn, #v (v < 256)
        return struct.pack('<HH', 0xF1A0 | rn, (rd << 8) | v)

    push = struct.pack('<HH', 0xE92D, 0x44F0)
    pop = struct.pack('<HH', 0xE8BD, 0x84F0)
    img = bytearray(0x2F0D000 + 0x100)

    def emit(at, parts):
        code = bytearray()
        for p in parts:
            code += p(at + len(code)) if callable(p) else p
        img[at - BASE:at - BASE + len(code)] = code

    # builder: two entries, the second of 3 words
    adds_r3_r4_r0 = struct.pack('<H', 0x1823)          # adds r3, r4, r0
    addw_r1_r6 = lambda v: struct.pack('<HH', 0xF106, (1 << 8) | v)   # add.w r1, r6, #v
    emit(BUILDER, [push,
                   mov32(6, 0x3011E000),
                   mov32(0, 0x3021236C), adds_r3_r4_r0, addw_r1_r6(0x04), movs(2, 7),
                   lambda a: bl(a, BUILDER_ENTRY),
                   mov32(0, 0x30212388), adds_r3_r4_r0, mov32(1, 0x3011E130), movs(2, 3),
                   lambda a: bl(a, BUILDER_ENTRY),
                   # a stale-register trap: r1 recomputed from an unknown register
                   mov32(0, 0x302123A0), adds_r3_r4_r0,
                   struct.pack('<HH', 0xF8D5, 0x1000),      # ldr.w r1, [r5]
                   movs(2, 2), lambda a: bl(a, BUILDER_ENTRY), pop])
    lab = 0xC07D39B4
    img[lab - BASE:lab - BASE + 10] = b'YUV_PACK\n\0'
    emit(DUMPER, [push,
                  mov32(1, lab), lambda a: bl(a, DUMP_LABEL),
                  mov32(1, 0x3011E024), subw(0, 1, 0x20), lambda a: bl(a, DUMP_RANGE),
                  mov32(1, 0x3011E158), subw(0, 1, 0x58), lambda a: bl(a, DUMP_RANGE), pop])
    m = shadow_map(bytes(img))
    assert m[0x3021236C] == (0x3011E004, 'YUV_PACK'), m.get(0x3021236C)
    assert m[0x30212384] == (0x3011E01C, 'YUV_PACK')
    assert m[0x30212390] == (0x3011E138, 'YUV_PACK')
    assert 0x30212394 not in m and len(m) == 10, len(m)
    print('self-test passed: builder entries, dumper windows, join')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.dump:
        ap.error('dump required')
    buf = load_image(args.dump)
    ents, blocks = builder_entries(buf), dumper_blocks(buf)
    m = shadow_map(buf)
    named = sum(1 for _, (_, s) in m.items() if s)
    print(f'builder: {len(ents)} entries, {len(m)} shadow words; dumper: {len(blocks)} windows; '
          f'{named} words named')
    for sh, reg, n in sorted(ents):
        print(f'  0x{sh:08X}..0x{sh + 4 * n - 1:08X}  -> 0x{reg:08X} x{n:<3}  {m[sh][1] or "?"}')


if __name__ == '__main__':
    main()
