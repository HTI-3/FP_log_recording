# 10-bit MOV — the plan

Written 2026-09-23, on branch `10-bit`, from the findings in
`results/encrec_1/`, `results/encrec_2/`, `results/dram_mov_23_09_2026/`,
`results/dram_rec_23_09_2026/`, `results/dram_uhd_23_09_2026/` and
`results/code_10bit/`, plus `docs/BIT_DEPTH.md` and `docs/CHROMA_CEILING.md`.
**Firmware Ver.5.02 only. RAM only.**

The objective is unchanged: `PLAN.md` §8 q.2. **10-bit is 4× the output code
values** and the biggest lever left against banding in a lifted log shadow
(`docs/BIT_DEPTH.md`). It is still an upside to check, not a branch to design
around. The plan below puts the answer first and the build after it.

---

## 1. What the findings establish

| | status | source |
|---|---|---|
| Stock stream: H.264 High (`profile_idc 100`), 4:2:0, **8-bit**, full range, ALL-I, VBR, ~77 Mbps FHD | measured | `results/mov_recording/` |
| The SPS/PPS **are** in ARM DRAM — at `0xC38D4060`, only during and after a take, not at boot or idle | measured | `dram_rec`, `dram_uhd` |
| Nothing in DRAM points at `0xC38D4060`; the descriptor before it carries addresses outside the ARM window (`0x66681000`, `0x685AB6C0`) | measured; *who writes it* inferred as the non-ARM side | `dram_rec` §1 |
| The recording parameter block starts at `0xC38D62BC`, reached only by pointer, and belongs to **`XC_MovClass`** (the muxer), not the encoder | measured / inferred | `code_10bit` |
| The two `8`s at block `+0x2C` and `+0x84` survive FHD→UHD; not proven to be bit depth | measured | `dram_uhd` |
| **The encoder's input luma plane is 1 byte/sample** at FHD and UHD (`W × H_aligned × 1`) | measured | `dram_uhd` §1 |
| A bitrate cap in kbps at `+0x064` (138,500 FHD / 438,500 UHD) | inferred, fits both | `dram_uhd` |
| Every `10bit` string in the image is sensor- or DNG-side; **no encoder-side 10-bit / High10 / P010 name** | measured, for the strings searched | `code_10bit` |
| The ARM queues requests to a sequencer. ~~The ISP register bases are not built anywhere in the image~~ — **corrected 2026-09-23:** that search was ARM-only; Thumb-2 code builds `0x3011xxxx`/`0x3021xxxx` in the sequencer's command list (`0xC019C810`) | measured | `code_10bit` §YUV_PACK |
| The sensor offers `movie_raw_10bit` / `movie_raw_12bit` readouts | measured | `docs/BIT_DEPTH.md` |
| **Register reads in live view freeze the camera** — twice, at different addresses | measured | `encrec_1`, `encrec_2` |
| **A DRAM dump during a take is safe** and does not harm the MOV | measured | `dram_rec` |
| UHD ALL-I (~390 Mbps) is stopped by the card after 4 s | confirmed by operator | `code_10bit` |

## 2. What 10-bit MOV needs — all six, not one

A 10-bit file is only worth having if every link carries more than 8 bits.
Changing the SPS alone would give a file that *says* 10-bit and holds 8-bit
data, or a stream nothing can decode.

1. **Data** — `YUV_PACK` hands the encoder more than 8 bits per sample. If it
   packs to 8 bits, a 10-bit encode is 8-bit data with two zero LSBs.
2. **Encoder** — the hardware implements High 10 (`profile_idc 110`).
3. **Configuration** — something the firmware writes tells it to.
4. **Buffers** — the planes at block `+0x000`, `+0x028`, `+0x104`, `+0x038`
   and the `{address, size}` table at `0xC38D624C..0xC38D62BB` grow together
   (≥1.25× packed, 2× in 16-bit words).
5. **Headers** — the SPS carries `profile_idc 110`, `bit_depth_*_minus8 = 2`.
   If the encoder writes it (as §1 suggests), this follows from 3 for free.
6. **Container** — the `avcC` box carries that SPS and its High-profile
   extension bytes. The muxer already receives SPS copies (`0xC3B175E8`,
   `0xC3B17758`), so this probably follows from 5; the template at
   `0xC2EF4F40` says whether the extension bytes are copied or constant.

**2 and 1 are the gates.** 3–6 are engineering once they pass.

