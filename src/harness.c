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

extern uint64_t sum_array(const uint64_t *, size_t);
extern uint64_t call_sum_abi_checked(const uint64_t *, size_t, int *);
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

/* Call sum_array with callee-saved sentinel registers; *abi_ok=0 on corruption. */
/* Implemented in src/abi_wrap.s as call_sum_abi_checked. */

typedef struct {
    void *map;
    size_t map_bytes;
    uint64_t *data;
    size_t n;
} GuardedBuf;

static void guarded_free(GuardedBuf *g) {
    if (g && g->map && g->map != MAP_FAILED)
        munmap(g->map, g->map_bytes);
    if (g) memset(g, 0, sizeof(*g));
}

/* Allocate [guard][payload][guard].
 * place mode: 0=start (underread surface), 1=end (overread surface), 2=center (slack both sides). */
static int guarded_alloc(GuardedBuf *g, size_t n, int place_mode, int read_only) {
    long psz = sysconf(_SC_PAGESIZE);
    if (psz <= 0) return -1;
    size_t page = (size_t)psz;
    size_t need = n ? n * sizeof(uint64_t) : sizeof(uint64_t);
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
    uint64_t *data;
    if (n == 0) {
        data = NULL;
    } else if (place_mode == 1) {
        data = (uint64_t *)((char *)mid + payload - n * sizeof(uint64_t));
    } else if (place_mode == 2) {
        data = (uint64_t *)((char *)mid + slack);
    } else {
        data = (uint64_t *)mid;
    }
    for (size_t i = 0; i < n; ++i) data[i] = next_u64();
    if (read_only && mprotect(mid, payload, PROT_READ) != 0) {
        munmap(map, total);
        return -1;
    }
    g->map = map;
    g->map_bytes = total;
    g->data = data;
    g->n = n;
    return 0;
}

static int probe_modes(int place_mode) {
    /* place_mode: 0 start, 1 end, 2 center (for auto-vectorized correct kernels). */
    const size_t lens[] = {0, 1, 3, 4, 7, 8, 16, 64};
    for (size_t li = 0; li < sizeof(lens) / sizeof(lens[0]); ++li) {
        size_t n = lens[li];
        if (place_mode == 1 && n == 0) continue;
        GuardedBuf g;
        memset(&g, 0, sizeof(g));
        if (guarded_alloc(&g, n, place_mode, 1) != 0) {
            fprintf(stderr, "FAIL probe mmap n=%zu\n", n);
            return 1;
        }
        int abi_ok = 0;
        uint64_t got = call_sum_abi_checked(g.data, n, &abi_ok);
        if (!abi_ok) {
            fprintf(stderr, "ABI_FAIL n=%zu place_mode=%d\n", n, place_mode);
            guarded_free(&g);
            return 3;
        }
        uint64_t want = expected(g.data, n);
        if (got != want) {
            fprintf(stderr, "FAIL probe n=%zu got=%" PRIu64 " expected=%" PRIu64 "\n",
                    n, got, want);
            guarded_free(&g);
            return 1;
        }
        guarded_free(&g);
    }
    puts("PASS");
    return 0;
}

static int probe(void) { return probe_modes(2); }
static int probe_tight(void) { return probe_modes(1); }
static int probe_head(void) { return probe_modes(0); }

static int verify(void) {
    uint64_t a[4096];
    if (check(NULL, 0, "empty")) return 1;
    for (size_t n = 0; n <= 4096; ++n) {
        for (size_t i = 0; i < n; ++i) a[i] = next_u64();
        if (check(a, n, "random") || check(a + (n ? 1 : 0), n ? n - 1 : 0, "offset")) return 1;
    }
    const uint64_t edges[] = {UINT64_MAX, 1, UINT64_MAX, UINT64_MAX, 4, 0, 1};
    for (size_t n = 0; n <= 7; ++n) if (check(edges, n, "overflow")) return 1;
    /* Centered RO + ABI probe (slack avoids false faults from auto-vectorization). */
    return probe();
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
static int sum_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror("fopen"); return 2; }
    unsigned long long n_ull = 0;
    if (fscanf(f, "%llu", &n_ull) != 1) { fclose(f); return 2; }
    if (n_ull > 16777216ull) { fclose(f); return 2; }
    size_t n = (size_t)n_ull;
    if (n == 0) {
        fclose(f);
        printf("%" PRIu64 "\n", sum_array(NULL, 0));
        return 0;
    }
    uint64_t *a = malloc(n * sizeof(*a));
    if (!a) { fclose(f); return 2; }
    for (size_t i = 0; i < n; ++i) {
        unsigned long long v = 0;
        if (fscanf(f, "%llu", &v) != 1) { free(a); fclose(f); return 2; }
        a[i] = (uint64_t)v;
    }
    fclose(f);
    printf("%" PRIu64 "\n", sum_array(a, n));
    free(a);
    return 0;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "verify")) return verify();
    if (argc == 2 && !strcmp(argv[1], "probe")) return probe();
    if (argc == 2 && !strcmp(argv[1], "probe-tight")) return probe_tight();
    if (argc == 2 && !strcmp(argv[1], "probe-head")) return probe_head();
    if (argc == 3 && !strcmp(argv[1], "sum-file")) return sum_file(argv[2]);
    if (argc == 4 && !strcmp(argv[1], "bench")) {
        char *end1, *end2;
        unsigned long long n = strtoull(argv[2], &end1, 10);
        unsigned long long samples = strtoull(argv[3], &end2, 10);
        if (*end1 || *end2) return 2;
        return bench((size_t)n, (size_t)samples);
    }
    fprintf(stderr,
            "usage: harness verify | probe | probe-tight | probe-head | sum-file PATH | bench N SAMPLES\n");
    return 2;
}
