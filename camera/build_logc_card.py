#!/usr/bin/env python3
"""Build the Log C card.  *** THIS ONE WRITES TO THE CAMERA ***

    python3 camera/build_logc_card.py --out camera/cards/logc

Writes an ARRI Log C V3 curve into colour mode Off's entry in the
`GAM_TOP GAMMA TABLE` registry — the RGB transfer function `results/invert/`
proved reaches live view and the recorded MOV.

WHY THIS CAN BE A PLAIN `mem set` CARD, WITH NO PAYLOAD
  `results/invert/` needed a payload because it had to dump registers around a
  mode change.  This does not: the operator reported the picture switching **as
  soon as the card loaded, with nothing touched**, so the firmware re-reads the
  table itself.  (That also explains `results/selector/`: the *pointer* is
  cached, the *table contents* are not.)  So this card is 1024 `mem set` words
  and a readback, which is the simplest thing that can work.

THE MAPPING, AND WHERE IT COMES FROM
  The stock table was identified exactly, against the dump:

      stock curve #82  ==  sRGB OETF( index / 1918 )   max error 2 of 8190 codes

  So the input is scene-linear with **diffuse white = 1.0 at index 1918**, which
  is ARRI's "exposure value" by definition, and 18% grey lands at index 345.
  `tools/logc.py` holds the curve and the reasoning.

  **That mapping is a hypothesis until the exposure sweep confirms it**, which is
  what `tools/verify_logc.py` and `docs/cards/logc.md` are for.

WHAT IT WRITES
  4096 bytes of DRAM inside one tone-curve table.  No prom, no fwup, no NAND, no
  register pokes.  Battery-out cold boot reverts.  Firmware Ver.5.02 only.
"""
import argparse, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'tools'))
import logc

