.text
.globl _sum_array
.p2align 2
_sum_array:
    // Eight-wide scalar unroll with scalar tail; caller-saved temps only.
    mov x2, #0
    mov x3, #0
    mov x4, #0
    mov x5, #0
    mov x6, #0
    mov x7, #0
    mov x8, #0
    mov x9, #0
    cmp x1, #8
    b.lo 2f
1:
    ldp x10, x11, [x0]
    ldp x12, x13, [x0, #16]
    ldp x14, x15, [x0, #32]
    ldp x16, x17, [x0, #48]
    add x2, x2, x10
    add x3, x3, x11
    add x4, x4, x12
    add x5, x5, x13
    add x6, x6, x14
    add x7, x7, x15
    add x8, x8, x16
    add x9, x9, x17
    add x0, x0, #64
    sub x1, x1, #8
    cmp x1, #8
    b.hs 1b
2:
    cbz x1, 4f
3:
    ldr x10, [x0], #8
    add x2, x2, x10
    subs x1, x1, #1
    b.ne 3b
4:
    add x2, x2, x3
    add x4, x4, x5
    add x6, x6, x7
    add x8, x8, x9
    add x2, x2, x4
    add x6, x6, x8
    add x0, x2, x6
    ret
