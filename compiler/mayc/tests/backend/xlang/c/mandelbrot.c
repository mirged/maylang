#include <stdio.h>
int main(void) {
    int size = 600; long inside = 0;
    for (int y = 0; y < size; y++) {
        double ci = 2.0 * y / size - 1.0;
        for (int x = 0; x < size; x++) {
            double cr = 2.0 * x / size - 1.5, zr = 0, zi = 0; int escaped = 0;
            for (int k = 0; k < 100; k++) {
                double tr = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = tr;
                if (zr * zr + zi * zi > 4.0) { escaped = 1; break; }
            }
            if (!escaped) inside++;
        }
    }
    printf("%ld\n", inside);
    return 0;
}
