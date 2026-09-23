.text
.globl _sum_array
.p2align 2
/* Read one element past the declared length (n). */
_sum_array:
    mov x2, #0
    mov x4, x0
    mov x5, x1
    cbz x1, 2f
1:
    ldr x3, [x0], #8
    add x2, x2, x3
    subs x1, x1, #1
    b.ne 1b
2:
    /* overread: load one past end (or at base when n==0) */
    ldr x3, [x4, x5, lsl #3]
    add x2, x2, x3
    mov x0, x2
    ret
