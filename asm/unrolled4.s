.text
.globl _sum_array
.p2align 2
_sum_array:
    mov x2, #0
    mov x3, #0
    mov x4, #0
    mov x5, #0
    cmp x1, #4
    b.lo 2f
1:
    ldp x6, x7, [x0]
    ldp x8, x9, [x0, #16]
    add x2, x2, x6
    add x3, x3, x7
    add x4, x4, x8
    add x5, x5, x9
    add x0, x0, #32
    sub x1, x1, #4
    cmp x1, #4
    b.hs 1b
2:
    cbz x1, 4f
3:
    ldr x6, [x0], #8
    add x2, x2, x6
    subs x1, x1, #1
    b.ne 3b
4:
    add x2, x2, x3
    add x4, x4, x5
    add x0, x2, x4
    ret
