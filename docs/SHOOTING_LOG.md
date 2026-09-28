# Confirming a curve is right

**Method, not target.** Four checks, weakest to strongest, that say whether a
written curve encodes what it was meant to encode. They apply to whatever stage
the curve ends up in, so they outlive any particular card.

> **The card table that used to head this page has been removed.** It told you
> to shoot log in mode Off via `camera/build_logcurve_card.py --record neutral`.
> Those records are chroma (`results/logoff1/REFRAME.md`) and the four "neutral"
> ones hold an identity array in exactly the field that card writes, so the
> procedure could not have worked. `docs/CURVE_TARGETS.md` is the live plan.

Nothing here needs a chart. **Shutter time is the reference**: doubling it
doubles the light, exactly, and no printed chart spans the 10+ stops this needs.

---

## 1. Recover the transfer function from an exposure ramp

Point at a **flat, evenly lit, defocused** surface — a wall, paper, an overcast
sky — with ISO, aperture and focus fixed. Shoot one short clip at each of:

```
1/50   1/100   1/200   1/400   1/800   1/1600   1/3200   1/6000
```

Daylight or a DC source: **mains flicker ruins the short exposures.** Make the
last clip clearly black and the first clearly clipped.

```bash
python3 tools/measure_transfer.py <dir of clips> --out transfer.png
```

Shutter speeds are read from the camera's own metadata (the `SIGM` maker atom in
`udta`, `ExposureTime` at tag `0x829A`), so no renaming.

Shoot the ramp **twice**: once with the curve at identity, once with the curve
written.

- The **identity** ramp gives whatever gamma the stage sits behind. That number
  is what a log curve has to be composed against — `Log(gamma⁻¹(x))` — because a
  stage late in the pipeline receives an already-curved signal, not scene light.
- The **written** ramp says whether the composition came out as intended.

**What right looks like:** roughly equal code-value spacing per stop across the
mid-range. That is what log is *for* — a stop of light costs the same number of
code values wherever it falls.

### What has already been measured this way

The Off half of the `results/neutralize` ramp is an identity-stage ramp and was
read for the pre-gamma. Centre-patch mean alone reads only the toe; whole-frame
percentiles over the well-exposed range (codes 60–200) fit **gamma 0.47–0.48,
i.e. a pre-gamma of ~2.1**. Lower codes fit steeper, which is the toe every
display gamma has near black and which a pure power law does not describe.

**Caveat, and it matters:** that was a mixed scene rather than a flat field, and
the top never clipped cleanly, so the highlight end is under-measured. Treat 2.1
as provisional until a proper flat-field ramp replaces it.

## 2. Round-trip against CinemaDNG — the strongest check

Shoot one scene with a wide tonal range twice: once as log MOV, once as
CinemaDNG. The DNG is linear and is ground truth.

Linearise the MOV with the inverse of your curve, then compare per patch against
the DNG. **They should agree to within the 8-bit quantisation step.** If they
diverge at one end, the composition in §1 is wrong there.

This is the check that catches a curve which *looks* plausible but encodes the
wrong thing.

## 3. Grade headroom

Pull ±2 stops and shift white balance in Resolve. Look for posterisation and
chroma break-up. **A log file that cannot take a grade has no reason to exist**,
and 8-bit 4:2:0 is where this is decided.

## 4. Banding — the real risk

Shoot a smooth gradient at base ISO. Count distinct code values across it, log
against stock, and look again after a 2-stop lift.

If the stage that carries the curve is a 24-knot piecewise-linear block, that is
linear interpolation between 24 points, and **log puts its precision exactly
where the knots are sparsest**. If it bands here, no cleverer fit rescues it —
the stage does not have the resolution, and that is a finding rather than a bug.

---

## Before any of this is worth doing

A curve has to reach the picture first, and no write has yet changed contrast.
`docs/CURVE_TARGETS.md` is what stands between here and there; this page is what
you do once one of its targets passes.
