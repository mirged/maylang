public class Mandelbrot { public static void main(String[] a) { int size = 600; long inside = 0;
    for (int y = 0; y < size; y++) { double ci = 2.0 * y / size - 1.0;
        for (int x = 0; x < size; x++) { double cr = 2.0 * x / size - 1.5, zr = 0, zi = 0; boolean escaped = false;
            for (int k = 0; k < 100; k++) { double tr = zr * zr - zi * zi + cr; zi = 2.0 * zr * zi + ci; zr = tr; if (zr * zr + zi * zi > 4.0) { escaped = true; break; } }
            if (!escaped) inside++; } }
    System.out.println(inside); } }
