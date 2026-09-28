/* tonedrive -- drive the luma setters from the card, with no menu access.
 *
 * The camera's menus expose no Contrast, Tone Control or Fill Light we can
 * reach, so there is no UI way to move the luma curve and diff it. But the
 * firmware has the setters, and an AutoRun payload can call the firmware's own
 * shell executor -- every card in this project already does, to print to
 * screen. The only missing piece was capturing what a command prints.
 *
 * That is what this adds, using the recipe in fp_sup's SHELL_CAPABILITIES.md:
 * push an output sink onto the shell context, run the line, pop the sink.
 * The sink is a printf-style varargs callback, so it spills r1-r3 and hands
 * vsnprintf the address of the first one.
 *
 * It unlocks, with no USB and no menu entry:
 *   menu dump              every setting and its value
 *   pic / optic            the ISP sub-function tables, printed by the firmware
 *   menu Set<X> <value>    drive a luma control directly, then diff registers
 *
 * READ-ONLY apart from the output file: the commands here only print. No
 * mem set, no prom, no fwup, no NAND. Battery-out cold boot reverts.
 * Ver.5.02 only.
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
.equ FN_SHPUSH,  0xC03D9AC0
.equ FN_SHPOP,   0xC03D9B20
.equ SHELL_CTX,  0xC3756904
.equ VSNPRINT,   0xC0013F48      /* f(buf, size, fmt, &a1) */

.equ FOBJ,       0xC072F000
.equ PATHBUF,    0xC072F800
.equ SHBUF,      0xC072F900      /* the command line: strtok NULs it        */
.equ CAPPTR,     0xC0730FF0
.equ CAPBUF,     0xC0731000
.equ CAPSZ,      0x8000
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC0739000

    .global tonedrive
tonedrive:
    push    {r4, r5, lr}
    ldr_addr r0, CAPPTR
    mov     r1, #0
    str     r1, [r0]

    /* let the subsystems finish coming up -- menu and pic need their drivers */
    ldr_addr r0, 20000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    /* ISP registers BEFORE the setters */
    adr     r0, n_b
    ldr_addr r1, 0x30212000
    mov     r2, #0x400
    bl      dumpreg

    adr     r4, cmds
    mov     r5, #0                  @ command index
1:  ldrb    r0, [r4]
    cmp     r0, #0
    beq     2f
    mov     r0, r4
    bl      runcap
    mov     r0, r5
    bl      flush                   @ T<n>.TXT after EVERY command, so a
    add     r5, r5, #1              @ freeze names the command that caused it
3:  ldrb    r0, [r4], #1
    cmp     r0, #0
    bne     3b
    b       1b
2:
    /* Let the setting settle before touching anything else. tone2 froze on a
     * `menu dump` issued immediately after the setter returned OK -- most
     * likely straight into a reconfiguration still in progress. */
    ldr_addr r0, 5000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    /* ISP registers AFTER -- taken BEFORE anything risky, so a freeze in the
     * closing dump cannot cost us the measurement. */
    adr     r0, n_a
    ldr_addr r1, 0x30212000
    mov     r2, #0x400
    bl      dumpreg

    adr     r0, s_look
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd
    ldr_addr r0, 15000
    ldr_addr ip, TK_DLY_TSK
    blx     ip

    /* the closing settings dump goes LAST, as T9.TXT. If it freezes again,
     * everything that matters is already on the card. */
    adr     r0, c_dump
    bl      runcap
    mov     r0, #9
    bl      flush
    bl      writeout
    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd
    mov     r0, #0
    pop     {r4, r5, pc}

    .align  2
/* NUL-separated, double-NUL terminated. Read-only commands only. */
/* ONE setter per card. Five at once froze the camera and left nothing to
 * say which -- exactly the mixed-variable failure fp_sup's firmware-map warns
 * about. Change the setter here, rebuild, run again. */
cmds:
    .asciz  "menu dump"
    .asciz  "SETTER_LINE"
    .byte   0
    .align  2
c_dump:
    .asciz  "menu dump"
    .align  2
