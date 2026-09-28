# Runbook — how to run a card, every time

Operational discipline, not a route. **The route is `docs/CURVE_TARGETS.md`**;
each card's own page in `docs/cards/` says what that card does and how to read
what it produced.

> The six-step "get to a working log mode" procedure that was here until
> 2026-09-22 has been removed. It shot log in mode Off through the look records,
> which are chroma (`results/logoff1/REFRAME.md`), so none of its steps could
> have worked.

Everything is RAM-only and a battery-out cold boot reverts it — **except**
`menu Set…`, which writes a camera *setting* and persists. Cards that use it say
so in their header. **Firmware Ver.5.02 only.**

All commands run from the project root:
```bash
cd /Users/andreasfink/Documents/PRIVATE/projects/fp_log
```

## Camera settings — the same every time

Get these wrong and the run is wasted, usually silently.

- **Power saving OFF** — a camera that sleeps mid-run gives half an experiment
- **Manual exposure**, fixed **ISO** (800 is what previous runs used), fixed
  **aperture**, fixed **focus**
- **Colour mode fixed**, and named in the notes — do not change it unless the
  card asks you to, because a colour-mode change moves 89 ISP registers at once
- Keep the camera **awake in live view** while a card is doing its work
- Point at a scene with a **real range of tones**, or a flat defocused field if
  the card is a ramp

## The card

- `AutoRun.txt` **alone** on the card root
- **Delete old output files** before each run — `mem save` may fail rather than
  overwrite, and a stale file reads as a successful capture
- One card, one variable. Mixed variables have produced wrong conclusions here
  more than once

## While it runs

Watch the screen. Every card in this repository prints its own progress through
the firmware's shell executor, and the messages are the only timing signal you
get. When a card says **`LOOK AT SCREEN`**, look at the live image at that
moment — several results in `results/` are the answer to "did the picture
change", and nothing recovers that afterwards.

## Reading it back

Each card's page in `docs/cards/` names its checker. Read the card **before**
concluding anything, including after a freeze: whatever the payload wrote is
still on it.

## If it freezes

1. **Read the card first.** Numbered per-command files (`T0.TXT`, `T1.TXT`, …)
   mean the highest one that exists is the last command that completed — that is
   how `results/tone2` named its failing command exactly.
2. Battery out, card out, power on.
3. Nothing non-volatile in the firmware is touched by any card here — no `prom`,
   no `fwup`, no NAND. If a *setting* looks wrong afterwards, reset it from the
   camera's own menu. **Do not run `menu reset` or `menu factoryReset` from a
   card.**

## Safety rules that were paid for

- `mem set` and RAM payloads only. No `prom write`, no `fwup`, no NAND.
- Judge from a clean boot.
- Do not cold-call the lossless-JPEG engine at `0x300D0000`; it broke stills
  compression until a reboot. Hook it, do not call it.
- Never touch `0xC343A624.2` (`still_raw_dump`) — it hangs the camera.
- Never the `Cyc` pair (`0xC01F885C` / `0xC01F8D90`); it freezes the camera.
- `stksz` never above `0x2000` — the pool is shared.
- Call a borrowed routine directly once before hooking it to anything.

`PLAN.md` §6 is the full list with its reasoning.
