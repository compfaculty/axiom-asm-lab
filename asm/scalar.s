.text
.globl _sum_array
.p2align 2
_sum_array:
    mov x2, #0
    cbz x1, 2f
1:
    ldr x3, [x0], #8
    add x2, x2, x3
    subs x1, x1, #1
    b.ne 1b
2:
    mov x0, x2
    ret
