#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>

// Matching algorithms/inputs for raw_performance.may (issue #76).
// Compile: gcc -O3 -march=native -std=c11 compiler/mayc/tests/backend/raw_performance.c -o /tmp/benchmark_c
typedef int64_t i64;

static i64 now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) abort();
    return (i64)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void report(const char *label, i64 result, i64 elapsed) {
    printf("%-18s%14lld %14lld\n", label, (long long)result, (long long)elapsed);
}

static i64 prng_bench(void) {
    i64 state = 1, i = 0;
    while (i < 1000000) {
        state = state * 48271 % 2147483647;
        i = i + 1;
    }
    return state;
}

static i64 collatz_bench(void) {
    i64 total = 0, seed = 1;
    while (seed <= 30000) {
        i64 n = seed;
        while (n > 1) {
            if (n % 2 == 0) { n = n / 2; }
            else { n = n * 3 + 1; }
            total = total + 1;
        }
        seed = seed + 1;
    }
    return total;
}

static i64 histogram_bench(uint8_t *memory) {
    uint8_t *bins = memory + 262144;
    i64 i = 0;
    while (i < 256) {
        *(i64 *)(void *)(bins + i * 8) = 0;
        i = i + 1;
    }
    i = 0;
    while (i < 262144) {
        memory[i] = (uint8_t)((i * 73 + 19) % 256);
        i = i + 1;
    }
    i = 0;
    while (i < 262144) {
        i64 byte = memory[i];
        i64 *slot = (i64 *)(void *)(bins + byte * 8);
        *slot = *slot + 1;
        i = i + 1;
    }
    i64 checksum = 0;
    i = 0;
    while (i < 256) {
        checksum = checksum + (i + 1) * *(i64 *)(void *)(bins + i * 8);
        i = i + 1;
    }
    return checksum;
}

static i64 automaton_bench(uint8_t *memory) {
    const i64 width = 8192;
    uint8_t *front = memory + 300000;
    uint8_t *back = memory + 310000;
    i64 i = 0;
    while (i < width) {
        front[i] = (uint8_t)((i * 7 + i / 13) % 2);
        i = i + 1;
    }
    i64 round = 0;
    while (round < 120) {
        i = 0;
        while (i < width) {
            i64 left = i - 1;
            i64 right = i + 1;
            if (i == 0) { left = width - 1; }
            if (right == width) { right = 0; }
            i64 value = (front[left] + front[i] + front[right]) % 2;
            back[i] = (uint8_t)value;
            i = i + 1;
        }
        uint8_t *temporary = front;
        front = back;
        back = temporary;
        round = round + 1;
    }
    i64 checksum = 0;
    i = 0;
    while (i < width) {
        checksum = checksum + (i % 17 + 1) * front[i];
        i = i + 1;
    }
    return checksum;
}

static i64 pointer_chase_bench(uint8_t *memory) {
    i64 i = 0;
    while (i < 32768) {
        *(i64 *)(void *)(memory + i * 8) = (i + 8191) % 32768;
        i = i + 1;
    }
    i64 index = 0, checksum = 0;
    i = 0;
    while (i < 1500000) {
        index = *(i64 *)(void *)(memory + index * 8);
        checksum = (checksum + index) % 1000000007;
        i = i + 1;
    }
    return checksum;
}

static i64 walk_bench(void) {
    i64 state = 1, x = 0, y = 0, i = 0;
    while (i < 1000000) {
        state = state * 16807 % 2147483647;
        i64 direction = state % 4;
        if (direction == 0) { x = x + 1; }
        else if (direction == 1) { x = x - 1; }
        else if (direction == 2) { y = y + 1; }
        else { y = y - 1; }
        i = i + 1;
    }
    return (x + 1000000) * 2000001 + (y + 1000000);
}

int main(void) {
    uint8_t *memory = mmap(NULL, 1048576, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) { perror("mmap"); return 1; }
    uint8_t *work = memory + 4096;

    puts("RAW BENCHMARK (Linux x86-64)");
    puts("Benchmark               Checksum        Time (ns)");
    puts("------------------------------------------------");

    i64 total_ns = 0, start = now_ns();
    i64 rng = prng_bench(), dt_rng = now_ns() - start;
    report("PRNG", rng, dt_rng); total_ns += dt_rng;

    start = now_ns();
    i64 collatz = collatz_bench(), dt_collatz = now_ns() - start;
    report("Collatz", collatz, dt_collatz); total_ns += dt_collatz;

    start = now_ns();
    i64 histogram = histogram_bench(work), dt_histogram = now_ns() - start;
    report("Byte histogram", histogram, dt_histogram); total_ns += dt_histogram;

    start = now_ns();
    i64 automaton = automaton_bench(work), dt_automaton = now_ns() - start;
    report("Cellular automaton", automaton, dt_automaton); total_ns += dt_automaton;

    start = now_ns();
    i64 pointer = pointer_chase_bench(work), dt_pointer = now_ns() - start;
    report("Pointer chase", pointer, dt_pointer); total_ns += dt_pointer;

    start = now_ns();
    i64 walk = walk_bench(), dt_walk = now_ns() - start;
    report("Random walk", walk, dt_walk); total_ns += dt_walk;

    puts("------------------------------------------------");
    report("TOTAL", 0, total_ns);
    munmap(memory, 1048576);
    return 0;
}
