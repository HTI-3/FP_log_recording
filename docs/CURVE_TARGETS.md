# Where a log curve should sit

The ranked list of places the curve could go, what each would cost, and what
would confirm or kill each one. Reference for the pipeline itself is
`docs/ISP_PIPELINE.md`; `docs/MAIN_GAMMA.md` is the negative record.

**Target 1 has been executed and it PASSED**, 2026-09-22 —
[`results/invert/FINDINGS.md`](../results/invert/FINDINGS.md). The rest of this
page is unexecuted and its ranking still stands, but targets 2 and 3 exist to
serve a search that is now over: the curve is found. Read §7 of the findings for
what replaced them.

---

## The criterion, stated before the list

A log encoding has three requirements, and most candidate stages fail one of
them for structural reasons that no experiment will fix.

1. **It must act on RGB, before the YUV matrix.** `GAM_TOP GAMMA TABLE` sits
   beside `GAM_TOP YCMAT`, the RGB→YCbCr matrix; everything in `PST_TOP` and
   `CEQ` is after it. A curve applied to Y alone, with chroma left on a
   different transfer function, is not a log encoding — it is a luma crush with
   saturation that no longer corresponds to the luma, and it grades badly. This
   rules out the whole `PST_TOP`/`CEQ` family as the *primary* target regardless
   of whether we can reach them.
2. **It must be the transfer function, not a trim on top of one.** Composing a
   log curve onto an unknown 2.1-gamma predecessor costs precision twice and
   needs the predecessor measured first.
3. **The firmware must be the one to move it.** Five verified writes have failed
   to reach the picture and one has succeeded; the one that succeeded wrote a
   DRAM source and let the firmware upload it. Direct MMIO stores into
   `0x3021xxxx` are *ignored* — the bank is shadow registers behind a `V LATCH`.

**The rule: do not move the data, change what the firmware moves.**

---

## Target 1 — `GAM_TOP GAMMA TABLE`, via the 452-curve registry

**This is the right place, and it is the only candidate that satisfies all three
criteria.**

| | |
|---|---|
| where | RGB, immediately before `YCMAT`, per channel with a shared table |
| data | 452 curves, 2048 × u16, stride `0x1000`, `0xC0971F34..0xC0B34F34` |
| registry | `0xC0971118`, `{pointer, id}`, abutting the curve data |
| selector | `{index, pointer}` in live state at `0xC3414510` / `0xC3414D48-4C` / `0xC3414D84`; mode **Off → 82**, **Teal & Orange → 16** |
| hardware | decimated to 65 knots and interpolated — `GAM_BAS` + `GAMDEC` + `GAMINT`; 2048 ÷ 32 = 64 segments = the 65-knot ramp seen at `0x30210594` |

**Why it was written off, and why that was premature.** `results/selector/`
repointed the three selector words live, in mode Off, and the picture did not
change — recorded as "the bank is inert". But that test **deliberately did not
change the colour mode**, to isolate the variable, and `results/looksrc1/`
established that the firmware uploads **when a colour mode is selected**. So the
test changed a pointer and never triggered the read that would consume it.

That is the same failure the project already made four times and then solved:
write the source, then *select the mode*. The test proved the pointer is not
re-read per frame. **It did not prove the bank is dead.**

### The experiment

**Built: `camera/build_invert_card.py`, documented in
[`docs/cards/invert.md`](cards/invert.md).**

One card. **Invert** curves #82 (mode Off) and #16 (Teal & Orange) —
`v := max(table) − v`, the maximum measured rather than assumed — then **toggle
the colour mode away and back** to force the upload. Dump both tables, the live
selector and the ISP shadow bank three times, so a failed write and a failed
upload are distinguishable.

**Invert, not flatten.** A flattened span makes a band on a gradient, and
whether a band is there is a judgement call on a live LCD. This project has
already drawn a wrong conclusion from "the picture changed" once — the literal
report was *"it changed the color"* (`results/logoff1/REFRAME.md`). **An
inverted curve renders a photographic negative.** Nobody has to decide whether
they saw it.

**Both curves, not one.** Off is the mode to ship on, but every write aimed at
Off has failed to move the picture and the one write that *worked* was aimed at
Teal & Orange. The toggle that forces the upload runs between exactly those two
modes, so both ends of it land on an inverted table. **If only one responds,
that asymmetry is the finding.**

| outcome | meaning |
|---|---|
| **picture goes negative** | the transfer function is reachable by the proven mechanism. Everything after is curve fitting |
| table holds our bytes, ISP bank unchanged across the toggle | written but never uploaded — the trigger is something other than a mode change |
| table holds our bytes, bank moved, picture unchanged | this bank feeds a path that is not the video render |
| table does not hold our bytes | the firmware rewrote it; find what composes it |

`tools/check_invert.py` reads the twelve files and names the outcome; it
self-tests, and it does **not** predict a value for `0x30210594`, which
`results/isprobe_1/` measured as a *unity* ramp and so reads as a knot axis
rather than as output values.

**Cost:** one card, ~15 minutes. **This is the highest-value experiment in the
project** and it is cheaper than anything below it.

### The sub-question if it passes

