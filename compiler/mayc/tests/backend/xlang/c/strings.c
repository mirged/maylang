#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    long count = 300000, total = 0; char **parts = malloc(count * sizeof *parts); char buf[32];
    for (long i = 0; i < count; i++) { int len = snprintf(buf, sizeof buf, "item-%ld;", i); parts[i] = strdup(buf); total += len; }
    size_t size = 0; for (long i = 0; i < count; i++) size += strlen(parts[i]) + 1;
    char *joined = malloc(size), *p = joined;
    for (long i = 0; i < count; i++) { if (i) *p++ = ','; size_t l = strlen(parts[i]); memcpy(p, parts[i], l); p += l; }
    *p = 0;
    printf("%ld %zu\n", total, strlen(joined));
    return 0;
}
