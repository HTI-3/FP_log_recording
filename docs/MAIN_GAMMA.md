# The luma tone curve — where it is not

> **FOUND, 2026-09-22.** It is `GAM_TOP GAMMA TABLE`, the 452-curve registry at
> `0xC0971118`, and it is reached by writing the DRAM table and toggling the
> colour mode to force the upload. Inverting curve #82 turned the picture
> negative in live view and in the recorded MOV —
> [`results/invert/FINDINGS.md`](../results/invert/FINDINGS.md).
>
> **This page stays, unchanged below, as the negative record it always was.**
> Everything it rules out is still ruled out; the "inert" retraction it already
> carried is what pointed at the answer. Two things on it are now settled the
> other way and are marked in place: the bank is not inert, and the search is
> over.

**Not found.** This page is the negative record: what has been ruled out, with
the evidence, so none of it gets tried a second time. The plan for finding it is
`docs/CURVE_TARGETS.md`.

The curve exists. The exposure ramp in `results/neutralize/` measures a real
transfer function of roughly gamma 2.1 on the recorded video, and
`GAM_TOP GAMMA TABLE` is a real name in the ISP block pool at `0xC07D3C00`.
Something applies it. Nothing this project has written is that something.

## Ruled out

| target | verified how | result |
|---|---|---|
| the 89-curve DRAM bank at `0xC0971F34` | curve #16's table overwritten, read back byte-perfect on 3 runs through cached, uncached **and** bus aliases | no change live, recording or JPEG. `results/curve_1_res/`, `results/cachetest_!/` |
| ~~**the same bank, as a bank**~~ | ~~the three selector words repointed #82 → #16 live in mode Off~~ | **RULED OUT PREMATURELY — see below.** The test never triggered the upload |
| ISP knot registers at `0x30212020` | `x^0.40` written live in mode Off, readback byte-identical to before | **the store was ignored.** `results/knottest/` |
| ISP blocks `0x3020`, `0x3022`–`0x3026` | two-round sweep across a colour-mode change, look trim neutralised | no mode-dependent LUT in any of them. `results/sweep2/` |
| the 36 look records at `0xC0B3AB80` | the curve written into `knots B` of 35 records, then `knots A` of 12 | **colour moved, contrast never did, Monochrome never changed.** `results/logoff1/REFRAME.md` |
| a second bank of look records | all 64 MB scanned for the 24-knot identity array | **there is only one bank.** `tools/look_records.py` |
| the `pic` ISP sub-function list | the firmware printed its own usage to the card | **no tone or gamma entry.** `results/shellcap/FINDINGS.md` |

## The "inert" verdict is withdrawn

`results/selector/` repointed the three selector words live, in mode Off, and
the picture did not change. That was recorded as proof the 452-curve bank is
inert. **It is not.**

The test *deliberately did not change the colour mode*, in order to isolate the
variable — and `results/looksrc1/` established that the firmware uploads **when a
colour mode is selected**. So it changed a pointer and never triggered the read
that would consume it. Exactly the failure the project already made four times
and then solved: write the source, *then select the mode*.

What the test actually proved: the selector pointer is not re-read per frame.
That is all.

**Re-running it with a mode toggle is the cheapest experiment in the project**
— `docs/CURVE_TARGETS.md` target 1.

> **Done, and it passed.** `results/invert/` inverted curves #82 and #16 and
> toggled the mode. The picture went negative, in live view and in the recording.
> **The bank is not inert; the upload trigger was the whole of it.**

### And the bank is bigger than recorded

Not 89 curves and a separate bank of 34. The descriptor array at `0xC0971118`
is `{pointer, id}` and runs **452 entries**, ending at `0xC0971F38` where curve 0
begins — the array abuts its data. The curves are contiguous at stride `0x1000`
from `0xC0971F34` to `0xC0B34F34`. "89" and "a second bank" were both artifacts
of a shape detector finding the homogeneous head and tail of one structure.

```bash
python3 tools/isp_map.py results/dram_21_09_2026/dram_C0000000.bin --only curves
```

The selector only ever addresses the first ~89. Curve **451** is byte-identical
to curve **82** over entries 0–1899 and differs only by running full-scale to
8191 instead of clipping to 8190 at `15/16`, so unclipped variants exist.

## Two retractions worth remembering

**"The 89-curve bank is on the render path"** (`results/neutralize/`) was drawn
from an exposure ramp that differed between two colour modes. A colour mode
changes 89 registers in `0x3021`; only 70 were the ones neutralised. The other
19 — gains and matrices — could produce the whole difference on their own, and
the selector-redirect test later showed they did. **The variable was not
isolated, and the count of what else moves was not taken.**

**"The look records are the per-mode luma trim"** survived from the first write
that changed the picture until three more runs contradicted it. The literal
report of that first run was *"it changed the color"*; it was read as "the
picture changed".

Both errors have the same shape: a positive result attributed to the thing being
tested, without counting what else could have caused it.

## And the target was misidentified

This page was written to hunt "the luma curve". That framing is wrong.
`GAM_TOP GAMMA TABLE` sits beside `GAM_TOP YCMAT`, the RGB→YCbCr matrix, so the
transfer function acts on **RGB before YUV conversion**. `PST_TOP Y_GAMMA` and
`CEQ_YGAM` come after it, on Y alone — and a log curve on Y alone, with chroma
left on the stock transfer function, is not a log encoding.

The target is the shared RGB gamma. `docs/ISP_PIPELINE.md` §2,
`docs/CURVE_TARGETS.md`.

## The one thing every search so far has in common

**The variable was the colour mode.** The DRAM diff, the ISP sweeps at
`0x3021`, the sweep of `0x3020`–`0x3026`, the selector capture — all of them
changed the colour mode and looked for what moved.

Colour mode does not move the luma curve. That is the reframe's whole content,
and it means those sweeps are not negative results for luma at all. **They are
untested regions.** A luma-only variable has never been swept once.

That is where `docs/CURVE_TARGETS.md` starts.

## What is available as a luma variable

The camera's UI exposes no Contrast, Tone Control or Fill Light. The firmware
does, and a card can drive it without any menu — `menu Set<Name> <value>`
through the shell executor, proven on hardware:

```
0xC0BBD65C  SetColorModeContrast        0xC0BBD7AC  SetToneManualHighlight
0xC0BBD774  SetToneControlMode          0xC0BBD7F8  SetToneManualShadow
0xC0BBD83C  SetFillLightEffect
```

`menu SetFillLightEffect 5` returned **`OK`** on hardware
(`results/tone2/FINDINGS.md`). Whether it moved the picture is still unread —
that run froze on the `menu dump` issued straight after it, before the
after-dump was taken.
