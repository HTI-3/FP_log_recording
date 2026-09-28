#!/usr/bin/env python3
"""Read what camera/yuvpack_probe.S left on the card: YUV_PACK idle, in a take, after.

    tools/check_yuvpack.py /Volumes/UNTITLED
    tools/check_yuvpack.py run_fhd --against run_uhd    # which words scale with size
    tools/check_yuvpack.py --self-test

Three rounds, one file per window: Y1n idle, Y2n inside the take, Y3n after.
The window table is read out of the .S, so this and the probe cannot disagree.

What it says, in order of how much to trust it:

  1. Completeness.  The first missing file in a round is where that round stopped.
  2. The take control.  Round 2 must show the recording block's width at
     0xC38D62BC and the SPS at 0xC38D4060.  Without them round 2 was not
     inside a take and nothing below is YUV_PACK packing for the encoder.
  3. The 29 YUV_PACK words, by the register the sequencer copies them to
     (map at 0xC019D6E4), per round, with what the take changed.
  4. Geometry.  Words or 16-bit halves equal to the picture's width, height,
     MB-aligned height (and minus-one forms) are dimensions; a word equal to
     W x bytes/sample is a line stride, and the multiple is the bit-depth
     reading: 1 -> 8-bit, 1.25 -> 10-bit packed, 2 -> 16-bit words (or
     interleaved 4:2:2).  A reading, never a verdict: a stride can also be
     padded, and a 2x can be chroma.

--against compares round 2 of two runs with ONE setting changed (FHD vs UHD):
the words that move with the picture size name themselves.
"""
import argparse, pathlib, re, struct, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = REPO / 'camera' / 'yuvpack_probe.S'

REC_BLOCK = 0xC38D6000      # window base; the parameter block starts at 0xC38D62BC
WIDTH_AT = 0xC38D62BC       # +0x03C of 0xC38D6280: width, then height
SPS_AT = 0xC38D4060
SHADOW = 0x30212000

# shadow -> YUV_PACK register, from the command-list builder at 0xC019D6E4
YUV_MAP = [(0x3021236C, 0x3011E004, 7), (0x30212388, 0x3011E130, 11),
           (0x302123B4, 0x3011E1B0, 11)]
ROUNDS = {'1': 'idle', '2': 'take', '3': 'after'}


def windows(src=SRC):
    """The .word pairs under `windows:` in the probe, up to the 0 terminator."""
    text = src.read_text()
    body = text.split('\nwindows:', 1)[1]
    out = []
    for m in re.finditer(r'\.word\s+(0x[0-9A-Fa-f]+|0)(?:\s*,\s*(0x[0-9A-Fa-f]+))?', body):
        base = int(m.group(1), 16) if m.group(1) != '0' else 0
        if base == 0:
            break
        out.append((base, int(m.group(2), 16)))
    return out


def load(card, wins, prefix='Y'):
    """{round: {window index: bytes}} and the first missing file per round."""
    got, missing = {}, {}
    for r in ROUNDS:
        got[r] = {}
        for i, (base, size) in enumerate(wins):
            name = f'{prefix}{r}{i}.BIN'
            p = card / name
            if not p.exists():
                p = card / name.lower()
            if p.exists():
                got[r][i] = p.read_bytes()
            elif r not in missing:
                missing[r] = name
    return got, missing


def word(got_r, wins, addr):
    for i, (base, size) in enumerate(wins):
        if base <= addr < base + size and i in got_r:
            b = got_r[i]
            o = addr - base
            if o + 4 <= len(b):
                return struct.unpack_from('<I', b, o)[0]
    return None


def sps_present(got_r, wins):
    for i, (base, size) in enumerate(wins):
        if base <= SPS_AT < base + size and i in got_r:
            o = SPS_AT - base
            return got_r[i][o:o + 5] == b'\x00\x00\x00\x01\x67'
    return False


def yuv_words(got_r, wins):
    """[(register, shadow, value or None)] for the 29 words."""
    out = []
    for sh, reg, n in YUV_MAP:
        for k in range(n):
            out.append((reg + 4 * k, sh + 4 * k, word(got_r, wins, sh + 4 * k)))
    return out


