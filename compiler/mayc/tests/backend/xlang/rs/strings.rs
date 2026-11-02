fn main() {
    let mut parts: Vec<String> = Vec::new();
    let mut total = 0usize;
    for i in 0..300000 { let s = format!("item-{};", i); total += s.chars().count(); parts.push(s); }
    let joined = parts.join(",");
    println!("{} {}", total, joined.chars().count());
}
