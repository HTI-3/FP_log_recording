#!/usr/bin/env python3
"""Read what camera/shadowbank_probe.S left on the card: the ISP shadow bank
0x30210000..0x30214000, idle and inside a MOV take, every word named by stage.

    tools/check_shadowbank.py <live run>                        # the baseline
    tools/check_shadowbank.py <recording run> --live <live run> # the result
    tools/check_shadowbank.py --self-test

One card, two runs, three rounds each (S1n, S2n, S3n; n = window, table read
out of the .S).  A LIVE run never presses record; a RECORDING run records from
the first prompt.  The take control (recording block width at 0xC38D62BC, SPS
at 0xC38D4060, as in tools/check_yuvpack.py) says which rounds were in a take,
so the run type is measured, not assumed.

What it prints:

  1. Completeness and the take control per round.
  2. Volatile words: differ between rounds in the same state -- the live run's
     three idle rounds, or the recording run's two in-take rounds.  They change
     by themselves (counters, statistics) and are excluded from 3.
  3. Record-driven words: idle -> take changed, not volatile here or in the
     live baseline.  Each with its register and ISP stage (tools/shadow_map.py,
     from the firmware image) and what its value looks like.
  4. Geometry in the take, over EVERY word: the picture width, height,
     MB-aligned height, minus-one forms and 16-bit halves; a line stride of
     W x 1 / 1.25 / 1.5 / 2 (aligned to 16..128); a plane size W x H16 x the
     same factors.  A stride or plane size is the bytes-per-sample reading the
     10-bit question needs: x1 is 8-bit, x1.25 10-bit packed, x2 16-bit words.
     Readings, not verdicts -- x2 can also be interleaved 4:2:2, x1.5 a 4:2:0
     frame.
  5. Stages: which ones the take touched, and which hold geometry.
"""
import argparse, pathlib, struct, sys, tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools'))
import check_yuvpack as cy                                   # noqa: E402

SRC = REPO / 'camera' / 'shadowbank_probe.S'
PREFIX = 'S'
BANK_LO, BANK_HI = 0x30210000, 0x30214000
DEFAULT_IMAGE = REPO / 'results' / 'dram_rec_23_09_2026' / 'dram_C0000000.bin'
ROUNDS = cy.ROUNDS


def stage_map(image):
    """{shadow address: (register, stage)} from a firmware image, or {} if absent."""
    if not image or not pathlib.Path(image).exists():
        return {}
    import shadow_map
    return shadow_map.shadow_map(shadow_map.load_image(image))


def bank(got_r, wins):
    """{address: word} over the shadow bank, for the windows present."""
    out = {}
    for i, (base, size) in enumerate(wins):
        if i in got_r and BANK_LO <= base < BANK_HI:
            b = got_r[i]
            for o in range(0, len(b) - 3, 4):
                out[base + o] = struct.unpack_from('<I', b, o)[0]
    return out


def controls(got, wins):
    """{round: (width, height, sps, in_take)}"""
    out = {}
    for r in ROUNDS:
        w = cy.word(got[r], wins, cy.WIDTH_AT)
        h = cy.word(got[r], wins, cy.WIDTH_AT + 4)
        sps = cy.sps_present(got[r], wins)
        out[r] = (w, h, sps, bool(sps) and w in (1920, 3840, 4096) and h in (1080, 2160))
    return out


def readings(v, w, h):
    """What a word looks like against picture width w, height h."""
    if not w or v in (0, None):
        return []
    ha = (h + 15) // 16 * 16
    dims = {w: 'W', h: 'H', ha: 'H16', w - 1: 'W-1', h - 1: 'H-1', ha - 1: 'H16-1'}
    out = [f'{n}={x}:{dims[x]}' for n, x in (('word', v), ('lo16', v & 0xFFFF), ('hi16', v >> 16))
           if x in dims]
    for mult in (1.0, 1.25, 1.5, 2.0):
        s = int(w * mult)
        # not /256: it rounds 1920 up to 2048 = 0x800, a unity constant all over
        # the RAW stages, and turns every one of them into a false stride
        for align in (1, 16, 32, 64, 128):
            if v == (s + align - 1) // align * align:
                out.append(f'stride W x{mult:g}' + (f' /{align}' if align > 1 else ''))
                break
        if v == int(w * ha * mult):
            out.append(f'plane W x H16 x{mult:g}')
    return out


