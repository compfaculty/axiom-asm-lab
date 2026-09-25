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

extern size_t map_filter_u64(const uint64_t *, size_t, uint64_t *);
extern size_t call_map_filter_abi_checked(const uint64_t *, size_t, uint64_t *, int *);

static uint64_t rng = UINT64_C(0x9e3779b97f4a7c15);
static uint64_t next_u64(void) {
    uint64_t x = rng;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    rng = x;
    return x * UINT64_C(2685821657736338717);
}

static size_t expected(const uint64_t *in, size_t n, uint64_t *out) {
    size_t w = 0;
    for (size_t i = 0; i < n; ++i) {
        uint64_t x = in[i];
        if ((x & 1ull) == 0) out[w++] = x >> 1;
    }
    return w;
}

static int check(const uint64_t *in, size_t n, const char *label) {
    uint64_t *got_buf = malloc((n ? n : 1) * sizeof(uint64_t));
    uint64_t *want_buf = malloc((n ? n : 1) * sizeof(uint64_t));
    if (!got_buf || !want_buf) { free(got_buf); free(want_buf); return 2; }
    size_t got_n = map_filter_u64(in, n, got_buf);
    size_t want_n = expected(in, n, want_buf);
    int rc = 0;
    if (got_n != want_n) {
        fprintf(stderr, "FAIL %s n=%zu got_n=%zu want_n=%zu\n", label, n, got_n, want_n);
        rc = 1;
    } else {
        for (size_t i = 0; i < got_n; ++i) {
            if (got_buf[i] != want_buf[i]) {
                fprintf(stderr, "FAIL %s n=%zu i=%zu got=%" PRIu64 " want=%" PRIu64 "\n",
                        label, n, i, got_buf[i], want_buf[i]);
                rc = 1;
                break;
            }
        }
    }
    free(got_buf); free(want_buf);
    return rc;
}

