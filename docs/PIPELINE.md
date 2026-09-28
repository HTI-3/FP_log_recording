# Recording pipeline — Phase 1, partial

**Target: FHD 24p CinemaDNG.** Host-side static analysis only; **no camera was
involved.** Everything below is reproducible from `resources/` and from
the published OpenGate releases under `resources/fp_sup/releases/`.

Each claim is marked **[measured]** (read out of a file on disk) or
**[inferred]** (a reading of what was measured, which could be wrong).

---

> **Read `docs/ISP_PIPELINE.md` first.** That page maps the *image* pipeline —
> the ISP stage map, the eight ISP patterns, and how the MOV and CinemaDNG paths
> differ — out of the DRAM dump, which did not exist when this page was written.
> This page is about something else: how **OpenGate** installs a recording mode,
> from its published payloads. Both are useful; they are not the same subject.
>
> **Scope note (container decision changed after this was written).** fpLog now
> targets **MOV/H.264**, not CinemaDNG — storage reduction is the objective and the
> raw family caps out near 2×, see `PLAN.md` §1. This page was written against the
> CinemaDNG geometry path, so read it as **infrastructure, not target**: the VBIN
> mechanism, the detour idiom in §7, the 32 mode-independent `1600` writes in §4 and
> the three-copies lesson in §6 all still apply. The `0xC043xxxx` cluster and the
> descriptor at `context+0x5C` were mapped as the *recording format* path; whether
> they also serve the MOV pipeline is an open question the dump answers. §8's
> question 2 — where 12→10 bit happens — is no longer fpLog's kill criterion; the
> ISP tone curve is.

## 1. What this analysis could and could not reach

`FIRMWARE_BASE.md` establishes that the update file is packed, so the ROM itself
was not disassembled. What *was* available is the **published, camera-tested
OpenGate payloads** — OG2K `fpSup.BIN` and OG3K `VSHL.BIN` — which are plain
`VBIN` containers of `{destination, bytes}` sections.

Those payloads are the negative image of the ROM. Every place OpenGate has to
reach in order to install a recording mode shows up as a section, so the patch
table alone maps the recording path's seams without decompressing anything.

**This is how far that gets, and where it stops.** The call sites and the shape
of the data they manipulate are now known. The ROM code on the other side of
those sites is not, and cannot be until the DRAM dump exists.

## 2. The two payloads are structurally identical **[measured]**

Both are `VBIN`, **80 sections**, entry `0x00000000`. The section *addresses* are
the same in both builds apart from one scratch word (`0xC0732A00` in OG2K,
`0xC0732600` in OG3K). Only the *contents* of ten blocks differ.

**Installing a recording mode is a fixed recipe on this firmware.** OG2K and
OG3K are the same machine with different numbers in it — which is exactly the
property fp_log needs, because it means the recipe can be followed for FHD.

## 3. The fourteen ROM hook sites **[measured]**

Identical in both builds. Each is a single word overwriting a ROM instruction,
redirecting into the payload:

| ROM site | kind | → payload block |
|---|---|---|
| `0xC005C020` | `B` | `0xC0731800` |
| `0xC02092CC` | `BL` | `0xC0730A00` |
| `0xC0218AEC` | `BL` | `0xC0730A00` |
| `0xC0219260` | `BL` | `0xC0730A00` |
| `0xC0306EA0` | `B` | `0xC0731B00` |
| `0xC0306EEC` | `B` | `0xC0731B40` |
| `0xC03A6DD8` | `B` | `0xC0732900` |
| `0xC03AA568` | `BL` | `0xC0730A00` |
| **`0xC0437AF8`** | prologue `push {r4,r5,r6,lr}` | — |
| **`0xC0437B48`** | `B` | `0xC0731A00` |
| **`0xC0437E98`** | `B` | `0xC0731D00` |
| **`0xC043A19C`** | `BL` | `0xC0732400` |
| **`0xC043BE68`** | `B` | `0xC0732200` |
| **`0xC043CCF8`** | `B` | `0xC0730800` |
| **`0xC043D258`** | prologue `push {r4,r5}` | — |
| `0xC05E5B58` / `0xC05E6400` / `0xC05E84D8` | Thumb | — |

