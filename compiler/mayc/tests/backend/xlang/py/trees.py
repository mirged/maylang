class Node:
    __slots__ = ("left", "right")
    def __init__(self, left, right):
        self.left, self.right = left, right

def make(d):
    return Node(None, None) if d == 0 else Node(make(d - 1), make(d - 1))

def check(node):
    return 1 if node.left is None else 1 + check(node.left) + check(node.right)

def main():
    max_depth = 16
    long_lived = make(max_depth)
    total = 0
    for depth in range(4, max_depth + 1, 2):
        for _ in range(1 << (max_depth - depth + 4)):
            total += check(make(depth))
    print(total, check(long_lived))
main()
