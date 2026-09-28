/* enc_rec_probe -- read the codec register banks DURING A RECORDING.
 *
 * WHY.  PLAN.md section 8 question 2: does the encoder take profile_idc 110
 * (High 10)?  The boot probe (results/run1_21_09_2026) found the datapath
 * blocks gated, and the ARM image does not hold the codec configuration
 * (docs/CHROMA_CEILING.md section 5).  So the block has to be read while the
 * FIRMWARE has powered it -- in a take -- and it has to be found first: the
 * live ISP probe read 0x300C/0x300D/0x300E dead around a record press
 * (results/isprobe_1), and nothing says the encoder is in any block named so
 * far.  The result is the diff: a block that is dead before the take, live
 * during it and dead again afterwards is the codec's datapath.
 *
 * THREE ROUNDS.
 *   A  idle, live view      read and written region by region
 *   B  in the take          read into RAM ONLY -- no file I/O while the
 *                           camera is writing the MOV to the same card
 *   C  idle, after the stop read and written region by region
 * Files are \E<round><nn>.BIN, one per region; tools/check_encrec.py reads
 * the region table out of THIS file, so the two cannot disagree.
 *
 * ONE ON-SCREEN PROMPT DURING THE TAKE, AND IT COMES LAST.  STOP RECORDING
 * NOW is the first time any card here calls the shell executor while the
 * camera records.  It is issued only once round B is already in RAM, so if it
 * hangs, what is lost is the writing of round B, not the reading -- and the
 * card still says how far it got: EA complete, EB missing.
 *
 *   T0+20s   round A, then RECORD NOW
 *   +15s     round B -> RAM              (inside the take)
 *            STOP RECORDING NOW
 *   +20s     round B -> card             (take stopped ~15 s ago)
 *            round C, then ENC PROBE DONE
 *
 * ORDER WITHIN A ROUND IS BY RISK.  DRAM first, then every bank at the size
 * a previous card already read it without incident, then what encrec_1 read
 * live, then sweep group 2 ONE BLOCK PER FILE -- encrec_1 froze inside it in
 * live view -- then 1 KiB into its gated blocks, then 0x303xxxxx.
 * In rounds A and C each file is written as soon as its region is read, so
 * the first missing file names the region that stopped it.  Reaching round B
 * at all means round A read every region, idle.
 *
 * SAFETY.  Every access to a register bank is a 32-bit load.  The only stores
 * are into the cave buffers below and the files, through the firmware's own
 * file API -- the six calls of gyro/gcsvgen.S, including destroying the object
 * when the open fails.  No mem set, no prom, no fwup, no NAND, no clock or
 * power register touched: a gated block is read gated, never ungated
 * (results/run1 section 5, "Not recommended").  Battery out reverts.
 * Ver.5.02 only.
 */
    .syntax unified
    .arm

.macro ldr_addr reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

/* ---- firmware entry points, as isp_live_probe.S names them ---------------- */
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

/* ---- cave, all above build_autorun.py's loader (0xC072E800..0xC072EF30) ---
 * SNAP is the 32 KiB shellcap.S and tonedrive.S capture into; it is empty at
 * this point in the boot on a --no-shell card.  build_encrec_card.py sums the
 * region table and refuses a build that does not fit SNAP_SZ. */
.equ FOBJ,       0xC072F000     /* 0x800 -- same reserve tableload.S uses     */
.equ PATHBUF,    0xC072F800     /* 0x40                                       */
.equ SHBUF,      0xC072F900     /* 0x40 -- writable copy of a shell command   */
.equ SNAP,       0xC0731000     /* one round, every region back to back       */
.equ SNAP_SZ,    0x8000
.equ BUFS_LO,    0xC072F000
.equ BUFS_HI,    0xC0739000

.equ DELAY_A_MS, 20000          /* boot -> round A: live view is up          */
.equ DELAY_B_MS, 15000          /* prompt -> round B: the take is rolling    */
.equ DELAY_W_MS, 20000          /* stop prompt -> round B's files            */

.equ SWEEP_HEAD, 16             /* words from the head of each 64 KiB block  */

    .global enc_rec_probe
