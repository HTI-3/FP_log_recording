#!/usr/bin/env python3
"""Read what camera/enc_rec_probe.S left on the card: which blocks the take woke.

    tools/check_encrec.py /Volumes/UNTITLED
    tools/check_encrec.py run_fhd --against run_uhd     # where the fields sit
    tools/check_encrec.py --self-test

Three rounds, one file per region: EA = idle, EB = inside the take, EC = idle
after it.  The region table is read out of the .S (via build_encrec_card.py),
so this and the probe cannot disagree about which file is which address.

What it says, in order of how much to trust it:

  1. Completeness.  The first missing file in a round is where that round
     stopped.  Round B is written after the take, so B missing with A present
     means the camera stopped during or after the take.
  2. The control.  0x30210000 moved on the record press in results/isprobe_1.
     If A and B read identical there, round B was NOT taken inside a take and
     nothing below means anything.
  3. Blocks.  Each 64 KiB block, dead or live per round.  DEAD-LIVE-DEAD is
     what a datapath the firmware powers only while recording looks like --
     the encoder is the thing to look for among those.
  4. Values.  In round B, words or halves holding the stream's known
     parameters: 1920, 1080 (and the minus-one forms), profile 100, level 51.
     A cluster of them in one block is a lead, one hit is noise.
  5. Signatures from tools/enc_ident.py -- a shortlist, never an answer.

--against compares round B of two runs taken with ONE setting changed
(FHD vs UHD, or two bitrates).  The words that differ in a candidate block
are where that setting lives.  That is the step towards finding bit depth.
"""
import argparse, pathlib, struct, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'camera'))
sys.path.insert(0, str(REPO / 'tools'))
from build_encrec_card import regions as _regions   # noqa: E402
from enc_ident import SIGNATURES, DEAD               # noqa: E402

ROUNDS = 'ABC'
ROUND_NAME = {'A': 'idle', 'B': 'take', 'C': 'after'}
CONTROL = 0x30210000
STRIDE, HEAD = 0x10000, 16

# The stock stream, results/mov_recording/FINDINGS.md.
KNOWN = {1920: 'width', 1919: 'width-1', 1080: 'height', 1079: 'height-1',
         1088: 'height, MB-aligned', 120: 'width in MBs', 68: 'height in MBs',
         100: 'profile_idc High', 51: 'level_idc 5.1'}
# Values too common to mean anything alone; they only count in a cluster.
WEAK = {100, 51, 120, 68}


