#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    long n = 10000000;
    char *flags = malloc(n);
    memset(flags, 1, n);
    flags[0] = flags[1] = 0;
    for (long i = 2; i * i < n; i++)
        if (flags[i]) for (long j = i * i; j < n; j += i) flags[j] = 0;
    long count = 0;
    for (long i = 0; i < n; i++) count += flags[i];
    printf("%ld\n", count);
    free(flags);
    return 0;
}
