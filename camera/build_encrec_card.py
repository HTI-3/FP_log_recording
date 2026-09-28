#!/usr/bin/env python3
"""Build the RECORDING-TIME encoder probe card: one AutoRun.txt, nothing else.

    camera/build_encrec_card.py --out camera/cards/encrec

The boot probe (build_probe_card.py) read the codec blocks gated.  This one
reads them in three rounds -- idle, inside a take, idle again -- and the diff
names the blocks the firmware only powers while recording.  Round B is held in
RAM and written after the take, so nothing touches the card while the camera
is writing the MOV.  docs/cards/encrec.md is the procedure.

Two checks, both against the files actually built rather than constants:
  - no AutoRun word lands in the probe's buffers (the enc_probe.S lesson);
  - the region table in enc_rec_probe.S fits SNAP_SZ, since round B holds
    every region in RAM at once and an overrun would run past the buffer.

Read-only apart from the files: no `mem set` from the payload, no prom, no
fwup, no NAND, no clock or power register.
"""
import argparse, pathlib, re, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
SHELL = REPO / 'resources' / 'fp_sup' / 'fp_usb_shell' / 'build_autorun.py'

PROBE_AT = 0xC072DE64        # CAVE_LOW -- build_autorun.py's own default
PROBE_SRC = HERE / 'enc_rec_probe.S'

# Ver.5.02 only.  Every address the probe uses was measured against this image.
FIRMWARE_SHA256 = 'c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8'


def _equ(src, name):
    """Read a .equ out of the assembly, so the two files cannot disagree."""
    m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+)', src.read_text(), re.M)
    if not m:
        raise SystemExit(f'{src.name} has no .equ {name}')
    return int(m.group(1), 16)


def regions(src=PROBE_SRC):
    """The region table, as (base, bytes, kind), in the order the probe reads
    it -- which is also file order.  tools/check_encrec.py imports this."""
    text = src.read_text()
    body = text[text.index('\nregions:'):]
    out = []
    for m in re.finditer(r'^\s*\.word\s+(0x[0-9A-Fa-f]+|0)\s*(?:,\s*(0x[0-9A-Fa-f]+)'
                         r'\s*,\s*([01]))?', body, re.M):
        if m.group(1) == '0':
            return out
        out.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3))))
    raise SystemExit(f'{src.name}: region table has no terminating .word 0')


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
    ap.add_argument('--out', type=pathlib.Path, required=True,
                    help='directory to write AutoRun.txt into')
    ap.add_argument('--banner', default='fpLog-ENCREC!')
    args = ap.parse_args()

    if not SHELL.exists():
        raise SystemExit(f'missing {SHELL} -- resources/fp_sup is not checked out')

    regs = regions()
    total = sum(n for _, n, _ in regs)
    snap_sz = _equ(PROBE_SRC, 'SNAP_SZ')
    for base, n, kind in regs:
        if n % 4 or (kind == 1 and n % 64):
            raise SystemExit(f'region 0x{base:08X}: {n} bytes is not a whole '
                             f'{"sweep block" if kind else "word"} count')
    if total > snap_sz:
        raise SystemExit(f'regions total 0x{total:X} bytes, SNAP holds 0x{snap_sz:X}: '
                         f'round B would overrun the buffer')
    if len(regs) > 100:
        raise SystemExit(f'{len(regs)} regions; file names carry two digits')

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

    lo, hi = _equ(PROBE_SRC, 'BUFS_LO'), _equ(PROBE_SRC, 'BUFS_HI')
    written = _cave_writes(out, size)
    clash = sorted(a for a in written if lo <= a < hi)
    if clash:
        raise SystemExit(
            f'{len(clash)} AutoRun words land in the probe buffers '
            f'0x{lo:08X}..0x{hi:08X}, first 0x{clash[0]:08X}. '
            f'Move FOBJ/PATHBUF/SHBUF/SNAP in enc_rec_probe.S.')
    if PROBE_AT + size > min(written, default=hi):
        raise SystemExit(f'probe is {size} bytes and reaches '
                         f'0x{PROBE_AT + size:08X}, into the loader at '
                         f'0x{min(written):08X}')
    print(f'checked    {len(written)} loader words, none inside '
          f'0x{lo:08X}..0x{hi:08X}')
    print(f'regions    {len(regs)}, 0x{total:X} of 0x{snap_sz:X} bytes of SNAP')
    print(f'probe      {size} bytes at 0x{PROBE_AT:08X}')
    print(f'AutoRun    {out} ({out.stat().st_size} bytes)')
    print(f'firmware   Ver.5.02 only, SHA-256 {FIRMWARE_SHA256}')
    print()
    print('Card root: AutoRun.txt only.  DELETE any old E*.BIN first.')
    print('Movie mode, FHD 24p, power saving OFF, live view awake.')
    print()
    print('  1. Power on.  Do nothing until the screen reads RECORD NOW')
    print('     (~25-30 s; round A is on the card).  Press record AT ONCE.')
    print('  2. ~15 s into the take the screen reads STOP RECORDING NOW.')
    print('     Stop straight away.  Round B is already in RAM by then.')
    print('  3. Wait for ENC PROBE DONE, about 20 s after the stop prompt.')
    print(f'  Expect {3 * len(regs)} files, EA00..EC{len(regs) - 1:02d}.BIN, and one MOV.')
    print()
    print('    python3 tools/check_encrec.py /Volumes/<card>')


if __name__ == '__main__':
    main()
