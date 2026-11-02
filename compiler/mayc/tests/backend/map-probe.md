# Inline map probe and coalesce fast path — issue #133

The last bullet of #133: `??` on a present map value reuses the probe state
instead of re-reading a temporary. That needs map probing inlined first, so this
change inlines the Str/Int hash-table probe and then folds the coalesce branch
into it. Inline `push` and string equality were the first two bullets
([inline-paths.md](inline-paths.md)).

## Changes

**The probe** (`fat_map_str_hash`, `fat_map_int_hash`, `fat_map_probe`, and
`fat_index_load` in `src/backend/x86_64_fat.may`). `m[k]` with a receiver the
checker proved `Map` and a key proved `Str` or `Int` now walks the runtime's
hash table inline instead of calling `rt_index_get` (which calls
`rt_map_lookup`, `rt_map_find`, `rt_key_hash` and, per matching entry,
`rt_str_eq`). The inline walk is `rt_map_find`'s exactly: the same key hash
(`h * 131 + byte` for strings, the folded high words for `Int`), the same three
linear steps and then CPython's `slot = slot * 5 + 1 + perturb` sequence, the
same 32-byte entries (key type, key, value type, value) and the same map header
(count, entries, hash table and hash capacity at 0, 16, 24 and 32). Only entries
are needed for a read, and a miss answers nil directly, as `rt_map_lookup`
does: a map read cannot fault.

The runtime call remains the fallback for every case the inline walk does not
prove: a receiver that is not a map, a key whose runtime type is not the proved
one, a map below the hash-table threshold (below eight entries `rt_map_find`
scans the entries linearly and has no table), every other key type, and an
`Any` receiver or key, where no static type is proved and the site keeps the old
path outright. The fallback pushes the two operand values in the same stack
layout the runtime call uses. Growth is not raced: the header and table pointers
are read once per lookup, nothing allocates inside the probe, and no user code
runs between those reads (`rt_str_eq` does not allocate), so a collection cannot
move the entries under it.

**The coalesce fold** (`fat_coalesce_fusable`, `fat_index_coalesce`). `a ?? b`
lowers to the indexed value, a copy into the coalesce result and an `IR_NONNULL`
branch on that value. When the indexed value's only two readers are that copy
and the branch, the backend no longer materialises the temporary: the probe
leaves the value in RDX/RAX, the fold tests its type word right there, jumps to
the coalesce's join point on a present non-nil value and otherwise falls through
to the right operand. The temporary store, the reload and the separate branch
instruction all disappear; the probe's hit or miss is the branch condition.

The nil test itself stays, and must: a present entry can hold nil, for example a
`Map<Str, Int>` aliased to `Any` into which a program stores nil. There is no
probe state that proves otherwise, because the checker's value type is not a
proof at runtime (the same reason this backend proves types from operations).
`tests/map_probe.may` covers that case: the present nil must take the fallback,
and it does.

Both paths are skipped under `--no-opt`, which keeps the runtime call and the
ordinary branch for the oracle comparison.

## Measurements

**Method.** The machine was running other builds while this was measured
(`uptime` load average 6-7 on 16 logical CPUs), so timing one command at a time
as hyperfine does would let load drift bias one side. Instead the two
executables were sampled alternately, in alternating order, with every process
pinned to CPUs 4-5 (`taskset -c 4,5`), 20 samples per side per repeat and three
repeats for the two changed benchmarks (60 samples per side). Whole-process wall
time, identical output required for every run. "before" is the compiler built
from `e0f0932` in this worktree before the change, kept in a separate directory
with its own sidecars; "after" is this change. Both are `mayc 0.15.0`; the
runtime sidecars are unchanged.

| Benchmark | before, ms | after, ms | change |
| --- | --- | --- | --- |
| hashmap, 200k `Str` inserts + 400k lookups with `?? 0` | 110.1 (60 runs) | 102.6 | **-6.9%** |
| map probe, 1M present + 1M content-matched + 1M absent lookups with `??` | 239.8 (60 runs) | 182.1 | **-24.1%** |
| strings, 300k concatenations + join (control) | 51.1 (20 runs) | 51.4 | +0.7% |
| sieve, 10M `List<Bool>` pushes (control) | 220.2 (20 runs) | 217.1 | -1.4% |

The two changed benchmarks contain the inline probe; the two controls are the
same fixture compiled by two compilers that produce **byte-identical
executables** (`sieve` and `strings` md5 unchanged), so their deltas are the
noise floor of this machine under concurrent load: ±1.4%. The map-probe
workload measures the probe directly: `map_probe_bench.may` builds two maps from
equal key text, one sharing the key objects with the lookup list (pointer hit)
and one not (content hit), plus keys that were never inserted (miss), so the
three probe exits are exercised without measuring string building. The hashmap
workload allocates two strings per lookup, which dilutes the lookup cost; its
-6.9% is the same effect seen through that noise.

Peak RSS is unchanged (hashmap 72.0 -> 71.9 MiB; the probe's 96-byte stack
frame allocates nothing). The compiler's own binary grows from 3,107,944 to
3,158,328 bytes (+1.6%) because the compiler sources contain map-index sites
that now carry the inline probe; `make test-bootstrap` keeps stage 2 = stage 3,
so the compiler still compiles itself to the same image whichever stage does it.

Raw samples: [map-probe-performance.json](map-probe-performance.json).

## Tests

- `tests/map_probe.may` covers the probe's exits and the fold: Str and Int keys
  on hash-table maps (present, missing, dynamic key text and literals), a map
  below the threshold, key and fallback evaluation order with effects (the key
  once, the fallback only on nil), growth before, during and after a probe
  (including growth inside the coalesce fallback), an `Any` alias that keeps the
  runtime call and stores nil for a present key, list and string receivers,
  Float and Bool keys, nested maps, and a coalesced value that is discarded. Its
  output is pinned in `tests/legacy_behavior.json`.
- `tests/oracle.py` (part of `make test-compiler`) compiles every fixture with
  and without `--no-opt` and requires the same output; it passes for the whole
  suite, including the new fixture.
- `make test-compiler`: 133 checks pass. `raw_codegen.py` and `backends.py`
  pass. `make test-bootstrap` passes twice, source-only stage 2 = stage 3; the
  compiler was also rebuilt and its fixture corpus re-run after every probe
  change, since the earlier inline-store attempt in #133 corrupted the
  compiler's own build only when it compiled itself.
