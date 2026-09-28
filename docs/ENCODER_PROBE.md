# Encoder probe

A read-only AutoRun card that copies the SoC's imaging and codec register banks
onto the SD card, so the blocks can be identified on a host.

**It has not been run on a camera.** Everything here is built and checked
host-side. The first boot is the first test.

## The question it serves

`PLAN.md` §3: hardware encoder IP of this class often implements profiles the
firmware never exposes — High10, 4:2:2. A yes would remove most of the 8-bit
cost and rewrite the curve design in §2.

**This probe narrows which block to read the driver for. It does not answer the
question.** What a register bank can tell you is *which IP it is*; whether the
firmware can be made to drive it in High10 is in the driver code, and the driver
code comes out of the DRAM dump. Run this and the dump together.

## Build

```bash
python3 camera/build_probe_card.py --out camera/card
```

Copy **`AutoRun.txt`** alone to the card root. No payload container, no folder.
The probe is 520 bytes, so it is spelled out as `mem set` words.

## What it does, in order

| | | |
|---|---|---|
| `ENCW0.BIN` | `0x300C0000` | RFC readout — live during recording |
| `ENCW1.BIN` | `0x300D0000` | lossless JPEG engine — confirmed in `raw-sup.md` |
| `ENCW2.BIN` | `0x301B0000` | the DSP recording uses |
| `ENCW3.BIN` | `0x30210000` | the shadow config bank |
| `ENCW4.BIN` | `0x30110000` | SIG registers — expected dead, a control |
| `ENCS0..2.BIN` | `0x30000000..0x30300000` | 16 words from the head of each 64 KiB block |

1 KiB from each named bank, then the sweep. Each file is written as soon as it
is read, so **the first missing file is where it stopped.**

## Read the result

```bash
python3 tools/enc_ident.py /Volumes/<card>
```

It classifies each bank (dead / constant / live), prints the head words with
their ASCII, and matches ID-shaped words against a short list of candidate
signatures — each carrying its confidence. A match is a shortlist entry, not a
finding.

## Safety

- **Every access to a register bank is a 32-bit load.** Word at a time, in an
  explicit loop, because a `memcpy` is free to use byte or multi-word accesses
  and a peripheral bank is entitled to refuse both.
- **Nothing non-volatile is touched.** No `prom`, no `fwup`, no NAND. Files go to
  the SD card through the firmware's own file API — `F_CTOR`/`F_OPEN`/`F_WRITE`/
  `F_CLOSE`/`F_DTOR`, the same six calls `gyro/gcsvgen.S` makes, including the
  part that was paid for: **when the open fails the object is destroyed anyway.**
  Leaving one built wedged the file system until a power cycle.
- **Ver.5.02 only**, against
  `c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8`.
- **Revert:** delete `AutoRun.txt`, battery out, power on.
- The banner reads `fpLog-ENCPROBE!` so a result can be attributed to this build.

### The residual risk, stated

`resources/fp_sup/docs/SHELL_CAPABILITIES.md` says reads are safe and it is pokes that hang. That
is the repository's assessment, not a proof, and the sweep touches blocks nobody
here has read before. So the order is deliberate: the five established banks are
written first and the speculative sweep goes last, in three groups. **If the
camera stops, read the card before doing anything else** — the files that exist
say how far it got.

**Do not put this on a card that also carries the USB shell or OpenGate.** The
buffers live at `0xC072F000..0xC072FC40`, which is the shell's worker and state
region; this card is built `--no-shell` so nothing is there.

## A bug this found, and the check that now prevents it

The first build put the file object at `0xC072E300`. `build_autorun.py` lays its
own loader across `0xC072E800..0xC072EF30` — and that loader is what calls the
probe. The probe would have overwritten the code that called it, on its first
file write, and nothing in the build said so.

`build_probe_card.py` now reads `BUFS_LO`/`BUFS_HI` out of `enc_probe.S`,
re-derives every cave word from the `AutoRun.txt` it just generated, and refuses
to ship an overlap. The check is mechanical, against the file actually written,
because a constant someone has to remember to update is the thing that failed.

*(Confirmed by reintroducing the overlap: the build stops with
`460 AutoRun words land in the probe buffers 0xC072E300..0xC072FC40, first
0xC072E800`.)*

## Files

| | |
|---|---|
| `camera/enc_probe.S` | the payload — 520 bytes |
| `camera/build_probe_card.py` | builds the card and runs the overlap check |
| `camera/card/AutoRun.txt` | the built card |
| `tools/enc_ident.py` | reads the dumps and identifies the blocks |