typedef struct {
    void *map;
    size_t map_bytes;
    uint64_t *data;
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
    if (n == 0) data = NULL;
    else if (place_mode == 1)
        data = (uint64_t *)((char *)mid + payload - n * sizeof(uint64_t));
    else if (place_mode == 2) data = (uint64_t *)((char *)mid + slack);
    else data = (uint64_t *)mid;
    for (size_t i = 0; i < n; ++i) data[i] = next_u64();
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
        uint64_t *out = calloc(n ? n : 1, sizeof(uint64_t));
        uint64_t *want = calloc(n ? n : 1, sizeof(uint64_t));
        if (!out || !want) { free(out); free(want); guarded_free(&g); return 2; }
        int abi_ok = 0;
        size_t got_n = call_map_filter_abi_checked(g.data, n, out, &abi_ok);
        if (!abi_ok) {
            fprintf(stderr, "ABI_FAIL n=%zu place_mode=%d\n", n, place_mode);
            free(out); free(want); guarded_free(&g);
            return 3;
        }
        size_t want_n = expected(g.data, n, want);
        int bad = (got_n != want_n);
        for (size_t i = 0; !bad && i < got_n; ++i) if (out[i] != want[i]) bad = 1;
        free(out); free(want);
        if (bad) {
            fprintf(stderr, "FAIL probe n=%zu\n", n);
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
    uint64_t a[4096];
    if (check(NULL, 0, "empty")) return 1;
    for (size_t n = 0; n <= 1024; ++n) {
        for (size_t i = 0; i < n; ++i) a[i] = next_u64();
        if (check(a, n, "random")) return 1;
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

static int alloc_bench_buf(size_t n, uint64_t **out_in, uint64_t **out_out) {
    uint64_t *in = malloc((n ? n : 1) * sizeof(uint64_t));
    uint64_t *out = malloc((n ? n : 1) * sizeof(uint64_t));
    if (!in || !out) { free(in); free(out); return 2; }
    for (size_t i = 0; i < n; ++i) in[i] = next_u64();
    if (check(in, n, "bench")) { free(in); free(out); return 1; }
    *out_in = in; *out_out = out;
    return 0;
}

static uint64_t time_iters(uint64_t *in, uint64_t *out, size_t n, uint64_t iterations,
                           volatile uint64_t *sink) {
    uint64_t start = ns_now();
    for (uint64_t j = 0; j < iterations; ++j) *sink ^= (uint64_t)map_filter_u64(in, n, out);
    return ns_now() - start;
}

static int calibrate(size_t n, uint64_t target_ns, uint64_t max_iters) {
    if (n > 16777216 || target_ns < 1000 || max_iters < 1) return 2;
    uint64_t *in = NULL, *out = NULL;
    int rc = alloc_bench_buf(n, &in, &out);
    if (rc) return rc;
    volatile uint64_t sink = 0;
    (void)time_iters(in, out, n, 1, &sink);
    uint64_t iters = 1, elapsed = 0;
    int capped = 0;
    for (;;) {
        elapsed = time_iters(in, out, n, iters, &sink);
        if (elapsed >= target_ns || iters >= max_iters) {
            if (elapsed < target_ns && iters >= max_iters) capped = 1;
            break;
        }
        uint64_t next = iters > (max_iters / 2) ? max_iters : iters * 2;
        if (next == iters) { capped = 1; break; }
        iters = next;
    }
    printf("%" PRIu64 " %" PRIu64 " %d\n", iters, elapsed, capped);
    free(in); free(out);
    return 0;
}

static int bench_raw(size_t n, size_t samples, uint64_t iterations) {
    if (n > 16777216 || samples < 1 || samples > 10000 || iterations < 1) return 2;
    uint64_t *in = NULL, *out = NULL;
    int rc = alloc_bench_buf(n, &in, &out);
    if (rc) return rc;
    volatile uint64_t sink = 0;
    (void)time_iters(in, out, n, iterations < 8 ? iterations : 8, &sink);
    for (size_t s = 0; s < samples; ++s) {
        uint64_t elapsed = time_iters(in, out, n, iterations, &sink);
        printf("%" PRIu64 " %" PRIu64 " %.6f\n", elapsed, iterations,
               (double)elapsed / (double)iterations);
    }
    free(in); free(out);
    return 0;
}

static int map_filter_file(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror("fopen"); return 2; }
    unsigned long long n_ull = 0;
    if (fscanf(f, "%llu", &n_ull) != 1) { fclose(f); return 2; }
    if (n_ull > 16777216ull) { fclose(f); return 2; }
    size_t n = (size_t)n_ull;
    uint64_t *in = malloc((n ? n : 1) * sizeof(uint64_t));
    uint64_t *out = malloc((n ? n : 1) * sizeof(uint64_t));
    if (!in || !out) { free(in); free(out); fclose(f); return 2; }
    for (size_t i = 0; i < n; ++i) {
        unsigned long long v = 0;
        if (fscanf(f, "%llu", &v) != 1) { free(in); free(out); fclose(f); return 2; }
        in[i] = (uint64_t)v;
    }
    fclose(f);
    size_t w = map_filter_u64(n ? in : NULL, n, out);
    printf("%zu\n", w);
    for (size_t i = 0; i < w; ++i) printf("%" PRIu64 "\n", out[i]);
    free(in); free(out);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "verify")) return verify();
    if (argc == 2 && !strcmp(argv[1], "probe")) { int rc = probe(); if (!rc) puts("PASS"); return rc; }
    if (argc == 2 && !strcmp(argv[1], "probe-tight")) { int rc = probe_tight(); if (!rc) puts("PASS"); return rc; }
    if (argc == 2 && !strcmp(argv[1], "probe-head")) { int rc = probe_head(); if (!rc) puts("PASS"); return rc; }
    if (argc == 3 && !strcmp(argv[1], "map-filter-file")) return map_filter_file(argv[2]);
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
            "usage: harness_map_filter verify | probe* | map-filter-file PATH\n"
            "       | calibrate N TARGET_NS MAX_ITERS | bench-raw N SAMPLES ITERATIONS\n");
    return 2;
}
