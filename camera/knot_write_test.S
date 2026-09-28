/* knot_write_test -- does writing an ISP register reach the picture?
 *
 * results/isprobe2 found a 16-knot piecewise-linear curve at 0x30212020 that
 * the colour mode rewrites: exactly linear in mode Off, gently curved in Teal
 * & Orange. It is not the main transfer function -- it does not match either
 * DRAM curve -- but it is a mode-dependent hardware LUT, and that makes it the
 * right thing to test the WRITE path on.
 *
 * Writing a DRAM curve table changed nothing (results/cachetest_!). If writing
 * these registers changes the picture, the mechanism fpLog needs exists and
 * the remaining job is finding the block that holds the main gamma. If it
 * changes nothing either, MMIO config writes do not reach the render path and
 * the approach needs rethinking rather than more searching.
 *
 * Runs at T+20 s with the camera live, in mode OFF -- where this curve is
 * currently a straight line, so any change at all is unmistakable. The curve
 * written is x^0.40 over the same 0..0xA000 span: a large lift.
 *
 * Reads before, writes, then reads back after a pause -- a write is only real
 * once it has been read back, and the second read also says whether the
 * firmware put its own values back.
 *
 * RAM/MMIO only. No prom, no fwup, no NAND. Battery-out cold boot reverts.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

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

.equ FOBJ,       0xC072F000
.equ PATHBUF,    0xC072F800
.equ STAGING,    0xC072F900
.equ SHBUF,      0xC072FD00
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC072FD40

.equ KNOTS,      0x30212020      /* the 16 contiguous knot words */
.equ KLEN,       0x40
.equ DUMP,       0x30212000      /* the whole record, for context */
.equ DLEN,       0x400

    .global knot_write
knot_write:
    push    {r4, r5, r6, lr}

    ldr_addr r0, 20000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    adr     r0, n_before
    ldr_addr r1, DUMP
    mov     r2, #DLEN
    bl      dump

    /* write the 16 knots */
    ldr_addr r0, KNOTS
    adr     r1, newknots
    mov     r2, #16
1:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     1b

    adr     r0, s_look
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, 25000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    adr     r0, n_after
    ldr_addr r1, DUMP
    mov     r2, #DLEN
    bl      dump
    adr     r0, n_mirror
    ldr_addr r1, 0x30216000
    mov     r2, #DLEN
    bl      dump

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd
    mov     r0, #0
    pop     {r4, r5, r6, pc}

/* dump -- r0 = path template, r1 = src, r2 = bytes */
dump:
    push    {r4, r5, r6, r7, lr}
    mov     r5, r1
    mov     r6, r2
    ldr_addr r2, PATHBUF
    mov     r3, r0
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
    ldr_addr r0, STAGING
    mov     r1, r5
    lsr     r2, r6, #2
2:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     2b
    ldr_addr ip, F_MGR
    blx     ip
    mov     r1, #0
    ldr_addr ip, F_VOL
    blx     ip
    mov     r1, r0
    ldr_addr r4, FOBJ
    mov     r0, r4
    ldr_addr ip, F_CTOR
    blx     ip
    mov     r0, r4
    ldr_addr r1, PATHBUF
    mov     r2, #F_MODE_RW
    ldr_addr ip, F_OPEN
    blx     ip
    cmp     r0, #0
    beq     3f
    mov     r0, r4
    ldr_addr r1, STAGING
    mov     r2, r6
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r0, r4
    ldr_addr ip, F_CLOSE
    blx     ip
3:  mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, r6, r7, pc}

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

    .align  2
newknots:
    .word   0x00000000
    .word   0x00003629
    .word   0x00004777
    .word   0x0000540D
    .word   0x00005E4D
    .word   0x0000671A
    .word   0x00006EE7
    .word   0x000075F5
    .word   0x00007C6E
    .word   0x0000826E
    .word   0x0000880C
    .word   0x00008D55
    .word   0x00009256
    .word   0x00009719
    .word   0x00009BA5
    .word   0x0000A000

s_look:
    .asciz  "display text LOOK AT SCREEN"
    .align  2
s_done:
    .asciz  "display text KNOT TEST DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2
n_before:
    .byte   0x5C
    .asciz  "KB.BIN"
    .align  2
n_after:
    .byte   0x5C
    .asciz  "KA.BIN"
    .align  2
n_mirror:
    .byte   0x5C
    .asciz  "KM.BIN"
    .align  2
