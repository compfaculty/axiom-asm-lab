#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

extern size_t find_u8(const uint8_t *, size_t, uint8_t);
extern size_t call_find_abi_checked(const uint8_t *, size_t, uint8_t, int *);

static uint64_t rng = UINT64_C(0x9e3779b97f4a7c15);
static uint64_t next_u64(void) {
    uint64_t x = rng;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    rng = x;
    return x * UINT64_C(2685821657736338717);
}
static uint8_t next_u8(void) { return (uint8_t)(next_u64() & 0xffu); }

static size_t expected(const uint8_t *a, size_t n, uint8_t needle) {
    for (size_t i = 0; i < n; ++i) if (a[i] == needle) return i;
    return n;
}

static int check(const uint8_t *a, size_t n, uint8_t needle, const char *label) {
    size_t got = find_u8(a, n, needle), want = expected(a, n, needle);
    if (got != want) {
        fprintf(stderr, "FAIL %s n=%zu needle=%u got=%zu expected=%zu\n",
                label, n, (unsigned)needle, got, want);
        return 1;
    }
    return 0;
}

typedef struct {
    void *map;
    size_t map_bytes;
    uint8_t *data;
    size_t n;
} GuardedBuf;

static void guarded_free(GuardedBuf *g) {
    if (g && g->map && g->map != MAP_FAILED) munmap(g->map, g->map_bytes);
    if (g) memset(g, 0, sizeof(*g));
}

static int guarded_alloc(GuardedBuf *g, size_t n, int place_mode, int read_only) {
    long psz = sysconf(_SC_PAGESIZE);
    if (psz <= 0) return -1;
    size_t page = (size_t)psz;
    size_t need = n ? n : 1;
    size_t slack = 256;
    size_t inner = need + (place_mode == 2 ? 2 * slack : 0);
    size_t payload = ((inner + page - 1) / page) * page;
    if (payload < page) payload = page;
    size_t total = page + payload + page;
    void *map = mmap(NULL, total, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (map == MAP_FAILED) return -1;
    void *mid = (char *)map + page;
    if (mprotect(mid, payload, PROT_READ | PROT_WRITE) != 0) {
        munmap(map, total);
        return -1;
    }
    uint8_t *data;
    if (n == 0) data = NULL;
    else if (place_mode == 1) data = (uint8_t *)((char *)mid + payload - n);
    else if (place_mode == 2) data = (uint8_t *)((char *)mid + slack);
    else data = (uint8_t *)mid;
    for (size_t i = 0; i < n; ++i) data[i] = next_u8();
    if (read_only && mprotect(mid, payload, PROT_READ) != 0) {
        munmap(map, total);
        return -1;
    }
    g->map = map; g->map_bytes = total; g->data = data; g->n = n;
    return 0;
}

static int probe_modes(int place_mode) {
    const size_t lens[] = {0, 1, 3, 4, 7, 8, 16, 64};
    for (size_t li = 0; li < sizeof(lens) / sizeof(lens[0]); ++li) {
        size_t n = lens[li];
        if (place_mode == 1 && n == 0) continue;
        GuardedBuf g; memset(&g, 0, sizeof(g));
        if (guarded_alloc(&g, n, place_mode, 1) != 0) {
            fprintf(stderr, "FAIL probe mmap n=%zu\n", n);
            return 1;
        }
        uint8_t needle = n ? g.data[n / 2] : 0;
        int abi_ok = 0;
        size_t got = call_find_abi_checked(g.data, n, needle, &abi_ok);
        if (!abi_ok) {
            fprintf(stderr, "ABI_FAIL n=%zu place_mode=%d\n", n, place_mode);
            guarded_free(&g);
            return 3;
        }
        size_t want = expected(g.data, n, needle);
        if (got != want) {
            fprintf(stderr, "FAIL probe n=%zu got=%zu expected=%zu\n", n, got, want);
            guarded_free(&g);
            return 1;
        }
        guarded_free(&g);
    }
    return 0;
}

static int probe(void) { return probe_modes(2); }
static int probe_tight(void) { return probe_modes(1); }
static int probe_head(void) { return probe_modes(0); }

static int verify(void) {
    uint8_t a[4096];
    if (check(NULL, 0, 0, "empty")) return 1;
    for (size_t n = 0; n <= 4096; ++n) {
        for (size_t i = 0; i < n; ++i) a[i] = next_u8();
        uint8_t needle = n ? a[n / 2] : 0;
        if (check(a, n, needle, "random")) return 1;
        if (n && check(a, n, (uint8_t)(needle ^ 0xffu), "miss")) return 1;
    }
    int rc = probe_head();
    if (rc) return rc;
    rc = probe_tight();
    if (rc) return rc;
    rc = probe();
    if (rc) return rc;
    puts("PASS");
    return 0;
}

static uint64_t ns_now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &t)) { perror("clock_gettime"); exit(2); }
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}

#define BENCH_NEEDLE ((uint8_t)0x5A)

