# The ISP and the two recording paths

What the camera actually does to a frame, read out of the DRAM dump. This is
reference, not plan — `docs/CURVE_TARGETS.md` is where a log curve goes.

Everything here is reproducible:

```bash
python3 tools/isp_map.py results/dram_21_09_2026/dram_C0000000.bin
python3 tools/xref.py    results/dram_21_09_2026/dram_C0000000.bin 0xC0BAC14C --disasm 4
```

Both tools self-test. Claims are **[measured]** (read out of the dump) or
**[inferred]** (a reading of what was measured, which could be wrong).

---

## 1. The eight ISP patterns — the thing that was missing

**[measured]** A pointer array of eight names at `0xC0B38A6C`:

| # | name | what it is |
|---|---|---|
| 0 | `Jpg` | stills JPEG |
| 1 | `Dng` | stills DNG |
| 2 | `HdmiRaw` | HDMI raw output |
| 3 | `Mov` | **MOV record** |
| 4 | `UpdateMov` | **MOV live view / monitoring** |
| 5 | `Cdng` | **CinemaDNG record** |
| 6 | `UpdateCdng` | **CinemaDNG live view / monitoring** |
| 7 | `JpgScreen` | JPEG screennail |

These are the `(pattern)` argument that **every** `pic` sub-function takes —
`pic set (pattern) …`, `pic shading (pattern) …`, and so on. The ISP is
configured per pattern, and the firmware's own shell can address them.

**The record/monitor pairing is the important part.** `Mov`/`UpdateMov` and
`Cdng`/`UpdateCdng` are separate configurations of the same hardware. A camera
recording CinemaDNG is running `Cdng` for the card **and** `UpdateCdng` for the
LCD, HDMI and histogram, at the same time. **[inferred, from the pairing and
from `LiveViewModeMgr` reporting `raw`, `small_raw` and `recSize` as three
separate streams]**

### Why it matters to fpLog

1. **A tone curve is live during CinemaDNG recording and reaches only the
   monitor.** A write that "did nothing to the DNG" is the expected result, not
   a failed write.
2. **`PLAN.md` §8 question 5 — can the LCD stay Rec.709 while recording log? —
   has a plausible mechanism for the first time.** Two patterns, configured
   independently, is exactly the shape that question needs. Untested.
3. `pic set <pattern> <0:off | 1:only tag | 2:reset>` is a per-pattern ISP
   handle **reachable from a card today** and never used.

## 2. The stage map — 149 names at `0xC07D36A4`

**[measured]** A packed pool of block and function names, `\n\0`-terminated.
Grouped by block prefix, in pipeline order **[inferred from the prefixes and
from where `YCMAT` sits]**:

```
SIG0     DELTA DARK · DARK SHADING · DS_SEL · BAYER_NR · FPNR · RWMEDF · SW_DCT
         RAW_CORR · RAWSHAD_LINEAR · DLTEXP · RAWBLT · RAWOUT · VLN_C · NLmeans
SIG1     RAW ZOOM · SHADING1 · SHADING2{,_R,_B,_GR,_GB} · WHITE BALANCE · 3DDNR
         GRV_C · RAWOUT
   |                                             <-- raw Bayer to here
PRE_TOP  GAPSUP · APKNEE · RWAPKNEE · HSEP · CSEP · MEDF · LM
         CORRECT_G · GNR · APGEN · SHUSA_EXT     <-- demosaic
   |
MAT_TOP  IGAMMA -> RGBLMAT -> PSTIGAM · PSTAPKNEE          linear RGB, matrix
   |
GAM_TOP  GAM_BAS · GAMINT · GAM_GS GAMDEC · GAMMA TABLE · SBUS GAMMA
   |                                             <-- the transfer function, in RGB
GAM_TOP  YCMAT · RGBMAT_PL                       <-- RGB -> YCbCr
   |
PST_TOP  Y_GAMMA · CUVCONT · CKNEE · CSUP · ECSUP · APSUP · SHOOT_G
         YUVHMF · YUVIIR · YSHD_C · CUVLPF YLPF · CUVAREA CARE_SEL · DITHER
   |
CEQ      ORG · TGT · CEQ24_ORG · CEQ24_TGT · YGAM · Y_GAMMA · KNEE · CLIP
         CORING · CORING2 · OFFSET · COMPATI     <-- colour equaliser
   |
YMED_TOP · FIR_TOP · BLT_YUV/NLM · CENH · DOPT_* · PSF_TOP · MT2_TOP · HSR_TOP
TMAP · CONTRAST · HDR_HIST · ROTATE · ZOOM · DIS · DHAZ · TNCR · MLNR · DEFC
   |
YUV_PACK  ->  H.264 encoder
```