def load_run(card, wins):
    got, missing = cy.load(card, wins, PREFIX)
    return got, missing, controls(got, wins), {r: bank(got[r], wins) for r in ROUNDS}


def volatile(banks, rounds):
    """Addresses whose value differs across the given rounds (all present)."""
    out = set()
    for a in banks[rounds[0]]:
        vals = [banks[r].get(a) for r in rounds]
        if None not in vals and len(set(vals)) > 1:
            out.add(a)
    return out


def report(card, wins, live=None, smap=None):
    smap = smap or {}
    got, missing, ctl, banks = load_run(card, wins)
    print(f'=== {card}')
    for r, what in ROUNDS.items():
        tail = f', first missing {missing[r]}' if r in missing else ''
        w, h, sps, t = ctl[r]
        print(f'  round {r}: {len(got[r])}/{len(wins)} files{tail};  width {w}, height {h}, '
              f'SPS {"yes" if sps else "no"}  -> {"IN A TAKE" if t else "not in a take"}')
    in_take = [r for r in ROUNDS if ctl[r][3]]
    idle = [r for r in ROUNDS if not ctl[r][3] and banks[r]]
    kind = 'recording' if in_take else 'live'
    print(f'  -> {kind} run: {len(banks["1"])} shadow words per round')

    vol = set()
    if len(idle) > 1:
        vol |= volatile(banks, idle)
    if len(in_take) > 1:
        vol |= volatile(banks, in_take)
    base_vol = set()
    if live:
        lg, _, lctl, lbanks = load_run(live, wins)
        lidle = [r for r in ROUNDS if not lctl[r][3] and lbanks[r]]
        base_vol = volatile(lbanks, lidle) if len(lidle) > 1 else set()
        same = sum(1 for a, v in lbanks['1'].items() if banks['1'].get(a) == v)
        print(f'  live baseline {live}: {len(base_vol)} volatile words; '
              f'its idle round 1 matches this run\'s in {same}/{len(lbanks["1"])} words')
    print(f'\n  volatile here: {len(vol)} words' + (f', +{len(base_vol - vol)} more from the live run' if live else ''))
    by_stage = {}
    for a in sorted(vol | base_vol):
        by_stage.setdefault(smap.get(a, (None, None))[1] or '(unmapped)', []).append(a)
    for st, addrs in sorted(by_stage.items(), key=lambda kv: -len(kv[1]))[:12]:
        print(f'    {len(addrs):4}  {st}   0x{addrs[0]:08X}..0x{addrs[-1]:08X}')
    exclude = vol | base_vol

    rec = []
    if in_take and idle:
        r0, r1 = idle[0], in_take[0]
        w, h = ctl[r1][0], ctl[r1][1]
        for a in sorted(banks[r1]):
            x, y = banks[r0].get(a), banks[r1].get(a)
            if x is not None and x != y and a not in exclude:
                rec.append(a)
        print(f'\n  record-driven: {len(rec)} words (round {r0} idle -> round {r1} take, volatile excluded)')
        print('    shadow       register    stage                         idle      take      reading')
        for a in rec:
            reg, st = smap.get(a, (None, None))
            regs = f'0x{reg:08X}' if reg else '    --    '
            print(f'    0x{a:08X}   {regs}  {(st or "(unmapped)")[:28]:28}  {banks[r0][a]:08X}  '
                  f'{banks[r1][a]:08X}  {", ".join(readings(banks[r1][a], w, h))}')

        geo = [(a, readings(v, w, h)) for a, v in sorted(banks[r1].items())]
        geo = [(a, g) for a, g in geo if g]
        strides = [(a, g) for a, g in geo if any(x.startswith(('stride', 'plane')) for x in g)]
        print(f'\n  geometry in the take: {len(geo)} words; stride/plane-size readings: {len(strides)}')
        for a, g in geo:
            reg, st = smap.get(a, (None, None))
            mark = 'R' if a in rec else ' '
            print(f'   {mark} 0x{a:08X}  {(st or "(unmapped)")[:28]:28}  {banks[r1][a]:08X}  {", ".join(g)}')
        stages = {}
        for a in rec:
            stages.setdefault(smap.get(a, (None, None))[1] or '(unmapped)', []).append(a)
        print('\n  stages the take touched:')
        for st, addrs in sorted(stages.items(), key=lambda kv: -len(kv[1])):
            print(f'    {len(addrs):4}  {st}')
    elif not in_take:
        print('\n  No round was in a take: this is the baseline.  Now the recording run, then')
        print(f'    tools/check_shadowbank.py <recording run> --live {card}')
    return kind, rec


