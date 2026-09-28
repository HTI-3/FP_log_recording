#!/usr/bin/env python3
"""Build the YUV_PACK card: read the packer's configuration idle, inside a MOV
take, and after.  One AutoRun.txt, nothing else.

    camera/build_yuvpack_card.py --out camera/cards/yuvpack

Serves docs/TEN_BIT_PLAN.md gate 1: can YUV_PACK hand the encoder more than
8 bits?  docs/cards/yuvpack.md says how to run it and read it;
tools/check_yuvpack.py reads the card.

Read-only apart from the files: no `mem set`, no prom, no fwup, no NAND.
"""
import argparse, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_ispprobe_card import (SHELL, PROBE_AT, FIRMWARE_SHA256,   # noqa: E402
                                 _equ, _cave_writes)

PROBE_SRC = HERE / 'yuvpack_probe.S'


def build(probe_src, out_dir, banner):
    """Assemble `probe_src` into out_dir/AutoRun.txt as a --boot-call, and check
    the loader leaves the probe's buffers and code alone.  Returns the path."""
    if not SHELL.exists():
        raise SystemExit(f'missing {SHELL} -- resources/fp_sup is not checked out')

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / 'AutoRun.txt'

    sys.path.insert(0, str(SHELL.parent))
    from armasm import assemble
    size = len(assemble(probe_src))

    subprocess.run([sys.executable, str(SHELL),
                    '--no-shell',
                    '--boot-call', f'0x{PROBE_AT:08X}:{probe_src}',
                    '--banner', banner,
                    '--out', str(out)], check=True)

    lo, hi = _equ(probe_src, 'BUFS_LO'), _equ(probe_src, 'BUFS_HI')
    written = _cave_writes(out, size)
    clash = sorted(a for a in written if lo <= a < hi)
    if clash:
        raise SystemExit(f'{len(clash)} AutoRun words land in the probe buffers '
                         f'0x{lo:08X}..0x{hi:08X}, first 0x{clash[0]:08X}.')
    if PROBE_AT + size > min(written, default=hi):
        raise SystemExit(f'probe is {size} bytes and reaches 0x{PROBE_AT + size:08X}, '
                         f'into the loader at 0x{min(written):08X}')
    print(f'checked    {len(written)} loader words, none inside 0x{lo:08X}..0x{hi:08X}')
    print(f'probe      {size} bytes at 0x{PROBE_AT:08X}')
    print(f'AutoRun    {out} ({out.stat().st_size} bytes)')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True,
                    help='directory to write AutoRun.txt into')
    ap.add_argument('--banner', default='fpLog-YUVPACK!')
    args = ap.parse_args()
    build(PROBE_SRC, args.out, args.banner)
    print(f'firmware   Ver.5.02 only, SHA-256 {FIRMWARE_SHA256}')
    print()
    print('Card root: AutoRun.txt only.  DELETE any old Y*.BIN first.')
    print('Camera: MOV mode, FHD 24p ALL-I, power saving OFF, live view.')
    print()
    print('  1. Card in, power on.  Stay in live view.  Do NOT press record yet.')
    print('  2. ~25 s: RECORD NOW  -> press record at once.')
    print('  3. ~15 s later: STOP RECORDING NOW  -> stop the take.')
    print('  4. ~20 s later: YUVPACK DONE  -> power off.')
    print()
    print('    python3 tools/check_yuvpack.py /Volumes/<card>')


if __name__ == '__main__':
    main()
