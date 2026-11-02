# Inline map probe for Float and Bool keys — issue #133

The inline map probe landed for Str and Int keys ([map-probe.md](map-probe.md));
Float and Bool keys still took the runtime `rt_index_get` path. This extends the
probe to those two key types with the runtime's exact hashing and equality, and
it pays where Float-keyed maps are hot: a Float+Bool-key map workload runs
**51% faster**, while Str/Int-only programs compile to byte-identical binaries
and do not move.

## Mechanism

`ir.may` now records the proved key type on `E_INDEX` as 4 Str, 3 Float, 2 Int
or 1 Bool (`mapProbe`); 0 still means the site keeps the runtime call. The fat
backend's `fat_index_load` dispatches on that guarded runtime key type exactly
as before, and `fat_map_probe` grows two branches:

- **Bool keys** hash with `rt_key_hash`'s `kt <= 2` formula, the same folded
  payload as Int (a Bool payload is 0 or 1, which the fold leaves unchanged),
  and compare by payload equality, which is what `rt_same` does for `kt == 1`.
  `fat_map_int_hash` is reused for the hash.
- **Float keys** hash with the runtime's `rt_hash_mix` inlined — `h = x*C1;
  h ^= h >> 32; h *= C2; h ^= (h >> 29) & (2^35-1)` with C1 =
  1024421277861575701 and C2 = 1105712242481227193 — after folding the `-0.0`
  payload (`1 << 63`) onto `mix(0)`, exactly as `rt_key_hash` does, so both
  zeros land in the same slot. Equality is `rt_same`'s `__fbits(20, a, b)`:
  `ucomisd` plus "ordered equal", so `-0.0` equals `+0.0` and NaN never equals
  anything, including itself (`jp` takes the NaN case to the next probe slot,
  `je` takes ordered equality to the hit).

The fallback set is unchanged and complete: a receiver that is not a map, a
runtime key type that differs from the proved one, a map below the hash-table
threshold (rt_map_find scans those linearly and has no table to probe), growth,
faults, an `Any` receiver or key, and `--no-opt` all keep `rt_index_get`. Maps
that grow during construction and entry arrays that move are covered by the
same fresh header/table/entries loads the probe already made.

**Bool reachability.** A typed `Map<Bool, V>` can hold at most two entries
(there are only two Bool payloads), so it never reaches rt_map_put's
eight-entry hash-table threshold and the Bool inline block would be unreachable.
It does fire when a map proved `Map<Bool, V>` has a hash table grown by keys of
other types mixed in through an `Any` alias: the typed Bool read then takes the
full probe path. `tests/map_probe_keys.may` and the benchmark exercise exactly
that, and the Bool block is guarded by the same sub-threshold check as every
other key type, so it can never run on a map that has no table.

Only sites whose key the checker proved Float or Bool emit the new code; a
program with only Str/Int-keyed map reads compiles to a byte-identical binary
(controls below).

## Measurements

Intel i5-13500H, Linux 6.12.113, full runtime, identical output on both sides.
The machine runs other builds, so the two executables were sampled alternately
in alternating order, every child pinned to CPU 4 with `taskset`, 20 samples per
side per run and three runs for the changed benchmark (60 samples per side).
"before" is a compiler built from `40ae868` (the integration tip) kept with its
own sidecars; "after" is this change.

| Benchmark | before, ms | after, ms | change |
| --- | ---: | ---: | ---: |
| `map_probe_keys_bench`: Float+Bool-key map workload | 258.8 (60 runs) | 126.1 (60 runs) | **-51.3%** |
| `map_probe_bench`: Str-key probe (control) | 197.8 (20 runs) | 197.7 | -0.1% |
| xlang `hashmap`: Str-key build + lookups (control) | 109.6 (20 runs) | 109.2 | -0.3% |

The per-run change of the key workload is -50.5%, -52.9% and -52.3%, so the win
is stable. The workload (`compiler/mayc/tests/backend/map_probe_keys_bench.may`)
prebuilds a Float-keyed map plus lists of present and absent Float keys and
times, 20 rounds each: 100k present-key lookups (`?? -1`, probe hit with no
content compare), 100k absent-key lookups (probe miss), a hashmap-shaped phase
that builds another 100k-entry Float map and looks 200k keys up with `?? 0`
(half present), and 200k Bool-key lookups on a Bool map whose hash table was
grown through an `Any` alias. Before the change every one of those lookups was
four runtime calls; now they are the inline walk.

The controls are byte-identical executables: the Str-key probe and hashmap
binaries have the same md5 before and after, so their -0.1%/-0.3% is the noise
floor, and no existing suite workload uses a Float-keyed map in a hot loop, so
suite timings are unchanged. The compiler image grows 3,056,520 to 3,056,616
bytes (+96 B, +0.003%): the compiler's own sources have no hot Float/Bool-keyed
map reads.

Raw samples: [map-probe-keys-performance.json](map-probe-keys-performance.json).

## Tests

- `tests/map_probe_keys.may` pins the semantics: Float hits and misses across a
  map that crosses the hash-table threshold; `-0.0` and `+0.0` as one key with a
  write through either spelling; NaN self-inequality (`==` false, `<`/`>` false)
  and NaN entries that stay unfindable and append on each insert; key and
  fallback evaluation order with effects; Bool keys `true`/`false`, a one-key
  map missing the other, and updates; a Bool map grown through an `Any` alias so
  the typed Bool reads take the inline hash-table path; a Float key inserted
  through an `Any` alias and then read through the typed inline probe; and a
  dynamic (`Any`) receiver/key pair on the runtime fallback. Its output is
  pinned in `tests/legacy_behavior.json`.
- `tests/oracle.py` requires the same output with and without `--no-opt` for
  every fixture; the existing `map_probe.may` Float/Bool map reads now exercise
  the inline path while keeping their pinned output, and the whole suite
  compares equal.
- `make test-compiler`: 142 checks pass (the new fixture plus the oracle
  harness). `gc.py` (including the #134 record probe), `gc_stress.py`,
  `raw_codegen.py`, `backends.py` and `make test-compliance` (65) pass, and
  `make test-bootstrap` keeps source-only stage 2 = stage 3 twice.

## Risks and limits

- The Float hash and comparison are emitted per statically Float/Bool-keyed
  site. That is code the program did not carry before; the existing suite has no
  such hot sites, and the two controls are byte-identical, so nothing else
  moves. A program with many Float-keyed map reads grows by roughly a hundred
  bytes per site.
- The inline code mirrors `rt_key_hash` and `rt_same` exactly, including their
  handling of `-0.0` and NaN. A change to either runtime function must update
  `fat_map_float_hash` and the Float compare in the same commit; the runtime
  sidecars themselves are untouched by this change.
- NaN keys can be inserted but never found (rt_same semantics), and each NaN
  insert appends an entry. That is what the runtime does; the probe mirrors it
  rather than fixing it.
- Bool-keyed maps only have a hash table when they have been grown through an
  `Any` alias; the Bool block is a completeness matrix entry that is exercised
  there, and it costs nothing on ordinary two-entry Bool maps because the
  sub-threshold check sends them to the runtime first.