def self_test():
    wins = cy.windows(SRC)
    assert [b for b, _ in wins] == [cy.REC_BLOCK, 0xC38D4000, 0x30210000, 0x30211000,
                                    0x30212000, 0x30213000], wins
    STRIDE_AT, COUNTER_AT, LIVECOUNT_AT, HEIGHT_AT = 0x30211A10, 0x30213004, 0x30213008, 0x3021237C
    smap = {STRIDE_AT: (0x30118A10, 'FAKE_WDMA'), HEIGHT_AT: (0x3011E014, 'YUV_PACK')}

    def card(d, take, stride=1920, counter_live=False):
        for r in ROUNDS:
            for i, (base, size) in enumerate(wins):
                b = bytearray(size)
                t = take and r != '1'
                if base == cy.REC_BLOCK and t:
                    struct.pack_into('<2I', b, cy.WIDTH_AT - base, 1920, 1080)
                if base == 0xC38D4000 and t:
                    b[cy.SPS_AT - base:cy.SPS_AT - base + 5] = b'\0\0\0\1\x67'
                if base <= COUNTER_AT < base + size:
                    struct.pack_into('<I', b, COUNTER_AT - base, 100 + int(r))  # per-round counter
                if base <= LIVECOUNT_AT < base + size and (counter_live or not take):
                    struct.pack_into('<I', b, LIVECOUNT_AT - base, 7 + int(r))
                if base <= STRIDE_AT < base + size and t:
                    struct.pack_into('<I', b, STRIDE_AT - base, stride)
                if base <= HEIGHT_AT < base + size and t:
                    struct.pack_into('<I', b, HEIGHT_AT - base, 1080)
                (d / f'S{r}{i}.BIN').write_bytes(bytes(b))

    import contextlib, io
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        live, rec, rec10 = t / 'live', t / 'rec', t / 'rec10'
        for p in (live, rec, rec10):
            p.mkdir()
        card(live, take=False); card(rec, take=True); card(rec10, take=True, stride=2400)

        def run(*a, **k):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                ret = report(*a, **k)
            return ret, out.getvalue()

        (kind, recw), s = run(live, wins, smap=smap)
        assert kind == 'live' and not recw and 'this is the baseline' in s, s
        assert 'volatile here: 2 words' in s, s

        (kind, recw), s = run(rec, wins, live=live, smap=smap)
        assert kind == 'recording', s
        # the counter moves every round and must not count as record-driven; the
        # live-only counter is excluded by the baseline
        assert COUNTER_AT not in recw and LIVECOUNT_AT not in recw, (recw, s)
        assert recw == [STRIDE_AT, HEIGHT_AT], (recw, s)
        assert 'FAKE_WDMA' in s and 'stride W x1' in s and 'word=1080:H' in s, s

        (kind, recw), s = run(rec10, wins, live=live, smap=smap)
        assert 'stride W x1.25' in s, s
    print('self-test passed: window table, run type, volatile exclusion (in-run and baseline), '
          'record-driven words, stage labels, stride readings')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card', nargs='?', type=pathlib.Path)
    ap.add_argument('--live', type=pathlib.Path, help='the live run, as the per-frame baseline')
    ap.add_argument('--image', default=str(DEFAULT_IMAGE),
                    help='firmware DRAM dump for stage names (default: %(default)s)')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.card:
        ap.error('card directory required')
    smap = stage_map(args.image)
    if not smap:
        print(f'(no firmware image at {args.image}: stages unnamed)')
    report(args.card, cy.windows(SRC), live=args.live, smap=smap)


if __name__ == '__main__':
    main()
