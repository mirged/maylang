#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <time.h>

// Matching algorithms/inputs for raw_suite.may: the extended RAW benchmark suite.
// Compile: gcc -O3 -march=native -std=c11 compiler/mayc/tests/backend/raw_suite.c -o /tmp/suite_c
typedef int64_t i64;

#define MEMORY_BYTES 8388608

static i64 now_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) abort();
    return (i64)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void report(const char *label, i64 result, i64 elapsed) {
    printf("%-18s%14lld %14lld\n", label, (long long)result, (long long)elapsed);
}

static i64 sieve_bench(uint8_t *flags) {
    i64 n = 2000000, i = 0;
    while (i < n) { flags[i] = 1; i = i + 1; }
    flags[0] = 0;
    flags[1] = 0;
    i = 2;
    while (i * i < n) {
        if (flags[i] != 0) {
            i64 j = i * i;
            while (j < n) { flags[j] = 0; j = j + i; }
        }
        i = i + 1;
    }
    i64 count = 0;
    i = 0;
    while (i < n) { count = count + flags[i]; i = i + 1; }
    return count;
}

static i64 matmul_bench(i64 *memory) {
    i64 n = 96;
    i64 *a = memory, *b = memory + n * n, *c = memory + 2 * n * n;
    i64 i = 0;
    while (i < n) {
        i64 j = 0;
        while (j < n) {
            a[i * n + j] = (i * 7 + j * 3) % 17 - 8;
            b[i * n + j] = (i * 5 + j * 11) % 13 - 6;
            j = j + 1;
        }
        i = i + 1;
    }
    i = 0;
    while (i < n) {
        i64 j = 0;
        while (j < n) {
            i64 sum = 0, k = 0;
            while (k < n) { sum = sum + a[i * n + k] * b[k * n + j]; k = k + 1; }
            c[i * n + j] = sum;
            j = j + 1;
        }
        i = i + 1;
    }
    i64 checksum = 0;
    i = 0;
    while (i < n * n) { checksum = checksum + c[i] * (i % 31 + 1); i = i + 1; }
    return checksum;
}

static i64 fib(i64 n) {
    if (n < 2) { return n; }
    return fib(n - 1) + fib(n - 2);
}

static i64 fib_bench(void) { return fib(27); }

static i64 sort_bench(i64 *a) {
    i64 n = 4000, state = 1, i = 0;
    while (i < n) {
        state = state * 48271 % 2147483647;
        a[i] = state % 100000;
        i = i + 1;
    }
    i = 1;
    while (i < n) {
        i64 key = a[i], j = i - 1;
        while (j >= 0 && a[j] > key) { a[j + 1] = a[j]; j = j - 1; }
        a[j + 1] = key;
        i = i + 1;
    }
    i64 checksum = 0;
    i = 0;
    while (i < n) { checksum = checksum + (i + 1) * a[i]; i = i + 1; }
    return checksum;
}

static i64 gcd_bench(void) {
    i64 total = 0, i = 1;
    while (i <= 300) {
        i64 j = 1;
        while (j <= 300) {
            i64 x = i, y = j;
            while (y != 0) { i64 r = x % y; x = y; y = r; }
            total = total + x;
            j = j + 1;
        }
        i = i + 1;
    }
    return total;
}

static i64 hash_bench(uint8_t *data) {
    i64 n = 1048576, i = 0;
    while (i < n) { data[i] = (i * 131 + i / 7) % 256; i = i + 1; }
    i64 h = 2166136261, pass = 0;
    while (pass < 4) {
        i = 0;
        while (i < n) { h = (h * 16777619 + data[i] + 1) % 4294967296; i = i + 1; }
        pass = pass + 1;
    }
    return h;
}

static i64 search_bench(i64 *a) {
    i64 n = 65536, i = 0;
    while (i < n) { a[i] = i * 3 + i % 3; i = i + 1; }
    i64 state = 7, total = 0, q = 0;
    while (q < 150000) {
        state = state * 48271 % 2147483647;
        i64 key = state % 196608, low = 0, high = n;
        while (low < high) {
            i64 middle = (low + high) / 2;
            if (a[middle] < key) { low = middle + 1; } else { high = middle; }
        }
        total = total + low;
        q = q + 1;
    }
    return total;
}

