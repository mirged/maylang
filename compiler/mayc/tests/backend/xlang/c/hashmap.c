#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { char *key; long value; } Entry;
static Entry *table; static size_t cap = 1 << 19;
static size_t hash(const char *s) { size_t h = 1469598103934665603u; while (*s) { h ^= (unsigned char)*s++; h *= 1099511628211u; } return h; }
static Entry *slot(const char *k) { size_t i = hash(k) & (cap - 1); while (table[i].key && strcmp(table[i].key, k)) i = (i + 1) & (cap - 1); return &table[i]; }
int main(void) {
    long n = 200000; char buf[32];
    table = calloc(cap, sizeof(Entry));
    for (long i = 0; i < n; i++) { snprintf(buf, sizeof buf, "k%ld", i * 7); Entry *e = slot(buf); if (!e->key) e->key = strdup(buf); e->value = i; }
    long sum = 0;
    for (long i = 0; i < n * 2; i++) { snprintf(buf, sizeof buf, "k%ld", i); Entry *e = slot(buf); if (e->key) sum += e->value; }
    printf("%ld\n", sum);
    return 0;
}