enc_rec_probe:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}

    ldr_addr r0, DELAY_A_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r0, #'A'
    mov     r1, #1                      @ write each region as it is read
    bl      do_round

    adr     r0, s_record
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY_B_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r0, #'B'
    mov     r1, #0                      @ RAM only -- the camera owns the card
    bl      do_round

    @ round B is safe in RAM before the only shell call made inside the take
    adr     r0, s_stop
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    ldr_addr r0, DELAY_W_MS
    ldr_addr ip, TK_DLY_TSK
    blx     ip
    mov     r0, #'B'
    bl      write_round

    mov     r0, #'C'
    mov     r1, #1
    bl      do_round

    adr     r0, s_done
    bl      shcmd
    adr     r0, s_osd
    bl      shcmd

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

/* The prompts sit next to the code that adr's them: at the end of the file
 * they are out of adr's reach. */
    .align  2
s_record:
    .asciz  "display text RECORD NOW"
    .align  2
s_stop:
    .asciz  "display text STOP RECORDING NOW"
    .align  2
s_done:
    .asciz  "display text ENC PROBE DONE"
    .align  2
s_osd:
    .asciz  "display osd 1"
    .align  2


/* do_round -- r0 = round char, r1 = 1 to write each region as it is read.
 * Every region lands in SNAP at its running offset, so write_round can put
 * the same bytes on the card later. */
do_round:
    push    {r4, r5, r6, r7, r8, r9, r10, lr}
    mov     r8, r0
    mov     r9, r1
    adr     r4, regions
    mov     r5, #0                      @ region index
    ldr_addr r10, SNAP                  @ where this region goes
dr_next:
    ldr     r6, [r4], #4                @ base
    cmp     r6, #0
    beq     dr_done
    ldr     r7, [r4], #4                @ bytes
    ldr     r3, [r4], #4                @ kind: 0 contiguous, 1 sweep heads
    cmp     r3, #0
    bne     dr_sweep
    mov     r0, r10
    mov     r1, r6
    lsr     r2, r7, #2
    bl      copy_words
    b       dr_read
dr_sweep:                               @ bytes / 64 blocks, 0x10000 apart
    push    {r6, r7, r10}
1:  mov     r0, r10
    mov     r1, r6
    mov     r2, #SWEEP_HEAD
    bl      copy_words
    add     r10, r10, #(SWEEP_HEAD * 4)
    add     r6, r6, #0x10000
    subs    r7, r7, #(SWEEP_HEAD * 4)
    bne     1b
    pop     {r6, r7, r10}
dr_read:
    cmp     r9, #0
    beq     dr_skip
    mov     r0, r8
    mov     r1, r5
    bl      make_path
    mov     r0, r10
    mov     r1, r7
    bl      write_buf
dr_skip:
    add     r10, r10, r7
    add     r5, r5, #1
    b       dr_next
dr_done:
    pop     {r4, r5, r6, r7, r8, r9, r10, pc}

/* write_round -- r0 = round char.  SNAP -> one file per region. */
write_round:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0
    adr     r4, regions
    mov     r5, #0
    ldr_addr r6, SNAP
1:  ldr     r0, [r4], #4
    cmp     r0, #0
    beq     2f
    ldr     r7, [r4], #8                @ bytes; step over kind too
    mov     r0, r8
    mov     r1, r5
    bl      make_path
    mov     r0, r6
    mov     r1, r7
    bl      write_buf
    add     r6, r6, r7
    add     r5, r5, #1
    b       1b
2:  pop     {r4, r5, r6, r7, r8, pc}

/* write_buf -- r0 = buffer, r1 = bytes.  Path already in PATHBUF.
 * When F_OPEN fails the object F_CTOR built must still be destroyed: leaving
 * one built wedged the file system until a power cycle (gyro/gcsvgen.S). */
write_buf:
    push    {r4, r5, r6, lr}
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
    beq     wb_dtor                     @ did not open -- still destroy it

    mov     r0, r6
    mov     r1, r4
    mov     r2, r5
    ldr_addr ip, F_WRITE
    blx     ip

    mov     r0, r6
    ldr_addr ip, F_CLOSE
    blx     ip
