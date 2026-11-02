public class Trees { record Node(Node left, Node right) {}
    static Node make(int d) { return d == 0 ? new Node(null, null) : new Node(make(d - 1), make(d - 1)); }
    static long check(Node n) { return n.left() == null ? 1 : 1 + check(n.left()) + check(n.right()); }
    public static void main(String[] a) { int maxDepth = 16; Node longLived = make(maxDepth); long total = 0;
        for (int depth = 4; depth <= maxDepth; depth += 2) for (long i = 0; i < (1L << (maxDepth - depth + 4)); i++) total += check(make(depth));
        System.out.println(total + " " + check(longLived)); } }
