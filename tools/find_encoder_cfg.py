#!/usr/bin/env python3
"""Find where the firmware sets the H.264 profile, in a DRAM dump.

    tools/find_encoder_cfg.py firmware_C0000000.bin
    tools/find_encoder_cfg.py --self-test

The measured stock stream is profile_idc 100 (High), level_idc 51, 8-bit 4:2:0
(results/mov_recording/FINDINGS.md). So the firmware writes 100 and 51
somewhere. This looks for that, and for any sign that 110 (High 10) or 122
(High 4:2:2) is known to the code.

It does NOT search for raw bytes. In ARM code an immediate is part of an
instruction word, so the tool decodes candidate words and keeps only real
`mov`/`movw`/`cmp` immediate loads. Raw-byte searching is what does not work:
on the packed update file, `6e 00 33` (High 10) occurs exactly as often as
`64 00 33` (the profile actually in use) -- nine times each, both noise.

A cluster of 100 and 51 close together is the signal. Encoder init parameters
travel as a group: {profile, level, width, height, bitrate, gop}.
"""
import argparse, pathlib, struct, sys

PROFILES = {66: 'Baseline', 77: 'Main', 88: 'Extended', 100: 'High (STOCK)',
            110: 'High 10  <-- 10-bit', 122: 'High 4:2:2  <-- 10-bit 422',
            244: 'High 4:4:4 Predictive'}
LEVEL_51 = 51

# ARM data-processing immediate, cond = AL (0xE). bits[27:20] -> mnemonic.
OPS = {0x3A: 'mov', 0x3B: 'movs', 0x30: 'movw', 0x35: 'cmp',
       0x28: 'add', 0x29: 'adds', 0x24: 'sub', 0x25: 'subs'}


def imm_sites(words, base, value):
    """Every ARM instruction word that loads `value` as a rotate-0 immediate."""
    out = []
    for i, w in enumerate(words):
        if (w >> 28) != 0xE or (w & 0xFFF) != value:
            continue
        op = OPS.get((w >> 20) & 0xFF)
        if op is None:
            continue
        if op == 'movw' and ((w >> 16) & 0xF):   # imm4 != 0 -> not this value
            continue
        out.append((base + i * 4, op, (w >> 12) & 0xF, w))
    return out


def scan(data, base):
    words = struct.unpack(f'<{len(data) // 4}I', data[:len(data) // 4 * 4])
    found = {v: imm_sites(words, base, v) for v in list(PROFILES) + [LEVEL_51]}
    return found


def report(found, window=0x40):
    for v, name in PROFILES.items():
        n = len(found.get(v, []))
        flag = ''
        if v in (110, 122) and n:
            flag = '   <<< CHECK THESE'
        print(f'  profile {v:3d} {name:26s} {n:5d} immediate loads{flag}')
    print(f'  level   {LEVEL_51:3d} {"(stock level 5.1)":26s} {len(found.get(LEVEL_51, [])):5d} immediate loads')

    lv = {a for a, *_ in found.get(LEVEL_51, [])}
    print(f'\n  CLUSTERS -- a profile immediate within 0x{window:X} bytes of a level-51 immediate:')
    hit = False
    for v in PROFILES:
        for addr, op, rd, w in found.get(v, []):
            near = [x for x in lv if abs(x - addr) <= window]
            if near:
                hit = True
                tag = '  <<< NOT THE STOCK PROFILE' if v != 100 else ''
                print(f'    0x{addr:08X}  {op} r{rd}, #{v}  ({PROFILES[v]})'
                      f'  level-51 at 0x{min(near, key=lambda x: abs(x - addr)):08X}{tag}')
    if not hit:
        print('    none. Either the profile is not an inline immediate (a table in '
              'ROM, or built by the bitstream writer), or the window is too tight.')
    return hit


def self_test():
    """Validate on a synthetic positive and a real negative, before trusting it."""
    print('SELF-TEST\n')
    # positive control: plausible encoder init, plus decoys that must NOT match
    import struct as st
    code = [
        0xE3A00064,  # mov  r0, #100      <- profile
        0xE3A01033,  # mov  r1, #51       <- level        (cluster)
        0xE3001064,  # movw r1, #100      <- profile, movw form
        0xE59F2010,  # ldr  r2,[pc,#16]   (not an immediate load)
        0xE3A0306E,  # mov  r3, #110      <- High 10, far from any level
        0x1064E3A0,  # the bytes of "mov r0,#100" MISALIGNED -> must not match
        0xE3A0407A,  # mov  r4, #122
        0xE3A05033,  # mov  r5, #51       <- level, clusters with #122 above
    ]
    buf = b''.join(st.pack('<I', w) for w in code)
    f = scan(buf, 0xC1000000)
    ok = True
    n100 = len(f[100])
    print(f'  positive control: found {n100} loads of 100 (expected 2: mov + movw)')
    ok &= n100 == 2
    print(f'                    found {len(f[110])} of 110 (expected 1), '
          f'{len(f[122])} of 122 (expected 1), {len(f[51])} of 51 (expected 2)')
    ok &= len(f[110]) == 1 and len(f[122]) == 1 and len(f[51]) == 2
    clustered = report(f)
    ok &= clustered
    print()

    # negative control: real shipped ARM code that has nothing to do with H.264
    og = pathlib.Path(__file__).resolve().parent.parent / \
        'resources/fp_sup/opengate/VSHL.BIN'
    if og.exists():
        f2 = scan(og.read_bytes(), 0)
        noise = sum(len(f2[v]) for v in (110, 122))
        print(f'  negative control (OpenGate VSHL.BIN, {og.stat().st_size} bytes of real '
              f'ARM): {noise} loads of 110/122')
        print(f'                    {len(f2[100])} of 100, {len(f2[51])} of 51')
        c = report(f2)
        ok &= not c
        print(f'  -> no false cluster in unrelated shipped code: '
              f'{"PASS" if not c else "FAIL"}')
    print(f'\nSELF-TEST {"PASSED" if ok else "FAILED"}')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump', nargs='?', type=pathlib.Path)
    ap.add_argument('--base', type=lambda s: int(s, 0), default=0xC0000000)
    ap.add_argument('--window', type=lambda s: int(s, 0), default=0x40)
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.dump:
        ap.error('give a dump, or --self-test')
    data = a.dump.read_bytes()
    print(f'{a.dump}  {len(data):,} bytes at 0x{a.base:08X}\n')
    report(scan(data, a.base), a.window)
    print('\nA cluster is a lead, not an answer. Read the code around it: the '
          'question is whether 110/122 reach a register write, or only sit in a '
          'table the firmware never selects.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
