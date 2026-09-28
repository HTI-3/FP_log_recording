#!/usr/bin/env python3
"""Is the curve write actually reaching DRAM, or only the CPU's cache?

*** RUN, AND CLOSED.  All three address views identical -- DRAM really held
*** the write, so cache coherency was not the explanation.  results/cachetest_!/

    camera/build_cachetest_card.py --out camera/cachetest

THE PROBLEM THIS TESTS
  The write landed: three readbacks of curve #16 matched the intended table
  exactly (results/curve_1_res/). The picture did not change.

  One explanation fits that exactly. `mem set` writes through the CPU's data
  cache, and `mem save` reads back through the same cache -- so a readback can
  confirm a write that never reached DRAM at all. If the ISP fetches the curve
  by DMA, it reads DRAM directly and would see the ORIGINAL bytes. Write
  verified, picture unchanged, both true at once.

  fp_sup's own loader flushes the cache after placing code (F_CACHE 0xC000E91C,
  F_ICACHE 0xC000EABC), which is the same hazard from the other side.

HOW IT TESTS IT
  DRAM is aliased at more than one address with different cache attributes.
  fp_sup's worker uses UNCACHED = +0x40000000 to get "the uncached view of the
  frame", and TO_BUS = +0xC0000000 (== -0x40000000) to turn that into a bus
  address for DMA. So for a table at 0xC0981F34 the other views are
  0x40981F34 and 0x00981F34.

  This card writes the same flattened block, then saves the SAME 4 KiB table
  through all three views IN ONE BOOT. Comparing across boots would be
  confounded; comparing within one boot is not.

    CACHED.BIN  0xC0981F34   what the CPU sees
    UNCACH.BIN  0x40981F34   the uncached alias
    BUSVIEW.BIN 0x00981F34   the bus/physical view

  CACHED shows the plateau and the others do not  -> cache coherency. The fix
    is a cache clean after writing, and fpLog needs a payload to call it.
  All three show the plateau                      -> DRAM really is updated and
    this bank is not what the video path renders from. Different problem.

READ-ONLY except for the same 200-word write the previous card made. No prom,
no fwup, no NAND. Battery-out cold boot reverts. Ver.5.02 only.

  The two alias reads are the only untested thing here. They are reads, which
  this project has done across a 3 MB sweep without incident, but if the camera
  stops, the file that is missing says which view did it.
"""
import argparse, pathlib, sys
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent.parent
CURVES = HERE / 'results/dram_21_09_2026/curves/all_curves.npy'
BANK, STRIDE, N = 0xC0971F34, 0x1000, 2048


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, required=True)
    ap.add_argument('--curve', type=int, default=16)
    ap.add_argument('--from', dest='lo', type=int, default=800)
    ap.add_argument('--to', dest='hi', type=int, default=1200)
    a = ap.parse_args()

    base = BANK + a.curve * STRIDE
    val = int(np.load(CURVES)[a.curve][a.lo])
    word = (val << 16) | val
    nwords = (a.hi - a.lo) // 2
    # Named by address prefix, not by a guess at which alias is which. The
    # alias map is INFERRED from fp_sup's UNCACHED/TO_BUS constants, so the
    # filenames must not assert it -- the comparison is what tells us.
    views = [('VC', base),                                   # 0xC... cached CPU view
             ('V4', (base + 0x80000000) & 0xFFFFFFFF),       # 0x4... likely uncached
             ('V0', (base + 0x40000000) & 0xFFFFFFFF)]       # 0x0... likely bus

    L = []
    W = L.append
    W('# ' + '=' * 72)
    W('# fpLog -- CACHE COHERENCY TEST.  *** WRITES TO MEMORY ***')
    W('#')
    W(f'# Writes the same flattened block into curve #{a.curve} (0x{base:08X}),')
    W('# then reads the SAME table back through three address views in ONE boot.')
    W('#')
    for n, addr in views:
        W(f'#   {n + ".BIN":12s} 0x{addr:08X}')
    W('#')
    W('# VC differs from V4/V0 -> the write is stuck in the CPU cache')
    W('#   and DRAM still holds the original. That is why the picture did not')
    W('#   change, and the fix is a cache clean.')
    W('# All three identical -> DRAM is updated and this bank is not what the')
    W('#   video path renders from.')
    W('#')
    W('# SAFETY: RAM only. No prom, no fwup, no NAND. Delete AutoRun.txt, take')
    W('# the BATTERY OUT, power on to revert. Ver.5.02 only.')
    W('# If the camera stops, the missing file names the view that did it.')
    W('# ' + '=' * 72)
    W('')
    W('display monitor 0 1')
    W('display osd 1 0xFFFFFFFF')
    W('display text CACHE[...]000')
    W('display osd 1')
    W('')
    W(f'# the same write as the previous card: entries {a.lo}..{a.hi - 1} -> {val}')
    for i in range(nwords):
        W(f'mem set 0x{base + a.lo * 2 + i * 4:08X} 0x{word:08X}')
    W('display text CACHE[#..]033')
    W('display osd 1')
    W('')
    for i, (n, addr) in enumerate(views):
        W(f'# read the table through the {n} view')
        W(f'mem save \\{n}.BIN 0x{addr:08X},,0x{N * 2:X}')
        W(f'display text CACHE[{"#" * (i + 1)}{"." * (2 - i)}]'
          f'{int(100 * (i + 1) / 3):03d}')
        W('display osd 1')
        W('')
    W('display text CACHE DONE')
    W('display osd 1')

    a.out.mkdir(parents=True, exist_ok=True)
    dest = a.out / 'AutoRun.txt'
    dest.write_text('\n'.join(L) + '\n')
    print(f'wrote {dest}')
    for n, addr in views:
        print(f'  {n + ".BIN":12s} 0x{addr:08X}')
    print(f'  {sum(1 for l in L if l.startswith("mem set"))} mem set, '
          f'{sum(1 for l in L if l.startswith("mem save"))} mem save, '
          f'{sum(1 for l in L if l.startswith("prom"))} prom (must be 0)')
    print('\n  then: python3 tools/compare_views.py <card>')
    return 0


if __name__ == '__main__':
    sys.exit(main())
