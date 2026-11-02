struct Node { kids: Option<(Box<Node>, Box<Node>)> }
fn make(d: u32) -> Box<Node> { Box::new(Node { kids: if d == 0 { None } else { Some((make(d - 1), make(d - 1))) } }) }
fn check(n: &Node) -> i64 { match &n.kids { None => 1, Some((l, r)) => 1 + check(l) + check(r) } }
fn main() {
    let max_depth = std::hint::black_box(16u32);
    let long_lived = make(max_depth);
    let mut total = 0i64;
    let mut depth = 4;
    while depth <= max_depth {
        for _ in 0..(1u64 << (max_depth - depth + 4)) { total += check(&make(depth)); }
        depth += 2;
    }
    println!("{} {}", total, check(&long_lived));
}
