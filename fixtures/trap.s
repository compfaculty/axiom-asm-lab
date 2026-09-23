.text
.globl _sum_array
.p2align 2
/* Illegal / trap instruction. */
_sum_array:
    brk #0x1
    ret
