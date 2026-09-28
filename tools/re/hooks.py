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
def br(word,addr):
    top=word>>24
    if top not in (0xEA,0xEB): return None
    o=word&0xFFFFFF
    if o&0x800000: o-=0x1000000
    return ("BL" if top==0xEB else "B"), (addr+8+(o<<2))&0xFFFFFFFF

for name,p in [("OG2K","/Users/andreasfink/Documents/PRIVATE/projects/fp_log/resources/fp_sup/releases/fpsup-og2k-v0.1.1a/fpSup.BIN"),
               ("OG3K","/Users/andreasfink/Documents/PRIVATE/projects/fp_log/resources/fp_sup/opengate/VSHL.BIN")]:
    s=parse(p); blocks=sorted(k for k in s if len(s[k])>4)
    def owner(t):
        c=[b for b in blocks if b<=t<b+len(s[b])]
        return f"payload block 0x{c[0]:08X}+0x{t-c[0]:X}" if c else "OUTSIDE payload"
    print(f"=== {name} ROM hook sites -> target")
    for k in sorted(s):
        if k<0xC0700000 and len(s[k])==4:
            w=struct.unpack("<I",s[k])[0]; r=br(w,k)
            if r: print(f"  0x{k:08X}  {r[0]:2s} -> 0x{r[1]:08X}   {owner(r[1])}")
            else: print(f"  0x{k:08X}  word 0x{w:08X}  (not an ARM branch -- prologue/Thumb)")
    print()
