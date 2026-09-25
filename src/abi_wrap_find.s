.text
.globl _call_find_abi_checked
.p2align 2
/* size_t call_find_abi_checked(const uint8_t *a, size_t n, uint8_t needle, int *abi_ok); */
_call_find_abi_checked:
    stp x29, x30, [sp, #-112]!
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    stp x23, x24, [sp, #48]
    stp x25, x26, [sp, #64]
    stp x27, x28, [sp, #80]
    str x3, [sp, #96]
    mov x29, sp

    movz x19, #0xA119
    movk x19, #0xB119, lsl #16
    movz x20, #0xA120
    movk x20, #0xB120, lsl #16
    movz x21, #0xA121
    movk x21, #0xB121, lsl #16
    movz x22, #0xA122
    movk x22, #0xB122, lsl #16
    movz x23, #0xA123
    movk x23, #0xB123, lsl #16
    movz x24, #0xA124
    movk x24, #0xB124, lsl #16
    movz x25, #0xA125
    movk x25, #0xB125, lsl #16
    movz x26, #0xA126
    movk x26, #0xB126, lsl #16
    movz x27, #0xA127
    movk x27, #0xB127, lsl #16
    movz x28, #0xA128
    movk x28, #0xB128, lsl #16

    /* x0=ptr, x1=n, x2=needle */
    bl _find_u8
    mov x12, x0

    mov w13, #1
    movz x16, #0xA119
    movk x16, #0xB119, lsl #16
    cmp x19, x16
    b.ne 1f
    movz x16, #0xA120
    movk x16, #0xB120, lsl #16
    cmp x20, x16
    b.ne 1f
    movz x16, #0xA121
    movk x16, #0xB121, lsl #16
    cmp x21, x16
    b.ne 1f
    movz x16, #0xA122
    movk x16, #0xB122, lsl #16
    cmp x22, x16
    b.ne 1f
    movz x16, #0xA123
    movk x16, #0xB123, lsl #16
    cmp x23, x16
    b.ne 1f
    movz x16, #0xA124
    movk x16, #0xB124, lsl #16
    cmp x24, x16
    b.ne 1f
    movz x16, #0xA125
    movk x16, #0xB125, lsl #16
    cmp x25, x16
    b.ne 1f
    movz x16, #0xA126
    movk x16, #0xB126, lsl #16
    cmp x26, x16
    b.ne 1f
    movz x16, #0xA127
    movk x16, #0xB127, lsl #16
    cmp x27, x16
    b.ne 1f
    movz x16, #0xA128
    movk x16, #0xB128, lsl #16
    cmp x28, x16
    b.ne 1f
    b 2f
1:
    mov w13, #0
2:
    ldr x11, [sp, #96]
    str w13, [x11]
    mov x0, x12

    ldp x19, x20, [sp, #16]
    ldp x21, x22, [sp, #32]
    ldp x23, x24, [sp, #48]
    ldp x25, x26, [sp, #64]
    ldp x27, x28, [sp, #80]
    ldp x29, x30, [sp], #112
    ret
