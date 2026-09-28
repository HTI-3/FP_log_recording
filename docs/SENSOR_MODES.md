# Sensor modes, and what geometries are reachable

Answering: **is anything between OG2K (2016) and OG3K (3024) possible — a 2.6K?**

Short answer: **no sensor mode is 2.6K, but 2.6K is still reachable**, because the
recorded width is not the sensor mode's width. There is a scaler between them, and
the scale factor is a programmable word.

```bash
python3 tools/isp_map.py results/dram_21_09_2026/dram_C0000000.bin --only modes
```

---

## 1. The sensor mode table — `0xC0B59E24`

**[measured]** Found by following fp_sup's own pointers: `FUN_c0321028(obj, mode)`
indexes a table at `[[obj]+8]` with stride **0x64 = 100 bytes**, and
`FUN_c0320B38` resolves a mode id to an index by scanning `entry[0]`. The table
is **70 entries**, which matches what `imager mode_list` prints.

Columns: `[0]` mode id, `[1]` width, `[2]` height, `[16]` max fps,
`[17]`/`[19]` horizontal/vertical decimation.

Every mode number fp_sup names is in it and lands where fp_sup says: **7** UHD30
(6064×3412), **106** 1080p29.97 (3032×1708), **117** the mode OG3K borrows
(3032×2012), **139** the OG2K quiet readout (2016×1344), and **111** present at
3032×1708.

## 2. The fourteen geometries

| width × height | modes | max fps | decimation | note |
|---|---|---|---|---|
| 6064 × 4042 | 5 | 40 | 1:1 | **full sensor, 3:2** |
| 6064 × 3412 | 4 | 30 | 1:1 | full width 16:9 — UHD30 is mode 7 |
| 6064 × 2022 | 1 | 60 | 1:1 | full width, 3:1 |
| 5712 × 3216 | 1 | 24 | 1:1 | |
| 4176 × 2174 | 7 | 30 | 1:1 | the Super35/crop family, 16:9 |
| **3968 × 2640** | **4** | **40** | **1:1** | **3:2 crop — never used by OpenGate** |
| 3032 × 2012 | 4 | 105 | 2:2 | **OG3K's source (mode 117)** |
| 3032 × 1708 | 14 | 120 | 2:2 | the everyday 16:9 family |
| 2088 × 1174 | 16 | 120 | 2:2 | Super35 binned |
| 2016 × 1344 | 7 | 120 | 3:3 | **OG2K's source (mode 139)** |
| 2016 × 1136 | 1 | 120 | 3:3 | |
| 2016 × 672 | 3 | **240** | 3:3 (V 6) | the high-speed slit |
| 1984 × 1320 | 2 | 78 | 2:2 | = 3968×2640 halved |

**There is nothing between 2088 and 3032.** So 2.6K is not a native readout.

## 3. But the recorded width is not the mode width

`RWZM` is `SIG1 RAW ZOOM` in the ISP name pool — a raw-domain scaler whose factor
is a word with **`0x400` = 1.0**. fp_sup's open-gate page identifies the columns:
`0x640` (= 1600, ratio **1.5625×**) is "a 1.5625× reduction that pinned the
filled region to 1936 wide", and unity releases it.

That reconciles exactly:

```
mode 117   3032 wide  ÷ 1.5625  = 1940.5  ->  the stock FHD filled width, 1936
mode 117   3032 wide  ÷ 1.0     = 3032    ->  OG3K, stored 3024×2010
mode 139   2016 wide  ÷ 1.0     = 2016    ->  OG2K, stored 2000×1334
```

**So recorded width ≈ sensor mode width ÷ (RWZM / 0x400).** OG3K does not change
the sensor mode at all — it borrows stills mode 117 and ends up with no
reduction applied. It does **not** get there by writing RWZM (§5); it gets there
by switching profiles. That is what fp_sup means by "OG3K borrows a stills
profile for its geometry", and it implies the reduction is a property of the
profile, not a global setting.

### Which makes 2.6K a choice of two numbers

