#!/usr/bin/env python3
"""Did the selector redirect stick?"""
import pathlib, sys
import numpy as np
BANK, ST = 0xC0971F34, 0x1000
c = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
p = c / 'SEL.BIN'
if not p.exists():
    sys.exit('no SEL.BIN -- the card did not finish')
w = np.frombuffer(p.read_bytes(), dtype='<u4')
base = 0xC3414000
for off, what in ((0x510, 'pointer A'), (0xD48, 'index'), (0xD4C, 'pointer B'),
                  (0xD84, 'pointer C')):
    v = int(w[off // 4])
    if what == 'index':
        print(f"0x{base+off:08X}  {what:10s} {v:>10}  (16 = redirected, 82 = restored)")
    else:
        n = (v - BANK) // ST if BANK <= v < BANK + 89 * ST else None
        print(f"0x{base+off:08X}  {what:10s} 0x{v:08X}  "
              f"{'curve #%d' % n if n is not None else 'not a curve pointer'}")
ptrs = [int(w[o // 4]) for o in (0x510, 0xD4C, 0xD84)]
if all(p_ == BANK + 16 * ST for p_ in ptrs):
    print("\nAll three still point at curve #16 -- the redirect held.")
    print("So whether the picture moved is a clean answer about the bank.")
elif all(p_ == BANK + 82 * ST for p_ in ptrs):
    print("\nBack at curve #82 -- the firmware restored them within 20 s.")
    print("A one-shot write cannot hold here; the result is inconclusive.")
else:
    print("\nMixed -- read the rows above.")
