#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

extern uint64_t sum_array(const uint64_t *, size_t);
static uint64_t rng = UINT64_C(0x9e3779b97f4a7c15);
static uint64_t next_u64(void) {
    uint64_t x = rng;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    rng = x;
    return x * UINT64_C(2685821657736338717);
}
static uint64_t expected(const uint64_t *a, size_t n) {
    uint64_t s = 0;
    for (size_t i = 0; i < n; ++i) s += a[i];
    return s;
}
static int check(const uint64_t *a, size_t n, const char *label) {
    uint64_t got = sum_array(a, n), want = expected(a, n);
    if (got != want) {
        fprintf(stderr, "FAIL %s n=%zu got=%" PRIu64 " expected=%" PRIu64 "\n", label, n, got, want);
        return 1;
    }
    return 0;
}
static int verify(void) {
    uint64_t a[4096];
    if (check(NULL, 0, "empty")) return 1;
    for (size_t n = 0; n <= 4096; ++n) {
        for (size_t i = 0; i < n; ++i) a[i] = next_u64();
        if (check(a, n, "random") || check(a + (n ? 1 : 0), n ? n - 1 : 0, "offset")) return 1;
    }
    const uint64_t edges[] = {UINT64_MAX, 1, UINT64_MAX, UINT64_MAX, 4, 0, 1};
    for (size_t n = 0; n <= 7; ++n) if (check(edges, n, "overflow")) return 1;
    puts("PASS");
    return 0;
}
static uint64_t ns_now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &t)) { perror("clock_gettime"); exit(2); }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}
static int bench(size_t n, size_t samples) {
    if (n > 16777216 || samples < 1 || samples > 10000) return 2;
    uint64_t *a = malloc((n ? n : 1) * sizeof(*a));
    if (!a) return 2;
    for (size_t i = 0; i < n; ++i) a[i] = next_u64();
    if (check(a, n, "bench")) { free(a); return 1; }
    volatile uint64_t sink = 0;
    size_t iterations = n <= 64 ? 100000 : n <= 4096 ? 10000 : n <= 1048576 ? 100 : 8;
    for (size_t j = 0; j < iterations; ++j) sink ^= sum_array(a, n);
    for (size_t s = 0; s < samples; ++s) {
        uint64_t start = ns_now();
        for (size_t j = 0; j < iterations; ++j) sink ^= sum_array(a, n);
        uint64_t elapsed = ns_now() - start;
        printf("%.3f\n", (double)elapsed / (double)iterations);
    }
    if (sink == UINT64_C(0xdeadbeef)) fprintf(stderr, "sink=%" PRIu64 "\n", sink);
    free(a);
    return 0;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "verify")) return verify();
    if (argc == 4 && !strcmp(argv[1], "bench")) {
        char *end1, *end2;
        unsigned long long n = strtoull(argv[2], &end1, 10);
        unsigned long long samples = strtoull(argv[3], &end2, 10);
        if (*end1 || *end2) return 2;
        return bench((size_t)n, (size_t)samples);
    }
    fprintf(stderr, "usage: harness verify | bench N SAMPLES\n");
    return 2;
}
