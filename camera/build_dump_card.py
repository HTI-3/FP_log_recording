#!/usr/bin/env python3
"""Build a READ-ONLY AutoRun.txt that copies DRAM onto the SD card.

    camera/build_dump_card.py --out camera/dump_card

This is PLAN.md §9 step 3 -- the gate on everything. The update file is packed
(docs/FIRMWARE_BASE.md), so nothing byte-level can see the firmware until the
boot loader has decompressed it into DRAM. This copies that out.

READ-ONLY. Every line the generated file contains is `mem save`, `display`, or
a comment. There is no `mem set`, no `prom`, no `fwup`, no NAND write, and no
payload. Delete AutoRun.txt, power-cycle, and the camera is exactly as it was.
Running it against a firmware other than Ver.5.02 cannot damage anything -- it
only ever reads -- it just would not be a meaningful image.

WHY IT GOES PAST 0xC2F30800
  fp_sup establishes that the boot loader decompresses NAND into
  0xC0000000..0xC2F30800, and a dump of exactly that range is the right thing
  for disassembly. But 39 of the addresses in ADDRESSES.md sit ABOVE it, up to
  0xC38D2DE8 -- live state, heap, and the object pools. If the ACTIVE tone
  curve is a RAM copy rather than the ROM default, that is where it lives, and
  a dump stopping at 0xC2F30800 would miss it entirely. Hence the default end
  of 0xC4000000.

  Order matters: the firmware image is written FIRST, in whole. If the camera
  stops somewhere in the speculative region above it, the part that matters is
  already on the card.
"""
import argparse, pathlib, sys

FIRMWARE_END = 0xC2F30800      # fp_sup: end of the decompressed image
PRESETS = {
    'all':      (0xC0000000, 0xC4000000),   # image + live state + margin
    'firmware': (0xC0000000, FIRMWARE_END),  # the classic image-only dump
    'live':     (FIRMWARE_END, 0xC4000000),  # only what sits above the image
}
BAR = 19


def bar(frac):
    n = 8
    f = int(round(frac * n))
    return f'FPLOG[{"#" * f}{"." * (n - f)}]{int(round(frac * 100)):03d}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--preset', choices=PRESETS, default='all')
    ap.add_argument('--start', type=lambda s: int(s, 0))
    ap.add_argument('--end', type=lambda s: int(s, 0))
    ap.add_argument('--chunk', type=lambda s: int(s, 0), default=0x400000)
    a = ap.parse_args()

    start, end = PRESETS[a.preset]
    if a.start is not None:
        start = a.start
    if a.end is not None:
        end = a.end
    if end <= start:
        ap.error('end must be above start')
    if start % 4 or a.chunk % 4:
        ap.error('start and chunk must be word-aligned')

    chunks = []
    p = start
    while p < end:
        n = min(a.chunk, end - p)
        chunks.append((p, n))
        p += n
    if len(chunks) > 100:
        ap.error(f'{len(chunks)} chunks -- raise --chunk')

    total = end - start
    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / 'AutoRun.txt'

    L = []
    W = L.append
    W('# ' + '=' * 74)
    W('# fpLog -- DRAM dump.  READ-ONLY.')
    W('#')
    W('# Copies the firmware image the camera\'s own boot loader already')
    W('# decompressed from NAND, plus the live state above it, onto the card --')
    W('# one file per chunk.  Nothing is written to NAND, EEPROM or any other')
    W('# non-volatile store: every line below is `mem save`, `display`, or a')
    W('# comment.  Remove this file, power-cycle, and the camera is stock.')
    W('#')
    W(f'# range  0x{start:08X}..0x{end:08X}  ({total:,} bytes, {len(chunks)} files)')
    W(f'# files  FPLD00.BIN .. FPLD{len(chunks) - 1:02d}.BIN, 0x{a.chunk:X} bytes each')
    W('#')
    W('# Firmware Ver.5.02 only: these addresses are that build\'s.  Reading them')
    W('# on another version cannot damage anything, it just would not be a')
    W('# meaningful image.')
    W('#')
    W('# THE CARD MUST HAVE THE OLD FPLD*.BIN DELETED FIRST.  `mem save` may fail')
    W('# rather than overwrite a file that is already there, and a stale chunk is')
    W('# worse than a missing one -- it reassembles silently into a wrong image.')
    W('#')
    W(f'# Needs {total / 1e6:.0f} MB free on the card.')
    W('#')
    W('# The screen reads FPLOG[........]000 and climbs.  A bar that stops means')
    W('# the dump stopped there; the files already written are good.  The')
    W(f'# firmware image (to 0x{FIRMWARE_END:08X}) is written FIRST, so a stop in the')
    W('# speculative region above it still leaves the part that matters.')
    W('# ' + '=' * 74)
    W('')
    W('display monitor 0 1')
    W('display osd 1 0xFFFFFFFF')
    W(f'display text {bar(0)}')
    W('display osd 1')
    W('')

    for i, (addr, n) in enumerate(chunks):
        done = (addr + n - start) / total
        note = ''
        if addr < FIRMWARE_END <= addr + n:
            note = '   <-- the decompressed firmware image ends inside this chunk'
        elif addr >= FIRMWARE_END:
            note = '   (live state / heap, above the image)'
        W(f'# chunk {i + 1}/{len(chunks)}: 0x{addr:08X}..0x{addr + n:08X} '
          f'({n:,} bytes){note}')
        W(f'mem save \\FPLD{i:02d}.BIN 0x{addr:08X},,0x{n:X}')
        W(f'display text {bar(done)}')
        W('display osd 1')
        W('')

    W('display text FPLOG DONE')
    W('display osd 1')
    dest.write_text('\n'.join(L) + '\n')

    man = a.out / 'MANIFEST.txt'
    M = [f'fpLog DRAM dump -- read-only, firmware Ver.5.02',
         f'range 0x{start:08X}..0x{end:08X}  {total:,} bytes  {len(chunks)} files',
         f'decompressed firmware image ends at 0x{FIRMWARE_END:08X}',
         '', f'{"file":14s}{"start":>12s}{"end":>12s}{"bytes":>12s}']
    for i, (addr, n) in enumerate(chunks):
        M.append(f'FPLD{i:02d}.BIN  {addr:#012x}{addr + n:#12x}{n:12,d}')
    M += ['', 'reassemble: python3 tools/reassemble_dump.py <card> -o dram_C0000000.bin',
          'load address for a disassembler: 0x%08X' % start]
    (a.out / 'MANIFEST.txt').write_text('\n'.join(M) + '\n')

    print(f'wrote  {dest}  ({len(L)} lines)')
    print(f'       {man}')
    print(f'range  0x{start:08X}..0x{end:08X}  {total:,} bytes in {len(chunks)} chunks')
    print(f'card   needs {total / 1e6:.0f} MB free, and NO existing FPLD*.BIN')
    print(f'check  {sum(1 for l in L if l.startswith("mem save"))} mem save, '
          f'{sum(1 for l in L if l.startswith("mem set"))} mem set '
          f'(must be 0), {sum(1 for l in L if l.startswith("prom"))} prom (must be 0)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