Also in the pool: `V LATCH` (`0xC07D3A00`) and `VSYNC` — a shadow-register plus
vertical-latch design, which is why direct MMIO pokes at `0x3021xxxx` are
ignored (`results/knottest/FINDINGS.md`).

### Three findings from the names

**`CEQ24_ORG` / `CEQ24_TGT` names the table this project has been writing.**
A 24-entry colour equaliser with an *origin* array and a *target* array — which
is exactly the record format in `docs/LOOK_CURVE.md`: `knots A` identity in all
36 records (the ORG axis), `knots B` shaped (the TGT map). It explains every
observation at once: green from writing TGT, magenta from writing ORG,
Monochrome unaffected (no chroma to equalise), contrast never moving (a hue map
has no luma term). `results/logoff1/REFRAME.md` was right, and now for a
positive reason.

**`GAM_TOP` is a segmented gamma.** `GAM_BAS` (base) + `GAMINT` (interpolate) +
`GAM_GS GAMDEC` (decimate) is the standard arrangement: the table holds knots,
the hardware decimates the input to pick a knot pair and interpolates between
them. This is why a table's *length* says nothing about the input width — see
`docs/BIT_DEPTH.md`.

**`GAMMA TABLE` sits beside `YCMAT`, so it acts on RGB, before YUV conversion.**
`PST_TOP Y_GAMMA` and `CEQ_YGAM` / `CEQ_Y_GAMMA` come after it, on Y alone.
That ordering decides where a log curve belongs and is the single most
consequential thing on this page — `docs/CURVE_TARGETS.md`.

## 3. The two recording paths

```
                        IMX410
                          |   imager mode sets readout: 8 / 10 / 12-bit
                          |   (no 14-bit movie mode -- imager set_gain_state)
                          v
        LiveViewModeMgr resolves a mode into  { table, imgr, sig }
        library/LiveViewState/src/LiveViewModeMgr.cpp
        format string: "table: %d, imgr: %d, sig: %d, "
        and reports "raw: %dx%d", "small_raw: %dx%d", "recSize: (%dx%d) @ %d bit"
                          |
                          v
        XC_LiveViewRawMemInterface · XC_LiveViewSmallRawManage
        XC_LiveViewDispParamWithRaw · XC_LiveViewStateRawInfo
                          |
          +---------------+----------------------------------+
          |                                                  |
   pattern Cdng (5)                            pattern Mov (3) / UpdateMov (4)
   NOT DE-BAYERED                              full ISP, as mapped in §2
          |                                                  |
   XC_RecMgrRawCapture                          XC_MovSigYuvOutParam   (YUV)
   XC_RawCaptureRequestInterface                library/SigProcess/MovSigProcess
          |                                                  |
   framework/recMgr/CinemaDngFile.cpp           H.264 encoder
   XC_RecMgrTagCinema                                        |
   library/FileMgr/XC_DngTileFormatter.cpp      library/MovClass/XC_MovClass{,Conv,File}
   hal/RawCD/XC_HalLjpeg.cpp:                               |
     NoCompress | SwitchedRunLength                         |
     (SRLEByte / SRLEWord / SRLEDWord)                       |
          |                                                  |
   CINEMA\...  + cine_log.txt                   DCIM\...  + mov_log.txt
   MovRecFuncStateCinemaDng                     MovRecFuncStateREC
```

