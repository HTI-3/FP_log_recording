# Bit depth through the chain

Everything below is measured in this project except where marked. It applies
wherever the log curve ends up, so it is kept separate from any one stage.

| stage | bits | how we know |
|---|---|---|
| sensor, **stills** | **14** | fp_sup: 14-bit `Compression=7`, `WhiteLevel 16383` |
| sensor readout, **movie** | 8 / 10 / **12** — **no 14** | `imager set_gain_state` offers `5` movie_raw_10bit, `6` movie_raw_12bit, `7` movie_raw_8bit. fp_sup: *"What blocks 14-bit video is the readout path"* |
| **`GAM_TOP GAMMA TABLE`** (the 452-curve registry) | **13-bit out** — tables run `0..8190` or `0..8191` | **on the render path, confirmed**: inverting curve #82 turned the recorded MOV negative (`results/invert/`). Input width unknown — see *A table length is not an input width* below |
| **look records** (what we can write) | **16-bit in and out** — identity spans `0..0xF555` of `0x10000` | DRAM source and ISP registers, byte-identical |
| H.264 output | **8-bit** 4:2:0, full range | `ffprobe` on a stock clip |

## What that means

**14-bit is not on the table for video.** The sensor and codec both do it for
stills; the movie readout path does not offer it. 12 is the ceiling.

**The internal pipeline is already wider than the sensor** — 13-bit out of a
gamma table, 16-bit at the look records. The pipeline is not the constraint, and
there is nothing to gain by finding somewhere "wider" to put the curve.

**The constraint is the 8-bit exit.** 256 output codes is the hard limit
whatever the front end does. Going 12→8 is where the loss is, and adding input
bits above 12 would not change it.

## The levers, in order of what they are worth

1. **10-bit output.** `profile_idc 110` instead of `100` would be **4× the
   output codes** — by far the biggest lever, and still unanswered
   (`PLAN.md` §8 question 2). Everything else is a few percent next to this.
2. **Confirm the readout is 12-bit, not 8 or 10.** The `gain_state` modes are
   named `movie_raw_*`, which suggests CinemaDNG; **whether the MOV path
   honours them at all is untested.** If it does, `6` is the one to force.
3. **Fit to full range 0..255**, not 16..235 — 1.17×, free, already established.
4. **Put the curve as late as possible.** The stage nearest the encoder loses
   the least to anything upstream of it.

## A table length is not an input width

The 89-curve bank was recorded here as "2048 in → 11-bit index". **That was
inferred from `log2(2048)` and it does not hold.** The same reasoning applied to
the LUTs this project has actually seen in hardware gives 4.6 bits for the
24-knot look records and 6.0 bits for the 65-knot ramp at `0x30210594`. Those
are knot counts, not input widths: a tone map is a *sampled curve*, and how
finely the curve is sampled is independent of how finely the signal is
quantised.

The firmware says as much. `GAM_TOP` is a segmented gamma:

```
0xC07D377C  GAM_TOP GAMINT          interpolate
0xC07D3BDC  GAM_TOP GAM_BAS         base
0xC07D3BC4  GAM_TOP GAM_GS GAMDEC   decimate
0xC07D3C00  GAM_TOP GAMMA TABLE
0xC07D3820  GAM_TOP SBUS GAMMA      the upload port
```

Base + interpolate + decimate means the table holds knots and the hardware picks
a knot pair and interpolates. That serves an input of any width, which is why
the arrangement exists.

**~~And the decimation factor is visible.~~ RETRACTED 2026-09-22.** The ISP was
seen holding a 65-knot ramp at `0x30210594`, `0..2048` in exact steps of 32
(`results/isprobe_1/`), and this page read it as the decimated form of a
2048-entry table — "the concrete link between the registry and the hardware".

**It is not.** `results/invert/` inverted the table, the picture went negative,
and **that ramp read identically in all three rounds**. A ramp that does not move
when the curve it supposedly holds is turned upside down is not the curve. It is
the **input axis** the table is sampled on, which is also why it is a perfect
unity ramp and why it has no literal match in DRAM.

The decimation argument itself survives — `GAM_BAS` + `GAMINT` + `GAMDEC` is
still a segmented gamma, and 2048 ÷ 32 is still 65 knots. What does not survive
is the claim that `0x30210594` is where those knots land. **The hardware LUT has
not been located, and fpLog does not need it** (`results/invert/` §4).

What the data does and does not support:

- **12 of the 89 curves** run `0..2047 → 0..8191` exactly, which is consistent
  with 11-in / 13-out;
- **the other 77** top out at **8190** and reach it at index 1918–1919 —
  `15/16` of the range. No bit width explains a curve that saturates at 93.75%
  of its own index space; it reads as a white point set at 15/16 with 1/16 of
  headroom above it;
- **2048 is also the stride.** The tables sit `0x1000` apart with no padding:
  4096 bytes ÷ 2 = 2048 entries. "One 4 KiB page per curve" explains the count
  at least as well as 2^11 does.

**The `15/16` clip is now load-bearing, because the bank is not inert.**
`results/invert/` put curve #82 on the render path, and #82 is one of the 77 that
top out at 8190 at index 1918. So the stock transfer function reaches white at
`15/16` of its index range with 1/16 of headroom above it — and a log curve
fitted to this stage has to decide deliberately whether to keep that headroom or
spend it. Curves 434/435, which the same run found pointed at from the live
selector, run full-scale to 8191 instead, so **both conventions exist in the
bank** and the choice is ours.

**Why no table here could match 8/10/12 anyway.** Those are the ends of the
pipe — sensor readout and encoder output. Gamma sits in the middle, after black
level, white balance, demosaic and the colour matrix, on an internally
normalised signal whose scale the readout no longer sets. The middle is measured
wider than both ends, above.

## The quantisation that could bite before the 8-bit output

If the luma gamma turns out to be a LUT indexed by the top *n* bits **without
interpolation**, the signal arriving at whatever stage carries the log curve is
quantised to 2^*n* levels no matter how many bits the readout had. `GAMINT` is
evidence against that for `GAM_TOP`, and says nothing about the other blocks.

A log curve then lifts the shadows hard and amplifies that quantisation along
with the picture. **Banding from that stage would look like banding from the
8-bit output and would not be fixed by anything at the exit.**

`tools/measure_transfer.py` is what would show it either way: quantisation
upstream appears as steps in the measured transfer function that do not move
when the written curve changes.
