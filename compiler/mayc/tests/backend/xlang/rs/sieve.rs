fn main() {
    let n: usize = 10_000_000;
    let mut flags = vec![true; n];
    flags[0] = false; flags[1] = false;
    let mut i = 2;
    while i * i < n {
        if flags[i] { let mut j = i * i; while j < n { flags[j] = false; j += i; } }
        i += 1;
    }
    println!("{}", flags.iter().filter(|&&f| f).count());
}
