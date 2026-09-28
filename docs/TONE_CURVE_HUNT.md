# Answering question 3: is there a programmable tone curve in the video path?

This is the kill criterion (`PLAN.md` §3). Four tiers, cheapest first.

> **Historical, with outcomes (2026-09-22).** All four tiers have now been run.
> The method is kept because tiers 0 and 2 are still how a candidate gets
> confirmed; the *verdict table at the bottom is wrong* and is annotated there.
>
> | tier | outcome |
> |---|---|
> | 0 — measure from outside | **never done.** Still the cheapest unrun thing in this document |
> | 1a — ask the firmware | **done, no USB shell needed** (`results/shellcap/`). `pic` has no tone or gamma entry. `menu dump` turned out to be a hex dump of the live settings block at `0xC31B32BC`, size 2496 — which is better, because it is diffable |
> | 1b — the colour-mode differential | **done, repeatedly, and it was the wrong variable.** Colour mode does not move the luma curve |
> | 2 — the dump | **done** (`results/dram_21_09_2026/`). Found the 89-curve bank |
> | 3 — confirm by writing one entry | **done, and the 89-curve bank failed it.** Repointed live, picture unchanged: inert (`results/selector/`) |
>
> `docs/MAIN_GAMMA.md` is the negative record; `docs/CURVE_TARGETS.md` is the
> plan that replaces this one, and `docs/ISP_PIPELINE.md` the reference.

The through-line: **a tone curve has a shape almost nothing else in memory has.**
A long run of monotonically non-decreasing values at a regular element width,
with a smooth second derivative. Code is not monotonic. Pointers are not
monotonic. Image data is not monotonic. A gamma LUT is. That is what
`tools/find_curves.py` looks for, and it is why you do not need to know where to
look.

---

## Tier 0 — measure the curve from outside the camera

**Cost: one shoot. Risk: none. Needs nothing.**

Shoot a grey step wedge, identical exposure and lighting, in several colour modes
— Standard, Vivid, Neutral, Cinema, Monochrome — plus **one CinemaDNG take of the
same scene as linear ground truth**.

For each mode, plot recorded code value against linear scene value. That gives
you the actual transfer function the camera applied. Three things fall out:

1. **Do the modes differ by a curve, or by a matrix?** Check whether R, G and B
   move together. Together = a shared tone curve. Separately = a matrix, and the
   curve may sit elsewhere.
2. **How many stops does the curve span?** This is what §2 fits the reduced-range
   log to, so it is needed regardless.
3. **Is it a LUT or an analytic function?** *This is the diagnostic one.* A
   hardware gamma LUT has a finite number of knots with interpolation between
   them, so the measured curve has small, regularly spaced second-derivative
   discontinuities. An analytic curve does not. **Knot spacing gives you the
   table size** — and a table size is most of what you need to write one.

**What it cannot tell you:** where the table lives, or whether it is writable.
A negative here (perfectly smooth, no knots) does not kill the project — the LUT
may simply be finer than the wedge resolves.

## Tier 1 — ask the firmware, and diff its memory

**Cost: a USB shell card. Risk: low. Needs no dump.**

> **It never needed a USB shell.** This tier was deferred for months as "needs
> the USB shell" and was finally done from a plain AutoRun, by calling the
> firmware's own shell executor (`FN_SHRUN 0xC03D9C20`) and capturing its output
> to a file on the card (`camera/shellcap.S`, `results/shellcap/`). Any card in
> this repository can run any shell command. **Check what a stated prerequisite
> actually requires before letting it gate a cheap step.**

### 1a. Make the firmware list its own ISP functions

```
shl pic
shl optic
shl menu dump
```

`pic` and `optic` already expose per-ISP-function control — `0 auto / 1
force_off / 2 test` over `distortion`, `aberration`, `shading`, `3ddnr`,
`monofilter`, `tbsd` (sub-table at `0xC0BC00E8`). Run them with no arguments and
the firmware prints its usage, which **enumerates every sub-function it has**. If
a tone or gamma entry is in that list, question 3 is answered in one command.

`menu dump` prints every setter and its value — roughly 65 of them. A
tone-related name there is a direct handle, with a setter already wired to it.

Also worth a look: `adj imager get` / `disp`, and `pic sig_dsccal`, which
`SHELL_CAPABILITIES.md` describes as signal-processing intermediate data.

> Reading usage text is free. `pic <fn> 1` and `2` are **writes** to ISP state —
> RAM only and cleared by a power cycle, but treat them as changes, one at a time.

### 1b. The memory differential — the sharp instrument

> **The bolded claim below is false and this project acted on it four times.**
> A table that changes with the colour mode is a table that changes with *one of
> the 89 ISP registers a colour mode moves* — chroma curves, colour matrices,
> gains. The luma curve is not among them. The technique is sound; **the variable
> was wrong.** Pick a variable that moves one thing, and confirm by moving the
> candidate and looking at the picture.

~~**A table that changes when the colour mode changes is a live tone curve.**~~
You do not need to disassemble anything to find it.

