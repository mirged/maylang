# Cross-language workloads

One program per language per workload, all computing the same thing and
printing the same output. `../xlang.py` builds and times them; the results and
the current baseline are in [../xlang-baseline.md](../xlang-baseline.md).

| Workload | Directory | Measures |
| --- | --- | --- |
| `fib` | `may/ c/ rs/ java/ js/ py/` | recursive calls, `Int` arithmetic |
| `collatz` | | top-level loops and mutated globals |
| `sieve` | | `List<Bool>` stores, allocation, page faults |
| `hashmap` | | `Map<Str, Int>` inserts and lookups |
| `strings` | | concatenation, `str(Int)` and `join` |
| `mandelbrot` | | `Float` arithmetic and comparisons in a loop |
| `nbody` | | struct field access, `Float` math, lists of structs |
| `trees` | | struct allocation, field reads, collection |

Sizes are fixed inside each program so that a run is comparable across
languages; they match the roadmap's baseline table. `fib` computes `fib(35)`,
`collatz` counts the steps of seeds 1 through 300000, the sieve marks 10M
booleans, the map test inserts 200k string keys and looks up 400k, `strings`
builds 300k three-part strings and joins them, Mandelbrot runs 600×600 for 100
iterations, n-body steps five bodies 200k times and binary trees run depth 16.

Adding a workload means adding one file per language here, listing its name in
`BENCHMARKS` in `../xlang.py`, and confirming that every language prints the
same output. C is built with `gcc -O2`, Rust with `rustc -C opt-level=3`, Java
with `javac`, and Node and CPython run the sources directly; a missing
toolchain is skipped.