### Is DNG ever de-bayered? No — but a de-bayered path runs beside it

**[measured]** evidence that the DNG file is not de-bayered:

- `MovRecFuncStateCinemaDng` is a **sibling** of `MovRecFuncStateREC` in the
  recorder state machine, not a variant of it. Full state list: `OFF`, `REC`,
  `RECSTART`, `RECHOLD`, `RECWAITAF`, `WAITAF`, `HOLD`, `CONT`, `HIGHCONT`,
  `INTERVAL`, `THR`, `CinemaDng`.
- The CinemaDNG compressor is `hal/RawCD/XC_HalLjpeg.cpp` and offers
  `NoCompress` and `SwitchedRunLength` — run-length coding, which only makes
  sense on Bayer, and which is why fp CinemaDNG measures as effectively
  uncompressed (`PLAN.md` §1).
- **`XC_MovSigYuvOutParam` is the only `*OutParam` type in the entire image.**
  The signal processor's output contract is YUV; the DNG path has no equivalent
  because it consumes the raw buffer directly.
- The DNG writer is a *file format* class (`XC_StillFileFormatDngTh`,
  `XC_DngTileFormatter`), not a sig-process class.

**[inferred]** evidence that the ISP still runs: `UpdateCdng` exists as its own
pattern, and there would be no reason for an ISP configuration attached to
CinemaDNG unless the ISP were running during CinemaDNG recording.

## 4. Module map

**[measured]**, from assert strings — the firmware carries 391 distinct
`src/...` source paths.

| stage | module |
|---|---|
| sensor | `hal/ImageSensor/src/config/IMX410/ImageSensor_factoryIMX410.c` |
| mode arbitration | `library/LiveViewState/src/LiveViewModeMgr.cpp`, `FieldAngleTableMgr.cpp` |
| raw buffers | `XC_LiveViewRawMemInterface`, `XC_LiveViewSmallRawManage` |
| ISP driver | `library/SigProcess/`: `SigproMgr`, `MovSigProcess`, `StillSigProcess`, `ImageRequest`, `SigproRawMix`, `SigproJpeg`, `SigproFillLight`, `SigproHdr`, `SigproMBlender`, `EisParamMgr` |
| ISP parameters | `library/CameraController/PictureQuality/`: `PictureQualityFunc`, `PictureQualityTags_moc`, `PictureQualityCommon`, `..._factory_w71c1` |
| param translation | `hal/SdkSigproConverter/src/SdkSigproConverter.c` |
| recorder FSM | `framework/recMgr/src/movie/MovRecFunc.c` |
| DNG file | `framework/recMgr/src/CinemaDngFile.cpp`, `RecMgrTag.cpp`, `library/FileMgr/src/XC_DngTileFormatter.cpp` |
| raw codec | `hal/RawCD/src/XC_HalLjpeg.cpp` |
| MOV file | `library/MovClass/src/XC_MovClass{,Common,Conv,File}.cpp` |
| raw playback | `library/CinemaDngPlay/`, `library/CameraController/RawDeveloperSimulator/` |

**`XC_SigproFillLight` and `XC_SigproFillLightMgr` are sigpro operations**, and
their `OpNew` records sit among the *stills* classes (`XC_StillYuvToY8`,
`XC_SigproJpegComp`). **[inferred]** Fill Light may therefore be a stills-path
operation that never acts on video — which would explain `menu
SetFillLightEffect 5` returning `OK` in `results/tone2/` with no confirmed
picture change, and makes it a poor first choice for a luma probe.

## 5. Shell entry points

**[measured]** The command table at `0xC0BAC14C` has 77 entries,
`{char name[0x14]; void *handler}`. Each handler holds its sub-table address in
a `movw`/`movt` pair, and sub-tables are `{name*, help*, fn*}`, stride 12.

