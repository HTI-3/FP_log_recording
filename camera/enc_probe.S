/* enc_probe -- read-only survey of the SoC's imaging/codec register banks.
 *
 * WHY.  fpLog's cost is that the fp's MOV is believed to be 8-bit 4:2:0.
 * Hardware encoder IP of this class frequently implements profiles the firmware
 * never exposes -- High10, 4:2:2 -- and most such blocks announce what they are,
 * and sometimes what they can do, in an ID or synthesis-config register at a
 * fixed offset from their base.  This copies those banks onto the card so the
 * blocks can be identified on a host, from the values rather than from a guess.
 *
 * WHAT IT DOES NOT DO.  It does not tell you how to *call* an encoder.  That
 * lives in the driver code, and the driver code comes out of the DRAM dump
 * (../sigma_write_firmware_to_sd_card/), not out of a register bank.  This
 * narrows which block to read the driver for; it does not replace reading it.
 *
 * SAFETY.  Every memory access here is a 32-bit load.  Nothing is written to
 * NAND, to EEPROM, or to any non-volatile store -- there is no `prom`, no
 * `fwup`, and no store to any address outside the cave staging buffer below.
 * The camera is stock again when AutoRun.txt is deleted and the battery is out.
 *
 * `docs/SHELL_CAPABILITIES.md` states the position this relies on: reads are
 * safe, and it is pokes that can hang until a reboot.  That is the repository's
 * assessment, not a proof, so the order here is deliberate: the five banks the
 * repository has already established are real go FIRST and land on the card as
 * five separate files, and the speculative sweep of everything else goes LAST,
 * in three groups.  If the camera stops, the files that exist say how far it
 * got, and the group says where.  Read the card before doing anything else.
 *
 * Every address below is from this repository or from the gyro sources:
 * the file API from gyro/tableload.S and gyro/gcsvgen.S, the register bank
 * bases from projects/raw-sup.md, the cave layout from
 * fp_usb_shell/build_autorun.py.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* ---- the firmware's file API, exactly as gyro/tableload.S names it -------- */
.equ F_MGR,     0xC0444658
.equ F_VOL,     0xC0444698
.equ F_CTOR,    0xC0365E90     /* f(obj, volume)                              */
.equ F_OPEN,    0xC0365FB0     /* f(obj, path, mode) -> 0 means it did NOT open */
.equ F_WRITE,   0xC03660E8     /* f(obj, buf, len)                            */
.equ F_CLOSE,   0xC0366020     /* close, NOT flush                            */
.equ F_DTOR,    0xC0365ED0     /* f(obj, 2)                                   */
.equ F_MODE_RW, 7              /* overwrites; mode 0x402 fails if it exists   */

/* ---- cave layout ---------------------------------------------------------
 * The probe is placed at CAVE_LOW by --boot-call.  The buffers CANNOT simply
 * follow it: build_autorun.py lays its own loader across
 * 0xC072E800..0xC072EF30, and that loader is what calls this routine -- the
 * first version of this file put the file object at 0xC072E300, straight
 * through it.  Everything therefore sits above the loader, in one block,
 * and build_probe_card.py re-derives the loader's extent from the AutoRun it
 * just generated and refuses to ship an overlap.
 *
 * 0xC072F000 upwards is the shell's worker and state region; this card is
 * built --no-shell, so nothing is there.  A card that carries the shell, or
 * OpenGate at 0xC0730700 and above, must not carry this probe.               */
.equ FOBJ,      0xC072F000     /* 0x800 -- the file object.  tableload.S
                                * reserves the same 0x800 for it.             */
.equ STAGING,   0xC072F800     /* 0x400 -- one window, or sixteen sweep heads */
.equ STAGING_SZ, 0x400
.equ PATHBUF,   0xC072FC00     /* 0x40 -- the filename being written          */
.equ BUFS_LO,   0xC072F000     /* what build_probe_card.py checks against     */
.equ BUFS_HI,   0xC072FC40

/* ---- the sweep -----------------------------------------------------------
 * 0x3xxxxxxx is the SoC peripheral space.  Three groups of sixteen 64 KiB
 * blocks covers 0x30000000..0x30300000, which contains every imaging block
 * this repository has named.  Sixteen words from the head of each block is
 * enough to tell a live bank from an empty one and to catch an ID register,
 * which is almost always at or very near offset 0.                           */
.equ SWEEP_BASE,   0x30000000
.equ SWEEP_GROUPS, 3
.equ SWEEP_BLOCKS, 16          /* per group; 16 * 64 B = STAGING_SZ           */
.equ SWEEP_HEAD,   16          /* words read from each block                  */

    .global enc_probe
enc_probe:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

