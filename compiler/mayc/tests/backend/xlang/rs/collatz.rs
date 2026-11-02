fn main() {
    let limit: i64 = std::hint::black_box(300000);
    let mut steps: i64 = 0;
    for seed in 1..=limit {
        let mut n = seed;
        while n > 1 { n = if n % 2 == 0 { n / 2 } else { n * 3 + 1 }; steps += 1; }
    }
    println!("{}", steps);
}
