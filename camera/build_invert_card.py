#!/usr/bin/env python3
"""Build the curve-inversion card.  *** THIS ONE WRITES TO THE CAMERA ***

    python3 camera/build_invert_card.py --out camera/cards/invert

docs/CURVE_TARGETS.md target 1, and the highest-value experiment in the project.
It inverts colour mode Off's AND Teal & Orange's entries in the 452-curve
`GAM_TOP GAMMA TABLE` registry, then asks the operator to toggle between exactly
those two modes -- because results/looksrc1/ established that **the firmware
uploads when a mode is selected**, and results/selector/ is the same experiment
WITHOUT that trigger, which is why its "the bank is inert" verdict was withdrawn.

WHY INVERT RATHER THAN FLATTEN
  Flattening a few hundred entries makes a band on a gradient, and whether a
  band is there is a judgement call on a live LCD.  This project has already
  drawn a wrong conclusion from "the picture changed" once -- the literal report
  of that run was "it changed the color" (results/logoff1/REFRAME.md).  An
  inverted curve renders a photographic NEGATIVE.  Nobody has to decide whether
  they saw it, and no second run is needed to be sure.

WHY BOTH CURVES
  #82 is Off, the neutral mode and the one to ship on.  #16 is Teal & Orange.
  Every write this project has aimed at Off has failed to move the picture,
  while the ONE write that worked was aimed at Teal & Orange (results/looksrc1/,
  record id 11).  Inverting both costs nothing -- the mode toggle that forces
  the upload runs between exactly those two modes, so both ends of it land on an
  inverted table.  If only one responds, that asymmetry is the finding.

WHAT IT WRITES
  4096 bytes of DRAM per curve, inside the tone-curve tables.  No prom, no fwup,
  no NAND, no register pokes -- the ISP bank is read only.  Battery-out cold boot
  reverts.  Firmware Ver.5.02 only.
"""
import argparse, pathlib, re, subprocess, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHELL = REPO / 'resources' / 'fp_sup' / 'fp_usb_shell' / 'build_autorun.py'
CURVES = REPO / 'results/dram_21_09_2026/curves/all_curves.npy'

TEMPLATE = HERE / 'invert_curve.S'
GENERATED = HERE / 'invert_curve_gen.S'
PROBE_AT = 0xC072DE64            # CAVE_LOW -- build_autorun.py's own default

BANK, STRIDE, N = 0xC0971F34, 0x1000, 2048
NCURVES = 452                    # the registry at 0xC0971118 is 452 {ptr,id}
MODES = {82: 'Off', 16: 'Teal & Orange'}

# Read alongside the two curves, every round.
EXTRA_WINDOWS = [
    (0xC3414000, 0x1000, 'live selector (+0x510/+0xD4C/+0xD84)'),
    (0x30210000, 0x1000, 'shadow bank, hardware ramp at +0x594'),
]

FIRMWARE_SHA256 = 'c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8'


def _equ(text, name):
    m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+)', text, re.M)
    if not m:
        raise SystemExit(f'{TEMPLATE.name} has no .equ {name}')
    return int(m.group(1), 16)


def _replace_block(src, label, body):
    """Swap the .word list under `label:` for `body`, leaving the rest alone."""
    m = re.search(rf'^{label}:\n(?:[ \t]*\.word.*\n)+', src, re.M)
    if not m:
        raise SystemExit(f'{TEMPLATE.name} has no generated `{label}:` block')
    return src[:m.start()] + f'{label}:\n' + body + src[m.end():]


