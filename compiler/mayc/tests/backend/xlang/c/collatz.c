#include <stdio.h>
int main(void) {
    long steps = 0;
    for (long seed = 1; seed <= 300000; seed++) {
        long n = seed;
        while (n > 1) { n = n % 2 == 0 ? n / 2 : n * 3 + 1; steps++; }
    }
    printf("%ld\n", steps);
    return 0;
}
