/* shadowbank_probe -- read the whole ISP shadow bank idle, and (on a recording
 * run) inside a MOV take, to find the stage that writes the frame to DRAM.
 *
 * WHY.  results/yuvpack_1/ and results/code_10bit/ showed YUV_PACK has no width,
 * stride, address or format field, its selectors are only ever written 0, and its
 * enables are off in a take -- so it does not set the encoder input's 1 byte per
 * sample.  Whatever writes the frame out does.  Its shadow words should hold
 * 1920, a line stride or a plane address while a take runs.  The bank is
 * 0x30210000..0x30214000 (16 KiB of distinct registers, mirrored every 0x4000,
 * results/isprobe2/); tools/shadow_map.py names the stage behind each word.
 *
 * ONE CARD, TWO RUNS.
 *   live run       never press record: three idle rounds.  Words that differ
 *                  between them change by themselves (per frame) -- the baseline.
 *   recording run  press record at the first prompt: idle, inside the take, and
 *                  late in the take (or after it).
 *
 *   T+20 s   round 1                              -> S1n.BIN
 *            REC RUN RECORD NOW
 *   +15 s    round 2                              -> S2n.BIN
 *            REC RUN STOP NOW
 *   +20 s    round 3                              -> S3n.BIN
 *            SHADOW DONE
 *
 * SAFETY.  yuvpack_probe.S with a bigger table.  0x30210000..0x30214000 was read
 * live in 4 KiB windows by isp_live_probe.S v3 (results/isprobe2/, 34 files, no
 * hang), and 0x30212000 again inside a take (results/yuvpack_1/).  No block that
 * froze results/encrec_1/ or encrec_2/ is read.  DRAM windows first; one file per
 * window, so the first missing file names the window that stopped.  Nothing is
 * written anywhere but the files: no `mem set`, no prom, no fwup, no NAND.
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

    .global shadowbank_probe
shadowbank_probe:
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

/* make_path -- r0 = round char, r1 = window index (< 10). Builds "\S<r><n>.BIN". */
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
 * does not.  Keep in step with tools/check_shadowbank.py, which reads this table. */
windows:
    .word   0xC38D6000, 0x400       @ S?0  recording block -- width at +0x2BC
    .word   0xC38D4000, 0x100       @ S?1  SPS buffer -- Annex-B at +0x60
    .word   0x30210000, 0x1000      @ S?2  shadow bank, as isprobe2 read it
    .word   0x30211000, 0x1000      @ S?3
    .word   0x30212000, 0x1000      @ S?4  YUV_PACK at +0x36C..+0x3E0
    .word   0x30213000, 0x1000      @ S?5
    .word   0
s_rec:
    .asciz  "display text REC RUN RECORD NOW"
    .align  2
s_stop:
    .asciz  "display text REC RUN STOP NOW"
    .align  2
s_done:
    .asciz  "display text SHADOW DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2

name_tmpl:
    .byte   0x5C                    @ backslash, spelled out
    .asciz  "S00.BIN"
    .align  2
