#!/usr/bin/env python3
"""Generate a look-curve card: 24 knots of a chosen transfer function.

*** THIS WRITES A CHROMA ARRAY.  IT WILL NOT PRODUCE A LOG PICTURE. ***

    camera/build_logcurve_card.py --out camera/cards/logcurve
    camera/build_logcurve_card.py --curve dvi --pre-gamma 2.1 --out DIR

Writes 24 knots into the DRAM source the firmware uploads to the ISP, at boot;
selecting the matching colour mode makes the firmware do the upload.  The
mechanism is proven on hardware (results/looksrc1/FINDINGS.md) -- but the array
it writes moves COLOUR, not contrast (results/logoff1/REFRAME.md).  The curve
arithmetic below is kept because it is correct and will be reused verbatim once
a reachable target is found; see docs/CURVE_TARGETS.md.

Address note: the values in RECORDS are record_start + 0x090, i.e. KNOTS B.
The record layout was corrected on 2026-09-22 -- docs/LOOK_CURVE.md,
tools/look_records.py.

  --curve      identity | gamma | dvi | log2
  --pre-gamma  what this stage's input has ALREADY been through. The look trim
               sits after the main gamma, so its input is gamma-encoded, not
               linear. 2.1 is the figure measured from the identity ramp
               in results/neutralize/, and composing its inverse gives a log of
               scene light rather than a log of an already-curved signal.
               1.0 means "treat the input as linear" -- only right if the main
               gamma has been neutralised some other way.

*** WRITES 48 BYTES OF DRAM. *** No registers, no prom, no fwup, no NAND.
Battery-out cold boot reverts. Firmware Ver.5.02 only.

The knots it writes are also saved as knots.txt beside the card, so what was
shot can always be matched to what was written.
"""
import argparse, pathlib, subprocess, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHELL = REPO / 'resources/fp_sup/fp_usb_shell/build_autorun.py'
TEMPLATE = HERE / 'look_src_write.S'
PROBE_AT = 0xC072DE64
NKNOT, FULL = 24, 0xF555          # 24 knots, identity ends at 0xF555

# knots B of four records, read out of the dump.  Their record starts are these
# addresses minus 0x090; their ids are 11, 16, 22, 2 and 17.
#   teal    id 11, the record confirmed on hardware
#   neutral *** DISPROVEN.  Do not use. ***  Chosen because these four hold an
#           identity knots-B array and mode Off renders with an identity look
#           curve, so Off was assumed to use one of them.  It does not: the card
#           was run (results/logoff1/) and Off still showed a pure identity ramp
#           in hardware.  These four records DO differ per mode -- but in their
#           `gains A` array, which this card does not write.
RECORDS = {'teal': [0xC0B3B2E8],
           'neutral': [0xC0B3B9C0, 0xC0B3BAE4, 0xC0B3BC08, 0xC0B3BD2C]}


def dvi(L):
    A, B, C, M, LC = 0.0075, 7.0, 0.07329248, 10.44426855, 0.00262409
    return np.where(L <= LC, L * M, (np.log2(np.maximum(L, 1e-9) + A) + B) * C)


def knots(curve, pre_gamma, gamma):
    x = np.arange(NKNOT) * (65536 / NKNOT) / 65535.0     # this stage's input
    lin = np.power(np.clip(x, 0, 1), pre_gamma)          # undo the preceding gamma
    if curve == 'identity':
        y = x
    elif curve == 'gamma':
        y = np.power(lin, gamma)
    elif curve == 'dvi':
        y = dvi(lin)
    elif curve == 'log2':
        y = np.log2(lin * 1023 + 1) / 10.0
    else:
        raise SystemExit(f'unknown curve {curve}')
    y = y - y.min()
    return np.clip(np.round(y / y.max() * FULL), 0, 0xFFFF).astype(int)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--curve', default='dvi', choices=['identity', 'gamma', 'dvi', 'log2'])
    ap.add_argument('--pre-gamma', type=float, default=2.1)
    ap.add_argument('--gamma', type=float, default=1 / 2.2)
    ap.add_argument('--record', default='neutral', choices=list(RECORDS),
                    help="'teal' = record id 11, the one confirmed on "
                         "hardware. 'neutral' = four records mode Off was "
                         "GUESSED to use and demonstrably does not -- kept only "
                         "so the disproven run stays reproducible.")
    a = ap.parse_args()

    k = knots(a.curve, a.pre_gamma, a.gamma)
    if np.any(np.diff(k) < 0):
        raise SystemExit('the curve is not monotonic after quantisation')
    addrs = RECORDS[a.record]

    src = TEMPLATE.read_text()
    words = [(int(k[i + 1]) << 16) | int(k[i]) for i in range(0, NKNOT, 2)]
    tbl = "\n".join(f"    .word   0x{w:08X}" for w in words)
    i, j = src.index('newknots:\n'), src.index('\ns_sel:')
    src = src[:i] + 'newknots:\n' + tbl + src[j:]

    # write every record in the set
    body = "\n".join(
        f"    ldr_addr r0, 0x{x:08X}\n    adr      r1, newknots\n"
        f"    mov      r2, #{len(words)}\n"
        f"{i+30}:  ldr      r3, [r1], #4\n    str      r3, [r0], #4\n"
        f"    subs     r2, r2, #1\n    bne      {i+30}b"
        for i, x in enumerate(addrs))
    old = src[src.index('    ldr_addr r0, SRC_TO'):src.index('\n\n    adr     r0, s_sel')]
    src = src.replace(old, body)
    gen = HERE / 'logcurve_gen.S'
    gen.write_text(src)

    a.out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(SHELL), '--no-shell',
                    '--boot-call', f'0x{PROBE_AT:08X}:{gen}',
                    '--banner', f'fpLog-{a.curve.upper()}!',
                    '--out', str(a.out / 'AutoRun.txt')], check=True)

    note = (f"curve      {a.curve}  pre-gamma {a.pre_gamma}"
            + (f"  gamma {a.gamma:.4f}" if a.curve == 'gamma' else "") + "\n"
            f"record     {a.record}: " + ", ".join(f"0x{x:08X}" for x in addrs)
            + f", {NKNOT} knots\n"
            f"knots      " + " ".join(f"{v:04X}" for v in k) + "\n")
    (a.out / 'knots.txt').write_text(note)
    print(note)
    print(f"wrote {a.out/'AutoRun.txt'} and knots.txt")
    print("\n  *** This writes a CHROMA array.  Expect a colour shift, not a")
    print("  flat picture.  See docs/CURVE_TARGETS.md before spending a shoot. ***")
    print("\n  Card in, power on, wait for SELECT T AND O, switch to Teal &")
    print("  Orange, shoot a step wedge.  Then recover the transfer function")
    print("  from the clip and compare against knots.txt.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
