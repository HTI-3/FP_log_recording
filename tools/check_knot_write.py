#!/usr/bin/env python3
"""Did the ISP knot write land, and did the firmware put its values back?"""
import pathlib, sys
import numpy as np
c = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
WANT = [0x0000,0x3629,0x4777,0x540D,0x5E4D,0x671A,0x6EE7,0x75F5,
        0x7C6E,0x826E,0x880C,0x8D55,0x9256,0x9719,0x9BA5,0xA000]
def knots(f):
    p = c / f
    if not p.exists(): return None
    w = np.frombuffer(p.read_bytes(), dtype='<u4')
    return w[0x20//4:0x60//4]
b, a, m = knots('KB.BIN'), knots('KA.BIN'), knots('KM.BIN')
for n, k in (('KB (before)', b), ('KA (after)', a), ('KM (mirror +0x4000)', m)):
    if k is None: print(f'{n:22s} MISSING'); continue
    print(f'{n:22s} ' + ' '.join(f'{int(x):04X}' for x in k))
print()
if a is None:
    print('No after-image: the write or the second dump did not complete.'); sys.exit(1)
if np.array_equal(a, np.array(WANT, dtype='<u4')):
    print('The write LANDED and survived 25 s -- the firmware did not put its')
    print('values back. So if the picture changed, this register is live; if it')
    print('did not, these registers are not on the render path.')
elif b is not None and np.array_equal(a, b):
    print('Unchanged: the write did not take, or was reverted immediately.')
else:
    print('Partially changed -- read the rows above.')
if m is not None and a is not None:
    print(f'\nMirror at +0x4000 {"MATCHES" if np.array_equal(a, m) else "DIFFERS"}'
          f' -- {"one aliased bank" if np.array_equal(a, m) else "separate banks; write all four"}')
