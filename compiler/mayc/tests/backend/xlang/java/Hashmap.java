import java.util.HashMap;
public class Hashmap { public static void main(String[] a) { long n = 200000; HashMap<String, Long> m = new HashMap<>();
    for (long i = 0; i < n; i++) m.put("k" + (i * 7), i);
    long sum = 0; for (long i = 0; i < n * 2; i++) sum += m.getOrDefault("k" + i, 0L); System.out.println(sum); } }