n_t:
    .byte   0x5C
    .asciz  "T0.TXT"
    .align  2
n_out:
    .byte   0x5C
    .asciz  "TONE.TXT"
    .align  2
n_b:
    .byte   0x5C
    .asciz  "TB.BIN"
    .align  2
n_a:
    .byte   0x5C
    .asciz  "TA.BIN"
    .align  2
s_look:
    .asciz  "display text LOOK AT SCREEN"
    .align  2
s_done:
    .asciz  "display text TONE TEST DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2


/* the capture sink: printf-style varargs, appends into CAPBUF */
sink:
    push    {r1, r2, r3}            @ spill a1..a3 so we can take their address
    push    {r4, r5, lr}
    mov     r2, r0                  @ fmt
    ldr_addr r4, CAPPTR
    ldr     r5, [r4]
    ldr_addr r1, CAPSZ
    subs    r1, r1, r5              @ remaining
    ble     4f
    ldr_addr r0, CAPBUF
    add     r0, r0, r5
    add     r3, sp, #12             @ &a1
    ldr_addr ip, VSNPRINT
    blx     ip
    cmp     r0, #0
    ble     5f
    ldr     r5, [r4]
    add     r5, r5, r0
    str     r5, [r4]
    b       5f
4:  mov     r0, #0
5:  pop     {r4, r5, lr}
    add     sp, sp, #12
    bx      lr

/* runcap -- r0 = a NUL-terminated command */
runcap:
    push    {r4, lr}
    ldr_addr r2, SHBUF
    mov     r3, r0
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
    ldr_addr r0, SHELL_CTX
    adr     r1, sink
    ldr_addr ip, FN_SHPUSH
    blx     ip
    ldr_addr r0, SHELL_CTX
    ldr_addr r1, SHBUF
    ldr_addr ip, FN_SHRUN
    blx     ip
    ldr_addr r0, SHELL_CTX
    ldr_addr ip, FN_SHPOP
    blx     ip
    pop     {r4, pc}

/* shcmd -- run a command with no capture (for the on-screen banner) */
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

/* flush -- r0 = index. Writes the capture so far to \T<n>.TXT.
 * The camera froze mid-run once with five setters in one card and nothing
 * but the pre-dump on the media, so there was no way to tell which command
 * did it. A numbered file after every command makes the next freeze
 * attributable: the highest file is the last command that completed. */
flush:
    push    {r4, r5, r6, lr}
    add     r6, r0, #0x30           @ digit
    ldr_addr r2, PATHBUF
    adr     r3, n_t
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
    ldr_addr r2, PATHBUF
    strb    r6, [r2, #2]
    ldr_addr r0, CAPPTR
    ldr     r6, [r0]
    cmp     r6, #0
    beq     9f
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
    beq     8f
    mov     r0, r4
    ldr_addr r1, CAPBUF
    mov     r2, r6
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r0, r4
    ldr_addr ip, F_CLOSE
    blx     ip
8:  mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
9:  pop     {r4, r5, r6, pc}

/* dumpreg -- r0 = path, r1 = src, r2 = bytes */
dumpreg:
    push    {r4, r5, r6, lr}
    mov     r5, r1
    mov     r6, r2
    ldr_addr r2, PATHBUF
    mov     r3, r0
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
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
    beq     2f
    mov     r0, r4
    mov     r1, r5
    mov     r2, r6
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r0, r4
    ldr_addr ip, F_CLOSE
    blx     ip
2:  mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, r6, pc}

/* writeout -- CAPBUF[0..CAPPTR] to \SHELL.TXT */
writeout:
    push    {r4, r5, r6, lr}
    ldr_addr r0, CAPPTR
    ldr     r6, [r0]
    cmp     r6, #0
    beq     9f
    ldr_addr r2, PATHBUF
    adr     r3, n_out
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
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
    beq     8f
    mov     r0, r4
    ldr_addr r1, CAPBUF
    mov     r2, r6
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r0, r4
    ldr_addr ip, F_CLOSE
    blx     ip
8:  mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
9:  pop     {r4, r5, r6, pc}

