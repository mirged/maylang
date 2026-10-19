#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

// Matching loops for raw_predictability.may (issues #78 and #83).
// Compile: gcc -O3 -march=native -std=c11 compiler/mayc/tests/backend/raw_predictability.c -o /tmp/predictability_c
typedef int64_t i64;

static i64 now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) abort();
    return (i64)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void report(const char *label, i64 result, i64 elapsed) {
    printf("%-18s%14lld %14lld\n", label, (long long)result, (long long)elapsed);
}

static __attribute__((noinline)) i64 periodic_bench(void) {
    i64 total = 0;
    for (i64 i = 0; i < 10000000; i++) {
        if (i % 1024 == 1023) total = total + 7;
        else total = total + 1;
    }
    return total;
}

static __attribute__((noinline)) i64 parity_two_bench(void) {
    i64 state = 1, total = 0;
    for (i64 i = 0; i < 10000000; i++) {
        state = state * 48271 % 2147483647;
        if (state % 2 == 0) total = total + 3;
        else total = total - 1;
    }
    return total;
}

static __attribute__((noinline)) i64 parity_one_bench(void) {
    i64 state = 1, total = 0;
    for (i64 i = 0; i < 10000000; i++) {
        state = state * 48271 % 2147483647;
        if (state % 2 == 0) total = total + 1;
    }
    return total;
}

static __attribute__((noinline)) i64 maximum_bench(void) {
    i64 state = 1, best = 0;
    for (i64 i = 0; i < 10000000; i++) {
        state = state * 48271 % 2147483647;
        if (state > best) best = state;
    }
    return best;
}

static __attribute__((noinline)) i64 guard_bench(void) {
    i64 x = 0;
    for (i64 i = 0; i < 10000000; i++) {
        x = x + i;
        if (x > 1000000000) x = 0;
    }
    return x;
}

int main(void) {
    i64 start = now_ns();
    i64 periodic = periodic_bench();
    report("Periodic branch", periodic, now_ns() - start);
    start = now_ns();
    i64 parity_two = parity_two_bench();
    report("PRNG parity two", parity_two, now_ns() - start);
    start = now_ns();
    i64 parity_one = parity_one_bench();
    report("PRNG parity one", parity_one, now_ns() - start);
    start = now_ns();
    i64 maximum = maximum_bench();
    report("Running maximum", maximum, now_ns() - start);
    start = now_ns();
    i64 guard = guard_bench();
    report("Rare guard", guard, now_ns() - start);
    return 0;
}
