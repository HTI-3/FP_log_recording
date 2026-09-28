#!/usr/bin/env python3
"""Build the timing-probe card: write markers to prove the payload runs.

    camera/build_ispprobe_card.py --out camera/ispprobe

The probe sleeps, then reads the ISP register banks while the camera is
RUNNING, and writes them to the card.  No USB shell required.

It runs by borrowing the echo shell handler, which executes in the dispatcher's
task -- the one context fp_sup says may block and do file I/O.  So it can just
`tk_dly_tsk` and then dump.

  T+20s  round 1 -> L10..L15.BIN
  T+50s  round 2 -> L20..L25.BIN

CHANGE THE COLOUR MODE BETWEEN THE TWO ROUNDS.  The diff is the result.

Read-only apart from the files: no `mem set`, no prom, no fwup, no NAND.
"""
import argparse, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHELL = REPO / 'resources' / 'fp_sup' / 'fp_usb_shell' / 'build_autorun.py'

PROBE_AT = 0xC072DE64        # CAVE_LOW -- build_autorun.py's own default
PROBE_SRC = HERE / 'timing_probe.S'

# Ver.5.02 only.  Every address the probe uses was measured against this image.
FIRMWARE_SHA256 = 'c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8'


def _equ(src, name):
    """Read a .equ out of the assembly, so the two files cannot disagree."""
    m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+)', src.read_text(), re.M)
    if not m:
        raise SystemExit(f'{src.name} has no .equ {name}')
    return int(m.group(1), 16)


def _cave_writes(autorun, probe_size):
    """Every cave address the generated AutoRun pokes, the probe's own excluded.

    The exclusion is the probe's measured extent, not a round number: an
    over-wide window here would hide exactly the overlap this is looking for,
    which is what a first pass with a flat 0x1000 did.
    """
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
    ap.add_argument('--out', type=pathlib.Path, required=True,
                    help='directory to write AutoRun.txt into')
    ap.add_argument('--banner', default='fpLog-ENCPROBE!')
    args = ap.parse_args()

    if not SHELL.exists():
        raise SystemExit(f'missing {SHELL} -- resources/fp_sup is not checked out')

    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / 'AutoRun.txt'

    sys.path.insert(0, str(SHELL.parent))
    from armasm import assemble
    size = len(assemble(PROBE_SRC))

    cmd = [sys.executable, str(SHELL),
           '--no-shell',
           '--boot-call', f'0x{PROBE_AT:08X}:{PROBE_SRC}',
           '--banner', args.banner,
           '--out', str(out)]
    subprocess.run(cmd, check=True)

    # The buffers are declared in timing_probe.S; the loader's extent is decided by
    # build_autorun.py and moves when it changes.  The first build of this card
    # put the file object inside the loader that calls the probe, and nothing
    # said so -- so the check is mechanical, against the file just written,
    # rather than a constant somebody has to remember to update.
    lo, hi = _equ(PROBE_SRC, 'BUFS_LO'), _equ(PROBE_SRC, 'BUFS_HI')
    written = _cave_writes(out, size)
    clash = sorted(a for a in written if lo <= a < hi)
    if clash:
        raise SystemExit(
            f'{len(clash)} AutoRun words land in the probe buffers '
            f'0x{lo:08X}..0x{hi:08X}, first 0x{clash[0]:08X}. '
            f'Move FOBJ/STAGING/PATHBUF in timing_probe.S.')
    if PROBE_AT + size > min(written, default=hi):
        raise SystemExit(f'probe is {size} bytes and reaches '
                         f'0x{PROBE_AT + size:08X}, into the loader at '
                         f'0x{min(written):08X}')
    print(f'checked    {len(written)} loader words, none inside '
          f'0x{lo:08X}..0x{hi:08X}')

    print(f'probe      {size} bytes at 0x{PROBE_AT:08X}')
    print(f'AutoRun    {out} ({out.stat().st_size} bytes)')
    print(f'firmware   Ver.5.02 only, SHA-256 {FIRMWARE_SHA256}')
    print()
    print('Card root: AutoRun.txt only.  DELETE any old MK*.BIN first.')
    print()
    print('  Card in, power on, leave the camera awake in live view.')
    print('  Markers land at T+0, 1s, 3s, 8s, 15s, 30s.  Change the colour mode')
    print('  partway if you like -- each marker records the curve selected then.')
    print()
    print('  Which files exist IS the result:')
    print('    no MK0     the payload never ran -- not a timing problem')
    print('    MK0 only   any delay kills the boot-call context')
    print('    MK0..MK3   survives ~8s but not 15')
    print('    all six    delays are fine; the ISP probe failed another way')
    print()
    print('    python3 tools/read_markers.py <card>')


if __name__ == '__main__':
    main()
