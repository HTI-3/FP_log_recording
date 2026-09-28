/* invert_curve -- invert one GAM_TOP gamma curve in place, then let the
 * firmware upload it.  *** THIS PAYLOAD WRITES TO MEMORY ***
 *
 * THE QUESTION.  docs/CURVE_TARGETS.md target 1.  The 452-curve registry at
 * 0xC0971118 is the data behind `GAM_TOP GAMMA TABLE` -- the RGB transfer
 * function, the one stage in the pipeline where a log curve belongs.  It was
 * recorded as inert because results/selector/ repointed the selector live and
 * the picture did not change.  That test deliberately did not change the
 * colour mode, and results/looksrc1/ established that the firmware uploads
 * WHEN A MODE IS SELECTED.  So it moved a pointer and never triggered the read.
 * The verdict was withdrawn; this card is the re-run, with the trigger.
 *
 * WHY INVERT AND NOT FLATTEN.  An earlier version of this experiment flattened
 * a few hundred entries to a constant, which shows up as a band on a gradient.
 * That is a judgement call on a live LCD, and this project has already drawn a
 * wrong conclusion from "the picture changed" once (results/logoff1/REFRAME.md
 * -- the literal report was "it changed the color").  An inverted curve renders
 * a PHOTOGRAPHIC NEGATIVE.  Nobody has to decide whether they saw it.
 *
 * TWO PASSES, NO CONSTANT.  Pass 1 takes each table's OWN maximum; pass 2
 * mirrors every entry about it.  The dump says curve #82 runs 0..8190, but the
 * card does not have to be right about that: a hardcoded ceiling that was too
 * low would clip instead of inverting, and a clipped picture is exactly the
 * ambiguous result this card exists to avoid.  Each output spans the same value
 * range as its input and is monotonically DECREASING.
 *
 * BOTH CURVES, NOT ONE.  #82 is colour mode Off and #16 is Teal & Orange.
 * Off is the neutral mode and the one to ship on, but every write this project
 * has aimed at Off has failed to move the picture, while the ONE write that
 * worked was aimed at Teal & Orange (results/looksrc1/, record id 11).  So both
 * are inverted -- and since the operator forces the upload by toggling between
 * exactly those two modes, every transition lands on an inverted table.  If
 * only one of them responds, that asymmetry is itself the finding.
 *
 * Teal & Orange carries a stylised colour matrix in 19 ISP registers that
 * cannot be neutralised, so ITS negative will be colour-skewed.  That does not
 * weaken the read: the question is whether the transfer function moved at all,
 * not what hue it landed on.
 *
 * THREE ROUNDS, SO A FAILED WRITE AND A FAILED UPLOAD STAY DISTINGUISHABLE.
 *   T+20s  round 1 -> V1*.BIN   baseline, before anything is written
 *          invert
 *          round 2 -> V2*.BIN   did the write land?
 *   prompt "TOGGLE OFF AND T+O"  the operator forces the upload
 *   T+50s  round 3 -> V3*.BIN   did the firmware upload it, or rewrite it?
 *
 * Each round captures the table, the live selector, and the ISP shadow bank
 * that holds the 65-knot hardware ramp at 0x30210594.  tools/check_invert.py
 * turns the nine files into one of the four outcomes.
 *
 * SAFETY.  4096 bytes of DRAM, inside one tone-curve table.  No prom, no fwup,
 * no NAND, no register pokes -- the ISP bank is READ only.  Delete AutoRun.txt,
 * BATTERY OUT, power on: the table is whatever the boot loader decompresses.
 * A warm restart does NOT clear RAM.  Firmware Ver.5.02 only.
 *
 * The file helpers below are isp_live_probe.S's, unchanged -- that payload ran
 * to completion on this camera.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* ---- firmware entry points, as gyro/tableload.S and ring_task.inc.S name them */
