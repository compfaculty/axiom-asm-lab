.text
.globl _sum_array
.p2align 2
/* Non-terminating loop (controller must time out). */
_sum_array:
1:
    b 1b