wb_dtor:
    mov     r0, r6
    mov     r1, #2
    ldr_addr ip, F_DTOR
    blx     ip
    pop     {r4, r5, r6, pc}

/* shcmd -- r0 = a NUL-terminated command template.  Copied into SHBUF first:
 * the executor's strtok writes NULs into the line. */
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

/* copy_words -- r0 = dst, r1 = src, r2 = words.  Word loads one at a time:
 * a peripheral bank is entitled to refuse byte and multi-word accesses.
 * r0-r3 only. */
copy_words:
    cmp     r2, #0
    bxeq    lr
1:  ldr     r3, [r1], #4
    str     r3, [r0], #4
    subs    r2, r2, #1
    bne     1b
    bx      lr

/* make_path -- r0 = round char, r1 = region index.  Builds "\E<r><nn>.BIN". */
make_path:
    push    {r4, lr}
    ldr_addr r2, PATHBUF
    adr     r3, name_tmpl
1:  ldrb    r4, [r3], #1
    strb    r4, [r2], #1
    cmp     r4, #0
    bne     1b
    ldr_addr r2, PATHBUF
    strb    r0, [r2, #2]                @ round letter
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
/* base, bytes, kind.  kind 1 = sweep: bytes/64 blocks 0x10000 apart, 16 words
 * from the head of each.  In order of risk -- see the header. */
regions:
    /* DRAM: the sigpro request parameter block (docs/ISP_PIPELINE.md 7.1) */
    .word   0xC3413000, 0x1000, 0
    /* read at these sizes before, without incident -- live view included */
    .word   0x30210000, 0x1000, 0   @ shadow config -- the take CONTROL: its
                                    @ geometry words moved on record (isprobe_1)
    .word   0x301B0000, 0x400,  0   @ DSP (raw-sup)
    .word   0x300C0000, 0x400,  0   @ RFC readout
    .word   0x300D0000, 0x400,  0   @ lossless JPEG -- read only, never driven
    .word   0x300E0000, 0x400,  0   @ gated with its neighbours
    .word   0x30110000, 0x400,  0   @ SIG registers -- dead control
    /* sweep groups 0 and 1: survived at boot AND in live view (encrec_1) */
    .word   0x30000000, 0x400,  1
    .word   0x30100000, 0x400,  1
    /* gated at boot, read 64 bytes deep live without trouble (encrec_1) */
    .word   0x30060000, 0x400,  0
    .word   0x30070000, 0x400,  0
    .word   0x30120000, 0x400,  0
    .word   0x30130000, 0x400,  0
    .word   0x30140000, 0x400,  0
    .word   0x301C0000, 0x400,  0
    .word   0x301D0000, 0x400,  0
    .word   0x301E0000, 0x400,  0
    /* sweep group 2, ONE BLOCK PER FILE.  results/encrec_1 froze inside this
     * group in live view, though it read clean at boot.  0x30210000 is not
     * here: it is region 1.  If this freezes again, the last file written is
     * the block BEFORE the one that hung. */
    .word   0x30200000, 0x40,   0
    .word   0x30220000, 0x40,   0
    .word   0x30230000, 0x40,   0
    .word   0x30240000, 0x40,   0
    .word   0x30250000, 0x40,   0
    .word   0x30260000, 0x40,   0
    .word   0x30270000, 0x40,   0
    .word   0x30280000, 0x40,   0
    .word   0x30290000, 0x40,   0
    .word   0x302A0000, 0x40,   0
    .word   0x302B0000, 0x40,   0
    .word   0x302C0000, 0x40,   0
    .word   0x302D0000, 0x40,   0
    .word   0x302E0000, 0x40,   0
    .word   0x302F0000, 0x40,   0
    /* group 2 blocks gated at boot, 1 KiB deep */
    .word   0x30270000, 0x400,  0
    .word   0x30280000, 0x400,  0
    .word   0x30290000, 0x400,  0
    .word   0x302B0000, 0x400,  0
    .word   0x302E0000, 0x400,  0
    .word   0x302F0000, 0x400,  0
    /* never read by anything -- last */
    .word   0x30300000, 0x400,  1
    .word   0

name_tmpl:
    .byte   0x5C                    @ backslash, spelled out
    .asciz  "EA00.BIN"
    .align  2
