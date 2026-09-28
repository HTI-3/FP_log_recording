/* logall -- write the log curve into BLOCK B of the 12 shaped records.
 *
 * results/logoff1: the four identity records were written and mode Off still
 * showed a pure identity in hardware, so Off does not load any of them --
 * either it uses a record we did not pick, or it bypasses the stage entirely.
 *
 * Every card so far has written block A at +0x000. Across 35 records and
 * across 12, that only ever moved COLOUR -- never contrast -- and Monochrome,
 * which has no chroma, never changed at all. So block A is chroma.
 *
 * Each record holds a SECOND knots/gains/slopes triple at +0x094, identity in
 * every record and every mode, which is what an untouched channel looks like.
 * If A is chroma then B is the obvious candidate for luma, and it has never
 * been written.
 *
 * This writes block B only. Block A is left alone, so there should be no
 * colour cast -- and if the contrast moves, that is the luma curve found.
 *
 * Writes 1680 bytes of DRAM. No registers, no prom, no fwup, no NAND.
 * Battery-out cold boot reverts. Ver.5.02 only.
 *
 * *** RECORD LAYOUT CORRECTED 2026-09-22 (docs/LOOK_CURVE.md). ***
 * The addresses below are NOT record starts. A record is 0x124 bytes:
 *   +0x000 knots A   +0x030 gains A  +0x060 slopes A
 *   +0x090 knots B   +0x0C0 id       +0x0C4 gains B  +0x0F4 slopes B
 * Every address here is a record_start + 0x090, i.e. KNOTS B.  The write is
 * still the array that was intended and that reached the picture; only the
 * label was wrong.  Verify with tools/look_records.py before reusing them.
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

    .global logall
logall:
    push    {r4, r5, r6, r7, lr}
    adr     r4, records
1:  ldr     r5, [r4], #4
    cmp     r5, #0
    beq     2f
    add     r5, r5, #0x94               @ BLOCK B, not block A
    adr     r6, knots
    mov     r7, #12
3:  ldr     r3, [r6], #4
    str     r3, [r5], #4
    subs    r7, r7, #1
    bne     3b
    b       1b
2:
    adr     r0, s_try
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, 45000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    adr     r0, n_src
    ldr_addr r1, 0xC0B3AC10
    mov     r2, #0x30
    bl      dump
    adr     r0, n_hw
    ldr_addr r1, 0x30212000
    mov     r2, #0x400
    bl      dump

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd
    mov     r0, #0
    pop     {r4, r5, r6, r7, pc}

    .align  2
knots:
    .word   0x066B0000
    .word   0x30D419DB
    .word   0x59954669
    .word   0x79576A72
    .word   0x9287869B
    .word   0xA7359D56
    .word   0xB8AEB049
    .word   0xC7C7C07C
    .word   0xD50FCE9E
    .word   0xE0E8DB24
    .word   0xEB99E662
    .word   0xF555F093
    .align  2
records:
    .word   0xC0B3AC10   @ id 3
    .word   0xC0B3AD34   @ id 5
    .word   0xC0B3AE58   @ id 6
    .word   0xC0B3AF7C   @ id 7
    .word   0xC0B3B0A0   @ id 8
    .word   0xC0B3B1C4   @ id 10
    .word   0xC0B3B2E8   @ id 11
    .word   0xC0B3B40C   @ id 12
    .word   0xC0B3B530   @ id 13
    .word   0xC0B3B654   @ id 14
    .word   0xC0B3B778   @ id 15
    .word   0xC0B3B89C   @ id 1
    .word   0

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
n_src:
    .byte   0x5C
    .asciz  "RECB.BIN"
    .align  2
n_hw:
    .byte   0x5C
    .asciz  "HW.BIN"
    .align  2
s_try:
    .asciz  "display text TRY MODES BLKB"
    .align  2
s_done:
    .asciz  "display text LOGALL DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2