static int alloc_bench_buf(size_t n, uint8_t **out) {
    uint8_t *a = malloc(n ? n : 1);
    if (!a) return 2;
    for (size_t i = 0; i < n; ++i) a[i] = next_u8();
    if (n) a[n / 2] = BENCH_NEEDLE;
    if (check(a, n, BENCH_NEEDLE, "bench")) { free(a); return 1; }
    *out = a;
    return 0;
}

static uint64_t time_iters(uint8_t *a, size_t n, uint64_t iterations, volatile uint64_t *sink) {
    uint64_t start = ns_now();
    for (uint64_t j = 0; j < iterations; ++j) *sink ^= (uint64_t)find_u8(a, n, BENCH_NEEDLE);
    return ns_now() - start;
}

static int calibrate(size_t n, uint64_t target_ns, uint64_t max_iters) {
    if (n > 16777216 || target_ns < 1000 || max_iters < 1) return 2;
    uint8_t *a = NULL;
    int rc = alloc_bench_buf(n, &a);
    if (rc) return rc;
    volatile uint64_t sink = 0;
    (void)time_iters(a, n, 1, &sink);
    uint64_t iters = 1, elapsed = 0;
    int capped = 0;
    for (;;) {
        elapsed = time_iters(a, n, iters, &sink);
        if (elapsed >= target_ns || iters >= max_iters) {
            if (elapsed < target_ns && iters >= max_iters) capped = 1;
            break;
        }
        uint64_t next = iters > (max_iters / 2) ? max_iters : iters * 2;
        if (next == iters) { capped = 1; break; }
        iters = next;
    }
    printf("%" PRIu64 " %" PRIu64 " %d\n", iters, elapsed, capped);
    free(a);
    return 0;
}

static int bench_raw(size_t n, size_t samples, uint64_t iterations) {
    if (n > 16777216 || samples < 1 || samples > 10000 || iterations < 1) return 2;
    uint8_t *a = NULL;
    int rc = alloc_bench_buf(n, &a);
    if (rc) return rc;
    volatile uint64_t sink = 0;
    (void)time_iters(a, n, iterations < 8 ? iterations : 8, &sink);
    for (size_t s = 0; s < samples; ++s) {
        uint64_t elapsed = time_iters(a, n, iterations, &sink);
        printf("%" PRIu64 " %" PRIu64 " %.6f\n", elapsed, iterations,
               (double)elapsed / (double)iterations);
    }
    free(a);
    return 0;
}

static int find_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror("fopen"); return 2; }
    unsigned long long n_ull = 0, needle_ull = 0;
    if (fscanf(f, "%llu %llu", &n_ull, &needle_ull) != 2) { fclose(f); return 2; }
    if (n_ull > 16777216ull || needle_ull > 255ull) { fclose(f); return 2; }
    size_t n = (size_t)n_ull;
    uint8_t needle = (uint8_t)needle_ull;
    if (n == 0) {
        fclose(f);
        printf("%zu\n", find_u8(NULL, 0, needle));
        return 0;
    }
    uint8_t *a = malloc(n);
    if (!a) { fclose(f); return 2; }
    for (size_t i = 0; i < n; ++i) {
        unsigned v = 0;
        if (fscanf(f, "%u", &v) != 1 || v > 255u) { free(a); fclose(f); return 2; }
        a[i] = (uint8_t)v;
    }
    fclose(f);
    printf("%zu\n", find_u8(a, n, needle));
    free(a);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "verify")) return verify();
    if (argc == 2 && !strcmp(argv[1], "probe")) { int rc = probe(); if (!rc) puts("PASS"); return rc; }
    if (argc == 2 && !strcmp(argv[1], "probe-tight")) { int rc = probe_tight(); if (!rc) puts("PASS"); return rc; }
    if (argc == 2 && !strcmp(argv[1], "probe-head")) { int rc = probe_head(); if (!rc) puts("PASS"); return rc; }
    if (argc == 3 && !strcmp(argv[1], "find-file")) return find_file(argv[2]);
    if (argc == 5 && !strcmp(argv[1], "calibrate")) {
        char *e1, *e2, *e3;
        unsigned long long n = strtoull(argv[2], &e1, 10);
        unsigned long long target = strtoull(argv[3], &e2, 10);
        unsigned long long max_iters = strtoull(argv[4], &e3, 10);
        if (*e1 || *e2 || *e3) return 2;
        return calibrate((size_t)n, target, max_iters);
    }
    if (argc == 5 && !strcmp(argv[1], "bench-raw")) {
        char *e1, *e2, *e3;
        unsigned long long n = strtoull(argv[2], &e1, 10);
        unsigned long long samples = strtoull(argv[3], &e2, 10);
        unsigned long long iters = strtoull(argv[4], &e3, 10);
        if (*e1 || *e2 || *e3) return 2;
        return bench_raw((size_t)n, (size_t)samples, iters);
    }
    fprintf(stderr,
            "usage: harness_find verify | probe* | find-file PATH\n"
            "       | calibrate N TARGET_NS MAX_ITERS | bench-raw N SAMPLES ITERATIONS\n");
    return 2;
}
