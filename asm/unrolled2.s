.text
.globl _sum_array
.p2align 2
_sum_array:
    // Two-accumulator scalar unroll; caller-saved x temps only.
    mov x2, #0
    mov x3, #0
    cmp x1, #2
    b.lo 2f
1:
    ldp x4, x5, [x0], #16
    add x2, x2, x4
    add x3, x3, x5
    sub x1, x1, #2
    cmp x1, #2
    b.hs 1b
2:
    cbz x1, 4f
3:
    ldr x4, [x0], #8
    add x2, x2, x4
    subs x1, x1, #1
    b.ne 3b
4:
    add x0, x2, x3
    ret
