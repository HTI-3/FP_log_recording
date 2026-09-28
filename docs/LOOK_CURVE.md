# The CEQ look records — format, and what they actually control

The stage proven to reach the recorded picture (`results/looksrc1/FINDINGS.md`):
overwrite the DRAM source, select the colour mode, the firmware uploads it.

**These are the colour equaliser's tables.** The ISP name pool names them:
`CEQ24_ORG` and `CEQ24_TGT` (`docs/ISP_PIPELINE.md` §2) — a 24-bin colour
equaliser with an *origin* array and a *target* array. That maps onto the record
exactly: `knots A` is identity in all 36 records, which is what an input axis
looks like, and `knots B` is the shaped target map.

It explains every observation at once, and replaces the elimination argument
that `results/logoff1/REFRAME.md` had to use:

| observed | because |
|---|---|
| writing `knots B` → green | the target map is rotated |
| writing `knots A` → magenta | the origin axis is rotated, the other way |
| Monochrome never changed | no chroma to equalise |
| contrast never moved, in any mode, in any run | a hue map has no luma term |

**So it cannot carry a log curve**, and not for want of trying: it is after the
YUV matrix and it is chroma. `docs/CURVE_TARGETS.md` is where the curve goes;
this page is the format reference and the record of what the mechanism proved.

Everything below is read out of `results/dram_21_09_2026/dram_C0000000.bin` and
is reproducible:

```bash
python3 tools/look_records.py results/dram_21_09_2026/dram_C0000000.bin
python3 tools/look_records.py --self-test
```

---

## The record — corrected 2026-09-22

**The layout published here until 2026-09-22 was wrong**, and every card in this
repository was built against it. The corrected layout, little-endian `u16`,
stride `0x124` (292 bytes):

| offset | count | what |
|---|---|---|
| `+0x000` | 24 | **knots, block A** |
| `+0x030` | 24 | gains, block A |
| `+0x060` | 24 | slopes, block A |
| `+0x090` | 24 | **knots, block B** |
| `+0x0C0` | 1 | **record id** |
| `+0x0C2` | 1 | zero |
| `+0x0C4` | 24 | gains, block B |
| `+0x0F4` | 24 | slopes, block B |

**What pins it:** on this grid, and on no other alignment, `+0x0C0` reads a
small distinct id and `+0x0C2` reads zero for **36 consecutive records**.
`tools/look_records.py` makes that check and refuses to print if it fails; its
self-test also requires the old alignment to be rejected.

### The error, and what it cost

The old table put the id at `+0x030` and the second knot array at `+0x092`. It
was built from one record read at the wrong start, and the `+0x092`/`+0x094`
disagreement with `docs/cards/blockb.md` was the visible symptom nobody chased.

**Consequence: every record address in this repository is a `knots B` address,
0x90 past the record it belongs to.** `0xC0B3B2E8`, the address of the
breakthrough, is `knots B` of the record at `0xC0B3B258`, whose id is 11.

That does not invalidate any hardware result — the cards wrote the array they
meant to write, and it reached the picture. It invalidates the *labels*:

| the repository said | it actually wrote |
|---|---|
| "block A of record *n*" | **knots B** of record *n* |
| "block B of record *n*" | **knots A** of record *n+1* |

So the green/magenta result reads: **writing `knots B` skews green, writing
`knots A` skews magenta.** Both are colour; neither is luma. The conclusion in
`REFRAME.md` stands, its mechanism does not.

## The bank

**One bank, 36 records, `0xC0B3AB80 .. 0xC0B3D490`.** A scan of all 64 MB for
the 24-knot identity array finds exactly 64 occurrences, and every one of them
falls in this bank — except four, below. There is **no second bank of this
shape anywhere in DRAM**, so the luma curve does not live in a record like this.

Ids run 1..39 with two duplicates (9 appears twice). **Id 11 is Teal & Orange**,
confirmed on hardware. No other id has been tied to a named colour mode.

### What is shaped, and what has never been touched

| array | stock content | ever written? |
|---|---|---|
| knots A | **identity in all 36 records** | yes — as "block B". Skews magenta |
| gains A | **shaped in 22 of 36 records** | **never** |
| slopes A | shaped in 13, zero in 10, uniform `02AB` in 13 | **never** |
| knots B | shaped in 13 records, identity in 23 | yes — as "block A". Skews green |
| gains B | uniform `0200` in all 36 | **never** |
| slopes B | uniform `02AB` or `0400` in all 36 | **never** |

**Two thirds of every record has never been written.** `gains A` is the array
that varies across the most colour modes, and it is untouched. That is the
cheapest untried lever in this table — `docs/CURVE_TARGETS.md` target 3 spends
one card on it, to pin the record semantics rather than to carry a curve.

Note also that the four records the `--record neutral` cards wrote — ids 16, 22,
2, 17 — have **identity knots B and shaped gains A**. Those modes do apply
something through this stage; the card wrote the one array in them that was
already identity, which is why nothing happened.

## The knots

24 knots at uniform input spacing of `65536/24 = 2730.67`, output `u16`.
Identity is `knot[i] = round(i * 65536/24)` — `0, 0AAB, 1555, …, F555`. Knot
*i* is the output for input `i × 2730.67`, the last knot sits at input 62805,
and inputs above that run on the final segment.

**Measured, not inferred:** these values appear byte-identical in the DRAM
source and in the ISP registers at `0x30212020`, and writing them changes the
recorded image.

## Gains and slopes — still not pinned

`0x0400` accompanies an identity curve, which makes `0x400 = 1.0` the natural
reading and `0x200` in the gain array `0.5` — or the two arrays use different
scales. In record 6 (id 11, Teal & Orange) `slopes A` is a uniform `0x2AB`
while `knots B` is plainly non-uniform, so the slopes are **not** simply the
per-segment derivative of the knots beside them.

A reading that fits the field order better than "two curves": the six arrays may
describe **one** curve — `knots A` the input axis (identity everywhere, as an
axis would be), `knots B` the output values, and the gains and slopes its
per-segment parameters. That is **inferred**, and one card settles it.

## The isolated record at `0xC0B392B0`

Four 24-knot identity arrays in the dump are not in the bank:

```
0xC0B392B0   a record-shaped object, 0x18D0 before the bank
0xC3424F70   |
0xC3425318   |  three byte-identical copies, in live RAM ABOVE the
0xC3824414   |  firmware image (which ends at 0xC2F30800)
```

Its `knots A` is identity, but its **`gains A`, `slopes A` and `knots B` match
no record in the bank**. So it is *composed* at runtime, not copied from a
template — and it is the only look record in the dump with live copies.

**Nothing in this project has ever written it, or looked at it.** Three copies
is the same pattern that broke OG3K v0.2.2a, where one of three was missed.
What composes it, and from what, is an open question worth one search.

---

See `docs/BIT_DEPTH.md` for the bit depth of every stage in the chain and where
the real constraint is.
