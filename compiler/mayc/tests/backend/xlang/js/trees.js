class Node { constructor(left, right) { this.left = left; this.right = right; } }
const make = d => d === 0 ? new Node(null, null) : new Node(make(d - 1), make(d - 1));
const check = n => n.left === null ? 1 : 1 + check(n.left) + check(n.right);
const maxDepth = 16, longLived = make(maxDepth);
let total = 0;
for (let depth = 4; depth <= maxDepth; depth += 2)
    for (let i = 0; i < 1 << (maxDepth - depth + 4); i++) total += check(make(depth));
console.log(total, check(longLived));