def words(b):
    return list(struct.unpack(f'<{len(b) // 4}I', b[:len(b) // 4 * 4]))


def fname(rnd, idx):
    return f'E{rnd}{idx:02d}.BIN'


def load(card, regs):
    """{round: {region index: bytes}} and {round: [missing indices]}."""
    got, missing = {}, {}
    for r in ROUNDS:
        got[r], missing[r] = {}, []
        for i in range(len(regs)):
            p = card / fname(r, i)
            if p.exists():
                got[r][i] = p.read_bytes()
            else:
                missing[r].append(i)
    return got, missing


def blocks(regs, got_round):
    """{block base: [words]} for one round.  A contiguous region is one block
    at its base; a sweep region is its 16 block heads."""
    out = {}
    for i, (base, size, kind) in enumerate(regs):
        if i not in got_round:
            continue
        ws = words(got_round[i])
        if kind == 0:
            out[base] = ws
        else:
            for k in range(size // (HEAD * 4)):
                out.setdefault(base + k * STRIDE, ws[k * HEAD:(k + 1) * HEAD])
    return out


def live(ws):
    return sum(1 for w in ws if w not in DEAD)


def state(ws):
    if ws is None:
        return '   -'
    n = live(ws)
    return 'dead' if n == 0 else f'{n:4d}'


def value_hits(ws, base):
    """(addr, value, meaning, as) for every word or 16-bit half in KNOWN."""
    hits = []
    for i, w in enumerate(ws):
        a = base + i * 4
        if w in KNOWN:
            hits.append((a, w, KNOWN[w], 'word'))
            continue
        for half, v in (('lo16', w & 0xFFFF), ('hi16', w >> 16)):
            if v in KNOWN and v not in WEAK and w not in DEAD:
                hits.append((a, v, KNOWN[v], half))
    return hits


def clusters(hits, span=0x40):
    """Groups of hits within `span` bytes holding >= 3 distinct meanings, at
    least one of them not WEAK."""
    out = []
    for j, (a, *_rest) in enumerate(hits):
        grp = [h for h in hits if a <= h[0] < a + span]
        kinds = {h[1] for h in grp}
        if len(kinds) >= 3 and kinds - WEAK and not any(a < g[0][0] + span and a >= g[0][0] for g in out):
            out.append(grp)
    return out


def classify(bA, bB, bC):
    """The verdict for one block across the three rounds."""
    if bB is None:
        return ''
    nA = live(bA) if bA is not None else None
    nB, nC = live(bB), (live(bC) if bC is not None else None)
    if nB and nA == 0 and nC in (0, None):
        return 'DEAD-LIVE-DEAD  <-- powered only in the take'
    if nB and nA == 0:
        return 'woke in the take, stayed up'
    if bA is not None and nB and nA:
        d = sum(1 for x, y in zip(bA, bB) if x != y)
        if d:
            return f'{d} words changed idle->take'
    return ''


def report(card, regs):
    got, missing = load(card, regs)
    ok = True

    print(f'{card}\n')
    for r in ROUNDS:
        n = len(regs) - len(missing[r])
        line = f'  round {r} ({ROUND_NAME[r]:5s})  {n:2d}/{len(regs)} files'
        if missing[r]:
            i = missing[r][0]
            line += f'   first missing {fname(r, i)} = 0x{regs[i][0]:08X}'
        print(line)
    if missing['B'] and not missing['A']:
        print('\n  Round A complete and B missing: the camera stopped during the take,'
              '\n  or before B was written.  Round B is in RAM only until then.')
    if len(missing['B']) == len(regs):
        return False

    bl = {r: blocks(regs, got[r]) for r in ROUNDS}

    # ---- the control -------------------------------------------------------
    print('\nCONTROL  0x30210000 idle vs take')
    cA, cB = bl['A'].get(CONTROL), bl['B'].get(CONTROL)
    if cA is None or cB is None:
        print('  missing -- cannot tell whether round B was inside a take')
        ok = False
    else:
        diff = [(i, x, y) for i, (x, y) in enumerate(zip(cA, cB)) if x != y]
        if not diff:
            print('  IDENTICAL.  Round B was almost certainly NOT inside a take --')
            print('  record was pressed late, or not at all.  Re-run; read nothing below.')
            ok = False
        else:
            print(f'  {len(diff)} words moved -- round B was inside a take.')
            for i, x, y in diff[:6]:
                print(f'    0x{CONTROL + i * 4:08X}  {x:08X} -> {y:08X}')

    # ---- blocks ------------------------------------------------------------
    print('\nBLOCKS  live words per round (dead = all 0x00000000 / 0xFFFFFFFF)')
    print(f'  {"block":10s}  {"A":>4s}  {"B":>4s}  {"C":>4s}')
    cand = []
    for base in sorted(set(bl['A']) | set(bl['B']) | set(bl['C'])):
        bA, bB, bC = (bl[r].get(base) for r in ROUNDS)
        verdict = classify(bA, bB, bC)
        if not verdict and not (bB and live(bB)):
            continue
        print(f'  0x{base:08X}  {state(bA)}  {state(bB)}  {state(bC)}  {verdict}')
        if verdict.startswith('DEAD-LIVE') or verdict.startswith('woke'):
            cand.append(base)
    if cand:
        print(f'\n  {len(cand)} block(s) woke for the take: '
              + ', '.join(f'0x{b:08X}' for b in cand))
    else:
        print('\n  No block woke for the take.  The codec is outside every region read,'
              '\n  or it is reached only through the sequencer (docs/ISP_PIPELINE.md 7.1).')

    # ---- values ------------------------------------------------------------
    print('\nVALUES  in round B -- the stream is 1920x1080, profile 100, level 51')
    anyhit = False
    for base in sorted(bl['B']):
        hits = value_hits(bl['B'][base], base)
        strong = [h for h in hits if h[1] not in WEAK]
        cl = clusters(hits)
        if not strong and not cl:
            continue
        anyhit = True
        tag = '   <-- woke for the take' if base in cand else ''
        print(f'  0x{base:08X}{tag}')
        for grp in cl:
            print(f'    CLUSTER at 0x{grp[0][0]:08X}: '
                  + ', '.join(f'{h[1]} {h[2]} ({h[3]} @+0x{h[0] - base:03X})' for h in grp))
        for a, v, m, how in strong[:8]:
            print(f'    +0x{a - base:03X}  {v:5d}  {m:20s} {how}')
    if not anyhit:
        print('  none')

    # ---- signatures --------------------------------------------------------
    print('\nSIGNATURES  (tools/enc_ident.py -- a shortlist, not an answer)')
    sig = False
    for base, ws in sorted(bl['B'].items()):
        for i, w in enumerate(ws[:HEAD]):
            for mask, val, name, conf, meaning in SIGNATURES:
                if w & mask == val:
                    sig = True
                    print(f'  0x{base + i * 4:08X} = 0x{w:08X}  {name} [{conf}] -- {meaning}')
    if not sig:
        print('  none')

    # ---- DRAM --------------------------------------------------------------
    dram = [b for b in bl['B'] if b >= 0xC0000000]
    for base in dram:
        dA, dB, dC = (bl[r].get(base) for r in ROUNDS)
        if dA is None:
            continue
        moved = [i for i, (x, y) in enumerate(zip(dA, dB)) if x != y]
        print(f'\nDRAM 0x{base:08X}  {len(moved)} words moved idle->take'
              + (f', {sum(1 for i in moved if dC and dC[i] == dA[i])} back after' if dC else ''))
        for i in moved[:12]:
            c = f' -> {dC[i]:08X}' if dC else ''
            print(f'    0x{base + i * 4:08X}  {dA[i]:08X} -> {dB[i]:08X}{c}')
    return ok


def against(card1, card2, regs):
    """Round B of two runs, one setting changed.  Words that differ."""
    b1 = blocks(regs, load(card1, regs)[0]['B'])
    b2 = blocks(regs, load(card2, regs)[0]['B'])
    print(f'\nAGAINST  round B of {card1} vs {card2}')
    n = 0
    for base in sorted(set(b1) & set(b2)):
        d = [(i, x, y) for i, (x, y) in enumerate(zip(b1[base], b2[base])) if x != y]
        if not d or not (live(b1[base]) or live(b2[base])):
            continue
        n += 1
        print(f'  0x{base:08X}  {len(d)} words differ')
        for i, x, y in d[:10]:
            lo = f'  lo16 {x & 0xFFFF} -> {y & 0xFFFF}' if (x ^ y) & 0xFFFF else ''
            hi = f'  hi16 {x >> 16} -> {y >> 16}' if (x ^ y) >> 16 else ''
            print(f'    +0x{i * 4:03X}  {x:08X} -> {y:08X}{lo}{hi}')
    if not n:
        print('  identical -- the setting did not reach any region read')


# ---------------------------------------------------------------------------
def self_test():
    """Synthetic card: one gated block wakes for the take and holds the
    stream parameters; the control moves.  Then a card where it does not."""
    regs = _regions()
    idx = {base: i for i, (base, _, _) in enumerate(regs)}
    sweep1 = idx[0x30100000]
    woke = 0x30150000                    # block 5 of sweep group 1

    def card(d, take=True, width=1920, drop=None):
        for r in ROUNDS:
            for i, (base, size, kind) in enumerate(regs):
                if (r, i) == drop:
                    continue
                ws = [0] * (size // 4)
                if base == CONTROL:
                    ws[0x3F0 // 4] = 0x03E905E0 if (r != 'B' or not take) else 0x014E01F8
                    ws[1] = 0x00214401
                if base == 0x301B0000:
                    ws[:3] = [1, 2, 3]
                if i == sweep1 and r == 'B' and take:
                    k = (woke - 0x30100000) // STRIDE * HEAD
                    ws[k:k + 5] = [0x80000001, width, 1080, 100, 51]
                (d / fname(r, i)).write_bytes(struct.pack(f'<{len(ws)}I', *ws))

    import contextlib, io
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        good, flat, part, uhd = (t / n for n in ('good', 'flat', 'part', 'uhd'))
        for p in (good, flat, part, uhd):
            p.mkdir()
        card(good); card(flat, take=False); card(part, drop=('B', 3)); card(uhd, width=3840)

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert report(good, regs)
        s = out.getvalue()
        assert 'round B was inside a take' in s, s
        assert f'0x{woke:08X}' in s and 'DEAD-LIVE-DEAD' in s, s
        assert 'CLUSTER' in s and '1920 width' in s, s
        assert '0x301B0000' in s and 'DEAD-LIVE' not in s.split('0x301B0000')[1].split('\n')[0]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert not report(flat, regs)
        assert 'IDENTICAL' in out.getvalue()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report(part, regs)
        assert f'first missing {fname("B", 3)}' in out.getvalue()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            against(good, uhd, regs)
        assert f'0x{woke:08X}  1 words differ' in out.getvalue() and '1920 -> 3840' in out.getvalue()
    print('self-test passed: wake detection, control, value cluster, missing file, --against')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', nargs='?', type=pathlib.Path)
    ap.add_argument('--against', type=pathlib.Path,
                    help='a second run, one setting changed: diff round B')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.card:
        ap.error('card directory required')
    regs = _regions()
    ok = report(args.card, regs)
    if args.against:
        against(args.card, args.against, regs)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