Which of the 452 to ship on. Curves 0–88 are the ones the selector addresses and
they clip at `15/16` of the index range; the rest are a different population in
repeating groups of 11. Curve **451** is byte-identical to curve **82** over
entries 0–1899 and differs only by running full-scale to 8191 instead of
clipping to 8190 — so unclipped variants exist and the clip is a property of the
curve data, not of the stage. Ship on a **colour-neutral** mode: Teal & Orange
carries a stylised colour matrix in 19 ISP registers we cannot neutralise, so
`0xC0B3B2E8` (id 11) is the wrong switch even though it is the proven one.

---

## Target 2 — `PST_TOP Y_GAMMA`

| | |
|---|---|
| where | YUV, after `YCMAT`, on Y alone |
| status | named in the pool at `0xC07D3C2C`; **no register base, no DRAM source, no data located** |

Fails criterion 1: a log curve here encodes luma while chroma keeps the stock
transfer function. **It is not a place to put a log curve.**

It is still worth finding, for two reasons: it is the most likely thing a luma
setter moves, which makes it the *instrument* for locating the luma path even if
it is not the destination; and if target 1 fails, a Y-only log plus a matching
chroma correction becomes the least-bad fallback rather than the first idea.

---

## Target 3 — `CEQ` gains and slopes

| | |
|---|---|
| where | colour equaliser, after `PST_TOP` |
| data | the 36-record bank at `0xC0B3AB80`, `docs/LOOK_CURVE.md` |
| status | **the mechanism is proven here and nowhere else** |

`CEQ24_ORG` / `CEQ24_TGT` names it: a 24-bin colour equaliser. It is chroma, it
fails criteria 1 and 2, and it cannot carry a log curve.

What is still untested is the **other two thirds of every record** — `gains A`
(shaped in 22 of 36 records), `slopes A`, `gains B`, `slopes B`, none of which
has ever been written. Cheap, and worth one card **only** to pin the record
semantics, because those semantics are what `docs/LOOK_CURVE.md` cannot state
and what any future curve fit into this stage would need. Expect colour.

---

## Target 4 — the `Cdng` / `UpdateCdng` pattern split

Not a curve target — a **monitoring** target, and the answer to `PLAN.md` §8
question 5.

The ISP is configured per pattern (`docs/ISP_PIPELINE.md` §1), and `Mov` and
`UpdateMov` are separate configurations. If the record pattern and the monitor
pattern can hold different curves, then **recording log while monitoring
Rec.709 is reachable** — the thing the plan assumed would need two render paths
and might be impossible.

Wholly untested, and cheap to probe: no ISP capture has ever been taken in
CinemaDNG mode at all.

---

## What the code trace changed

`docs/ISP_PIPELINE.md` §7 traced `pic set` into the sigpro library and found no
ISP register base anywhere in the ARM image — not as a constant, not assembled
from parts. The ARM queues a request onto a PictureQuality singleton
(`0xC341399C`) with a 0x1A0-byte parameter block at `0xC34139AC`, and something
else programs the shadow bank.

**If that reading holds, criterion 3 gets stronger, not weaker.** There is no
register to write, so "borrow the firmware's own path" stops being the best
option and becomes the only one. It also explains the `knottest` result exactly:
an ARM store into `0x30212020` was *ignored* rather than overwritten.

It does not change the ranking. Target 1 still writes a DRAM source and lets the
firmware upload it, which is the one mechanism proven to work.

## Target 5 — the code

`library/SigProcess/` and `library/CameraController/PictureQuality/`. The first
pass is done (`docs/ISP_PIPELINE.md` §7) and it found the request path but no
register bases. What remains is expensive and honest about it: **nothing in the
ARM image names a `0x3021xxxx` address or builds `0x30000000`**, and
`tools/xref.py` returns zero hits
for the curve registry, the CEQ bank and `0xC0B392B0`. This is real
disassembly over 64 MB, not another search script.

Do this only after target 1 has been tried with the trigger.

---

## Instruments, before any of the above

Two shell commands make the firmware describe its own configuration, both
reachable from a card today, neither ever run:

- **`pic print_tag`** (`0xC0404E78`) — "Printing pic_data When writing tags."
  It sets a logging flag rather than dumping, so it narrates the ISP
  configuration as the firmware writes it. Enable it, then change the colour
  mode or start a recording, and capture the shell output with the proven
  `camera/shellcap.S` mechanism.
- **`pic sig_dsccal`** (`0xC0404950`) — "Dumping out some data in signal
  process."

**Run `print_tag` before target 1.** If the firmware names the tag it writes and
the address it writes it to, targets 1–3 stop being a ranked guess.

---

## The order

1. `pic print_tag` + a mode change, captured to the card — *one card, and it may
   make everything below unnecessary*
2. **Target 1** — invert curves #82 and #16, toggle the mode, look at the
   picture. **Built and ready: `camera/build_invert_card.py`**
3. Target 4 — an ISP capture in CinemaDNG mode, which nothing has ever done
4. Target 2 as an instrument — a luma-only variable, sweeping for `Y_GAMMA`
5. Target 3 — the untouched gains/slopes, to pin the record semantics
6. Target 5 — the code

Steps 1 and 2 are two cards and under an hour. Everything else is behind them.

## What would end it

If target 1 fails with the trigger, target 4 shows no independent per-pattern
configuration, and no call site can be borrowed between the firmware's table and
the `SBUS GAMMA` port, then fpLog cannot be done this way.

Write that down and stop. **Do not go back to poking registers.** Five verified
writes that did not reach the picture is enough evidence that poking does not
work, and a sixth carries no new information.
