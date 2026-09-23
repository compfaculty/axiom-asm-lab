#include <stddef.h>
#include <stdint.h>
__attribute__((noinline)) uint64_t sum_array(const uint64_t *a, size_t n) {
    uint64_t s = 0;
    for (size_t i = 0; i < n; ++i) s += a[i];
    return s;
}