**The memory for 4 already exists.** FHD with 16-bit samples needs a
1920 × 1088 × 2 = 4,177,920-byte luma plane; the camera allocates
8,294,400 bytes for UHD's. So a 10-bit experiment belongs at **FHD**, where the
buffers the firmware already knows how to allocate are large enough — and where
the card keeps up (UHD does not, §1).

## 3. The honest prior

Most likely outcome: **not reachable.** The only chroma/format label in the
whole image is the HDMI `4:2:2 8bit`, no encoder-side 10-bit name exists, and
the luma plane is sized for 8 bits at every resolution seen. Against that: the
sensor side does offer 10 and 12 bits, and encoder IP of this class often
implements profiles the product never exposes. The plan is ordered so the
cheapest evidence that could say **no** comes first.

---

## 4. The steps

Each step has what it produces and what would stop it. Host-side steps need no
camera. Camera steps follow `RUNBOOK.md`: one variable, clean boot, old files
deleted.

### Phase A — finish the static work *(host-side, the rest of `code_10bit`)*

**A1. Who writes the parameter block, and where its `8`s come from.** Follow
the writers of `0xC38D62BC +0x2C` / `+0x84` back from the `XC_MovClass`
handlers (`0xC06B1178 … 0xC06B2528`) to the value's origin — a constant, a
format row, or a field passed in from the recording manager
(`MovRecFunc.cpp`, code at `0xC0388BF8`).
→ *Produces:* the `8`'s provenance.
→ *Stops if:* both are container-level values (e.g. a sample-description
field) that nothing on the encode side reads. Then they are labels, and A2
carries the question.

**A2. Who writes the SPS at `0xC38D4060`.** Resolve the address map behind the
descriptor at `0xC38D4010` (find another buffer whose contents appear under
both an ARM and a `0x66…`/`0x68…` address and take the offset). If an ARM
routine composes the SPS, its bit-depth and profile writes are the lever. If the
other side writes it, the ARM sends a request, and A3 is how to find it.
→ *Produces:* "ARM-built" or "encoder-built", with the address map.
→ *Stops if:* ARM-built with `profile_idc` and `bit_depth` as literals and no
branch — that is an 8-bit-only driver. Record it and go to §5.

**A3. `YUV_PACK` on the `Mov` pattern.** *Started 2026-09-23: the registers, their shadow and the firmware's own dump are found (`results/code_10bit/` §YUV_PACK); the camera-side read is `docs/cards/yuvpack.md`, run once (`results/yuvpack_1/`). **Result: YUV_PACK is the wrong stage** — no width/stride/format field, selectors only ever 0, enables off in a Mov take. Gate 1 moves to the stage that writes the frame to DRAM.* In the ISP stage map
(`tools/isp_map.py`), read `YUV_PACK`'s setting per pattern (`Mov`,
`UpdateMov`, `HdmiRaw`, `Jpg`). A format field that differs between patterns
names the packer's output formats; an 8-bit-only packer ends the project here
(gate 1).
→ *Stops if:* every pattern packs 8-bit.

### Phase B — find the encoder's own configuration *(camera, read-only dumps)*

The proven safe method, used exactly as in `dram_rec`/`dram_uhd`: **the
read-only dump card during a take, one setting changed, then a diff.** No
register reads — they froze the camera twice.

**B1. Dump pairs that move encoder settings but not the muxer's.**
In order of what they isolate:

1. **ALL-I vs the long-GOP option**, if the menu offers one — GOP structure is
   an encoder setting the muxer barely sees;
2. **the MOV quality / bitrate setting**, if selectable — confirms `+0x064`
   and finds any second copy of it outside the MovClass block;
3. **24 vs 25 fps** — separates timing fields from everything else.

Search each diff **outside** `0xC38D62BC` for a structure where
`100` (profile), `51` (level), `1` (chroma format) and `0`/`8` (bit depth) sit
together with a field that moved. That structure, or the request block that
builds it, is the encoder configuration.
→ *Produces:* the encoder's parameter block, or its request block (the same
shape as the sigpro request block `0xC34139AC`, `docs/ISP_PIPELINE.md` §7.1).
→ *Stops if:* no candidate appears in any diff. Then the configuration lives
wholly on the encoder side, and the only remaining question is whether its
request carries a bit-depth field (B2).