| from | RWZM for ~2600 wide | result |
|---|---|---|
| mode 117 (3032×2012) | `0x4AA` (1.1662×) | 2600 × 1725, 3:2 |
| modes 129/130 (3968×2640) | `0x61B` (1.5262×) | 2600 × 1730, 3:2 |
| modes 129/130 at `0x600` (1.5×) | clean binary ratio | **2645 × 1760** |

The third row is the interesting one: `0x600` is a clean 1.5×, and 3968×2640 is a
1:1 readout at up to 40 fps. **That is a 2.6K open gate**, from a sensor mode
OpenGate has never touched.

Note also `0x0F80` (3968) and `0x0A50` (2640) each occur four times in the
profile banks at `0xC0BD8000..0xC0BE3000`, so **profiles referencing that
geometry appear to exist already**. [inferred — the profile record layout is not
mapped, so these could be coincidental values.]

## 4. What is not established

1. **Whether RWZM accepts arbitrary ratios.** Only `0x400` and `0x640` have been
   observed in use. A raw-domain scaler on Bayer data usually has constrained
   ratios, because the CFA phase has to survive. `0x600` = 1.5× is the most
   plausible untested value precisely because it is simple.
2. **Whether the 3968×2640 modes are reachable from the video path**, or are
   stills-only like mode 117 was before OpenGate borrowed it.
3. **What `[16]` really is.** Read here as max fps: mode 12 at 2016×672 says 240,
   mode 7 says 30 and is UHD30, mode 106 says 30 and is 1080p29.97 — consistent,
   but not proven to be a ceiling rather than a nominal.
4. **Bandwidth.** Irrelevant for fpLog, which targets H.264 (the card sees ~10
   MB/s whatever the sensor does, and level 5.1 covers 4096×2304). It is the
   binding constraint for any CinemaDNG variant: 2645×1760 12-bit 24p is
   ~167 MB/s, still above a V90 card's sustained write.

## 5. A discrepancy in fp_sup worth knowing about

fp_sup's `projects/open-gate.md` patch set lists:

```
0xC0BD9A34  0x00000400   profile 122 live   RWZM H    stock 0x00000640
0xC0BE1684  0x00000400   profile 122 record RWZM H
0xC0BD9EFC  0x00000400   profile 122 live   RWZM V
0xC0BE1B4C  0x00000400   profile 122 record RWZM V
```

**No shipped OpenGate release writes `0x400` to any of them.** All nine payloads
— og2k v0.1.0test/v0.1.1a and og3k v0.1.0test through v0.2.4a — write `0x640` to
those four addresses, and to 28 more in the same two banks. The DRAM dump
confirms `0x640` is also the **stock** value, so those 32 writes are no-ops as
shipped.

Checked by applying every VBIN section in order, not by looking at short sections
only — a first pass that filtered to sections of ≤8 bytes would have missed a
larger covering section, and did.

It is not done at runtime either. There is **no section at `0xC072F800`** in
v0.2.4a (that cave address is from an older layout), only three payload
instructions build a `0xC0BD`/`0xC0BE` high half, and all three are in the block
at `0xC0730800` comparing against the three format-picker tables
(`0xC0BE5B50`/`0xC0BE59B0`/`0xC0BE5810`) — the `fmttable` hook, nothing to do
with RWZM.

**So OG3K reaches 3024 wide without ever touching RWZM.**

The likeliest reading, and it *helps* the 2.6K case: **RWZM is per profile, and
the profiles OG3K switches to already have it at unity.** `0x640` belongs to
profile 122 — the stock FHD path — while the factory triplets p131/p151/p171 that
OG3K registers itself into are stills-derived and presumably unity already. On
that reading the geometry comes from the canvas record at `r4+0x5C` plus
*whichever profile's* RWZM applies, and intermediate ratios are a per-profile
value rather than a global switch.

**[inferred, and the weakest link on this page.]** The profile record layout is
not mapped, so which word in which profile is RWZM is not established — only the
four addresses fp_sup names. Mapping one profile record is what would turn the
§3 arithmetic from a model into a measurement.
