# Map hashing for every key type — issue #97

Before this change the full runtime's `Map` hashed only `Str` keys. Every
other key type (`Int`, `Float`, `Bool`, `nil`, lists, maps and closures)
fell back to a linear scan of the entry array, so each insert and lookup was
O(n) and building a map was O(n²). The `Str` path did one 64-bit division
per key byte (`% 2147483647`) and a `% cap` per probe.

## Change

`compiler/mayc/runtime/fat.may` now indexes every entry once a map has
eight entries. Maps below that size are still scanned linearly, as before.
Entries stay in an insertion-ordered array, and the index table still holds
entry index + 1 in a power-of-two array, so iteration order is unchanged.

Hashes agree with `rt_same`, the equality `==` and map lookup already use:

- `Int`, `Bool` and `nil` hash to `x ^ x>>32 ^ x>>48` (logical shifts).
  Small and sequential keys keep their own low bits.
- `Str` hashes to a polynomial over its bytes (`h * 131 + byte`, wrapping),
  which is the old hash without the per-byte modulo.
- `Float` hashes its bits through a multiplicative mixer, with `-0.0`
  folded onto `0.0`. NaN never equals itself under `rt_same`, so a NaN key
  is still never found, as before.
- Lists, maps, closures and cells hash their address through the same
  mixer. The mark-sweep collector does not move objects, so addresses are
  stable, and `rt_same` already compared these values by identity.

A probe starts at `hash & mask`, takes up to three linear steps, then follows
CPython's dict recurrence `slot = 5 * slot + 1 + perturb`, shifting
`perturb` right by five bits each step. Once `perturb` reaches zero, the
recurrence visits every slot. A table hit compares the type word first, then
calls `rt_str_eq` for strings, IEEE equality for Floats, or compares
payloads for everything else.

### Why these hashes, not a well-mixed one

The first version hashed every key with a multiplicative mixer (and strings
eight bytes at a time), as the issue proposed. It fixed the O(n²) behavior,
but on a quiet machine the string workload got slower than before, and the
500 000-key `Int` workload took 0.6–0.9 s. Python simulations of both
tables showed the same probe counts (about 1.7 per lookup), so the cost was
memory traffic. The old string hash and an identity `Int` hash put
consecutive keys (`"k1"`, `"k2"`, … or `0`, `7`, `14`, …) in neighbouring
slots, and lookups in key order then stay in cache. A mixed hash scatters
them across a 4 MiB table and 6.4 MiB of entries.

Keeping the low bits creates a different hazard: keys that share their low
bits, such as packed coordinates `x * 65536 + y` or multiples of a power of
two. Plain linear probing clusters such keys into long runs: with it, the
grid workload below did not finish its timing run within ten minutes. The
perturbation recurrence brings in the high bits after the first few probes.
Folding `x>>32` and `x>>48` handles keys whose low 32 bits are all zero.

The simulated mean probes per lookup for 100 000 keys (90 000 for the grids)
are below. The final layout is in the last column.

| Keys | Perturbation only | Three linear steps, then perturbation |
| --- | --- | --- |
| `"k" + str(7i)`, looked up as `"k" + str(i)` | 1.52 | 1.71 |
| `i * 1024` | 2.97 | 5.94 |
| `i << 40` | 1.52 | 1.34 |
| `x * 65536 + y` | 2.67 | 5.63 |
| `x << 20 + y` | 3.15 | 6.14 |
| random 60-bit | 1.26 | 1.30 |

The linear steps add probes for structured keys, but they stay within one
cache line. Measured directly, they made the string workload 12% faster, the
500 000-key `Int` workload 40% faster (its many misses stop jumping across
the table) and the grid workload 13% slower. On balance they are kept.

## Measurements

[`map-hashing-performance.json`](map-hashing-performance.json) holds the raw
samples. They were taken with [`map_hash/run.py`](map_hash/run.py) on an
Intel i5-13500H under Linux 6.12, with the full runtime and default flags.
Nine interleaved rounds were run after one warm-up and an output check. The
values below are medians of the child's user+system CPU time; wall time
agrees within 1%. "Before" is the `63e5aad` compiler with its own runtime.

The machine was running other work (load average 3.0–5.2), and every time
is about three times what a quiet run gives. `str_floor` builds the same
strings as `str_keys` but uses no map, so its before/after gap (7%) is noise
and sets the floor for the comparisons.

| Workload | Before | After | Change |
| --- | ---: | ---: | --- |
| `int_keys_20k`: 20 000 `Int` keys, 140 000 lookups | 33 794 ms | 21.7 ms | about 1 550× faster |
| `str_keys`: 200 000 `Str` keys, 400 000 lookups | 430.7 ms | 386.5 ms | −10% |
| `str_floor`: `str_keys` without the map | 225.6 ms | 243.2 ms | noise |
| `small_maps`: 200 000 four-entry maps, three lookups each | 167.0 ms | 163.0 ms | noise (no index) |
| `int_keys`: the issue's reproduction, n = 500 000 | did not finish in 120 s | 343.0 ms | — |
| `grid_keys`: 360 000 packed `x * 65536 + y` keys | not run (O(n²)) | 256.5 ms | — |

Subtracting `str_floor`, the map work in `str_keys` falls from about 205 ms
to about 143 ms. An earlier hyperfine run at load 1.5–3, with the
perturbation-only probe, timed `int_keys` at 134 ms and `str_keys` at 133 ms
against 128 ms before. That probe was the one that lost on strings, and the
three linear steps since then fixed it.

Reproduce with:

```sh
# OLD_MAYC: a compiler built from 63e5aad, beside that revision's sidecars
python3 compiler/mayc/tests/backend/map_hash/run.py \
    "$OLD_MAYC" compiler/mayc/mayc_new /tmp/map-hashing.json --rounds 9
```

## Validation

- `compiler/mayc/tests/map_hash_keys.may` is a new feature fixture. It
  covers `1`, `"1"`, `1.0`, `true` and `nil` as distinct keys in one hashed
  map, `0.0` and `-0.0` as one key, negative and large `Int` keys, list keys
  by identity, removal and re-insertion (re-insertion appends the key),
  iteration order, and 5 000 `Int` keys with hits and misses. Its expected
  output was produced by the old linear-scan runtime and matches the new
  runtime byte for byte.
- `make check`, `make test-compiler` (122 passed), `make test-compliance`
  (65 passed) and `make test-bootstrap` (stage 2 = stage 3) pass with the
  rebuilt compiler.

## Limits

- Maps below eight entries are still scanned. That path also serves struct
  fields and is tracked in #98.
- `remove` still copies the map (as documented), so removal is O(n).
- Integer keys are not randomized. Adversarial keys chosen to share every
  bit the table looks at can still degrade one map to linear probing, but
  they cannot affect other maps.
