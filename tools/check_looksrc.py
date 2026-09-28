#!/usr/bin/env python3
"""Did changing the DRAM knot source reach the ISP registers?"""
import pathlib, sys
import numpy as np
c = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '.')
WANT = [0x0000,0x3629,0x4777,0x540D,0x5E4D,0x671A,0x6EE7,0x75F5,
        0x7C6E,0x826E,0x880C,0x8D55,0x9256,0x9719,0x9BA5,0xA000]
TO   = [0x0800,0x12AB,0x1D55,0x2800,0x32AB,0x3955,0x4200,0x4BAB,
        0x5655,0x5E00,0x64AB,0x6F55,0x7800,0x82AB,0x8D55,0x9800]
IDENT= [0x0000,0x0AAB,0x1555,0x2000,0x2AAB,0x3555,0x4000,0x4AAB,
        0x5555,0x6000,0x6AAB,0x7555,0x8000,0x8AAB,0x9555,0xA000]
def show(name, v):
    print(f"{name:26s} " + " ".join(f"{int(x):04X}" for x in v))
src = c/'SRC.BIN'; hw = c/'HW.BIN'
if not src.exists() or not hw.exists():
    sys.exit(f'missing {"SRC.BIN" if not src.exists() else "HW.BIN"}')
s = np.frombuffer(src.read_bytes(), dtype='<u2')[:16]
h = np.frombuffer(hw.read_bytes(),  dtype='<u4')[0x20//4:0x60//4]
show('DRAM source 0xC0B3B2E8', s)
show('ISP regs   0x30212020', h)
show('(what we wrote)', WANT)
print()
src_ok = list(s) == WANT
if not src_ok:
    print('The DRAM write did not stick. Nothing else here means anything.')
    sys.exit(1)
print('DRAM source holds our curve.')
if list(h) == WANT:
    print('\n*** AND THE ISP REGISTERS DO TOO. The firmware uploaded our curve. ***')
    print('    If the picture changed, fpLog has its mechanism: overwrite the')
    print('    look-curve source and let the firmware move it.')
    print('    If the picture did NOT change, this block is not on the render')
    print('    path -- but the upload route is proven and worth reusing.')
elif list(h) == TO:
    print('\nISP still holds the stock Teal & Orange knots: the upload did not')
    print('happen, or it came from somewhere other than 0xC0B3B2E8.')
    print('Was Teal & Orange actually selected AFTER the card ran?')
elif list(h) == IDENT:
    print('\nISP holds the identity ramp -- the camera was still in mode Off.')
    print('Re-run and make sure Teal & Orange is selected before the 25 s is up.')
else:
    print('\nISP holds something else again -- print it and compare by hand.')