/* ---- pass A: the banks this repository has already established ----------- */
    adr     r4, windows
    mov     r5, #0
A_next:
    ldr     r6, [r4], #4               @ base
    cmp     r6, #0
    beq     A_done
    ldr     r7, [r4], #4               @ words

    ldr_addr r0, STAGING
    mov     r1, r6
    mov     r2, r7
    bl      copy_words

    adr     r0, name_window
    mov     r1, r5
    bl      make_path

    ldr_addr r0, PATHBUF
    ldr_addr r1, STAGING
    lsl     r2, r7, #2
    bl      write_file

    add     r5, r5, #1
    b       A_next
A_done:

/* ---- pass B: the speculative sweep, last and in groups ------------------- */
    mov     r8, #0
B_next:
    cmp     r8, #SWEEP_GROUPS
    beq     B_done

    ldr_addr r9, STAGING
    ldr_addr r6, SWEEP_BASE
    add      r6, r6, r8, lsl #20       @ 16 blocks * 0x10000 = 0x100000
    mov      r10, #SWEEP_BLOCKS
B_block:
    mov     r0, r9
    mov     r1, r6
    mov     r2, #SWEEP_HEAD
    bl      copy_words
    add     r9, r9, #(SWEEP_HEAD * 4)
    add     r6, r6, #0x10000
    subs    r10, r10, #1
    bne     B_block

    adr     r0, name_sweep
    mov     r1, r8
    bl      make_path

    ldr_addr r0, PATHBUF
    ldr_addr r1, STAGING
    mov     r2, #STAGING_SZ
    bl      write_file

    add     r8, r8, #1
    b       B_next
B_done:

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

/* -------------------------------------------------------------------------
 * copy_words -- r0 = destination, r1 = source, r2 = word count.
 *
 * Word loads, one at a time, on purpose.  A memcpy is free to use byte or
 * multi-word accesses, and a peripheral register bank is entitled to refuse
 * both.  Uses r0-r3 only, so every caller's state survives it.
 */
copy_words:
    cmp     r2, #0
    bxeq    lr
1:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     1b
    bx      lr

/* -------------------------------------------------------------------------
 * make_path -- r0 = template, r1 = single digit.  Builds it in PATHBUF.
 * The digit is at index 5 of "\ENCW0.BIN": 0 is the backslash.
 */
make_path:
    ldr_addr r2, PATHBUF
    add     r1, r1, #0x30
1:  ldrb    r3, [r0], #1
    strb    r3, [r2], #1
    cmp     r3, #0
    bne     1b
    ldr_addr r2, PATHBUF
    strb    r1, [r2, #5]
    bx      lr

/* -------------------------------------------------------------------------
 * write_file -- r0 = path, r1 = buffer, r2 = length.
 *
 * The six-call sequence from gyro/gcsvgen.S, including the part that was paid
 * for: when F_OPEN fails the object F_CTOR built must still be destroyed.
 * Leaving one built wedged the file system until a power cycle -- \LENS.DAT
 * could not be opened again by anything -- and the damage does not heal.
 */
write_file:
    push    {r4, r5, r6, r7, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2

    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0                     @ r1 = volume

    ldr_addr r7, FOBJ
    mov     r0, r7
    ldr_addr ip, F_CTOR
    blx     ip

    mov     r0, r7
    mov     r1, r4
    mov     r2, #F_MODE_RW
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     wf_close                   @ did not open -- still destroy it

    mov     r0, r7
    mov     r1, r5
    mov     r2, r6
    ldr_addr ip, F_WRITE
    blx     ip

    mov     r0, r7
    ldr_addr ip, F_CLOSE
    blx     ip
wf_close:
    mov     r0, r7
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, r6, r7, pc}

/* -------------------------------------------------------------------------
 * The banks, in the order they are read.  Every base is one this repository
 * has already named; none of them is a guess.  0x100 words = 1 KiB each, which
 * covers the register file of every encoder IP this is trying to recognise.
 */
    .align  2
windows:
    .word   0x300C0000, 0x100    @ RFC readout -- live during recording (raw-sup)
    .word   0x300D0000, 0x100    @ lossless JPEG engine (raw-sup, confirmed)
    .word   0x301B0000, 0x100    @ the DSP recording uses (raw-sup)
    .word   0x30210000, 0x100    @ the shadow config bank (raw-sup, retraction)
    .word   0x30110000, 0x100    @ SIG registers -- expected to read 0, a control
    .word   0                    @ end

name_window:
    .byte   0x5C                 @ a backslash, spelled out so no escaping
    .asciz  "ENCW0.BIN"          @ convention can quietly change it
    .align  2
name_sweep:
    .byte   0x5C
    .asciz  "ENCS0.BIN"
    .align  2
