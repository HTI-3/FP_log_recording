/* yuvpack_probe -- read YUV_PACK's configuration idle, INSIDE a MOV take, and after.
 *
 * WHY.  The question is whether the packer in front of the H.264 encoder can
 * hand it more than 8 bits (docs/TEN_BIT_PLAN.md, gate 1).  The firmware
 * programs YUV_PACK through the sequencer's shadow bank: the command-list
 * builder at 0xC019D6E4 maps
 *
 *     shadow 0x3021236C  x 7  ->  YUV_PACK 0x3011E004..
 *     shadow 0x30212388  x11  ->  YUV_PACK 0x3011E130..
 *     shadow 0x302123B4  x11  ->  YUV_PACK 0x3011E1B0..
 *
 * and the per-pattern bank offset table at 0xC07D4360 puts Mov, UpdateMov,
 * HdmiRaw and both Jpg patterns in the 0x3021 bank (only Dng uses 0x3024).
 * Every capture so far was taken in live view with no take running, and all 29
 * words read zero except one 0x00100010 -- so the Mov pattern's packer has never
 * been read while it is actually packing for the encoder.
 *
 * THREE ROUNDS.
 *   T+20 s   round 1, idle live view            -> Y1n.BIN
 *            RECORD NOW
 *   +15 s    round 2, inside the take           -> Y2n.BIN
 *            STOP RECORDING NOW
 *   +20 s    round 3, after the take            -> Y3n.BIN
 *            YUVPACK DONE
 *
 * The DRAM windows are the take control: the recording block at 0xC38D62BC
 * holds the picture width and the SPS sits at 0xC38D4060 only during and after
 * a take (results/dram_rec_23_09_2026/, results/dram_uhd_23_09_2026/).  So a
 * round 2 without them was not inside a take, and nothing it read means
 * anything.
 *
 * SAFETY.  isp_live_probe.S with a smaller table.  The shadow page 0x30212000
 * has been read live twice without incident (results/isprobe2/ L103, the
 * tonedrive TB.BIN), and isprobe_1 read the same bank inside a take.  Register
 * banks that froze the camera in results/encrec_1/ and encrec_2/ are NOT read.
 * DRAM windows first, so a hang in the shadow read still leaves the control on
 * the card, and one file per window names the one that stopped.  Round 2 writes
 * three small files during the take; the dump card wrote 64 MB during a take
 * without harming the MOV.  Nothing is written anywhere but the files: no
 * `mem set`, no prom, no fwup, no NAND.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* ---- firmware entry points, as isp_live_probe.S uses them ---------------- */
.equ F_MGR,      0xC0444658
.equ F_VOL,      0xC0444698
.equ F_CTOR,     0xC0365E90
.equ F_OPEN,     0xC0365FB0
.equ F_WRITE,    0xC03660E8
.equ F_CLOSE,    0xC0366020
.equ F_DTOR,     0xC0365ED0
.equ F_MODE_RW,  7
.equ TK_DLY_TSK, 0xC01F89C4
.equ FN_SHRUN,   0xC03D9C20
.equ SHELL_CTX,  0xC3756904

/* ---- cave, the same layout isp_live_probe.S proved ------------------------ */
.equ FOBJ,       0xC072F000     /* 0x800                                      */
.equ PATHBUF,    0xC072F800     /* 0x40                                       */
.equ STAGING,    0xC072F900     /* 0x1000 -- up to one chunk                  */
.equ STAGING_SZ, 0x1000
.equ SHBUF,      0xC0730900     /* 0x40 -- a writable copy of the command     */
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC0730940

.equ DELAY1_MS,  20000          /* boot -> round 1, live view up              */
.equ DELAY2_MS,  15000          /* RECORD NOW -> round 2, well inside a take  */
.equ DELAY3_MS,  20000          /* STOP -> round 3, the MOV closed            */

    .global yuvpack_probe
yuvpack_probe:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    ldr_addr r0, DELAY1_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r8, #'1'
    bl      dump_all

    adr     r0, s_rec
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY2_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r8, #'2'
    bl      dump_all

    adr     r0, s_stop
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY3_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r8, #'3'
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

/* write_region -- r0 = source address, r1 = total bytes. Path in PATHBUF.
 * Word loads only: a register bank is entitled to refuse anything else. */
write_region:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r5, r1

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
    beq     wr_dtor

wr_chunk:
    cmp     r5, #0
    beq     wr_close
    mov     r7, #STAGING_SZ
    cmp     r5, r7
    movlt   r7, r5
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

/* shcmd -- r0 = a NUL-terminated command template, copied into SHBUF because
 * the executor's strtok writes into the line. */
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

/* make_path -- r0 = round char, r1 = window index (< 10). Builds "\Y<r><n>.BIN". */
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
    add     r1, r1, #0x30
    strb    r1, [r2, #3]                @ window digit
    pop     {r4, pc}

    .align  2
/* DRAM first: the take control must reach the card even if the register read
 * does not.  Keep in step with tools/check_yuvpack.py, which reads this table. */
windows:
    .word   0xC38D6000, 0x400       @ Y?0  recording block -- width at +0x2BC
    .word   0xC38D4000, 0x100       @ Y?1  SPS buffer -- Annex-B at +0x60
    .word   0x30212000, 0x400       @ Y?2  shadow page -- YUV_PACK at +0x36C..+0x3E0
    .word   0
s_rec:
    .asciz  "display text RECORD NOW"
    .align  2
s_stop:
    .asciz  "display text STOP RECORDING NOW"
    .align  2
s_done:
    .asciz  "display text YUVPACK DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2

name_tmpl:
    .byte   0x5C                    @ backslash, spelled out
    .asciz  "Y00.BIN"
    .align  2
