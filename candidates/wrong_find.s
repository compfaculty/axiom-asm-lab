.text
.globl _find_u8
.p2align 2
/* Intentional fault: last-match index, or n+1 on miss (not first-match). */
_find_u8:
    mov x3, #0
    mov x5, x1              /* last = n (miss sentinel before +1) */
    cbz x1, 4f
1:
    ldrb w4, [x0, x3]
    cmp w4, w2
    b.ne 2f
    mov x5, x3              /* remember last hit */
2:
    add x3, x3, #1
    cmp x3, x1
    b.lo 1b
    cmp x5, x1
    b.eq 4f
    mov x0, x5
    ret
4:
    add x0, x1, #1
    ret
