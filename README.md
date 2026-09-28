# fpLog - NOT WORKING

Recording a log-encoded picture on the SIGMA fp, from the SD card, in RAM only.

**Firmware Ver.5.02 only** —
`c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8`.
Every address here belongs to that build. Nothing in this repository writes to
NAND, EEPROM or any other non-volatile store; a battery-out cold boot reverts
everything. The one exception is a `menu Set…` command, which writes a camera
*setting* and does persist — see `docs/cards/tonedrive.md`.

Built on [ijigen/fpSup](https://github.com/ijigen/fpSup), checked out at
`resources/fp_sup`.

---

## Where it stands

> ### fpLog records log. Confirmed on hardware, 2026-09-22.
>
> Colour mode **Off** carries a bit-exact **ARRI Log C V3, EI 800** transfer
> function, written from the SD card into DRAM, in RAM only. The table was read
> back off the camera and matches the ARRI paper's own numbers to **0.5 of 8190
> codes** — integer rounding and nothing else. Resolve's stock *ARRI LogC3 EI800*
> dropdown decodes it. [`results/log2/`](results/log2/FINDINGS.md),
> [`share/`](share/), [`docs/cards/logc.md`](docs/cards/logc.md)
>
> **What is NOT measured: how many stops it carries.** The exposure series is
> unshot, and so is all of `PLAN.md` §7 — including storage, which is the
> project's actual objective. Nothing here is verified beyond "it is Log C and
> the picture is clean."

> ### The transfer function is reachable. Proven 2026-09-22.
>
> Curves #82 and #16 of the `GAM_TOP GAMMA TABLE` registry were inverted in
> DRAM and the colour mode toggled to force the upload. **The picture went
> negative in live view AND in the recorded MOV** — the first write in this
> project to reach a recorded file. `PLAN.md` §3's kill criterion is answered
> **yes**. [`results/invert/FINDINGS.md`](results/invert/FINDINGS.md)
>
> **In mode Off the negative was neutral; every other mode was cast, each
> differently.** Neutral-in-Off means **one table drives all three channels** —
> a per-channel stage could not have produced it from one write — and it passes
> `PLAN.md` §7.6 early and for free. The casts are the other modes' matrices and
> colour equalisers styling a signal whose transfer function was turned upside
> down, which is expected and says nothing bad about the stage.
>
> **So fpLog ships on mode Off, curve #82**, and the curve is global rather than
> per colour mode. `PLAN.md` §4B said the on/off switch would be a colour mode
> and it cannot be — but **the card is the switch**, as it is for every fp_sup
> product. The cost is that every other colour mode is unusable while fpLog is
> loaded. Shoot in Off.
>
> Also retracted by the same run: `0x30210594` is the knot **axis**, not the
> curve. It never moved while the picture inverted.

**The container is decided and measured.** MOV/H.264, because storage is the
objective and the whole raw family caps out near 2× while MOV is **7.7× smaller**
than stock 12-bit CinemaDNG. The stock clip measures 1920×1080, 24.000 fps
exactly, **8-bit 4:2:0 full range, ALL-I, VBR, 77 Mbps** — full range and ALL-I
both help a log curve more than expected. `results/mov_recording/FINDINGS.md`

**A mechanism for changing the picture is proven.** This is the real asset:

```
write a DRAM source  ->  select the colour mode  ->  the firmware uploads it
                                                 ->  0x30212020  ->  picture changes
```

Confirmed end to end on hardware — DRAM source, ISP registers and the rendered
image all changed. `results/looksrc1/FINDINGS.md`

**The rule it bought: do not move the data, change what the firmware moves.**
Four earlier writes failed for want of it, every one of them aimed at a place
*inferred* to be the source. The one that worked was found by searching the
64 MB dump for the exact values the hardware was holding.

**The stage it was proven on is the colour equaliser.** The ISP names it —
`CEQ24_ORG` / `CEQ24_TGT`, a 24-bin hue map — which explains every observation:
writing one array skews green, the other magenta, Monochrome never changed, and
contrast never moved in any mode across four runs. So the mechanism works and is
pointed at a chroma table. `results/logoff1/REFRAME.md`, `docs/LOOK_CURVE.md`

**The pipeline is now mapped, out of the dump.** The ISP has a 149-entry stage
map and **eight named patterns** — `Jpg`, `Dng`, `HdmiRaw`, `Mov`, `UpdateMov`,
`Cdng`, `UpdateCdng`, `JpgScreen` — the `(pattern)` argument every `pic`
sub-function takes. MOV and CinemaDNG are separate ISP configurations, and each
has its own *monitoring* configuration beside it. The DNG file is never
de-bayered; a de-bayered path runs in parallel for the LCD.
`docs/ISP_PIPELINE.md`

**The transfer function is `GAM_TOP GAMMA TABLE`**, which sits beside
`GAM_TOP YCMAT` — so it acts on **RGB, before YUV conversion**. That is where a
log curve belongs. `PST_TOP Y_GAMMA` and `CEQ_YGAM` come after it on Y alone,
and a log curve on luma with chroma left behind is not a log encoding.

**Its data is a 452-curve registry** at `0xC0971118`, 2048 × u16 each,
`0xC0971F34..0xC0B34F34`, decimated 32:1 to the 65 knots the hardware holds.
The colour mode selects one — Off → 82, Teal & Orange → 16.

**It was recorded as inert, and that verdict is withdrawn.** The test repointed
the selector live *without changing the colour mode*, and the firmware uploads
**when a mode is selected** — so it changed a pointer and never triggered the
read. Re-running it with a mode toggle is the cheapest experiment in the project.

**That re-run has been shot, and it passed.** `camera/build_invert_card.py`
**inverts** curves #82 (Off) and #16 (Teal & Orange) — `v := max(table) − v` —
and asks the operator to toggle between exactly those two modes to force the
upload. Inverted rather than flattened because **a negative picture is not a
judgement call**, and both curves rather than one because every write aimed at
Off has failed while the one that worked was aimed at Teal & Orange. Three
rounds of four windows; `tools/check_invert.py` names which of the four outcomes
it was. `docs/cards/invert.md`

**→ Where a log curve should sit, ranked: `docs/CURVE_TARGETS.md`.**

## Repository

| | |
|---|---|
| **`docs/CURVE_TARGETS.md`** | **the plan: where a log curve should sit, ranked, with what confirms or kills each** |
| **`docs/ISP_PIPELINE.md`** | **the reference: ISP stage map, the eight patterns, MOV vs CinemaDNG, module map, missing data** |
| `docs/GAMMA_PLAN.md` | once a target passes — measure the stage, fit the curve, ship |
| `PLAN.md` | the project: container reasoning, curve choice, phases, safety, verification |
| `docs/MAIN_GAMMA.md` | the negative record — what is ruled out, what was ruled out prematurely, and why |
| `docs/LOOK_CURVE.md` | the look-record format, corrected 2026-09-22 |
| `docs/BIT_DEPTH.md` | bit depth per stage, and where the real constraint is |
| `docs/CHROMA_CEILING.md` | why 4:4:4:4 is not reachable, and what the actual ceiling is |
| `docs/SENSOR_MODES.md` | the 70-entry sensor mode table, the 14 geometries, and whether 2.6K is reachable |
| `ADDRESSES.md` | 387 addresses, generated by `tools/gen_addresses.py`, with confidence per row |
| `changelog.md` | append-only record of every change and why |
| `docs/` | `FIRMWARE_BASE.md`, `PIPELINE.md`, `TONE_CURVE_HUNT.md`, `ENCODER_PROBE.md` |
| **`share/`** | **the distributable card — AutoRun.txt, the builder, the decode. Generated by `tools/make_share.py`; `--check` proves it is current** |
| **`docs/cards/logc.md`** | **the Log C card: write the curve, shoot the series, score it** |
| `docs/cards/invert.md` | the decisive experiment: invert the transfer function and see whether the picture follows |
| `docs/cards/` | one page per card: how to run it and how to read it |
| `camera/*.S`, `camera/build_*.py` | payload sources and card builders |
| `camera/cards/` | generated cards — rebuild, do not edit, gitignored |
| `results/` | one directory per hardware run, each with its own `FINDINGS.md` |

Cards are read-only unless the header says otherwise.

```bash
python3 camera/build_dump_card.py --out camera/cards/dump_card   # e.g.
python3 tools/look_records.py results/dram_21_09_2026/dram_C0000000.bin
```

Tools with a `--self-test`: `find_curves.py`, `find_encoder_cfg.py`,
`diff_selector.py`, `look_records.py`, `xref.py`, `isp_map.py`,
`check_invert.py`, `logc.py`, `verify_logc.py`, `check_logc.py`, `check_encrec.py`,
`check_yuvpack.py`, `check_shadowbank.py`, `shadow_map.py`.
`plot_logc.py` draws the Log C tables against the stock curve (`docs/logc_curves.png`).

**The stock transfer function is identified, not fitted:**
`stock curve #82 == sRGB OETF(index / 1918)`, to within 2 code values of 8190.
So the gamma table's input is scene-linear with **diffuse white = 1.0 at index
1918** and 18% grey at index 345 — which is what makes ARRI's *exposure-value*
Log C parameters the right ones to write. `tools/logc.py`, `docs/cards/logc.md`

`xref.py` finds the code that builds a given address — `movw`/`movt` pairs,
literal pools and plain pointers. `isp_map.py` prints the ISP name pool, the
pattern table, the shell command tables and the curve registry.

`results/` holds ~150 MB of captures, of which the DRAM dump is stored twice —
`chunks/` is the raw capture and `dram_C0000000.bin` is its exact concatenation.
Either can be deleted without losing information.

---

## ~~What would end it~~ — it did not end

*Kept as written, because the condition it names is exactly the one that was
tested:* "If `GAM_TOP GAMMA TABLE` fails with the upload trigger … then fpLog
cannot be done this way."

**It did not fail.** `results/invert/` is that experiment, and the picture went
negative. The rule that got there is the one worth keeping:

> **Do not move the data, change what the firmware moves.**

Six verified writes had failed to reach the picture; both that succeeded wrote a
DRAM source the firmware then uploaded. **Do not go back to poking registers** —
including for the hardware LUT, which this run showed is somewhere we have never
dumped and which fpLog does not need.
