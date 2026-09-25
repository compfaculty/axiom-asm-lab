.text
.globl _map_filter_u64
.p2align 2
/* Intentional fault: write matching even>>1 values in reverse order. */
_map_filter_u64:
    mov x3, #0
    mov x4, #0
    cbz x1, 3f
1:
    ldr x5, [x0, x3, lsl #3]
    tbnz x5, #0, 2f
    lsr x5, x5, #1
    str x5, [x2, x4, lsl #3]
    add x4, x4, #1
2:
    add x3, x3, #1
    cmp x3, x1
    b.lo 1b
3:
    /* Reverse the compacted prefix in-place. */
    cbz x4, 6f
    mov x3, #0
    sub x5, x4, #1
4:
    cmp x3, x5
    b.hs 6f
    ldr x6, [x2, x3, lsl #3]
    ldr x7, [x2, x5, lsl #3]
    str x7, [x2, x3, lsl #3]
    str x6, [x2, x5, lsl #3]
    add x3, x3, #1
    sub x5, x5, #1
    b 4b
6:
    mov x0, x4
    ret
