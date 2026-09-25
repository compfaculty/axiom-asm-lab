.text
.globl _map_filter_u64
.p2align 2
// size_t map_filter_u64(const uint64_t *in, size_t n, uint64_t *out)
// ABI: x0=in, x1=n, x2=out; returns written count. Keep even, store x>>1.
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
    mov x0, x4
    ret