**Seven of the fourteen are in `0xC043xxxx`.** That cluster is the recording
format decision path, and it is where fp_log's work lives. **[inferred]**

The three `0xC05Exxxx` sites are Thumb (`0xB9..`, `0xBC..`, `0xBB..` are not ARM
branch encodings). fp_sup puts the lossless-JPEG wrappers at `0xC05A6890` /
`0xC05A6920`, so `0xC05Exxxx` is plausibly the same imaging/DNG neighbourhood —
**unverified, and worth checking first once a dump exists**, because that is
where a DNG header is most likely assembled.

## 4. The thirty-two `1600` writes are **not** geometry **[measured]**

Both builds write the constant `1600` (`0x640`) to the same 32 addresses, in two
mirrored banks exactly `0x7C50` apart:

```
bank A  0xC0BD9A2C .. 0xC0BDA194
bank B  0xC0BE167C .. 0xC0BE1DE4      (= bank A + 0x7C50)
```

OG2K is 2016×1344 and OG3K is 3024×2010. Neither is 1600, and **both builds write
the identical value**, so this is a mode-independent prerequisite — a raised limit
or allocation reserve, not a mode descriptor. **[inferred]**

fp_log will very likely need these same 32 writes. **Do not try to derive them;
copy them, and find out what they mean before shipping.**

## 5. The menu row is a CSV string in ROM **[measured]**

`0xC0F8E7EC`, 92 bytes, a UTF-8-BOM CSV resource:

```
OG2K:  NO,TEXT,IMAGE,Enabled,Enabled2\n1,0313,blank,1,2\n2,0314,blank,1,2\n3,OG2K 2000x1334,,1,2
OG3K:  NO,TEXT,IMAGE,Enabled,Enabled2\n1,0313,blank,1,2\n2,0314,blank,1,2\n3,OG3K 3008x2000,,1,2
```

Rows 1 and 2 are stock (string ids `0313`, `0314` — UHD and FHD). **Row 3 is the
third resolution slot**, and the only bytes that differ between the two builds are
its label. This is the whole of "OpenGate has native UI": one replaced CSV row.

**fp_log must not take this slot.** It is a *bit-depth and encoding* change, not a
geometry one — it should stay on stock FHD and put its switch somewhere else.
Taking row 3 would also make fp_log permanently incompatible with either OpenGate
build on one card.

## 6. The format descriptor — the central finding **[measured + inferred]**

`0xC0732400` is reached by `BL` from `0xC043A19C`. Disassembled (OG3K):

```asm
C0732400  push  {r0,r1,r2,r3,ip,lr}
C0732404  add   r1, r4, #0x5c          ; r1 = format descriptor
C0732408  movw  ip, #0x2600            ; payload scratch 0xC0732600
C073240C  movt  ip, #0xc073
C0732410  str   r5, [ip, #8]           ; record the mode id it was called with
C0732414  cmp   r5, #0x53              ; 83 = the third-slot mode
C0732418  bne   #0xc0732434
...
C0732434  movw  r0, #0x80
C0732438  ldr   r3, [r1, r0]           ; descriptor +0x80 = capability flags
C073243C  tst   r3, #0x10000           ; one bit gates the whole thing
C0732440  beq   #0xc07325a4            ; not eligible -> leave stock
...
C0732458  ldr   r3, [ip, #4]           ; a call counter, for observability
C073245C  add   r3, r3, #1
C0732460  str   r3, [ip, #4]
```

then a straight run of stores into the descriptor:

