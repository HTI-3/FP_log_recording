#!/usr/bin/env python3
"""Generate ADDRESSES.md from the sources, rather than transcribing it.

    python3 tools/gen_addresses.py

Two halves, and the difference matters:

  HARVESTED  -- read mechanically out of resources/fp_sup on every run: the
                `.equ` constants in its assembly, and the shell command table
                in its docs. These cannot drift from fp_sup.
  CURATED    -- the table in this file: addresses that live in prose (fp_sup's
                markdown) or that fp_log established itself. These are typed,
                so each carries its source and its confidence.

A hand-typed address table is exactly the kind of thing one wrong hex digit
ruins silently -- fp_sup lost weeks to a merged card nobody could see was wrong.
Half of this is therefore machine-read, and the typed half says so.
"""
import pathlib, re, subprocess, sys, datetime

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
FPSUP = REPO / 'resources' / 'fp_sup'
OUT = REPO / 'ADDRESSES.md'

# --- CURATED ---------------------------------------------------------------
# (address, name, group, note, source, confidence)
C = 'confirmed'      # stated as proven in fp_sup, or measured here
R = 'reported'       # stated in fp_sup prose without a proof note
D = 'derived'        # fp_log worked it out; the reasoning is in docs/
CURATED = [
 # ---- shell plumbing
 (0xC0BAC14C,'shell command table','Shell','77 entries, stride 0x18, {char name[0x14]; void *handler}; ends when handler==0','SHELL_CAPABILITIES.md',C),
 (0xC03D9C20,'shell dispatcher','Shell','f(ctx, char *line). Tokenises on space, matches token[0], calls handler(ctx, argc-1, &argv[1]). The line must be WRITABLE and persist -- strtok NULs it','SHELL_CAPABILITIES.md',C),
 (0xC03D9BC8,'command table walker','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC03DB5A0,'command table accessor','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC03DB840,'sub-table walker','Shell','two-tier commands; handler at entry +8','SHELL_CAPABILITIES.md',R),
 (0xC01F575C,'command name compare','Shell','strncmp over 0x14','SHELL_CAPABILITIES.md',R),
 (0xC067986C,'strtok','Shell','per-task TLS, so safe from a worker task','SHELL_CAPABILITIES.md',R),
 (0xC0BABB9C,'strtok delimiter " "','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC3756904,'global shell context','Shell','singleton; ctx[0] is the output callback. Nested output uses this address hard-coded, so capture MUST push onto this ctx','SHELL_CAPABILITIES.md',C),
 (0xC3756938,'shell ctx one-shot guard','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC03D9A10,'shell ctx init','Shell','f(ctx); already initialised at boot','SHELL_CAPABILITIES.md',C),
 (0xC03D9AC0,'output sink push','Shell','f(ctx, fn); depth cap 4','SHELL_CAPABILITIES.md',C),
 (0xC03D9B20,'output sink pop','Shell','f(ctx)','SHELL_CAPABILITIES.md',C),
 (0xC000EE60,'default output sink (UART)','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC0013F48,'vsnprintf','Shell','f(buf, size, fmt, &arg1) -- for a custom sink','SHELL_CAPABILITIES.md',C),
 (0xC03D9D18,'shell REPL','Shell','reads a 256-byte line, calls the dispatcher','SHELL_CAPABILITIES.md',R),
 (0xC03D9DD8,'shell REPL loop','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC03DA3F8,'XC_ShellScriptAutoRun','Shell','the AutoRun entry point','SHELL_CAPABILITIES.md',C),
 (0xC03DA758,'AutoRun file open','Shell','f("_AutoRun.txt", 1)','SHELL_CAPABILITIES.md',R),
 (0xC03DA178,'AutoRun shell task','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC0BAC2F8,'echo handler pointer','Shell','command table entry 17 -- the slot every payload borrows to run code. 0xC0BAC14C + 17*0x18 + 0x14','fp-usb-shell skill',C),
 (0xC03FA010,'`mem set` handler','Shell','*addr = data. Checks 4-byte alignment ONLY -- no range limit','SHELL_CAPABILITIES.md',C),
 (0xC03F9DD8,'address parser','Shell','','SHELL_CAPABILITIES.md',R),
 (0xC03E98D0,'i2c write handler','Shell','payload <= 0x10 bytes','SHELL_CAPABILITIES.md',C),
 (0xC0406190,'prom write handler','DANGER','NON-VOLATILE. Can destroy calibration or brick the body. fp_log never calls this','SHELL_CAPABILITIES.md',C),
 # ---- ROM tables
 (0xC0BBB0FC,'menu setter table','ROM tables','~65 setters reached by `menu [Setter] [value]`, handler 0xC0402F98','SHELL_CAPABILITIES.md',C),
 (0xC0BC00E8,'pic/optic sub-table','ROM tables','per-ISP-function 0 auto / 1 force_off / 2 test: distortion, aberration, shading, 3ddnr, monofilter, tbsd','SHELL_CAPABILITIES.md',C),
 (0xC0BB1410,'display sub-table','ROM tables','12 bytes per entry, {name, help, fn}','firmware-map.md',C),
 (0xC030C610,'device table','ROM tables','which i2c name is the sensor vs the PMIC -- unread','SHELL_CAPABILITIES.md',R),
 (0xC0041F78,'prom device-id registry','ROM tables','which id is the calibration EEPROM -- unread','SHELL_CAPABILITIES.md',R),
 (0xC0F8E7EC,'resolution menu CSV resource','ROM tables','92 bytes. Rows 1-2 are stock (string ids 0313 UHD, 0314 FHD); row 3 is the third slot both OpenGate builds replace. fpLog must NOT take it','fp_log docs/PIPELINE.md',D),
 (0xC0B94364,'lens table','ROM tables','','fp_usb_shell/templates/lensblock.S',R),
 # ---- recording format decision -- fp_log's own findings
 (0xC043A19C,'format descriptor writer, call site','Recording format','BL, patched by both OpenGate builds -> their 0xC0732400. The callee builds the recording format descriptor','fp_log docs/PIPELINE.md',D),
 (0xC0437AF8,'format path prologue A','Recording format','patched to push {r4,r5,r6,lr} -- a detour entry','fp_log docs/PIPELINE.md',D),
 (0xC0437B48,'geometry call site','Recording format','B, patched -> OpenGate 0xC0731A00, which tail-jumps back to 0xC0437B4C','fp_log docs/PIPELINE.md',D),
 (0xC0437E98,'format path site','Recording format','B, patched -> OpenGate 0xC0731D00','fp_log docs/PIPELINE.md',D),
 (0xC043BCBC,'caller discriminated by return address','Recording format','OpenGate compares lr against this to tell two callers of one routine apart','fp_log docs/PIPELINE.md',D),
 (0xC043BE68,'format path site','Recording format','B, patched -> OpenGate 0xC0732200 (writes cropped dimensions)','fp_log docs/PIPELINE.md',D),
 (0xC043CCF8,'format path site','Recording format','B, patched -> OpenGate 0xC0730800','fp_log docs/PIPELINE.md',D),
 (0xC043D258,'format path prologue B','Recording format','patched to push {r4,r5} -- a detour entry','fp_log docs/PIPELINE.md',D),
 (0xC005C020,'OpenGate hook site','Recording format','B -> 0xC0731800','fp_log docs/PIPELINE.md',D),
 (0xC02092CC,'OpenGate hook site','Recording format','BL -> 0xC0730A00 (one of four callers of the same routine)','fp_log docs/PIPELINE.md',D),
 (0xC0218AEC,'OpenGate hook site','Recording format','BL -> 0xC0730A00','fp_log docs/PIPELINE.md',D),
 (0xC0219260,'OpenGate hook site','Recording format','BL -> 0xC0730A00','fp_log docs/PIPELINE.md',D),
 (0xC0306EA0,'OpenGate hook site','Recording format','B -> 0xC0731B00','fp_log docs/PIPELINE.md',D),
 (0xC0306EEC,'OpenGate hook site','Recording format','B -> 0xC0731B40','fp_log docs/PIPELINE.md',D),
 (0xC03A6DD8,'OpenGate hook site','Recording format','B -> 0xC0732900','fp_log docs/PIPELINE.md',D),
 (0xC03AA568,'OpenGate hook site','Recording format','BL -> 0xC0730A00','fp_log docs/PIPELINE.md',D),
 (0xC05E5B58,'OpenGate hook site (Thumb)','Recording format','Thumb word 0xB904F14D. 0xC05Exxxx neighbours the lossless-JPEG wrappers at 0xC05A6xxx -- the likeliest place a DNG header is assembled. UNVERIFIED','fp_log docs/PIPELINE.md',D),
 (0xC05E6400,'OpenGate hook site (Thumb)','Recording format','Thumb word 0xBCE6F14C','fp_log docs/PIPELINE.md',D),
 (0xC05E84D8,'OpenGate hook site (Thumb)','Recording format','Thumb word 0xBBD4F14A','fp_log docs/PIPELINE.md',D),
 (0xC0BD9A2C,'format limit bank A','Recording format','start of 16 words both OpenGate builds set to 1600. Mode-INDEPENDENT: OG2K and OG3K write identical values, so this is not geometry','fp_log docs/PIPELINE.md',D),
 (0xC0BE167C,'format limit bank B','Recording format','the mirror of bank A, exactly +0x7C50','fp_log docs/PIPELINE.md',D),
 # ---- imaging / codec
 (0xC03F52E8,'imager set_gain_state','Imaging','0 default, 1 acq, 2 movie, 3 through+acq, 4 movie_raw, 5 movie_raw_10bit, 6 movie_raw_12bit, 7 movie_raw_8bit, 8 digital-gain off. There is NO 14-bit movie mode','SHELL_CAPABILITIES.md / raw-sup.md',C),
 (0xC05A6890,'lossless JPEG: init','Imaging','','raw/lossless_codec',C),
 (0xC05A6920,'lossless JPEG: encode','Imaging','measured 169.7 Mpixel/s on a COLD call, 6064x4042 in 144,431 us. That is a floor, not the rate','raw-sup.md',C),
 (0xC05A6990,'lossless JPEG: size','Imaging','','raw/lossless_codec',R),
 (0xC062FEE8,'lossless JPEG: power/clock bring-up','Imaging','brings up power domain 5, the clock and IRQ 0x29 INSIDE encode, so a cold call pays it every time','raw-sup.md',C),
 (0xC062F6F8,'lossless JPEG watchdog','Imaging','timeout = pixels/32000. This is a watchdog with ~5.3x headroom, NOT a throughput. The old "32 Mpixel/s" conclusion built on it was wrong','raw-sup.md',C),
 (0xC037E7AC,'stills-path bl to the encoder','Imaging','the site raw/ljtime.S hooks to time the engine','raw-sup.md',C),
 (0xC0722AFC,'live FHD DNG writer seam','Imaging','passes a 3,244,544-byte DNG segment to 0xC069AC88. The seam a per-frame change would use','raw-sup.md',C),
 (0xC069AC88,'DNG segment write','Imaging','','raw/lossless_codec',C),
 (0xC069ADE0,'DNG flush','Imaging','','raw/lossless_codec',R),
 (0xC0403558,'`movrec` handler','Imaging','the movie recorder command -- the entry point to walk toward the H.264 encoder','SHELL_CAPABILITIES.md',C),
 (0xC0404E98,'`pic` handler','Imaging','ISP per-function control; sub-table 0xC0BC00E8','SHELL_CAPABILITIES.md',C),
 (0xC04037D8,'`optic` handler','Imaging','','SHELL_CAPABILITIES.md',C),
 (0xC3291958,'mposm -- focus position in encoder pulses','Imaging','','focus/dfd/README.md',C),
 (0xC375D8C0,'detection image channel','Imaging','320x240 linear 8-bit greyscale, proven clean. The display scanout is TILED (16 px) -- do not decode that one','raw-sup.md',C),
 # ---- danger
 (0xC01F885C,'Cyc pair (a)','DANGER','FREEZES THE CAMERA. Do not use','firmware-map.md',C),
 (0xC01F8D90,'Cyc pair (b)','DANGER','FREEZES THE CAMERA. Do not use','firmware-map.md',C),
 (0xC343A624,'still_raw_dump flag','DANGER','bit 2 HANGS THE CAMERA','raw-sup.md',C),
 (0x50000000,'RETRACTED: not the Bayer DMA base','DANGER','idle and empty. The argument built on "every 0x3011xxxx SIG register reads 0" is void -- configuration lives in a shadow bank at 0x3021xxxx','raw-sup.md',C),
 # ---- MMIO, with fp_log run 1 results
 (0x300C0000,'RFC readout','MMIO','used by recording. fp_log run 1: DEAD at boot -- gated when idle','raw-sup.md + results/run1_21_09_2026',C),
 (0x300D0000,'lossless JPEG engine','MMIO','~300 MHz, ~1 pixel/clock. Idle during video, so no contention. fp_log run 1: DEAD at boot, consistent with its wrappers powering it themselves','raw-sup.md + results/run1_21_09_2026',C),
 (0x301B0000,'the DSP recording uses','MMIO','fp_log run 1: 3 of 256 words live at boot (+0x030, +0x070, +0x0C0)','raw-sup.md + results/run1_21_09_2026',C),
 (0x30210000,'shadow config bank','MMIO','where the SIG configuration actually lives. fp_log run 1: 102 of 256 words live -- the richest bank read','raw-sup.md + results/run1_21_09_2026',C),
 (0x30110000,'SIG registers','MMIO','reads zero. fp_log run 1: DEAD, as predicted -- used as the probe control','raw-sup.md + results/run1_21_09_2026',C),
 (0x30030000,'unidentified, live','MMIO','fp_log run 1: 13/16 head words live, w0=0x17024B60. Not yet identified','results/run1_21_09_2026',D),
 (0x302D0000,'unidentified, live','MMIO','fp_log run 1: 14/16 live, small byte-sized values -- counters or status','results/run1_21_09_2026',D),
 (0x30020000,'unidentified, live','MMIO','fp_log run 1: w0=0x7F3F3514, w1=0x7F3F7F3F','results/run1_21_09_2026',D),
 (0x30190000,'unidentified, live','MMIO','fp_log run 1: 10/16 live, w0=0x00038070','results/run1_21_09_2026',D),
 # ---- firmware identity
 (0xC0000000,'MAIN load address','Firmware','the boot loader decompresses NAND into 0xC0000000..0xC2F30800. First word reads e5 9f f0 18 = ldr pc,[pc,#0x18]','firmware-map.md',C),
]

GROUP_ORDER = ['Firmware','Shell','Shell commands','File system','Threads & RTOS',
               'Memory','Recording format','Recording state','Imaging','ROM tables',
               'MMIO','Cave (RAM)','Live state','DANGER','Other']

GROUP_BY_PREFIX = [
 (0xC0016000,0xC0018000,'Threads & RTOS'), (0xC001C000,0xC001E000,'Memory'),
 (0xC01F8000,0xC01F9000,'Threads & RTOS'), (0xC0365000,0xC0367000,'File system'),
 (0xC0444000,0xC0445000,'File system'),    (0xC036E000,0xC036F000,'Threads & RTOS'),
 (0xC072D000,0xC0740000,'Cave (RAM)'),     (0xC3000000,0xC4000000,'Live state'),
 (0x30000000,0x40000000,'MMIO'),
]


def harvest_equ():
    pat = re.compile(r'^\s*\.equ\s+([A-Za-z_]\w*)\s*,\s*(0x[0-9A-Fa-f]{6,8})', re.M)
    out = {}
    for p in sorted(FPSUP.rglob('*.S')):
        if '.git' in p.parts:
            continue
        for m in pat.finditer(p.read_text(errors='ignore')):
            a = int(m.group(2), 16)
            # Magic words and instruction encodings are not addresses.
            if not (0x30000000 <= a < 0x40000000 or 0xC0000000 <= a < 0xC4000000):
                continue
            out.setdefault(a, (m.group(1), str(p.relative_to(FPSUP))))
    return out


def harvest_shell_commands():
    t = (FPSUP / 'docs' / 'SHELL_CAPABILITIES.md').read_text()
    return {int('0xC' + a, 16): n
            for n, a in re.findall(r'`([#A-Za-z_0-9]+)`\s*c([0-9a-f]{7})', t)}


def group_of(addr):
    for lo, hi, g in GROUP_BY_PREFIX:
        if lo <= addr < hi:
            return g
    return 'Other'


def main():
    equ, cmds = harvest_equ(), harvest_shell_commands()
    rows = {}
    for a, (n, src) in equ.items():
        rows[a] = [a, n, group_of(a), '', f'`{src}` (.equ, harvested)', 'harvested']
    for a, n in cmds.items():
        rows[a] = [a, f'`{n}` command handler', 'Shell commands',
                   '', 'SHELL_CAPABILITIES.md (harvested)', 'confirmed']
    for a, n, g, note, src, conf in CURATED:
        if a in rows and rows[a][5] == 'harvested':
            note = (note + (' · ' if note else '') +
                    f'also `.equ {rows[a][1]}` in {rows[a][4].split("`")[1]}')
        rows[a] = [a, n, g, note, src, conf]

    by_group = {}
    for r in sorted(rows.values()):
        by_group.setdefault(r[2], []).append(r)

    L = []
    L.append('# SIGMA fp Ver.5.02 — address reference\n')
    L.append(f'Generated by `tools/gen_addresses.py` on '
             f'{datetime.date.today().isoformat()}. **Do not hand-edit** — '
             f'add to the `CURATED` table in that script and re-run.\n')
    L.append('Firmware **Ver.5.02 only**, SHA-256 '
             '`c9fa76f32f523bb2dc9a3fbda39418c31573cab6a1aa5c56d28c371862066ed8`. '
             'A card built for one version writes into whatever happens to sit at '
             'these addresses on another.\n')
    L.append('## How to read the confidence column\n')
    L.append('| | |\n|---|---|')
    L.append('| `confirmed` | fp_sup states it as proven on hardware, or fp_log measured it |')
    L.append('| `reported` | stated in fp_sup prose without a proof note — believe it, but verify before betting a card on it |')
    L.append('| `derived` | fp_log worked it out; the reasoning is in `docs/` and is cited |')
    L.append('| `harvested` | read mechanically out of an `.equ` in fp_sup assembly. It is a real address in shipped code; the *name* is fp_sup\'s and the meaning may need checking |\n')
    L.append(f'{len(rows)} addresses: {sum(1 for r in rows.values() if r[5] == "harvested")} '
             f'harvested from assembly, {len(cmds)} shell handlers harvested from docs, '
             f'{len(CURATED)} curated.\n')
    for g in GROUP_ORDER:
        if g not in by_group:
            continue
        L.append(f'\n## {g}\n')
        if g == 'DANGER':
            L.append('**Nothing in fp_log calls anything on this list.**\n')
        L.append('| address | what | notes | source | confidence |')
        L.append('|---|---|---|---|---|')
        for a, n, _, note, src, conf in by_group[g]:
            L.append(f'| `0x{a:08X}` | {n} | {note} | {src} | {conf} |')
    L.append('\n## The recording format descriptor\n')
    L.append('Reached from `0xC043A19C`. The descriptor is at **`context + 0x5C`**, '
             'the mode id arrives in **`r5`** (`0x53` is the third resolution slot), '
             'and **`descriptor + 0x80` bit 16** gates eligibility. '
             'Field offsets, from the OpenGate geometry constants:\n')
    L.append('| offset | OG3K | OG2K | reading |')
    L.append('|---|---|---|---|')
    for off, a, b, what in [(0x1C,2,2,'mode/readout kind'),(0x0C,3024,2016,'full width'),
                            (0x10,2010,1344,'full height'),(0x20,3008,2000,'stored width'),
                            (0x28,2000,1334,'stored height'),(0xD8,3024,2016,'full width, copy 2'),
                            (0xE0,2010,1344,'full height, copy 2'),(0xF4,3024,2016,'full width, copy 3'),
                            (0xF8,2010,1344,'full height, copy 3'),
                            (0x60,1024,1024,'alignment/pitch, mode-independent')]:
        L.append(f'| `+0x{off:02X}` | {a} | {b} | {what} |')
    L.append('\n**Geometry is written in three copies.** OG3K v0.2.2a shipped broken '
             'because one was missed, and 8-/10-bit silently fell back to UHD30 with '
             'nothing on screen. Assume anything else in this descriptor is duplicated '
             'the same way, and find every copy.\n')
    L.append('\n## Sources\n')
    L.append('- `resources/fp_sup/` — ijigen/fpSup: `docs/SHELL_CAPABILITIES.md`, '
             '`projects/firmware-map.md`, `projects/raw-sup.md`, `focus/dfd/README.md`, '
             'and the assembly under `gyro/`, `fp_usb_shell/`, `raw/`\n')
    L.append('- `docs/PIPELINE.md`, `docs/FIRMWARE_BASE.md` — fp_log\'s own analysis, '
             'reproducible with `tools/re/`\n')
    L.append('- `results/run1_21_09_2026/FINDINGS.md` — the MMIO column\n')
    OUT.write_text('\n'.join(L) + '\n')
    print(f'wrote {OUT}  ({len(rows)} addresses, {len(L)} lines)')


if __name__ == '__main__':
    main()