.equ F_MGR,      0xC0444658
.equ F_VOL,      0xC0444698
.equ F_CTOR,     0xC0365E90
.equ F_OPEN,     0xC0365FB0
.equ F_WRITE,    0xC03660E8
.equ F_CLOSE,    0xC0366020
.equ F_DTOR,     0xC0365ED0
.equ F_MODE_RW,  7
.equ TK_DLY_TSK, 0xC01F89C4     /* f(ms) -- ring_task.inc.S:50               */
.equ FN_SHRUN,   0xC03D9C20     /* f(ctx, char *line); line must be WRITABLE */
.equ SHELL_CTX,  0xC3756904

/* ---- cave, all above build_autorun.py's loader (0xC072E800..0xC072EF30) --- */
.equ FOBJ,       0xC072F000     /* 0x800                                      */
.equ PATHBUF,    0xC072F800     /* 0x40                                       */
.equ STAGING,    0xC072F900     /* 0x1000                                     */
.equ STAGING_SZ, 0x1000
.equ SHBUF,      0xC0730900     /* 0x40                                       */
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC0730940

/* The `targets` and `windows` tables at the end of this file are REGENERATED
 * by build_invert_card.py -- do not edit them by hand.  Curve n is at
 * 0xC0971F34 + n * 0x1000, 2048 u16, and the stride IS the table, so a 0x1000
 * window is the whole curve and nothing else. */

.equ DELAY1_MS,  20000
.equ DELAY2_MS,  30000

    .global invert_probe
invert_probe:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    ldr_addr r0, DELAY1_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    mov     r8, #'1'
    bl      dump_all                    @ baseline, before anything is written

    bl      invert_all

    mov     r8, #'2'
    bl      dump_all                    @ did the write land?

    adr     r0, s_toggle
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY2_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    mov     r8, #'3'
    bl      dump_all                    @ uploaded?  or rewritten by the firmware?

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

/* invert_all -- walk the `targets` table, inverting each curve in place. */
invert_all:
    push    {r4, r5, r6, lr}
    adr     r4, targets
1:  ldr     r5, [r4], #4                @ base
    cmp     r5, #0
    beq     2f
    ldr     r6, [r4], #4                @ u16 count
    mov     r0, r5
    mov     r1, r6
    bl      invert_one
    b       1b
2:  pop     {r4, r5, r6, pc}

/* invert_one -- r0 = base, r1 = u16 count.  v := max(table) - v, in place.
 * Two passes: the maximum is measured, never assumed. */
invert_one:
    push    {r4, r5, r6, lr}
    mov     r4, r0                      @ base
    mov     r5, r1                      @ count
    mov     r6, #0                      @ running maximum

    mov     r2, r4
    mov     r3, r5
1:  ldrh    r0, [r2], #2
    cmp     r0, r6
    movhi   r6, r0
    subs    r3, r3, #1
    bne     1b

    mov     r2, r4
    mov     r3, r5
2:  ldrh    r0, [r2]
    sub     r0, r6, r0
    strh    r0, [r2], #2
    subs    r3, r3, #1
    bne     2b
    pop     {r4, r5, r6, pc}

/* dump_all -- r8 = round character. Walks the window table. */
dump_all:
    push    {r4, r5, r6, r7, lr}
    adr     r4, windows
    mov     r5, #0
1:  ldr     r6, [r4], #4                @ base
    cmp     r6, #0
    beq     2f
    ldr     r7, [r4], #4                @ length
    mov     r0, r8
    mov     r1, r5
    bl      make_path
    mov     r0, r6
    mov     r1, r7
    bl      write_region
    add     r5, r5, #1
    b       1b
2:  pop     {r4, r5, r6, r7, pc}

/* write_region -- r0 = source address, r1 = total bytes. Path already in
 * PATHBUF. Opens once and streams in STAGING_SZ chunks.
 *
 * Word loads throughout: a memcpy is free to use byte or multi-word accesses
 * and a peripheral register bank is entitled to refuse both.
 */
