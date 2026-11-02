public class Sieve { public static void main(String[] a) { int n = 10000000; boolean[] flags = new boolean[n]; java.util.Arrays.fill(flags, true); flags[0] = flags[1] = false;
    for (int i = 2; (long) i * i < n; i++) if (flags[i]) for (int j = i * i; j < n; j += i) flags[j] = false;
    int count = 0; for (int i = 0; i < n; i++) if (flags[i]) count++; System.out.println(count); } }