| command | handler | sub-table |
|---|---|---|
| `movrec` | `0xC0403558` | `0xC0BBF91C` — `movc 0xC0403020`, `start 0xC0403298`, `stop 0xC0403400` |
| `pic` | `0xC0404E98` | `0xC0BC00E8` — 11 entries, matching the `results/shellcap/` capture exactly |
| `rec` | `0xC04074E8` | `0xC0BC1840` — logging control only |
| `imager` | `0xC03F54E8` | ~40 sub-commands incl. `mode_list`, `fixed_gain_state`, `createraw` |
| `menu` | `0xC0402F98` | the setter table at `0xC0BBD65C…` |

Two `pic` sub-commands are instruments nobody has used:

- **`pic print_tag`** (`0xC0404E78`) — "Printing pic_data When writing tags."
  It calls `0xC0404DD0` with mode 2, which **sets a logging flag**; it does not
  dump on the spot. So it makes the firmware narrate its own ISP configuration
  as it writes it, on the next mode change or record start.
- **`pic sig_dsccal`** (`0xC0404950`) — "Dumping out some data in signal
  process."

## 7. The code, as far as it goes

Traced 2026-09-22 with `tools/disasm.py` and `tools/xref.py`. Two of the four
questions have answers; two have clean negatives that bound the search.

### 7.1 `pic set` to the ISP — the ARM stops before the registers

```
pic set (0xC0404590)
  -> issues three requests, ids 0x0E, 0x0F, 0x01
  -> 0xC02B8E38   thin wrapper
       -> 0xC02B9768  singleton getter -> PictureQuality object at 0xC341399C
                      (vtable 0xC096ECF4, in the PictureQualityFunc neighbourhood)
       -> 0xC02B97A8  16-case jump table at 0xC02B97E0, dispatched on the id
            case 0x01 -> 0xC02B9828: copies 0x1A0 bytes from obj+0x10 into a
                         stack buffer, then 0xC02BA640(obj, params, id, arg)
```

**The request parameter block is `0xC34139AC`, 0x1A0 bytes, in live state.**
Object fields also seen at `+0x1AC`, `+0x34C`, `+0x358`, `+0x35C`.

**The ISP register bases are not in the ARM image.** Three searches, all
negative:

- no `movw`/`movt` pair, literal pool or plain word builds `0x3021xxxx`
  (the pre-existing claim, now reproduced with `tools/xref.py`);
- **no instruction anywhere constructs `0x30000000` as an ARM immediate** —
  zero `mov`, zero `orr`; the two `add` hits are inside data, not code. So the
  base is not assembled as `0x30000000 | (block << 16)` either;
- the apparent clusters of exact `0x30xx0000` words are the resource-index
  artefact `docs/TONE_CURVE_HUNT.md` already documents — byte 3 incrementing at
  a fixed stride. Not bases.

**[inferred]** Taken with `SIGSEQ_0`, `SIGSEQ_1`, `SIGSEQ_SRAM%1d`, `SRAM_MGR`
in the name pool and the block at `0x301B0000` that the boot probe labelled
DSP, the reading is that **the ARM never programs the shadow bank directly** —
it queues a request and a sequencer executes it. That would explain, together,
why an ARM store into `0x30212020` was *ignored* rather than overwritten
(`results/knottest/`), and why the firmware's own upload works.

**What this changes for fpLog:** the writable intermediate to look for is the
**sigpro request parameter block**, not a register base. A base address would
not have helped — the earlier knot-register write proves stores there do
nothing.

### 7.2 What composes the active CEQ record — not findable statically

`0xC0B392B0` and its three live copies (`0xC3424F70`, `0xC3425318`,
`0xC3824414`) have **zero references** by any of the three mechanisms, and so do
`0xC0B39000`, `0xC0B38000`, `0xC0B39340`, `0xC0B3AB80` and `0xC0B30000`.

That is a bounding result, not a failure: **no static reference exists**, so the
composer reaches the record through a runtime-computed pointer and no amount of
reading the image will find it. It has to be caught on the camera — which is
what `pic print_tag` is for (§5).

