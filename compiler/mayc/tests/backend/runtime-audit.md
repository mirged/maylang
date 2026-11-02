# Runtime library audit — roadmap phase 1

[#97](https://github.com/mirged/maylang/issues/97) and
[#99](https://github.com/mirged/maylang/issues/99) fixed map key hashing and
`join`/list growth. The roadmap's remaining phase 1 item is the rest of the
runtime library: `native.may`, `prelude.may` and `runtime/fat.may`. This
report records what those paths cost, what turned out to be superlinear, and
what was fixed.

The audit found three kinds of problem, all of them invisible on small inputs
and dominant on large ones:

- **code point indexing in a loop.** `char_at(s, i)` finds code point `i` by
  walking from byte 0, so a loop over `0..len(s)` that calls it is O(n²). The
  library used it for digit parsing (`int`, `parse_int`), trimming, string
  reversal, the JSON scanner and the JSON writer. The same shape appears as
  `len(s)` (a full code point count) inside a per-call helper such as
  `starts_with`.
- **pairwise concatenation.** `out = out + part` in a loop copies the whole
  prefix each time: `str` of a list or map, `pad_left`/`pad_right`, the JSON
  writer and its escaper. `rt_join` was fixed in #99; these were not.
- **quadratic comparison counts.** `sort` was an insertion sort, `display` of a
  map sorted its keys by insertion, and `unique` scanned the values kept so
  far. Each compares O(n²) times through a dynamic call.

## Changes

`compiler/mayc/runtime/fat.may`:

- **`rt_display_list` / `rt_display_map` allocate once.** Each element's text
  goes into a scanned scratch block; the total length is summed and one
  string is filled with one copy per part, exactly as `rt_join` does.
- **Map display sorts by merge.** The entry pointers are sorted bottom-up by
  key with a scratch array instead of by insertion sort. Taking the left run
  on a tie keeps equal keys in insertion order, so the printed order is
  unchanged.
- **`rt_map_column`** (`keys`, `values`) stores entries directly into the
  list buffer, which `rt_list_raw` already allocated at the final size,
  instead of calling `rt_list_add` per entry.
- **`rt_str_eq` compares eight bytes per step.** It is the map key comparison
  and the `==` behind every string comparison.

`compiler/mayc/native.may` (mirrored to `stdlib/native.may`):

- **`sort` is a stable bottom-up merge sort** over a copy of the input:
  O(n log n) `cmp` calls instead of O(n²).
- **`unique` uses a map of the values already seen.** Map key equality is the
  same total equality `has` used for a list — strings by bytes, numbers by
  value, collections by identity — so the linear form keeps the result.
- **`trim`, `int`, `parse_int` scan bytes.** Whitespace, signs and digits are
  ASCII, so the byte scan finds exactly the code point boundaries the old
  loop did; slices are taken by byte range.
- **`starts_with` / `ends_with` compare bytes without allocating.** A prefix
  or suffix whose width walk lands on its byte length (every well-formed
  string) walks identically inside the receiver, which makes the byte
  comparison the same test as the old code point comparison. A truncated
  sequence, or a suffix offset that is not a code point boundary, takes the
  old code point path, so the result is unchanged for any input.
- **`reverse` of a string copies each code point to its mirrored byte
  offset** in one pass, instead of `char_at(s, n - 1 - i)` plus a
  concatenation per character.
- **`pad_left` / `pad_right`** compute the number of padding copies and build
  them with `repeat`, then concatenate once.
- **`jq_escape` and `json_stringify`** copy runs and join the parts once.
- **The JSON scanner (`jd_skip`, `jd_string`, `jd_number`, `jd_array`,
  `jd_object`, `jd_value`, `json_parse`) works in byte offsets.** The
  structural characters it looks for are ASCII, and `jd_string` copies each
  run of unescaped bytes instead of appending a character at a time. The
  helpers document their positions as byte offsets; they are internal to the
  parser.

## Measurements

[`runtime_paths-performance.json`](runtime_paths-performance.json) holds every
sample, taken with [`runtime_paths/run.py`](runtime_paths/run.py) (`--runs 7`)
on an Intel i5-13500H under Linux 6.12 at load average 3.2. Each workload is
built by both compilers, both outputs must match byte for byte, and hyperfine
times each pair in one call, warmed up once; the call is repeated in the
opposite order and all fourteen samples are pooled, so load drift affects
before and after alike. "Before" is `a7af3c1` (this branch's parent) built
from source with its own runtime sidecars beside the binary; "after" is the
branch. `runtime/fat.may` hashes `8799f560…` before and `ee937436…` after.

| Workload | Before | After | Peak RSS before → after |
| --- | ---: | ---: | --- |
| `display_list`: `str` of 20 000 Ints | 1 312 ms | 6.5 ms | 288 → 19 MiB |
| `display_map`: `str` of a 15 000-entry map | 1 115 ms | 8.7 ms | 288 → 19 MiB |
| `json_paths`: encode 2 000 Ints, decode 20 kB | 615 ms | 1.5 ms | 240 → 19 MiB |
| `keys_values`: `keys`/`values` × 20 on 50 000 keys | 60.9 ms | 55.2 ms | 50.0 → 50.0 MiB |
| `pad`: `pad_left`/`pad_right` to width 20 000 | 99.3 ms | 1.2 ms | 216 → 19 MiB |
| `parse_int`: `int` of 4 000 digits × 8 | 289 ms | 1.8 ms | 18.5 MiB |
| `sort_ints`: `sort` of 10 000 Ints | 292 ms | 5.1 ms | 18.5 MiB |
| `starts_ends`: 2 000 prefix/suffix tests on 100 kB | 949 ms | 1.4 ms | 18.5 MiB |
| `str_eq`: 600 000 comparisons of 400-char strings | 71.7 ms | 19.3 ms | 18.5 MiB |
| `str_map`: 200 000 inserts + 400 000 lookups | 108 ms | 106 ms | 82.0 MiB |
| `str_reverse`: `reverse` of 20 000 characters | 524 ms | 2.0 ms | 245 → 19 MiB |
| `str_search`: 600 `index_of`/`has` over 200 kB | 175 ms | 174 ms | 18.5 MiB |
| `trim_long`: five `trim`s of a 50 000-character string | 7 032 ms | 2.0 ms | 18.5 MiB |
| `unique_ints`: `unique` of 8 000 Ints | 208 ms | 1.7 ms | 259 → 19 MiB |

The peak-RSS drop is the same effect in each case: the old code held every
intermediate string alive at once — 20 000 list texts for `display_list`, a
growing prefix per element — while the new code drops each part after one
copy. The remaining 19 MiB is the runtime's baseline.

### Growth check

The same program with its size literal doubled twice, timed the same way,
shows the complexity change rather than a constant-factor win. Time is the
median of five runs; "×4" is the time ratio for four times the input.

| Workload | n | Before | After |
| --- | ---: | ---: | ---: |
| `sort` | 10 000 / 20 000 / 40 000 | 270 / 1 060 / 4 102 ms (×15.2) | 5.9 / 6.9 / 15.0 ms (×2.5) |
| `trim` | 20 000 / 40 000 / 80 000 spaces | 1 426 / 5 446 / 21 068 ms (×14.8) | 1.7 / 1.6 / 2.8 ms (×1.7) |
| `display` | 15 000 / 30 000 / 60 000 Ints | 246 / 921 / 3 965 ms (×16.1) | 2.2 / 3.8 / 5.8 ms (×2.6) |
| `json` | 20 000 / 40 000 / 80 000-char string | 545 / 2 138 / 8 568 ms (×15.7) | 1.03 / 1.23 / 1.29 ms (×1.3) |

`sort` now grows like n log n (2.5× for 4× the input); the others are linear.

### The cross-language workloads

The eight roadmap workloads were re-timed on the branch (three runs each,
medians): nothing regressed. `hashmap` 120 → 106 ms and `strings` 56 → 48 ms
gain from `rt_str_eq`; `sieve`, `collatz` and `fib` move within the ±10%
run-to-run spread of this machine (`fib` 63 → 68 ms touches no changed code).
Every workload printed identical output.

## Validation

- `compiler/mayc/tests/runtime_paths.may` is a new feature fixture covering
  display of nested and cyclic collections and of maps across merge widths,
  `sort` (empty, equal keys, strings, Floats, already sorted and reversed
  input), `unique` with mixed types, `trim`/`pad`/`reverse` including UTF-8,
  `int`/`parse_int` including their faults, prefix/suffix tests,
  `index_of`/`substring`/`chars`/`split`/`join`, `keys`/`values` for several
  key types, and JSON reading and writing including escapes, surrogate pairs,
  non-ASCII keys and malformed input. Its expected output is the `a7af3c1`
  run, checked line by line, and the branch reproduces it byte for byte.
- `compiler/mayc/tests/strings.py` now compares `trim`, `reverse`,
  `pad_left`, `pad_right`, `starts_with`, `ends_with`, `index_of` and
  `int`/`parse_int` against Python on the same random Unicode inputs it
  already used for `split`/`chars`/`substring`. The oracle passes on both
  compilers.
- With the rebuilt compiler: `compiler/mayc/tests/verify.py` 130 passed, 0
  failed; `gc_stress.py` all seeds passed; `make check`;
  `make test-bootstrap` (stage 2 = stage 3, the runtime functions the compiler
  itself uses are bootstrapped again).
- Collections during display were exercised directly: 3 000 rounds of `str` of
  a 1 000-element list of maps plus `str` of a 500-entry map (about 300 MB of
  garbage, so the collector runs while element texts are live) prints
  identical output on both compilers and takes 9.4 s against 37.5 s.

## Deliberately left

- **`substring`, `index_of`, `contains`, `split`, `has`** are linear per call.
  Their inner search is a byte-at-a-time scan (O(n·m) for a needle of m bytes);
  a Boyer-Moore-Horspool skip table would allocate 2 KiB per call and lose on
  short needles, so the scan stays. `str_search` measures it unchanged.
- **`string_repr`** has the same concatenate-per-element shape, but nothing in
  the library, tools or tests calls it: `str()` (which goes through
  `rt_display`) is the display path. Left as is rather than changed without a
  caller.
- **`rt_remove`** rehashes the map per removal. It is shadowed by `remove()` in
  `native.may`, which builds a new map, so it is not on the path programs take.
- **`rt_has`** searches a string with `rt_sub_eq` per position; `has()` in
  `native.may` uses `index_of` instead.
- **`keys`/`values`** still allocate the result list (that is their contract);
  the per-entry call to `rt_list_add` was the only avoidable cost, and the
  workload moves from 60.9 to 55.2 ms.
- **Small maps** still hash nothing and scan; **list growth, `join`, `len` of a
  string and `str(Int)`** were done in #97/#99 and were not touched.

## Limits

`rt_display_list` and `rt_display_map` now allocate two or three scratch
blocks per call (element texts, and the map's order and scratch arrays), which
the old version did not. They are freed with the rest of the garbage; the
traffic is O(n) instead of O(n²) bytes copied. The JSON scanner's positions
are byte offsets, which matters only to code calling `jd_*` directly with a
position from elsewhere.
