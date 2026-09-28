/* isp_live_probe -- read the ISP while the camera is RUNNING, with no USB shell.
 *
 * WHY.  The boot probe (results/run1_21_09_2026) found every imaging block
 * powered down, because an AutoRun runs before the imaging subsystem is up.
 * Writing the DRAM tone-curve tables was then shown not to reach the picture
 * (results/cachetest_!), so the live LUT is in ISP hardware, not DRAM. To see
 * it, something has to read those registers after the camera has started.
 *
 * HOW, WITHOUT A SHELL.  A `--boot-call` routine is run by borrowing the echo
 * shell handler, so it executes in the dispatcher's task -- and fp_sup's
 * fp-usb-shell notes say that is the one context that may BLOCK, take mutexes
 * and do file I/O. So this simply sleeps and then dumps. No thread to create,
 * no vtable to get wrong, no hook in the recording path.
 *
 * TWO ROUNDS, AND THE POINT IS THE DIFF.
 *   T+20s  round 1 -> L1*.BIN
 *   T+50s  round 2 -> L2*.BIN
 * Change the colour mode between them. Whatever differs in the ISP registers
 * is what the colour mode actually reconfigures -- the same trick that found
 * the DRAM selector, applied one level further in.
 *
 * WHY v1 WROTE NOTHING.  The timing probe wrote all six markers, so the payload
 * runs and a 30 s delay is fine.  What v1 did that the proven encoder probe did
 * not was read each register bank in one 16 KiB sweep.  A peripheral register
 * file is usually a few KiB; reading past the end of a mapped bank can abort,
 * and v1 hung inside its FIRST window before any file was closed -- which is
 * exactly "nothing was written".
 *
 * v2 therefore: windows of 0x400, the size the encoder probe actually read at
 * these same bases without incident; the safe DRAM window FIRST so there is
 * always evidence; and one file per window, so the first missing file names
 * the address that stopped it.
 *
 * SAFETY.  Every access to a register bank is a 32-bit load. Nothing is written
 * anywhere: no `mem set`, no prom, no fwup, no NAND. The only writes are the
 * files, through the firmware's own file API -- the same six calls
 * gyro/gcsvgen.S makes, including destroying the object when the open fails.
 * This payload is the read-only enc_probe.S with a delay and bigger windows;
 * that one ran to completion on this camera.
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
/* The firmware's own shell executor, so the payload can put text on screen at
 * the moment a round finishes instead of the user counting seconds.
 * f(ctx, char *line); the line must be WRITABLE because strtok NULs it, so
 * every call copies its template into SHBUF first.  SHELL_CTX is already
 * initialised at boot (docs/SHELL_CAPABILITIES.md). */
.equ FN_SHRUN,   0xC03D9C20
.equ SHELL_CTX,  0xC3756904

/* ---- cave, all above build_autorun.py's loader (0xC072E800..0xC072EF30) --- */
.equ FOBJ,       0xC072F000     /* 0x800 -- same reserve tableload.S uses     */
.equ PATHBUF,    0xC072F800     /* 0x40                                       */
.equ STAGING,    0xC072F900     /* 0x400 -- one window                        */
.equ STAGING_SZ, 0x1000
.equ SHBUF,      0xC0730900     /* 0x40 -- a writable copy of the command     */
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC0730940

.equ DELAY1_MS,  20000
.equ DELAY2_MS,  30000

    .global isp_probe
isp_probe:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    /* No DRAM write this time. The variable is the camera's CONTRAST setting,
     * changed by hand between the rounds -- it moves the luma tone curve and
     * little else, where colour mode moves chroma curves, matrices and gains
     * together and made every earlier diff ambiguous. */
    b       skip_write
    ldr_addr r0, 0xC0B3B2E8
    adr      r1, identknots
    mov      r2, #12
9:  ldr      r3, [r1], #4
    str      r3, [r0], #4
    subs     r2, r2, #1
    bne      9b
    b        past_knots
    .align   2
identknots:
    .word   0x0AAB0000
    .word   0x20001555
    .word   0x35552AAB
    .word   0x4AAB4000
    .word   0x60005555
    .word   0x75556AAB
    .word   0x8AAB8000
    .word   0xA0009555
    .word   0xB555AAAB
    .word   0xCAABC000
    .word   0xE000D555
    .word   0xF555EAAB
skip_write:
past_knots:

    ldr_addr r0, DELAY1_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r8, #'1'
    bl      dump_all

    @ round 1 is on the card before anything else is attempted
    adr     r0, s_change
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY2_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r8, #'2'
    bl      dump_all

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

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
 * PATHBUF. Opens once and streams in STAGING_SZ chunks, so a 16 KiB window
 * needs only a 4 KiB buffer.
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
 * (the executor's strtok writes NULs into the line, so a fresh copy each
 * time) and runs it through the firmware's own shell. */
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

/* make_path -- r0 = round char, r1 = window index. Builds "\L<r><n>.BIN". */
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
/* The imaging blocks the boot probe found DEAD -- they are the ones that were
 * powered down when idle, so they are the ones worth reading while running.
 * 0x30210000 answered at boot and is included as a change control.
 * The last entry is DRAM: the live curve selector, so each round records which
 * curve was selected at that moment. */
windows:
    .word   0xC3414000, 0x1000      @ DRAM selector, as a control
    .word   0x30210000, 0x1000   @ the ISP config block where the chroma knots live
    .word   0x30211000, 0x1000
    .word   0x30212000, 0x1000
    .word   0x30213000, 0x1000
    .word   0x30214000, 0x1000
    .word   0x30215000, 0x1000
    .word   0x30216000, 0x1000
    .word   0x30217000, 0x1000
    .word   0x30218000, 0x1000
    .word   0x30219000, 0x1000
    .word   0x3021A000, 0x1000
    .word   0x3021B000, 0x1000
    .word   0x3021C000, 0x1000
    .word   0x3021D000, 0x1000
    .word   0x3021E000, 0x1000
    .word   0x3021F000, 0x1000
    .word   0
s_change:
    .asciz  "display text CHANGE TONE NOW"
    .align  2
s_done:
    .asciz  "display text LIVE PROBE DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2

name_tmpl:
    .byte   0x5C                    @ backslash, spelled out
    .asciz  "L000.BIN"
    .align  2
