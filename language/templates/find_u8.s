.text
.globl _find_u8
.p2align 2
/* size_t find_u8(const uint8_t *a, size_t n, uint8_t needle)
   ABI: x0=ptr, x1=n, x2=needle; returns index or n. */
_find_u8:
    mov x3, #0
    cbz x1, 2f
1:
    ldrb w4, [x0, x3]
    cmp w4, w2
    b.eq 3f
    add x3, x3, #1
    cmp x3, x1
    b.lo 1b
2:
    mov x0, x1
    ret
3:
    mov x0, x3
    ret
