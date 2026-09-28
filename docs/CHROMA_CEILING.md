# Chroma, and whether 4:4:4:4 is reachable

**Answer: no, and not for one reason but four independent ones.** Written down
so it does not get asked again. Reference for the pipeline is
`docs/ISP_PIPELINE.md`; for the measured stock stream,
`results/mov_recording/FINDINGS.md`.

Claims are **[measured]** (read out of the dump or the clip) or **[inferred]**.

```bash
strings -a -t x results/dram_21_09_2026/dram_C0000000.bin | grep -iE '4:4:4|4:2:2|ProRes'
python3 tools/find_encoder_cfg.py results/dram_21_09_2026/dram_C0000000.bin
```

---

## What 4:4:4:4 means, before anything else

In a MOV container "4444" is **ProRes 4444**: 12-bit 4:4:4 Y'CbCr or RGB plus a
**16-bit alpha channel**. The fourth `4` is alpha. The nearest thing H.264 has
is **High 4:4:4 Predictive, `profile_idc 244`** — 4:4:4 chroma, up to 14-bit,
and **no alpha at all**.

So the question splits, and the two halves have different answers for different
reasons:

- **the fourth 4 (alpha)** — impossible, and would be meaningless;
- **4:4:4 chroma** — not reachable, and would be the wrong lever if it were.

## 1. There is no alpha, and nothing to put in one

**[measured]** `XC_MovSigYuvOutParam` is **the only `*OutParam` type in the
entire image** (`docs/ISP_PIPELINE.md` §3). The signal processor's output
contract is YUV — three planes. The stage map ends `YUV_PACK -> H.264 encoder`
(§2). There is no fourth plane anywhere in the chain.

**[inferred]** A camera has nothing to write into an alpha channel. It is a
compositing channel, produced by a keyer or a renderer. Even if the pipeline
carried one it would be a constant 1.0, costing storage and conveying nothing.

**This half of the question is closed on structure, not on capability.**

## 2. The firmware does not know the string "4:4:4"

**[measured]** Across 67 MB of DRAM there is **no `4:4:4` anywhere** — not as a
menu label, not as a format name, not in any resource block. The only
chroma-format label in the whole image is:

```
"4:2:2 8bit"   UI string id 1635   e.g. 0xC0D6BC49, and once per language block
```

and it belongs to the HDMI output — `MenuItemHdmiOutputFormat`, whose setter is
named `SetHdmiOutputFormat` in the `menu` setter table (name string at
`0xC0BBE660`). **The camera's own premium output path tops out at 4:2:2 8-bit**,
and the recorded file is a step below that at 4:2:0 8-bit.

## 3. The ProRes strings are a red herring — they are the Director's Viewfinder

The dump is full of `ProRes 4K UHD`, `ProRes S16 HD`, `ARRIRAW 2.8K`,
`Open Gate ARRIRAW`, `16:9 DNxHD`, `MPEG-2 HD`, `KOMODO 6K`. **None of it is a
codec the fp can write.**

**[measured]** They sit in one contiguous UI string-id block (`0630`–`0679`)
alongside the emulated bodies, and the bodies have their own data files:

```
../MenuB56/data/B5_2C_3_ALEXA_65.cvm      B5_2C_3_KOMODO.cvm
../MenuB56/data/B5_2C_3_ALEXA_LF.cvm      B5_2C_3_MONSTRO.cvm
../MenuB56/data/B5_2C_3_ALEXA_MINI.cvm    B5_2C_3_HELIUM.cvm
../MenuB56/data/B5_2C_3_ALEXA_SXT.cvm     B5_2C_3_VENICE.cvm
```

driven by `MenuDirectorsViewFinderHandler`, `UicGuiMenuDirectorsViewFinder`,
`XC_DisplayDirectorsViewFinder`. These are **framing presets**: pick a body and
a recording format and the fp draws that camera's field of view. The format name
is used to compute a sensor area. It never reaches an encoder.

**[measured]** There is **no codec fourcc anywhere** — no `avc1`, `ap4h`, `apcn`,
`hvc1`. The muxer is `XC_MovClass{,Common,Conv,File}.cpp` and carries no codec
name at all, which fits: the fourcc is emitted by whatever writes the sample
description, and that is not in the ARM image either (§5).

