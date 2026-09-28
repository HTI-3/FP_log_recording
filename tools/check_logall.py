#!/usr/bin/env python3
"""Did the write land, and did the mode you left it on pick it up?"""
import pathlib, sys
import numpy as np
K=[0x0000,0x066B,0x19DB,0x30D4,0x4669,0x5995,0x6A72,0x7957,
   0x869B,0x9287,0x9D56,0xA735,0xB049,0xB8AE,0xC07C,0xC7C7,
   0xCE9E,0xD50F,0xDB24,0xE0E8,0xE662,0xEB99,0xF093,0xF555]
IDENT=[round(i*65536/24) for i in range(24)]
c=pathlib.Path(sys.argv[1] if len(sys.argv)>1 else '.')
r=c/'REC0.BIN'; h=c/'HW.BIN'
if r.exists():
    v=list(np.frombuffer(r.read_bytes(),dtype='<u2')[:24])
    print("DRAM record  ", " ".join(f"{int(x):04X}" for x in v[:12]), "...")
    print("  write landed:", v==K)
else:
    print("REC0.BIN missing")
if h.exists():
    w=list(np.frombuffer(h.read_bytes(),dtype='<u4')[0x20//4:0x60//4])
    print("ISP knots    ", " ".join(f"{int(x):04X}" for x in w[:12]), "...")
    if w==K[:16]:
        print("\n  *** the mode you left it on IS rendering the log curve ***")
    elif w==IDENT[:16]:
        print("\n  identity -- that mode does not load a record, or bypasses the stage")
    else:
        print("\n  something else -- that mode loaded a record we did not write,")
        print("  or the curve went through a transform on the way")