static i64 mandelbrot_bench(void) {
    i64 total = 0, y = 0;
    while (y < 120) {
        i64 ci = y * 8192 / 120 - 4096, x = 0;
        while (x < 160) {
            i64 cr = x * 12288 / 160 - 8192, zr = 0, zi = 0, iteration = 0;
            while (iteration < 64) {
                i64 zr2 = zr * zr / 4096, zi2 = zi * zi / 4096;
                if (zr2 + zi2 > 16384) { break; }
                zi = 2 * zr * zi / 4096 + ci;
                zr = zr2 - zi2 + cr;
                iteration = iteration + 1;
            }
            total = total + iteration;
            x = x + 1;
        }
        y = y + 1;
    }
    return total;
}

static i64 queens(i64 row, i64 n, uint8_t *columns, uint8_t *rising, uint8_t *falling) {
    if (row == n) { return 1; }
    i64 count = 0, column = 0;
    while (column < n) {
        if (columns[column] == 0 && rising[row + column] == 0 && falling[row - column + n] == 0) {
            columns[column] = 1;
            rising[row + column] = 1;
            falling[row - column + n] = 1;
            count = count + queens(row + 1, n, columns, rising, falling);
            columns[column] = 0;
            rising[row + column] = 0;
            falling[row - column + n] = 0;
        }
        column = column + 1;
    }
    return count;
}

static i64 queens_bench(uint8_t *memory) {
    i64 i = 0;
    while (i < 96) { memory[i] = 0; i = i + 1; }
    return queens(0, 10, memory, memory + 32, memory + 64);
}

static i64 dot_bench(i64 *memory) {
    i64 n = 131072;
    i64 *a = memory, *b = memory + n;
    i64 i = 0;
    while (i < n) { a[i] = i % 1000 - 500; b[i] = i * 7 % 1000 - 500; i = i + 1; }
    i64 total = 0, round = 0;
    while (round < 20) {
        i64 sum = 0;
        i = 0;
        while (i < n) { sum = sum + a[i] * b[i]; i = i + 1; }
        total = total + sum + round;
        round = round + 1;
    }
    return total;
}

static i64 knapsack_bench(i64 *best) {
    i64 capacity = 10000, c = 0;
    while (c <= capacity) { best[c] = 0; c = c + 1; }
    i64 item = 0;
    while (item < 200) {
        i64 weight = 10 + item * 37 % 90, value = 20 + item * 53 % 200;
        c = capacity;
        while (c >= weight) {
            i64 candidate = best[c - weight] + value;
            if (candidate > best[c]) { best[c] = candidate; }
            c = c - 1;
        }
        item = item + 1;
    }
    return best[capacity];
}

int main(void) {
    uint8_t *memory = mmap(NULL, MEMORY_BYTES, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED) return 1;
    uint8_t *work = memory + 4096;
    puts("RAW SUITE (C reference)");
    puts("Benchmark               Checksum        Time (ns)");
    puts("------------------------------------------------");
    i64 total = 0, start, result, elapsed;
#define RUN(label, call) \
    start = now_ns(); result = (call); elapsed = now_ns() - start; \
    report(label, result, elapsed); total = total + elapsed;
    RUN("Sieve", sieve_bench(work));
    RUN("Matrix multiply", matmul_bench((i64 *)work));
    RUN("Recursive fib", fib_bench());
    RUN("Insertion sort", sort_bench((i64 *)work));
    RUN("GCD grid", gcd_bench());
    RUN("Hash", hash_bench(work));
    RUN("Binary search", search_bench((i64 *)work));
    RUN("Mandelbrot", mandelbrot_bench());
    RUN("N-queens", queens_bench(work));
    RUN("Dot product", dot_bench((i64 *)work));
    RUN("Knapsack", knapsack_bench((i64 *)work));
    puts("------------------------------------------------");
    report("TOTAL", 0, total);
    munmap(memory, MEMORY_BYTES);
    return 0;
}
