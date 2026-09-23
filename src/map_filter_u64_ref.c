#include <stddef.h>
#include <stdint.h>

size_t map_filter_u64(const uint64_t *in, size_t n, uint64_t *out) {
    size_t w = 0;
    for (size_t i = 0; i < n; ++i) {
        uint64_t x = in[i];
        if ((x & 1ull) == 0) out[w++] = x >> 1;
    }
    return w;
}