**So there is no ProRes encoder.** Writing ProRes 4444 would mean implementing a
new encoder *and* a new muxer path on-camera — `PLAN.md` §1's MJPEG fallback,
but harder, and for the wrong codec.

## 4. And it would defeat the objective anyway

`PLAN.md`'s objective is **storage reduction**. ProRes 4444 at FHD 24p runs
~264 Mbps:

| FHD 24p | GB/min | vs stock 12-bit CinemaDNG | vs stock MOV |
|---|---|---|---|
| CinemaDNG 12-bit | 4.55 | 1.0× | 0.13× |
| CinemaDNG 12-bit + lossless ~2:1 | 2.28 | 2.0× | 0.26× |
| **ProRes 4444 (hypothetical)** | **~1.98** | **~2.3×** | **0.30×** |
| **stock MOV, measured** | **0.593** | **7.7×** | 1.0× |

**~2.3× is the same league PLAN §1 already rejected the entire raw family for.**
A 4:4:4:4 MOV would be 3.3× *larger* than the file the project is already
shipping into, to buy chroma resolution the log curve does not need.

**And it is the wrong lever.** `docs/BIT_DEPTH.md` ranks them: the problem is
**256 luma code values** carrying a lifted shadow, which is what produces the
banding `PLAN.md` §7.3 calls the thing most likely to sink the project. 4:4:4
buys chroma edge fidelity — good for keying and heavy secondaries, irrelevant to
luma quantisation. **10-bit is 4× the code values; 4:4:4 is 0× the code values.**

## 5. What about plain 4:4:4, ignoring alpha and ProRes?

Still no. `profile_idc 244` would need **four** things to hold, and only the last
is firmware:

1. **`chroma_format_idc = 3`** in the SPS. The stock stream reads `1`
   **[measured]**, and unlike the bit-depth fields this one changes the entire
   residual and prediction structure of the bitstream.
2. **The `YUV_PACK` stage must emit 4:4:4.** If the ISP decimates chroma before
   the encoder — which is what a packer named `YUV_PACK` in front of a 4:2:0
   encoder is for — the chroma is already gone. Nothing has measured this stage.
3. **The encoder block must implement High 4:4:4 Predictive.** It is a
   professional/screen-content profile, essentially absent from embedded camera
   encoder IP. `results/run1_21_09_2026/` could not even read the codec blocks —
   they are clock-gated when idle.
4. **The firmware must write 244.** `tools/find_encoder_cfg.py` on the real dump
   returns **noise** — 1205 immediate loads of `100`, 117 of `51`, 127 of `244`,
   and none of the eight profile/level clusters sits anywhere near a codec
   neighbourhood. **[inferred]** Consistent with `docs/ISP_PIPELINE.md` §7.1:
   **the codec configuration is not in the ARM image**, the same way the ISP
   register bases are not. It is DSP-side, behind the block at `0x301B0000`.

Point 4 is worth stating carefully: **this is not evidence against 4:4:4, it is
evidence that the question cannot be answered from the ARM image at all.** The
same tool, same reasoning, applies to `110` (High 10) and returns the same
nothing. `PLAN.md` §9 step 4 is therefore **done, and its answer is "not here"**.

## What the actual ceiling is

| | status |
|---|---|
| 8-bit 4:2:0 full range, ALL-I, VBR | **what the camera writes today**, measured |
| 10-bit 4:2:0 (`profile_idc 110`) | **the only lever worth checking** — 4× the code values. `PLAN.md` §8 q.2, still open, and now known to be unanswerable from the ARM image |
| 10-bit 4:2:2 (`122`) | same gate as 110, plus a chroma datapath change |
| 4:4:4 (`244`) | **ruled out** — §5 |
| 4:4:4:4 / ProRes 4444 | **ruled out** — §1, §3, §4 |
| 4:2:2 8-bit **over HDMI** | **exists today**, to an external recorder. Out of scope: it is not card storage, and 8-bit is still 8-bit |

**Plan for 8-bit** (`PLAN.md` §9). Treat 10-bit as an upside to check on hardware
— the clock-gating fix in `results/run1_21_09_2026/FINDINGS.md`, during a
recording — not a branch to design around. **Do not spend any more time on
4:4:4.**
