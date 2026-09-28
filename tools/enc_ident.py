#!/usr/bin/env python3
"""Read what camera/enc_probe.S left on the card and say what the blocks are.

    tools/enc_ident.py /Volumes/UNTITLED

Two jobs, in order of how much they can be trusted:

  1. Structure.  Which register banks answered, which read back dead, and where
     an ID-shaped word sits.  This is measurement and it stands on its own.

  2. Identification.  The candidate signatures below are matched against those
     words.  They are a shortlist to check, NOT an answer: a match says "read
     this IP's documentation next", and the only thing that settles what the
     block is, and how the firmware drives it, is the driver code in the DRAM
     dump.  Every entry carries the confidence it deserves.
"""
import argparse, pathlib, struct, sys

WINDOWS = [
    ('ENCW0.BIN', 0x300C0000, 'RFC readout -- live during recording (raw-sup)'),
    ('ENCW1.BIN', 0x300D0000, 'lossless JPEG engine (raw-sup, confirmed)'),
    ('ENCW2.BIN', 0x301B0000, 'the DSP recording uses (raw-sup)'),
    ('ENCW3.BIN', 0x30210000, 'shadow config bank (raw-sup, retraction)'),
    ('ENCW4.BIN', 0x30110000, 'SIG registers -- expected dead, a control'),
]
SWEEPS = [('ENCS0.BIN', 0x30000000), ('ENCS1.BIN', 0x30100000),
          ('ENCS2.BIN', 0x30200000)]
SWEEP_STRIDE, SWEEP_HEAD_WORDS = 0x10000, 16

# (mask, value, name, confidence, what it would mean)
SIGNATURES = [
    (0xFFFF0000, 0x67310000, 'Verisilicon/Hantro G1 decoder', 'medium',
     'decoder only -- says nothing about encode profiles'),
    (0xFFFF0000, 0x67320000, 'Verisilicon/Hantro G2 decoder', 'medium',
     'decoder only'),
    (0xFFFF0000, 0x48310000, 'Verisilicon/Hantro H1 encoder', 'medium',
     'H1 reports its synthesis options in the registers just after the ID: '
     'that is where a High10 / 4:2:2 answer would be'),
    (0xFFFF0000, 0x96000000, 'Chips&Media CODA9xx', 'low',
     'CODA product code is conventionally BCD; confirm the offset first'),
    (0xFFFF0000, 0x42100000, 'Chips&Media WAVE4xx', 'low', 'BCD product code'),
    (0xFFFF0000, 0x51100000, 'Chips&Media WAVE5xx', 'low', 'BCD product code'),
]

DEAD = (0x00000000, 0xFFFFFFFF)


def words(b):
    return list(struct.unpack(f'<{len(b) // 4}I', b[:len(b) // 4 * 4]))


def ascii_of(w):
    b = struct.pack('<I', w)
    return ''.join(chr(c) if 32 <= c < 127 else '.' for c in b[::-1])


def classify(ws):
    if not ws:
        return 'empty'
    uniq = set(ws)
    if uniq <= set(DEAD):
        return 'dead (all 0x00/0xFF)'
    if len(uniq) == 1:
        return f'constant 0x{ws[0]:08X}'
    live = sum(1 for w in ws if w not in DEAD)
    return f'live ({live}/{len(ws)} words non-trivial)'


def match(w):
    return [(n, c, m) for mask, val, n, c, m in SIGNATURES if w & mask == val]


def report_window(path, base, note):
    ws = words(path.read_bytes())
    print(f'\n{path.name}  base 0x{base:08X}  -- {note}')
    print(f'  {classify(ws)}')
    if not ws or set(ws) <= set(DEAD):
        return
    print('  first 8 words:')
    for i, w in enumerate(ws[:8]):
        hits = match(w)
        tag = f'   <-- {hits[0][0]} ({hits[0][1]} confidence)' if hits else ''
        print(f'    +0x{i * 4:03X}  0x{w:08X}  "{ascii_of(w)}"{tag}')
    for i, w in enumerate(ws):
        for n, c, meaning in match(w):
            print(f'  MATCH +0x{i * 4:03X} = 0x{w:08X}: {n} [{c} confidence]')
            print(f'        {meaning}')


def report_sweep(path, base):
    ws = words(path.read_bytes())
    print(f'\n{path.name}  0x{base:08X}..0x{base + 16 * SWEEP_STRIDE:08X}')
    for blk in range(len(ws) // SWEEP_HEAD_WORDS):
        head = ws[blk * SWEEP_HEAD_WORDS:(blk + 1) * SWEEP_HEAD_WORDS]
        if set(head) <= set(DEAD):
            continue
        addr = base + blk * SWEEP_STRIDE
        hits = match(head[0])
        tag = f'  <-- {hits[0][0]} ({hits[0][1]})' if hits else ''
        print(f'  0x{addr:08X}  w0=0x{head[0]:08X} "{ascii_of(head[0])}"'
              f'  w1=0x{head[1]:08X}{tag}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', type=pathlib.Path, help='card mount point, or a directory of the files')
    args = ap.parse_args()

    found = missing = 0
    for name, base, note in WINDOWS:
        p = args.card / name
        if p.exists():
            report_window(p, base, note); found += 1
        else:
            print(f'\n{name}  MISSING -- the probe stopped before it, or never ran')
            missing += 1

    print('\n' + '=' * 70)
    print('SWEEP -- blocks that answered')
    for name, base in SWEEPS:
        p = args.card / name
        if p.exists():
            report_sweep(p, base); found += 1
        else:
            print(f'\n{name}  MISSING -- the sweep stopped in or before this group')
            missing += 1

    print('\n' + '=' * 70)
    print(f'{found} files read, {missing} missing.')
    if missing:
        print('A missing file is a result, not a failure of the tool: the probe')
        print('writes each one as it goes, so the first gap is where it stopped.')
    print()
    print('Nothing here proves a profile is supported. A signature match means')
    print('"find this block\'s driver in the DRAM dump and read what it sets" --')
    print('that is what says whether High10 or 4:2:2 is reachable.')


if __name__ == '__main__':
    main()