**B2. Follow the block to its builder and its source.** "Do not move the data,
change what the firmware moves": find the DRAM source the firmware builds the
encoder config *from* — a format table (candidate: `0xC0B51040`,
`{id, width, height, index}` rows, `results/encrec_2/` §3), a mode-table row
(`LiveViewModeMgr`'s `{table, imgr, sig}` and its `"recSize: (%dx%d) @ %d bit"`),
or a constant.
→ *Produces:* a RAM address that, written before record is pressed, changes
the encoder's bit depth.
→ *Stops if:* the builder has no bit-depth input — the value is fixed in the
encoder request. That is the same answer as A2's stop.

### Phase C — the decisive experiment *(camera, one write)*

**C1. Write only the bit-depth source, FHD, 2-second take.** One card, one
value, written from AutoRun before the take, exactly like the Log C and invert
cards. Then:

```bash
ffprobe -show_streams A001_xxx.MOV        # profile, pix_fmt, bits_per_raw_sample
```

| outcome | reading | next |
|---|---|---|
| `High 10`, `yuv420p10le`, plays | **gate 2 passes** | C2 |
| stream still 8-bit | wrong source, or the value is re-derived later | back to B2 |
| file corrupt / no file / freeze | buffers too small, or encoder rejects it | C1b |

**C1b. Resize the buffers with it.** Same card, plus the plane/frame sizes from
A1 and the `{address, size}` table, scaled for 16-bit samples — within the UHD
sizes, which the firmware is known to allocate. A freeze here is recoverable by
battery-out, like every card in this repository.

**C2. Is the data really 10-bit?** Shoot a smooth defocused gradient, decode to
16-bit, histogram the luma codes. **Codes only at multiples of 4 mean
`YUV_PACK` is 8-bit** — the file is 10-bit, the picture is not (gate 1 fails).
Populated in between means it passed. Try the sensor's `movie_raw_12bit` /
`10bit` readout here as a separate card if the codes are thin (`docs/BIT_DEPTH.md`
lever 2).

### Phase D — make it a product *(only after C2 passes)*

**D1. Container.** Check the `avcC` box and its High-profile extension bytes
against the SPS; Resolve, ffmpeg and QuickTime must all open the file. If the
template at `0xC2EF4F40` writes constant extension bytes, patch those in RAM
too.

**D2. Log C at 10 bits.** The gamma table is already 13-bit out
(`docs/BIT_DEPTH.md`), so the curve itself needs no change; the decode in
`share/decode` needs its scale checked for 10-bit legal/full range.

**D3. Storage.** The objective is storage (`PLAN.md` §1). Measure MB/min at the
stock bitrate cap, then try the cap at `+0x064` as its own one-variable card —
10-bit may justify a lower cap than 8-bit for the same banding.

**D4. Verification and share.** `PLAN.md` §7 with a 10-bit clip; `share/`
regenerated with `tools/make_share.py`; FHD only until UHD's card-speed limit
is addressed separately.

## 5. When to stop, and what to write down

Stop, and record the answer in `docs/BIT_DEPTH.md` and `PLAN.md` §8 q.2, when
any of these holds:

- **A2** finds an ARM SPS builder with no bit-depth branch;
- **A3** finds `YUV_PACK` 8-bit on every pattern;
- **B1 and B2** find no bit-depth input anywhere between the recording manager
  and the encoder request;
- **C1/C1b** exhaust the found sources without a High 10 stream.

Any one of those means 10-bit MOV needs an encoder the firmware does not drive,
which is out of scope. **fpLog ships 8-bit Log C either way** — it already does.

## 6. Safety — what this plan does not do

- **No register reads in live view or during a take.** Both encrec freezes
  were register reads; `docs/cards/encrec.md` stays DO NOT RUN.
- **No direct writes to codec or ISP registers** — they are shadowed behind a
  sequencer and ignored (`results/knottest/`). Write the DRAM source.
- **No SPS-only patch.** Relabelling the header without the encoder producing
  10-bit is a label, not a capability (`results/mov_recording/` §4).
- RAM only; `RUNBOOK.md` and `PLAN.md` §6 apply to every card.

## 7. Order and cost

| step | where | cost | can end the branch |
|---|---|---|---|
| A1 writers of the `8`s | host | hours | no — narrows |
| A2 SPS writer + address map | host | hours | **yes** |
| A3 `YUV_PACK` per pattern | host | an hour | **yes** |
| B1 one-variable take dumps | camera ×2–3 | ~15 min each | yes, weakly |
| B2 config builder and source | host | hours | **yes** |
| C1 / C1b the write | camera | one card each | **yes** |
| C2 gradient histogram | camera + host | one take | **yes** |
| D1–D4 | both | days | no |