| descriptor offset | OG3K | OG2K | reading **[inferred]** |
|---|---|---|---|
| `+0x1C` | 2 | 2 | mode/readout kind |
| `+0x0C` | 3024 | 2016 | **full width** |
| `+0x10` | 2010 | 1344 | **full height** |
| `+0x20` | 3008 | 2000 | **stored/cropped width** |
| `+0x28` | 2000 | 1334 | **stored/cropped height** |
| `+0xD8` | 3024 | 2016 | full width, second copy |
| `+0xE0` | 2010 | 1344 | full height, second copy |
| `+0xF4` | 3024 | 2016 | full width, third copy |
| `+0xF8` | 2010 | 1344 | full height, third copy |
| `+0x60`, `+0x64`, `+0xD0`, `+0xD4` | 1024 | 1024 | alignment/pitch, mode-independent |

**Read of this routine:** the recording format descriptor lives at
**`context + 0x5C`**, the mode id arrives in **`r5`**, a capability word at
**`descriptor + 0x80` bit 16** gates eligibility, and geometry is written in
**three separate copies** — consistent with the OG3K v0.2.2a bug, where one
pass-through copy was missed and 8-/10-bit silently fell back to UHD30 with no
sign on screen.

**For fp_log, this descriptor is the map, and the missing entry on it is where
bit depth lives.** Three geometry copies were found because three geometry values
were known to search for. The bit-depth field was not found, because its value is
unknown — it will fall out of the dump immediately, since OG3K demonstrably sets
8-, 10- and 12-bit at OG3K geometry.

## 7. The detour idiom **[measured]**

`0xC0731A00`, hooked from `0xC0437B48`, is the complete pattern in 168 bytes:

```asm
ldr   r3,[r2,#8]  /  cmp #3008  /  ldr r3,[r2,#0xc]  /  cmp #2000   ; is this our mode?
str   1 or 0 -> 0xC0731C0C                                          ; latch the answer
ldr   0xC0731C08 ; cmp 0 ; beq ...                                  ; armed?
movw/movt ip,#0xC043BCBC ; cmp lr, ip ; beq ...                     ; WHICH caller?
mov   r0,r1 ; r1=0xC0730C00 ("OG3K") ; r2=#0xF ; blx 0xC01F578C     ; strncpy the label
...
push  {r4..fp,lr} ; movw/movt ip,#0xC0437B4C ; bx ip                ; fall back into ROM
```

Four things worth copying verbatim: **latch the decision in payload state rather
than recomputing it**, **branch on the return address** when one routine serves
several callers, **tail-jump to the instruction after the patched one** rather
than trying to emulate it, and **keep a counter and the last-seen argument in a
fixed scratch word** (`0xC0732600+4`, `+8`) so a failure can be read out afterwards.

## 8. What is still unknown

| # | question | how it gets answered |
|---|---|---|
| 1 | Where is the bit-depth field in the descriptor? | dump + diff an 8/10/12-bit capture path |
| 2 | Is the 12→10 bit reduction a truncation, or is there a LUT? | **the kill criterion — see PLAN.md §3** |
| 3 | What does `imager set_gain_state 5` change — sensor readout, or a packing stage? | dump, then `i2c r` on a live body |
| 4 | Where is the CinemaDNG header assembled, and can a tag be added? | the `0xC05Exxxx` Thumb cluster is the first place to look |
| 5 | What are the 32 `1600` writes? | dump |
| 6 | FHD 24p's mode id, and its descriptor address | dump; OG3K's third slot is `0x53` |

Questions 2 and 4 decide whether this project is possible at all. Neither can be
answered from the files in this repository.

## 9. Reproducing this

Scripts are in the session scratchpad and should be moved into `tools/re/`:
`vbin.py` (parse), `diff.py` (OG2K vs OG3K), `hooks.py` (resolve branch targets),
`geo.py` (constant search), `dis.py` (capstone disassembly). Host-side, read-only,
`capstone` the only dependency.
