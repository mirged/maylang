use std::collections::HashMap;
fn main() {
    let n: i64 = 200000;
    let mut m: HashMap<String, i64> = HashMap::new();
    for i in 0..n { m.insert(format!("k{}", i * 7), i); }
    let mut sum: i64 = 0;
    for i in 0..n * 2 { sum += m.get(&format!("k{}", i)).copied().unwrap_or(0); }
    println!("{}", sum);
}