### 7.3 `MovRecFuncStateCinemaDng` — found

C++ RTTI in this build is `{..., 0xC0726FB8, name*, ...}` with the name inline
after it, and the class descriptor carries the method table.

| | CinemaDng | REC |
|---|---|---|
| name | `0xC0B9C238` | `0xC0B9CA58` |
| RTTI record | `0xC0B9C22C` | `0xC0B9CA4C` |
| descriptor | `0xC0B9C254` (0x16 entries) | `0xC0B9CA74` |
| **vtable** | **`0xC0B9C268`**, 20 methods | **`0xC0B9CA80`** |

CinemaDng's methods are mostly shared base handlers in `0xC038Bxxx`. **Seven sit
in `0xC03ABxxx`**, and two of those (`0xC03ABD98`, `0xC03ABDB8`) also appear in
REC's table. So the **CinemaDNG-specific handlers** are:

```
0xC03ABCC8   0xC03ABD10   0xC03ABE08   0xC03ABE38   0xC03ABE60
```

They are thin dispatchers into `0xC039Cxxx` and `0xC0383xxx` — for example
`0xC03ABCC8` calls `0xC03A6C68` then `0xC039CB10` with fields from the event at
`+0x14`/`+0x18` and the object at `+0x04`/`+0x0C`. Following them further is
the next step and has not been done.

### 7.4 `XC_LiveViewFieldAngleTable` — the accessors, not the data

The base class (`0xC0BCF718`) has two methods, `0xC0436238` and `0xC0436408`,
and **both are stubs that return 0** — pure virtuals. The implementation is
`<unnamed>::XC_LiveViewFieldAngleTableModel`:

| | |
|---|---|
| name | `0xC0BD0580` |
| RTTI record | `0xC0BD0574` |
| descriptor | `0xC0BD05AC` (parent `0xC0BCF714`) |
| methods | `0xC0439708`, `0xC0436248`, `0xC04363F8`, `0xC04397B8`, `0xC04397C8` |

`0xC0436248` copies two fields out of a descriptor at `[obj+4]`, from **`+0x60`
and `+0xD0`** — the same two offsets `docs/PIPELINE.md` §6 identified as
alignment/pitch in the OpenGate format descriptor. That is an independent
cross-link between the two analyses, and it says the field-angle model reads
the *same* recording-format descriptor OpenGate patches.

**The table data itself is not located.** The accessors reach it through an
object pointer, so it is runtime state, and the `{table, imgr, sig}` triple
still has to be captured on the camera rather than read out of the image.

## 6. Missing data

Flagged so nothing here is mistaken for established.

1. **No ISP capture has ever been taken in CinemaDNG mode.** Every register dump
   in `results/` was in movie or live-view. The `Cdng` / `UpdateCdng` split is
   invisible in everything captured so far. One card fixes this.
2. **No register base exists in the ARM image at all** (§7.1) — not as a
   constant, not assembled from parts. If the sequencer reading is right, there
   is no base to find on this side, and the request parameter block at
   `0xC34139AC` is the thing to study instead. **Unproven.**
3. **The `{table, imgr, sig}` triple is never captured at runtime.** The pattern
   numbering in §1 is array order, not a confirmed runtime enum.
4. **`XC_LiveViewFieldAngleTable` data is not located** — the accessors are
   found (§7.4), the table they read is runtime state.
5. **`pic set` / `print_tag` / `sig_dsccal` have never been run.**
6. **Whether Fill Light acts on video is unverified** (§4).
7. **The five CinemaDNG-specific handlers are named but not followed** (§7.3)
   into `0xC039Cxxx` / `0xC0383xxx`.
8. **The pipeline order in §2 is inferred from name prefixes**, not from code.
   `YCMAT` sitting inside `GAM_TOP` after `GAMMA TABLE` is the strongest single
   piece of evidence for the RGB-then-YUV split, and it is one piece.