```
# with the camera in colour mode A
shl mem save \MEMA.BIN 0xC1000000,,0x400000
# switch to colour mode B, then
shl mem save \MEMB.BIN 0xC1000000,,0x400000

python3 tools/find_curves.py MEMA.BIN MEMB.BIN --diff --base 0xC1000000
```

`--diff` reports only candidate tables whose contents differ between the two
states. Everything static drops out.

**This also works with no shell at all**, using the read-only dumper in
`camera/build_dump_card.py`: set colour mode A, boot the dump card,
keep the files; set mode B, boot it again; diff the two sets. Slower, but it
needs nothing that does not already exist.

*Caveat:* if the curve lives in a heap allocation, its address may move between
boots and an address-keyed diff will miss it. If the diff comes back empty,
compare the candidate tables **by shape** rather than by address before
concluding anything.

## Tier 2 — the dump

**Cost: it is already step 3 of §9. Risk: none, `mem save` only.**

```
python3 tools/find_curves.py firmware_C0000000.bin --base 0xC0000000
python3 tools/find_encoder_cfg.py firmware_C0000000.bin
```

`find_curves.py` returns every monotonic table in all 49 MB, sorted with
conventional LUT lengths first — 33, 65, 129, 257, 1025 entries are the sizes to
look at before anything else. It reports element width, endpoints, and a
best-fit gamma, so a table that reads 0→4095 over 1025 entries at gamma 1.00 is
an identity ramp and a table at gamma 0.45 is a display curve.

Then cross-reference against the code: the `pic` sub-table (`0xC0BC00E8`), the
`movrec` handler (`0xC0403558`), and the colour-mode parameter block. **A
candidate table that some ISP routine reads is the answer; one that nothing
reads is a coincidence.**

### Tier 2 was attempted against the update file — it does not work

Recorded so nobody repeats it. `find_curves.py` over all 25.7 MB of
`FP__V502.bin` runs in 0.4 s and returns **one** candidate: `0x0177F818`, 66
entries of u32, inside `DAT1`. Inspecting the bytes, it is a resource index —
records of `{group, index, 00, running-offset}` where only the last byte climbs.
Not a transfer function.

Lowering the threshold to 16 entries produces a handful more, and they are all
the same artefact: runs whose differences are exactly `10, 10, 10, …` then
`2560, 2560, 2560, …` (2560 = `0x0A00`). That is one byte incrementing by ten at
a fixed stride — the packer's own block framing, showing through as monotonic
u16. Real structure, wrong structure.

**A default curve is almost certainly in the firmware image.** It is just stored
compressed, so nothing byte-level can see it until the boot loader has
decompressed it — which is exactly what the DRAM dump captures
(`docs/FIRMWARE_BASE.md`). Note also that the *active* curve may be a RAM copy
that differs from the ROM default, which is what makes tier 1's colour-mode diff
worth doing even after the dump exists.

*(A note on the negative: a first pass at this claimed the compressed body should
yield essentially zero monotonic runs on i.i.d.-uniform grounds. The data
disproved that — packed firmware is not uniform noise, it has periodic framing.
The tool was right and the statistical argument was wrong.)*

### On the tool

`find_curves.py --self-test` plants a 257-entry gamma LUT and a 1025-entry
identity ramp in 200 KB of uniform random noise and requires exact recovery of
both — length, element width and fitted gamma — with **zero** false positives.

It earns that. The self-test caught three real defects while it was being
written: misaligned reads producing fifty phantom tables, the same bytes being
reported twice at two element widths, and an off-by-one that absorbed the element
which broke monotonicity and wrecked every gamma fit. A detector nobody has tried
to fool is not evidence.

## Tier 3 — confirm by writing one entry

**Cost: one command. Risk: RAM only. This is the proof.**

```
shl mem set <addr> <value>
```

Change one entry of a candidate table, camera idle, and look at the picture. If
it moves, the table is the tone curve, it is writable, and it is live — question
3 is answered *and* `PLAN.md` §10 stage D1 is done in the same stroke.

Change **one entry**, not the table. One variable at a time; mixed variables have
already produced wrong conclusions on this camera.

---

## What each outcome means

| result | verdict |
|---|---|
| a tone entry in `pic`/`optic`/`menu` | **answered yes** — stop looking, start reading that path |
| ~~a table that changes with colour mode~~ | ~~**answered yes**, and you have its address~~ **WRONG, and it cost this project four runs.** Colour mode changes 89 ISP registers at once — chroma curves, colour matrices and gains. A table that moves with it is a table that moves with *something* in that set, and that set does not include the luma curve. Use a variable that moves one thing |
| tables found, none changes, none is read by an ISP routine | inconclusive — the curve may be in hardware registers, not RAM. Try the recording-time MMIO probe (§9 step 6) |
| no monotonic tables anywhere near the video path | **the kill criterion fires.** Write down what was ruled out and stop |

**The rule the second row should have been:** a table that changes is a
candidate, not an answer. Confirm it by moving it and looking at the picture,
with everything else held still — which is exactly what tier 3 is for, and what
eventually showed the 89-curve bank to be inert.

A CPU pass over the frame is not the fallback for a "no" — see `PLAN.md` §3.
