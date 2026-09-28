# Firmware base — Phase 0

Host-side analysis only. **No camera was involved in anything on this page.**
Everything here is reproducible from `resources/` with the scripts named.

---

## The pinned image

```
resources/firmware/FP__V502.bin
SHA-256  c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8
size     25,692,160 bytes
```

Every address in this repository is derived from **this** file. A card built
against one firmware version writes into whatever happens to sit at those
addresses on another, so a build that cannot confirm this hash must refuse to run.

## Container format

Bytes `0x00..0xFF` are an ASCII header, space-padded:

```
LENGTH=24503296 w71c1 VER=V91 DVR=5.02 SUM=2768501654 IPL PTBL DAT1
```

`LENGTH` (24,503,296 = `0x175E200`) covers the main body only, and the trailing
`IPL PTBL DAT1` names the three sections that follow it. Each carries its own
ASCII header in the same shape:

| section | header at | declared length |
|---|---|---|
| main body | `0x100`, magic `@DFI` | 24,503,296 |
| `IPL` | `0x175E500` | 131,072 |
| `PTBL` | `0x177E600` | 4,096 |
| `DAT1` | `0x177F700` | 1,052,672 |

## The update file cannot be disassembled — this is the Phase 0 result that matters

Two measurements, both reproducible:

- **Shannon entropy of the main body is 7.71 bits/byte** (7.42 at `0x800000`,
  6.83 in the header region). Ordinary ARM code sits far below that.
- **There is no ARM vector table anywhere in the file.** `0xC0000000` is known
  from fp_sup to read `e5 9f f0 18` — `ldr pc, [pc, #0x18]`, the first vector.
  Searching the whole 25 MB for six consecutive `?? f0 9f e5` words returns
  **nothing**.

A `strings` pass agrees: `Gamma` 0 hits, `Curve` 0, `Matrix` 0, `ColorSpace` 0,
`LUT` 1, and the handful of plaintext fragments that do appear (`ProRes`,
`Teal`, `avc1`, `moov`) sit surrounded by high-entropy bytes, i.e. they are
inside compressed blocks, not in a symbol table.

**The body is packed. Static analysis of this file is a dead end.**

### What is needed instead

The boot loader decompresses the firmware into two contiguous DRAM segments at
**`0xC0000000..0xC2F30800`**, and that is what loads into a disassembler. The
read-only dumper is `camera/build_dump_card.py`, which uses nothing but
`mem save`. No dump exists on this machine yet.

*(An earlier revision of this page pointed at a sibling project,
`../sigma_write_firmware_to_sd_card/`. That folder is gone from this machine —
only its copy of `FP__V502.bin` survives, under `../decompile/`. The dumper in
`camera/` replaces it and extends the range; see `PLAN.md` §9 step 3.)*

> **This is the gate on Phase 1.** Producing that dump is one card, one boot and
> one file copy, and nothing in Phase 1 can be finished without it.

## Scripts

`vbin.py`, `diff.py`, `hooks.py`, `geo.py`, `dis.py` produced everything here and
in `PIPELINE.md`. They are host-side, read-only, and need only `capstone`.
