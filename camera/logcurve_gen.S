/* look_src_write -- write the DRAM SOURCE of the hardware knot registers.
 *
 * Writing the hardware registers at 0x30212020 did nothing: the readback was
 * byte-identical to before, so the device ignored the store
 * (results/knottest). But the knots the hardware holds for Teal & Orange
 * exist in DRAM at exactly ONE address -- 0xC0B3B2E8 -- inside a table of
 * 24-knot look curves at stride 0x124, one per colour mode -- of which this
 * card writes the first 16. The match is exact, so that table is what the
 * firmware uploads from.
 *
 * So: change the SOURCE at boot, then let the firmware do the upload itself by
 * selecting the mode. That is the same shape as every working fpSup product --
 * let the firmware move the data, change what it moves.
 *
 * Writes 32 bytes of DRAM. No prom, no fwup, no NAND, no register pokes.
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
.equ SRC_TO,0xC0B3B2E8      /* the Teal & Orange knot source */

    .global look_src_write
look_src_write:
    push    {r4, r5, r6, lr}
    /* overwrite the source, at boot, before any mode is applied */
    ldr_addr r0, 0xC0B3B9C0
    adr      r1, newknots
    mov      r2, #12
30:  ldr      r3, [r1], #4
    str      r3, [r0], #4
    subs     r2, r2, #1
    bne      30b
    ldr_addr r0, 0xC0B3BAE4
    adr      r1, newknots
    mov      r2, #12
31:  ldr      r3, [r1], #4
    str      r3, [r0], #4
    subs     r2, r2, #1
    bne      31b
    ldr_addr r0, 0xC0B3BC08
    adr      r1, newknots
    mov      r2, #12
32:  ldr      r3, [r1], #4
    str      r3, [r0], #4
    subs     r2, r2, #1
    bne      32b
    ldr_addr r0, 0xC0B3BD2C
    adr      r1, newknots
    mov      r2, #12
33:  ldr      r3, [r1], #4
    str      r3, [r0], #4
    subs     r2, r2, #1
    bne      33b

    adr     r0, s_sel
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, 25000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    adr     r0, n_src
    ldr_addr r1, SRC_TO
    mov     r2, #0x20
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
newknots:
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
s_sel:
    .asciz  "display text SELECT T AND O"
    .align  2
s_done:
    .asciz  "display text SRC TEST DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2
n_src:
    .byte   0x5C
    .asciz  "SRC.BIN"
    .align  2
n_hw:
    .byte   0x5C
    .asciz  "HW.BIN"
    .align  2
