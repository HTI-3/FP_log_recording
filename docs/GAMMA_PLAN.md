# Once a target passes — measure, fit, ship

**Target selection has moved to [`docs/CURVE_TARGETS.md`](CURVE_TARGETS.md).**

This page used to be the whole plan, and its first four steps were built on two
things that later turned out to be wrong: that the object of the search is "the
luma curve", and that colour mode was the only variable ever tried. Both are
corrected in `docs/ISP_PIPELINE.md`, and what replaced them is in
`CURVE_TARGETS.md`.

What survives is everything *after* a target is confirmed — the part that does
not depend on which stage it turns out to be. Nothing here is worth starting
until a write has visibly changed contrast in a recording.

---

> **Step 1 is half done, from the dump rather than a shoot.** The stock table
> is not *like* a standard curve, it **is** one:
> `curve #82 == sRGB OETF(index / 1918)`, max error 2 of 8190 codes. So the
> stage's input is scene-linear, diffuse white = 1.0 at index 1918, 18% grey at
> index 345 — no composition against an unknown predecessor is needed, and the
> "~2.1 pre-gamma" this page worried about was that sRGB curve seen end to end.
>
> **What is still open is the range**, and only a shoot answers it: the table's
> input stops 0.094 stops above white, so whether the fp's highlights reach this
> stage at all is unknown. `docs/cards/logc.md` is the experiment.

## Step 1 — characterise the stage

A curve written part-way down the pipeline sees an **already-curved** signal,
not scene light. Writing `Log(x)` there gives `Log(gamma(linear))`, which is not
a log encoding of anything.

So measure the stage before fitting to it. `docs/SHOOTING_LOG.md` §1 is the
procedure: an exposure ramp with the target at identity gives the preceding
transfer function, and shutter time is the reference, so no chart is needed.

Three things fall out, and nothing else settles any of them:

- **the preceding gamma**, to compose the inverse against. The provisional
  figure is **~2.1**, measured from the Off half of the `results/neutralize`
  ramp — but that was a mixed scene, not a flat field, and the top never clipped
  cleanly, so the highlight end is under-measured. Re-shoot it properly.
- **the gain and slope semantics**, if the target has them. `docs/LOOK_CURVE.md`
  pins the CEQ record's knots and not its two other array types.
- **whether the knot count is enough.** Linear interpolation between *n* points,
  and a log curve puts its precision exactly where the knots are sparsest. At 24
  knots this is the real risk; at 65 — which is what `GAM_TOP` decimates to —
  it is comfortable. **If it bands, no cleverer fit rescues it.** That is a
  finding, not a bug.

**Produces:** `docs/SENSOR.md` — the numbers the curve is fitted to.
**Stops if:** the stage bands at any curve. Then it cannot carry log, and the
search resumes at `CURVE_TARGETS.md`.

## Step 2 — fit the curve

> **First card built: spec-exact ARRI Log C V3, EI 800** —
> `camera/build_logc_card.py`, `docs/cards/logc.md`. Spec-exact **on purpose**,
> even though it uses only 48.5% of the output range, because it makes the
> verification series unambiguous and Resolve decodes it with a stock dropdown.
> The bake-off below is what decides what actually ships, and it cannot start
> until the series says whether the range is there at all.

Offline, no camera. `PLAN.md` §2 has the reasoning and it does not change:

- fit to **0–255 full range** — the encoder is full range, worth 1.17× the code
  values, and that is free;
- **reduced-range log**, fitted to the fp's measured dynamic range, not
  spec-exact DaVinci Intermediate. DVI spans ~16.5 stops and the fp delivers
  perhaps 12, so a spec-exact curve throws away ~70 of 256 codes on range the
  camera cannot produce;
- compose the inverse of step 1's measurement into the knots;
- **one generator, three outputs** — the camera-side table, a `.cube` and a DCTL
  — so the decode cannot drift from the encode;
- bake off the fitted curve against spec-exact DVI, scored as quantisation error
  against modelled sensor noise per level, at 8-bit. **If the fitted curve does
  not beat it by enough to justify shipping a DCTL, ship spec-exact and take
  Resolve's dropdown.**

`camera/build_logcurve_card.py` already does the knot arithmetic — curve
selection, pre-gamma composition, a monotonicity check after quantisation, and a
`knots.txt` beside the card so a clip can always be matched to what produced it.
Its table size and record layout are specific to the CEQ records and will need
changing for a 2048-entry `GAM_TOP` target.

## Step 3 — ship it

> **Rewritten 2026-09-22 by `results/invert/`.** This step said the switch would
> be an existing colour mode. **It cannot be** — the transfer function is global,
> so writing it gives log in every mode at once. The rest of the step was right
> and is now measured rather than reasoned.

**The switch is the card.** Card in, log; card out and battery cycled, stock —
which is how every fp_sup product ships, and it needs no menu work, no string
patching and no new UI. What that costs is the ability to toggle log without a
power cycle.

**Ship on mode Off, curve #82.** This was already the requirement — *it must be
colour-neutral*, and Teal & Orange carries a stylised colour matrix in 19 ISP
registers we cannot neutralise — and `results/invert/` §2a **measured** it:
inverting #82 gave a **neutral** negative in Off and a cast one in every other
mode. Grey stayed grey through the most hostile curve available, so the stage is
one shared table across R, G and B and the write is not landing on a matrix.

**Write into the README, not into the code:** every other colour mode is
unusable while fpLog is loaded, because each styles a log signal. Shoot in Off.

Then, in this order:

0. **§8 question 10 first — does a plain boot give log?** The upload fires on
   mode selection and the invert card prompted the operator for it, so this has
   never been tested alone. If the colour mode has to be touched after boot, the
   payload should drive it rather than the README explaining it.
1. **`PLAN.md` §7.1 — storage.** GB/min against stock. It is the objective, so
   it is the headline number, and it is a measured multiple or it is not stated.
2. **§7.6 — neutrality: already passed** in `results/invert/` §2a, qualitatively.
   Re-measure it on a grey wedge before release rather than shipping on an
   eyeball.
3. **§7.3 — banding**, against step 2's prediction. *If the prediction was
   wrong, the model is wrong, and that matters more than the measurement.*
3. **§7.2 — round trip against CinemaDNG.** The check that catches a curve which
   looks plausible and encodes the wrong thing.
4. §7.4–7.9 — grade headroom, clipping, neutrality, recording integrity, revert,
   every ISO.
5. **Decide and write down whether the LCD goes flat too.** `docs/ISP_PIPELINE.md`
   §1 found a plausible mechanism for keeping it Rec.709 — the ISP is configured
   per pattern, and `Mov` and `UpdateMov` are separate configurations. Untested,
   and `CURVE_TARGETS.md` target 4.

Release per `PLAN.md` §5 Phase 6: what was verified **and what was not**.
