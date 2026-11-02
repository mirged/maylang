import java.util.ArrayList;
public class Strings { public static void main(String[] a) { ArrayList<String> parts = new ArrayList<>(); long total = 0;
    for (int i = 0; i < 300000; i++) { String s = "item-" + i + ";"; total += s.length(); parts.add(s); }
    System.out.println(total + " " + String.join(",", parts).length()); } }