BANK, STRIDE, N = 0xC0971F34, 0x1000, 2048
NCURVES = 452
MODES = {82: 'Off', 16: 'Teal & Orange'}
FIRMWARE_SHA256 = 'c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--curve', type=int, default=82,
                    help='82 = colour mode "Off", the neutral mode and the one '
                         'results/invert/ confirmed neutral through an arbitrary curve')
    ap.add_argument('--ei', type=int, default=800, choices=sorted(logc.EXPOSURE),
                    help='ARRI exposure index. 800 is what the document '
                         'recommends when the actual EI is not being matched')
    ap.add_argument('--white', type=int, default=logc.WHITE_INDEX,
                    help='table index that means linear 1.0 (diffuse white). '
                         '1918 is measured from the stock curve')
    ap.add_argument('--rolloff', action='store_true',
                    help='DO NOT USE. Built to remove a highlight cliff that '
                         'results/log2/ showed was a half-written table, not the '
                         'camera. And the table is per-channel, so it lifts '
                         'whichever channel is over diffuse white (R-G +5 -> +68)')
    ap.add_argument('--rolloff-from', type=int, default=None,
                    help='table index where the roll-off starts. Default is '
                         'diffuse white (1918), so every Log C value at or '
                         'below white is untouched. Lower gives a gentler '
                         'roll-off over more of the hardware knots, at the '
                         'cost of bending Log C in the top stop')
    ap.add_argument('--stretch', action='store_true',
                    help='use all of 0..255: Log C over the usable input '
                         '(black..diffuse white, index 0..1918) stretched to fill '
                         'the output, flat above 1918 like curve #82. The input '
                         'mapping is spec-exact\'s -- NOT a fit of ARRI\'s whole '
                         'range. 38 codes per stop instead of 18. Retests the '
                         'logc2 violet/cyan band; untested on hardware')
    ap.add_argument('--fit-range', action='store_true',
                    help='DO NOT USE. Built for the same non-problem as '
                         '--rolloff. Its violet/cyan result (results/logc2/) came '
                         'from a run that may not have finished, so the 184..207 '
                         'chroma band it points at is unconfirmed')
    a = ap.parse_args()

    if not 0 <= a.curve < NCURVES:
        ap.error(f'--curve must be 0..{NCURVES - 1}')
    base = BANK + a.curve * STRIDE
    if base % 4:
        ap.error(f'curve #{a.curve} base 0x{base:08X} is not word-aligned')
    mode = MODES.get(a.curve, f'unknown (curve #{a.curve})')

    tbl = logc.camera_table(a.ei, a.white, fit_range=a.fit_range,
                            rolloff=a.rolloff, rolloff_from=a.rolloff_from,
                            stretch=a.stretch)
    if any(tbl[i + 1] < tbl[i] for i in range(len(tbl) - 1)):
        raise SystemExit('the table is not monotonic after quantisation -- '
                         'refusing to ship it')
    if len(tbl) != N:
        raise SystemExit(f'table is {len(tbl)} entries, expected {N}')

    # How far the top entry is below full scale. results/logc1/ once read this
    # as a hardware cliff; results/log2/ showed that was a half-written table --
    # a complete spec-exact write (top 4730) has no fringe. Kept only as a figure.
    cliff = logc.TABLE_MAX - tbl[-1]

    grey_i = round(0.18 * a.white)
    nwords = N // 2
    j = a.white if a.rolloff_from is None else a.rolloff_from
    kind = ('STRETCH: black..white onto 0..255' if a.stretch else
            'refitted to full range' if a.fit_range else
            f'spec-exact, highlight roll-off from index {j}' if a.rolloff else
            'spec-exact, NO roll-off')

    L, W = [], None
    W = L.append
    W('# ' + '=' * 62)
    W('# fpLog -- LOG C.  *** THIS CARD WRITES TO MEMORY ***')
    W(f'# ARRI Log C V3, EI {a.ei}, exposure-value params, {kind}.')
    W(f'# Curve #{a.curve} at 0x{base:08X} = colour mode "{mode}".')
    W(f'# index/{a.white} = scene linear, white = 1.0.')
    W(f'#   black {tbl[0]}  18% {tbl[grey_i]}  white {tbl[min(a.white, N-1)]}  '
      f'top {tbl[-1]}   of 8190')
    W('#')
    W(f'# *** WAIT FOR "LOGC DONE". {nwords} words, one command each, NOT quick.')
    W('# The picture goes flat LONG before it finishes -- shadows are written')
    W('# first -- so a flat picture is NOT the signal to shoot. The counter is.')
    W('# Stop early and the top of the table keeps what was there before: a')
    W('# coloured fringe on highlights. That is a half-written table.')
    W(f'# Proof it finished: LOGC{a.curve:02d}.BIN on the card. No file = not finished.')
    W('#')
    W('# RAM only -- no prom, no fwup, no NAND. REVERT: delete AutoRun.txt,')
    W('# BATTERY OUT, power on. A warm restart does NOT clear RAM.')
    W('# Firmware Ver.5.02 only.')
    W('# ' + '=' * 62)
    W('')
    W('display monitor 0 1')
    W('display osd 1 0xFFFFFFFF')
    W('display text LOGC 000 PCT WAIT')
    W('display osd 1')
    W('')
    # A counter that moves often enough to look alive. The picture goes flat
    # early -- the shadows are written first -- so the operator needs something
    # that says "still working" or they stop the run and get a half-table.
    STEP = 128
    for k in range(nwords):
        word = (tbl[2 * k + 1] << 16) | tbl[2 * k]
        W(f'mem set 0x{base + k * 4:08X} 0x{word:08X}')
        if k and k % STEP == 0:
            W(f'display text LOGC {int(k / nwords * 100):03d} PCT WAIT')
            W('display osd 1')
    W('')
    W('# read it back -- a write is only real once it has been read back')
    W(f'mem save \\LOGC{a.curve:02d}.BIN 0x{base:08X},,0x{N * 2:X}')
    W('display text LOGC 100 PCT')
    W('display osd 1')
    W(f'display text LOGC DONE - LOGC{a.curve:02d}.BIN WRITTEN')
    W('display osd 1')

    text = '\n'.join(L) + '\n'
    # fp_sup's own build_autorun.py refuses a script past 32768 bytes
    # (PAD_TO). This card does not go through that tool, so it has to check
    # itself -- and a card that is silently truncated writes HALF A TABLE,
    # which is the one failure mode that looks like a working curve.
    PAD_TO = 32768
    if len(text) > PAD_TO:
        raise SystemExit(
            f'AutoRun.txt is {len(text)} bytes, past the {PAD_TO} fp_sup treats '
            f'as the maximum. A truncated card writes a partial table and the '
            f'result looks like a curve artefact. Shorten the header or raise '
            f'STEP.')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'AutoRun.txt').write_text(text)

    # --- the decode, from the same source of truth, beside the card ----------
    logc.write_cube(a.out / 'fplog_decode.cube', a.ei, a.white,
                    fit_range=a.fit_range, rolloff=a.rolloff,
                    rolloff_from=a.rolloff_from, stretch=a.stretch)
    logc.write_dctl(a.out / 'fplog_decode.dctl', a.ei, a.white,
                    fit_range=a.fit_range, rolloff=a.rolloff,
                    rolloff_from=a.rolloff_from, stretch=a.stretch)
    (a.out / 'expected.csv').write_text(
        'index,linear,logc,written,code13,code8\n' + '\n'.join(
            f'{i},{i / a.white:.6f},{logc.lin2log(i / a.white, a.ei):.6f},'
            f'{logc.curve_norm(i, a.ei, a.white, N, a.fit_range, a.rolloff, a.rolloff_from, a.stretch):.6f},'
            f'{tbl[i]},{round(tbl[i] / logc.TABLE_MAX * 255)}'
            for i in range(N)) + '\n')
    (a.out / 'curve.txt').write_text(
        f'ei          {a.ei}\ncurve       {a.curve} ("{mode}") @ 0x{base:08X}\n'
        f'white index {a.white}\nfit_range   {a.fit_range}\nstretch     {a.stretch}\n'
        f'range       {tbl[0]}..{tbl[-1]} of {logc.TABLE_MAX}\n')

    nset = sum(1 for l in L if l.startswith('mem set'))
    nprom = sum(1 for l in L if l.startswith('prom'))
    if nprom:
        raise SystemExit('the AutoRun contains a prom command -- refusing to ship it')

    span = (tbl[-1] - tbl[0]) / logc.TABLE_MAX
    print(f'wrote {a.out}/AutoRun.txt')
    print(f'  curve      #{a.curve} @ 0x{base:08X}..0x{base + STRIDE:08X} = "{mode}"')
    print(f'  curve def  ARRI Log C V3, EI {a.ei}, exposure-value set, {kind}')
    print(f'  mapping    index / {a.white} = scene linear, white = 1.0, '
          f'18% grey at index {grey_i}')
    print(f'  writes     {nset} mem set ({nset * 4} bytes), 1 mem save, '
          f'{nprom} prom (must be 0)')
    print(f'  AutoRun    {len(text)} bytes of {PAD_TO} max '
          f'({PAD_TO - len(text)} to spare)')
    print(f'  range used {tbl[0]}..{tbl[-1]} of {logc.TABLE_MAX} = {span * 100:.1f}%'
          f'   8-bit codes {round(tbl[0] / logc.TABLE_MAX * 255)}'
          f'..{round(tbl[-1] / logc.TABLE_MAX * 255)}')
    if a.rolloff and not a.fit_range:
        print('  *** DO NOT USE --rolloff. It was built for a highlight fringe that')
        print('      results/log2/ showed was a half-written table, and it lifts')
        print('      whichever channel is over diffuse white (R-G +5 -> +68). ***')
        spec = logc.camera_table(a.ei, a.white, rolloff=False)
        assert tbl[:j + 1] == spec[:j + 1]
        print(f'  Log C        bit-exact for index 0..{j} '
              f'(8-bit {round(tbl[0]/logc.TABLE_MAX*255)}'
              f'..{round(tbl[j]/logc.TABLE_MAX*255)}) -- unchanged from spec-exact')
        print(f'  roll-off     index {j}..{N-1}, reaching full scale, so there is')
        print(f'               no step between the table and anything brighter')
        print(f'  grading      Resolve\'s stock ARRI LogC3 EI{a.ei} decode is EXACT')
        print(f'               over the whole Log C range')
    print(f'  also wrote fplog_decode.cube, fplog_decode.dctl, expected.csv, curve.txt')
    print()
    if not (a.fit_range or a.rolloff or a.stretch):
        print(f'  Log C        spec-exact, every entry, EI {a.ei} exposure-value set')
        print(f'  on camera    proven: read back bit-exact, and a complete write has')
        print(f'               no highlight fringe (results/log2/). Uses 8-bit '
              f'{round(tbl[0] / logc.TABLE_MAX * 255)}..{round(tbl[-1] / logc.TABLE_MAX * 255)}'
              f' -- --stretch uses all of 0..255.')
        print()
        print(f'  Resolve: set the clip to ARRI LogC3 EI{a.ei} -- exact over the whole')
        print('  table. fplog_decode.cube / .dctl are the same transform if you')
        print('  prefer them; all come from tools/logc.py so nothing can drift.')
    elif a.stretch:
        lo, hi = logc.stretch_span(a.ei)
        c8 = lambda v: round(v / logc.TABLE_MAX * 255)
        print(f'  stretch      Log C {lo:.4f}..{hi:.4f} (black..diffuse white) stretched to '
              f'0..255, x{1 / (hi - lo):.2f}')
        print(f'               input mapping unchanged from spec-exact; flat above index {a.white}')
        print(f'  8-bit        black {c8(tbl[0])}, 18% grey {c8(tbl[grey_i])}, white '
              f'{c8(tbl[min(a.white, N - 1)])}; {c8(tbl[round(grey_i * 2)]) - c8(tbl[grey_i])} '
              f'codes per stop around grey (spec-exact: 18)')
        band = sum(1 for v in tbl if 184 <= c8(v) <= 207)
        print(f'  *** RETEST   {band} entries land in the 8-bit 184..207 band, where')
        print(f'               results/logc2/ saw --fit-range (2 codes from this curve)')
        print(f'               cast the upper midtones violet/cyan. That run may not have')
        print(f'               finished. With LOGC82.BIN confirming a complete write, a')
        print(f'               cast this time means a chroma stage after the gamma --')
        print(f'               not the curve.')
        print()
        print('  Resolve: fplog_decode.dctl or .cube -- they undo the stretch first.')
        print(f'  The stock ARRI LogC3 dropdown will NOT decode this directly.')
    elif a.fit_range:
        print('  Resolve: apply fplog_decode.cube or .dctl. And do not shoot this.')
    else:
        print(f'  Resolve: ARRI LogC3 EI{a.ei} up to diffuse white; the roll-off above')
        print('  it needs fplog_decode.cube / .dctl.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
