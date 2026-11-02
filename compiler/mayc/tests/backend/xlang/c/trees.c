#include <stdio.h>
#include <stdlib.h>
typedef struct Node { struct Node *left, *right; } Node;
static Node *make(int d) { Node *n = malloc(sizeof *n); if (d == 0) n->left = n->right = NULL; else { n->left = make(d - 1); n->right = make(d - 1); } return n; }
static long check(Node *n) { return n->left ? 1 + check(n->left) + check(n->right) : 1; }
static void release(Node *n) { if (n->left) { release(n->left); release(n->right); } free(n); }
int main(void) {
    int max_depth = 16; Node *long_lived = make(max_depth); long total = 0;
    for (int depth = 4; depth <= max_depth; depth += 2) {
        long iterations = 1L << (max_depth - depth + 4);
        for (long i = 0; i < iterations; i++) { Node *t = make(depth); total += check(t); release(t); }
    }
    printf("%ld %ld\n", total, check(long_lived));
    return 0;
}
