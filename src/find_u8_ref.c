#include <stddef.h>
#include <stdint.h>

size_t find_u8(const uint8_t *a, size_t n, uint8_t needle) {
    for (size_t i = 0; i < n; ++i) {
        if (a[i] == needle) return i;
    }
    return n;
}
