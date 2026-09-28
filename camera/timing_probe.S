/* timing_probe -- how long does a --boot-call routine survive?
 *
 * The live ISP probe wrote nothing at all. It differed from the encoder probe,
 * which DID run to completion on this camera, in exactly one important way: it
 * slept for 20 s before writing anything. So the question is whether the
 * borrowed echo handler's context survives a delay at all, and for how long.
 *
 * This writes a marker BEFORE any delay, then after progressively longer ones.
 * The highest-numbered file on the card is the answer:
 *
 *   no MK0        the payload never ran -- not a timing problem
 *   MK0 only      any delay at all kills it
 *   MK0..MK3      it survives ~8 s but not 15
 *   all six       delays are fine and the ISP probe failed for another reason
 *
 * Each marker also dumps 0x100 bytes around the tone-curve selector, so the
 * set of files doubles as a log of which curve was selected over time -- change
 * the colour mode while it runs and the markers record when it took effect.
 *
 * Read-only apart from the files. No mem set, no prom, no fwup, no NAND.
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
.equ TK_DLY_TSK, 0xC01F89C4     /* f(ms) -- gyro/ring_task.inc.S:50 */

.equ FOBJ,       0xC072F000     /* 0x800 */
.equ PATHBUF,    0xC072F800     /* 0x40  */
.equ STAGING,    0xC072F900     /* 0x100 */
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC072FA00

.equ SRC,        0xC3414D00     /* the selector neighbourhood */
.equ LEN,        0x100

    .global timing_probe
timing_probe:
    push    {r4, r5, r6, lr}
    adr     r4, delays
    mov     r5, #0
1:  ldr     r6, [r4], #4
    cmn     r6, #1                      @ -1 terminates
    beq     2f
    cmp     r6, #0
    beq     3f
    mov     r0, r6
    ldr_addr ip, TK_DLY_TSK
    blx     ip
3:  mov     r0, r5
    bl      mark
    add     r5, r5, #1
    b       1b
2:  mov     r0, #0
    pop     {r4, r5, r6, pc}

/* mark -- r0 = index. Build \MKn.BIN and write LEN bytes from SRC into it. */
mark:
    push    {r4, r5, lr}
    ldr_addr r2, PATHBUF
    adr     r3, tmpl
1:  ldrb    r1, [r3], #1
    strb    r1, [r2], #1
    cmp     r1, #0
    bne     1b
    ldr_addr r2, PATHBUF
    add     r0, r0, #0x30
    strb    r0, [r2, #3]

    ldr_addr r0, STAGING
    ldr_addr r1, SRC
    mov     r2, #(LEN / 4)
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
    mov     r2, #LEN
    ldr_addr ip, F_WRITE
    blx     ip
    mov     r0, r4
    ldr_addr ip, F_CLOSE
    blx     ip
3:  mov     r0, r4
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, pc}

    .align  2
/* milliseconds to wait BEFORE each marker; cumulative T is in the comment */
delays:
    .word   0            @ MK0  T+0    -- proves the payload ran at all
    .word   1000         @ MK1  T+1s
    .word   2000         @ MK2  T+3s
    .word   5000         @ MK3  T+8s
    .word   7000         @ MK4  T+15s
    .word   15000        @ MK5  T+30s
    .word   -1

tmpl:
    .byte   0x5C
    .asciz  "MK0.BIN"
    .align  2
