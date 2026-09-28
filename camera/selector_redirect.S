/* selector_redirect -- does the 89-curve bank reach the picture?
 *
 * The neutralised ramp (results/neutralize) showed Off and Teal render up to
 * 46 code values apart with the look knots identity -- but colour mode changes
 * 89 registers in 0x3021 and only 70 of them are those knots. The other 19 are
 * gains and matrices, and they alone could account for the whole difference.
 * So that test did NOT isolate the curve bank, and the claim that it did was
 * wrong.
 *
 * This isolates it. With the camera live and in mode Off, it repoints the three
 * selector words from curve #82 to curve #16 and sets the index beside them.
 * NOTHING else changes -- same colour mode, same gains, same matrices, same
 * look trim. If the picture moves, the bank is on the render path. If it does
 * not, it is not, and the ramp difference was those other 19 registers.
 *
 * Writes 4 words of live state. No registers, no prom, no fwup, no NAND.
 * Battery-out cold boot reverts. Ver.5.02 only.
 */
    .syntax unified
    .arm
.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm
.equ F_MGR,0xC0444658
.equ F_VOL,0xC0444698
.equ F_CTOR,0xC0365E90
.equ F_OPEN,0xC0365FB0
.equ F_WRITE,0xC03660E8
.equ F_CLOSE,0xC0366020
.equ F_DTOR,0xC0365ED0
.equ F_MODE_RW,7
.equ TK_DLY_TSK,0xC01F89C4
.equ FN_SHRUN,0xC03D9C20
.equ SHELL_CTX,0xC3756904
.equ FOBJ,0xC072F000
.equ PATHBUF,0xC072F800
.equ STAGING,0xC072F900
.equ SHBUF,0xC072FD00
.equ BUFS_LO,0xC072F000
.equ BUFS_HI,0xC072FD40
.equ SEL_A,      0xC3414510      /* the three selector pointers */
.equ SEL_B,      0xC3414D4C
.equ SEL_C,      0xC3414D84
.equ SEL_IDX,    0xC3414D48      /* the index word beside SEL_B */
.equ CURVE16,    0xC0981F34      /* what mode Teal & Orange points at */

    .global selector_redirect
selector_redirect:
    push    {r4, r5, r6, lr}

    /* wait for the camera to be live and settled in mode Off */
    ldr_addr r0, 20000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    /* repoint all three selectors at curve #16, and the index with them */
    ldr_addr r1, CURVE16
    ldr_addr r0, SEL_A
    str     r1, [r0]
    ldr_addr r0, SEL_B
    str     r1, [r0]
    ldr_addr r0, SEL_C
    str     r1, [r0]
    mov     r1, #16
    ldr_addr r0, SEL_IDX
    str     r1, [r0]

    adr     r0, s_sel
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, 20000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    adr     r0, n_src
    ldr_addr r1, 0xC3414000
    mov     r2, #0x1000
    bl      dump

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd
    mov     r0, #0
    pop     {r4, r5, r6, pc}

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
s_sel:
    .asciz  "display text LOOK AT SCREEN"
    .align  2
s_done:
    .asciz  "display text SELECTOR DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2
n_src:
    .byte   0x5C
    .asciz  "SEL.BIN"
    .align  2
    .align  2
