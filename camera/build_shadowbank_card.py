#!/usr/bin/env python3
"""Build the shadow-bank card: the whole ISP shadow bank 0x30210000..0x30214000,
idle and -- on a recording run -- inside a MOV take.  One AutoRun.txt.

    camera/build_shadowbank_card.py --out camera/cards/shadowbank

Serves docs/TEN_BIT_PLAN.md gate 1 after results/yuvpack_1/: YUV_PACK does not
set the encoder input's bytes per sample, so find the stage that writes the
frame to DRAM.  One card, two runs -- live (never press record) and recording.
docs/cards/shadowbank.md says how to run and read it; tools/check_shadowbank.py
reads the card.

Read-only apart from the files: no `mem set`, no prom, no fwup, no NAND.
"""
import argparse, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_yuvpack_card import build, FIRMWARE_SHA256     # noqa: E402

PROBE_SRC = HERE / 'shadowbank_probe.S'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True,
                    help='directory to write AutoRun.txt into')
    ap.add_argument('--banner', default='fpLog-SHADOW!')
    args = ap.parse_args()
    build(PROBE_SRC, args.out, args.banner)
    print(f'firmware   Ver.5.02 only, SHA-256 {FIRMWARE_SHA256}')
    print()
    print('Card root: AutoRun.txt only.  DELETE any old S*.BIN (and Y*.BIN) first.')
    print('Camera: MOV mode, FHD 24p ALL-I, power saving OFF, live view.')
    print('Copy the S*.BIN files off the card between the two runs.')
    print()
    print('LIVE RUN -- never press record:')
    print('  power on, stay in live view, ignore the REC RUN prompts,')
    print('  power off at SHADOW DONE (~60 s).')
    print()
    print('RECORDING RUN -- same card, S*.BIN deleted:')
    print('  1. power on, stay in live view.')
    print('  2. ~25 s: REC RUN RECORD NOW  -> press record at once.')
    print('  3. ~15 s later: REC RUN STOP NOW  -> stop the take.')
    print('  4. ~20 s later: SHADOW DONE  -> power off.')
    print()
    print('    python3 tools/check_shadowbank.py <recording run> --live <live run>')


if __name__ == '__main__':
    main()