write_region:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0                      @ src
    mov     r5, r1                      @ remaining

    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
    ldr_addr r6, FOBJ
    mov     r0, r6
    ldr_addr ip, F_CTOR
    blx     ip

    mov     r0, r6
    ldr_addr r1, PATHBUF
    mov     r2, #F_MODE_RW
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     wr_dtor                     @ did not open -- still destroy it

wr_chunk:
    cmp     r5, #0
    beq     wr_close
    mov     r7, #STAGING_SZ
    cmp     r5, r7
    movlt   r7, r5                      @ r7 = this chunk's bytes
    ldr_addr r0, STAGING
    mov     r1, r4
    lsr     r2, r7, #2
    bl      copy_words
    mov     r0, r6
    ldr_addr r1, STAGING
    mov     r2, r7
    ldr_addr ip, F_WRITE
    blx     ip
    add     r4, r4, r7
    sub     r5, r5, r7
    b       wr_chunk

wr_close:
    mov     r0, r6
    ldr_addr ip, F_CLOSE
    blx     ip
wr_dtor:
    mov     r0, r6
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, r6, r7, r8, pc}

/* shcmd -- r0 = a NUL-terminated command template. Copies it into SHBUF
 * (the executor's strtok writes NULs into the line) and runs it. */
shcmd:
    push    {r4, lr}
    ldr_addr r2, SHBUF
    mov     r3, r0
1:  ldrb    r4, [r3], #1
    strb    r4, [r2], #1
    cmp     r4, #0
    bne     1b
    ldr_addr r0, SHELL_CTX
    ldr_addr r1, SHBUF
    ldr_addr ip, FN_SHRUN
    blx     ip
    pop     {r4, pc}

/* copy_words -- r0 = dst, r1 = src, r2 = words. r0-r3 only. */
copy_words:
    cmp     r2, #0
    bxeq    lr
1:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     1b
    bx      lr

/* make_path -- r0 = round char, r1 = window index. Builds "\V<r><nn>.BIN". */
make_path:
    push    {r4, lr}
    ldr_addr r2, PATHBUF
    adr     r3, name_tmpl
1:  ldrb    r4, [r3], #1
    strb    r4, [r2], #1
    cmp     r4, #0
    bne     1b
    ldr_addr r2, PATHBUF
    strb    r0, [r2, #2]                @ round digit
    mov     r3, #0                      @ no udiv on this core: subtract loop
mp_div:
    cmp     r1, #10
    blo     mp_done
    sub     r1, r1, #10
    add     r3, r3, #1
    b       mp_div
mp_done:
    add     r3, r3, #0x30
    add     r1, r1, #0x30
    strb    r3, [r2, #3]
    strb    r1, [r2, #4]
    pop     {r4, pc}

    .align  2
/* The two DRAM windows come FIRST so there is always evidence on the card even
 * if the register read stops the payload -- the lesson isp_live_probe.S v1
 * paid for.  0x30210000 is the only imaging block that answered live, and it
 * is where the 65-knot hardware ramp sits, at +0x594. */
targets:
    .word   0xC09C3F34, 2048        @ curve #82 -- colour mode "Off"
    .word   0xC0981F34, 2048        @ curve #16 -- colour mode "Teal & Orange"
    .word   0
windows:
    .word   0xC09C3F34, 0x1000      @ 00 -- curve #82, the table this card writes
    .word   0xC0981F34, 0x1000      @ 01 -- curve #16, ditto
    .word   0xC3414000, 0x1000      @ 02 -- live selector (+0x510/+0xD4C/+0xD84)
    .word   0x30210000, 0x1000      @ 03 -- shadow bank, hardware ramp at +0x594
    .word   0
s_toggle:
    .asciz  "display text TOGGLE OFF AND T+O"
    .align  2
s_done:
    .asciz  "display text INVERT DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2

name_tmpl:
    .byte   0x5C                    @ backslash, spelled out
    .asciz  "V000.BIN"
    .align  2