def _cave_writes(autorun, probe_size):
    """Every cave address the generated AutoRun pokes, the probe's own excluded."""
    out = set()
    for line in autorun.read_text().splitlines():
        m = re.match(r'\s*mem set\s+(0x[0-9A-Fa-f]+)', line)
        if m:
            a = int(m.group(1), 16)
            if 0xC0720000 <= a < 0xC0740000 and not (PROBE_AT <= a < PROBE_AT + probe_size):
                out.add(a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--curves', default='82,16',
                    help='registry indices to invert, comma separated. Default '
                         '"82,16" = colour modes Off and Teal & Orange, which '
                         'are the two ends of the toggle that forces the upload')
    ap.add_argument('--banner', default='fpLog-INVERT!')
    a = ap.parse_args()

    if not SHELL.exists():
        raise SystemExit(f'missing {SHELL} -- resources/fp_sup is not checked out')
    try:
        curves = [int(x) for x in a.curves.split(',') if x.strip() != '']
    except ValueError:
        ap.error('--curves must be comma-separated integers')
    if not curves:
        ap.error('--curves is empty')
    if len(set(curves)) != len(curves):
        ap.error('--curves has a repeat; inverting a table twice restores it')
    for c in curves:
        if not 0 <= c < NCURVES:
            ap.error(f'curve {c} is outside 0..{NCURVES - 1}')

    targets = []
    for c in curves:
        base = BANK + c * STRIDE
        if base % 4:
            ap.error(f'curve #{c} base 0x{base:08X} is not word-aligned')
        targets.append((c, base, MODES.get(c, f'unknown (curve #{c})')))

    # ---- regenerate the two tables, mechanically -----------------------------
    src = TEMPLATE.read_text()
    src = _replace_block(src, 'targets', ''.join(
        f'    .word   0x{b:08X}, {N}        @ curve #{c} -- colour mode "{m}"\n'
        for c, b, m in targets) + '    .word   0\n')

    windows = [(b, STRIDE, f'curve #{c}, a table this card writes')
               for c, b, m in targets] + EXTRA_WINDOWS
    src = _replace_block(src, 'windows', ''.join(
        f'    .word   0x{b:08X}, 0x{sz:04X}      @ {i:02d} -- {why}\n'
        for i, (b, sz, why) in enumerate(windows)) + '    .word   0\n')
    GENERATED.write_text(src)

    if len(windows) > 100:       # make_path formats the index as two digits
        raise SystemExit('more than 100 windows -- make_path cannot name them')

    # ---- what the inversion will do, from the dump ---------------------------
    #      A prediction, saved beside the card as a record of what this build
    #      expected.  It is NOT what check_invert.py scores against: that derives
    #      the expectation from round 1's own baseline, so the verdict holds even
    #      if the live table differs from the dump.  Same reason the payload
    #      measures each maximum rather than taking one from here.
    expected = {}
    if CURVES.exists():
        M = np.load(CURVES)
        for c, base, mode in targets:
            if c >= len(M):
                print(f'  curve #{c}: not in the dump, no expected result saved')
                continue
            orig = M[c].astype(np.int64)
            mx = int(orig.max())
            wide = mx - orig                 # stays signed: np.diff on a uint16
            inv = wide.astype(np.uint16)     # view would wrap every fall to +65k
            if not (np.diff(wide) <= 0).all():
                raise SystemExit(f'curve #{c} inverts to a non-monotonic table -- '
                                 'the source is not monotonic either; stop and '
                                 'look at it before running this')
            expected[c] = inv
            print(f'  curve #{c:3d} "{mode}" @ 0x{base:08X}: '
                  f'{orig[0]}..{orig[-1]} (max {mx})  ->  {inv[0]}..{inv[-1]}')
    else:
        print('  NOTE: no dump curves found -- no expected result will be saved')

    # ---- build ---------------------------------------------------------------
    a.out.mkdir(parents=True, exist_ok=True)
    out = a.out / 'AutoRun.txt'

    sys.path.insert(0, str(SHELL.parent))
    from armasm import assemble
    size = len(assemble(GENERATED))

    subprocess.run([sys.executable, str(SHELL), '--no-shell',
                    '--boot-call', f'0x{PROBE_AT:08X}:{GENERATED}',
                    '--banner', a.banner, '--out', str(out)], check=True)

    # The first build of the encoder probe put its file object inside the loader
    # that calls it, and nothing said so.  So the check is mechanical, against
    # the file just written, rather than a constant somebody has to update.
    lo, hi = _equ(src, 'BUFS_LO'), _equ(src, 'BUFS_HI')
    written = _cave_writes(out, size)
    clash = sorted(x for x in written if lo <= x < hi)
    if clash:
        raise SystemExit(
            f'{len(clash)} AutoRun words land in the probe buffers '
            f'0x{lo:08X}..0x{hi:08X}, first 0x{clash[0]:08X}. '
            f'Move FOBJ/STAGING/PATHBUF in {TEMPLATE.name}.')
    if PROBE_AT + size > min(written, default=hi):
        raise SystemExit(f'probe is {size} bytes and reaches 0x{PROBE_AT + size:08X}, '
                         f'into the loader at 0x{min(written):08X}')

    for c, inv in expected.items():
        np.save(a.out / f'expected_curve_{c:02d}.npy', inv)

    lines = out.read_text().splitlines()
    nset = sum(1 for l in lines if l.startswith('mem set'))
    nprom = sum(1 for l in lines if l.startswith('prom'))
    if nprom:
        raise SystemExit('the AutoRun contains a prom command -- refusing to ship it')

    names = ' and '.join(f'"{m}"' for _, _, m in targets)
    print()
    print(f'  targets    ' + ', '.join(
        f'#{c} @ 0x{b:08X}..0x{b + STRIDE:08X} = "{m}"' for c, b, m in targets))
    print(f'  writes     {len(targets) * STRIDE} bytes of DRAM, '
          f'{len(windows)} windows x 3 rounds = {len(windows) * 3} files')
    print(f'  payload    {size} bytes at 0x{PROBE_AT:08X}')
    print(f'  checked    {len(written)} loader words, none inside '
          f'0x{lo:08X}..0x{hi:08X}')
    print(f'  AutoRun    {out} ({out.stat().st_size} bytes, '
          f'{nset} mem set, {nprom} prom -- must be 0)')
    print(f'  firmware   Ver.5.02 only, SHA-256 {FIRMWARE_SHA256}')
    print()
    print('  HOW TO RUN -- read docs/cards/invert.md first')
    print('   1. Card root: AutoRun.txt ONLY.  Delete any old V*.BIN.')
    print('   2. Manual exposure, fixed ISO/aperture/focus, power saving OFF.')
    print(f'      Colour mode set to "{targets[0][2]}" BEFORE power on.')
    print('   3. Card in, power on, camera awake in live view. Wait ~20 s.')
    print(f'   4. At "TOGGLE OFF AND T+O": step through {names},')
    print('      and back, WATCHING THE IMAGE at each step.')
    print('      *** A NEGATIVE PICTURE IS THE PASS. ***')
    print('      Note which mode it happened in -- if only one responds, that')
    print('      asymmetry is the result.')
    print('   5. Wait for "INVERT DONE", then:')
    print(f'        python3 tools/check_invert.py <card> --curves {a.curves}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
