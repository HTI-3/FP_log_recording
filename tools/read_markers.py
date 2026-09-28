#!/usr/bin/env python3
"""Read the timing probe's markers: how far it got, and the curve over time."""
import pathlib, struct, sys
T = [0, 1, 3, 8, 15, 30]
BANK, ST, NC = 0xC0971F34, 0x1000, 89
card = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
seen = []
for i, t in enumerate(T):
    p = card / f'MK{i}.BIN'
    if not p.exists():
        print(f'  MK{i}.BIN  T+{t:2d}s   MISSING'); continue
    seen.append(i)
    b = p.read_bytes()
    w = struct.unpack(f'<{len(b)//4}I', b)
    cur = [f'#{(v-BANK)//ST}' for v in w if BANK <= v < BANK+NC*ST and (v-BANK) % ST == 0]
    idx = [v for v in w if v < NC]
    print(f'  MK{i}.BIN  T+{t:2d}s   {len(b)} bytes   curve ptr: '
          f'{", ".join(cur) if cur else "none"}')
print()
if not seen:
    print('NOTHING. The payload never ran -- this is not a timing problem.')
elif seen == [0]:
    print('Only MK0. Any delay kills the boot-call context: the borrowed echo')
    print('handler does not survive tk_dly_tsk. A resident pool thread is then')
    print('the only route (XT_CREATE 0xC036E108 -- see the fp-usb-shell skill).')
elif len(seen) == len(T):
    print('All six. Delays are fine, so the ISP probe failed for another reason --')
    print('most likely the 16 KiB windows or the streaming write. Retry it with')
    print('4 KiB windows first.')
else:
    print(f'Survived to T+{T[seen[-1]]}s but not T+{T[seen[-1]+1]}s.')
    print('Keep every later dump inside that budget.')
