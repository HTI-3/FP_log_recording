import struct
def parse(path):
    d=open(path,'rb').read()
    magic,count,entry,total=struct.unpack_from("<4sIII",d,0)
    secs=[];off=16
    for _ in range(count):
        dest,length=struct.unpack_from("<II",d,off);off+=8;secs.append((dest,length))
    pos=off;out={}
    for dest,length in secs:
        out[dest]=d[pos:pos+length];pos+=(length+3)&~3
    return out
a=parse("/Users/andreasfink/Documents/PRIVATE/projects/fp_log/resources/fp_sup/releases/fpsup-og2k-v0.1.1a/fpSup.BIN")
b=parse("/Users/andreasfink/Documents/PRIVATE/projects/fp_log/resources/fp_sup/opengate/VSHL.BIN")

print("=== 0xC0F8E7EC (92 bytes) -- ROM data patch, word by word")
wa=struct.unpack("<23I",a[0xC0F8E7EC]); wb=struct.unpack("<23I",b[0xC0F8E7EC])
for i,(x,y) in enumerate(zip(wa,wb)):
    mark="  <-- DIFFERS" if x!=y else ""
    print(f"  +0x{i*4:02X}  OG2K 0x{x:08X} {x:>10d}   OG3K 0x{y:08X} {y:>10d}{mark}")

names={3024:"OG3K W",2010:"OG3K H",3008:"OG3K crop W",2000:"OG3K crop H",
       2016:"OG2K W",1344:"OG2K H",2008:"?",1338:"?",
       1936:"FHD stored W",1090:"FHD stored H",3032:"FHD readout W",1708:"FHD readout H",
       3856:"UHD stored W",2170:"UHD stored H",6064:"sensor W",4042:"sensor H",3412:"UHD readout H"}
print("\n=== geometry constants found in payload blocks (16-bit and 32-bit LE)")
for label,s in (("OG2K",a),("OG3K",b)):
    print(f"--- {label}")
    for addr in sorted(s):
        c=s[addr]
        if len(c)<8: continue
        hits=[]
        for v,n in names.items():
            for width,packer in ((2,"<H"),(4,"<I")):
                t=struct.pack(packer,v)
                off=c.find(t)
                while off!=-1:
                    if off%2==0: hits.append(f"{v}({n})@+0x{off:X}/{width*8}b")
                    off=c.find(t,off+1)
        if hits: print(f"  0x{addr:08X} len={len(c):5d}: "+", ".join(sorted(set(hits))))