def geometry(v, w, h):
    """Readings of one word against picture width w and height h."""
    if v is None or not w:
        return []
    ha = (h + 15) // 16 * 16
    dims = {w: 'W', h: 'H', ha: 'H_aligned', w - 1: 'W-1', h - 1: 'H-1',
            ha - 1: 'H_aligned-1', w // 2: 'W/2', h // 2: 'H/2', ha // 2: 'H_aligned/2'}
    strides = {w: 1.0, w * 5 // 4: 1.25, w * 2: 2.0, w * 3 // 2: 1.5}
    out = []
    for name, x in (('word', v), ('lo16', v & 0xFFFF), ('hi16', v >> 16)):
        if x in dims and x > 16:
            out.append(f'{name}={x} {dims[x]}')
    for s, mult in strides.items():
        for align in (1, 16, 32, 64, 128, 256):
            if v == (s + align - 1) // align * align and v > 16:
                out.append(f'stride? {v} = W x {mult}' + (f' (aligned {align})' if align > 1 else ''))
                break
    return out


def report(card, wins):
    got, missing = load(card, wins)
    print(f'=== {card}')
    for r, what in ROUNDS.items():
        n = len(got[r])
        tail = f', first missing {missing[r]}' if r in missing else ''
        print(f'  round {r} ({what:5}): {n}/{len(wins)} files{tail}')

    ctl = {}
    for r in ROUNDS:
        w = word(got[r], wins, WIDTH_AT)
        h = word(got[r], wins, WIDTH_AT + 4)
        ctl[r] = (w, h, sps_present(got[r], wins))
    print()
    for r, (w, h, sps) in ctl.items():
        print(f'  control round {r}: width {w}, height {h}, SPS at 0x{SPS_AT:08X}: {"yes" if sps else "no"}')
    w2, h2, sps2 = ctl['2']
    in_take = bool(sps2) and w2 in (1920, 3840, 4096) and h2 in (1080, 2160)
    if in_take:
        print(f'  -> round 2 was inside a take, {w2}x{h2}')
    else:
        print('  -> round 2 was NOT inside a take: the YUV_PACK words below are not')
        print('     the packer configured for the encoder.  Re-run, pressing record at RECORD NOW.')

    rows = {r: yuv_words(got[r], wins) for r in ROUNDS}
    print()
    print('  YUV_PACK register  shadow        idle      take      after     reading (take)')
    changed = 0
    for k, (reg, sh, _) in enumerate(rows['1']):
        vals = [rows[r][k][2] for r in ROUNDS]
        cell = ['    --    ' if v is None else f'{v:08X}  ' for v in vals]
        moved = None not in vals[:2] and vals[0] != vals[1]
        mark = ' *' if moved else '  '
        changed += moved
        g = ', '.join(geometry(vals[1], w2, h2)) if in_take else ''
        print(f'  0x{reg:08X}{mark}     0x{sh:08X}  {"".join(cell)}{g}')
    nz = sum(1 for (_, _, v) in rows['2'] if v)
    read = sum(1 for (_, _, v) in rows['2'] if v is not None)
    print(f'\n  take vs idle: {changed} of 29 words changed (*); {nz} of {read} read non-zero in the take')
    if in_take and read == 29 and nz == 0:
        print('  All 29 read zero inside a take.  Either the shadow is not where the Mov')
        print('  pattern packs from, or it is loaded and cleared before the read; the')
        print("  firmware's own register dump (pic sig_dsccal) is the next instrument.")
    return in_take


def against(card1, card2, wins):
    g1, _ = load(card1, wins)
    g2, _ = load(card2, wins)
    a, b = yuv_words(g1['2'], wins), yuv_words(g2['2'], wins)
    w1, w2 = word(g1['2'], wins, WIDTH_AT), word(g2['2'], wins, WIDTH_AT)
    print(f'=== round 2: {card1} ({w1} wide) vs {card2} ({w2} wide)')
    n = 0
    for (reg, _, x), (_, _, y) in zip(a, b):
        if x != y:
            n += 1
            ratio = f'  x{y / x:.3f}' if x and y else ''
            print(f'  0x{reg:08X}  {x if x is None else f"{x:08X}"} -> {y if y is None else f"{y:08X}"}{ratio}')
    print(f'  {n} of 29 YUV_PACK words differ')
    return n


def self_test():
    wins = windows()
    assert [b for b, _ in wins] == [REC_BLOCK, 0xC38D4000, SHADOW], wins

    def card(d, take=True, width=1920, height=1080, drop=None, packed=None):
        for r in ROUNDS:
            for i, (base, size) in enumerate(wins):
                if (r, i) == drop:
                    continue
                b = bytearray(size)
                if base == REC_BLOCK and r != '1' and take:
                    struct.pack_into('<2I', b, WIDTH_AT - base, width, height)
                if base == 0xC38D4000 and r != '1' and take:
                    b[SPS_AT - base:SPS_AT - base + 5] = b'\x00\x00\x00\x01\x67'
                if base == SHADOW:
                    struct.pack_into('<I', b, 0x3021236C + 24 - base, 0x00100010)
                    if r == '2' and take:
                        stride = width if packed is None else int(width * packed)
                        struct.pack_into('<3I', b, 0x30212388 - base,
                                         (height << 16) | width, stride, 0x5)
                (d / f'Y{r}{i}.BIN').write_bytes(bytes(b))

    import contextlib, io
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        runs = {n: t / n for n in ('fhd', 'uhd', 'idle', 'part', 'ten')}
        for p in runs.values():
            p.mkdir()
        card(runs['fhd']); card(runs['uhd'], width=3840, height=2160)
        card(runs['idle'], take=False); card(runs['part'], drop=('2', 2))
        card(runs['ten'], packed=1.25)

        def run(fn, *a):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ret = fn(*a)
            return ret, out.getvalue()

        ok, s = run(report, runs['fhd'], wins)
        assert ok and 'inside a take, 1920x1080' in s, s
        assert 'lo16=1920 W' in s and 'hi16=1080 H' in s, s
        assert 'stride? 1920 = W x 1.0' in s, s
        assert '0x3011E130 *' in s and '3 of 29 words changed' in s, s

        ok, s = run(report, runs['ten'], wins)
        assert 'stride? 2400 = W x 1.25' in s, s

        ok, s = run(report, runs['idle'], wins)
        assert not ok and 'NOT inside a take' in s, s

        ok, s = run(report, runs['part'], wins)
        assert 'first missing Y22.BIN' in s, s
        assert '0 of 29 words changed' in s and 'All 29 read zero' not in s, s

        n, s = run(against, runs['fhd'], runs['uhd'], wins)
        assert n == 2 and 'x2.000' in s, s
    print('self-test passed: window table, take control, geometry and stride readings, '
          'missing file, --against')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', nargs='?', type=pathlib.Path)
    ap.add_argument('--against', type=pathlib.Path,
                    help='a second run, one setting changed: diff round 2')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.card:
        ap.error('card directory required')
    wins = windows()
    report(args.card, wins)
    if args.against:
        print()
        against(args.card, args.against, wins)


if __name__ == '__main__':
    main()
