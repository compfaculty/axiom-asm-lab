.text
.globl _sum_array
.p2align 2
_sum_array:
    // NEON sum using caller-saved v0-v3 only (avoid v8-v15 callee-saved).
    // Processes 4x u64 per iteration; scalar tail for remainders including odd n.
    movi v0.2d, #0
    movi v1.2d, #0
    cbz x1, 4f
    cmp x1, #4
    b.lo 2f
1:
    ld1 {v2.2d, v3.2d}, [x0], #32
    add v0.2d, v0.2d, v2.2d
    add v1.2d, v1.2d, v3.2d
    sub x1, x1, #4
    cmp x1, #4
    b.hs 1b
2:
    // Horizontal combine of vector accumulators into x2.
    add v0.2d, v0.2d, v1.2d
    addp d0, v0.2d
    fmov x2, d0
    cbz x1, 5f
3:
    ldr x3, [x0], #8
    add x2, x2, x3
    subs x1, x1, #1
    b.ne 3b
    mov x0, x2
    ret
4:
    mov x0, #0
    ret
5:
    mov x0, x2
    ret
