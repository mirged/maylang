# Maylang Standard Library

The standard library and active self-hosted runtime are written in Maylang.
The source [API inventory](../reference/STDLIB.md) records public signatures and runtime/platform
support; [contracts](CONTRACTS.md) describe mutation, errors, Unicode, numeric
limits and tested edge cases. ML APIs are experimental.

Import a module by name; the loader first looks next to the importing file,
then across the standard-library search path (see below).

```may
import "math.may";
from "algo" import quick_sort, binary_search;

print(gcd(48, 36));            // 12
print(quick_sort([3, 1, 2]));  // [1, 2, 3]
```

## Modules

| Module            | Highlights |
|-------------------|------------|
| `prelude.may`     | `id`, `inc`, `dec`, `truthy`, `default` (auto-loaded) |
| `math.may`        | `gcd`, `lcm`, `is_prime`, `factorial`, `fibonacci`, `average`, `median`, `clamp`, `degrees`, `radians`, `distance`, `is_power_of_two` |
| `string.may`      | `capitalize`, `words`, `lines`, `csv`, `repeat`, `pad_left`, `pad_right`, `starts_with_any`, `count_occurrences`, `truncate`, `is_empty` |
| `collections.may` | `stack_*`, `queue_*`, `set_*` (union/intersect/difference) |
| `algo.may`        | `quick_sort`, `merge_sort`, `binary_search`, `dedupe`, `zip`, `flatten`, `take`, `drop`, `chunk`, `partition`, `group_by`, `count_by` |
| `iter.may`        | `enumerate`, `zip_with`, `find_index`, `take_while`, `drop_while`, `scan`, `windows`, `pairwise`, `*_by`, `cartesian` |
| `functional.may`  | `compose`, `compose3`, `compose_all`, `flip`, `curry`, `uncurry`, `apply_n`, `pipeline`, `memoize`, `partial_first` |
| `stats.may`       | Mean/variance/stddev, quantiles, z-scores, covariance/correlation, linear regression |
| `random.may`      | Seeded Park–Miller generator, integer/uniform/normal draws, choice, shuffle, sample |
| `csv.may`         | Quoted CSV parse/stringify, records from headers |
| `path.may`        | Lexical normalize/join/basename/dirname/extension/relative paths |
| `io.may`          | Safe text, line, JSON, config and CSV file helpers |
| `net.may`         | IPv4 TCP clients/listeners, UDP, timeouts, binary I/O and socket cleanup (Linux x86-64) |
| `validate.may`    | Common predicates and structured field/rule validation |
| `format.may`      | Tables, key-value blocks, durations, byte sizes, percentages, ANSI styling |
| `result.may`      | `ok`, `error`, `is_ok`, `is_err`, `unwrap`, `unwrap_or`, `map_result`, `and_then`, `collect`, `attempt` |
| `test.may`        | `check`, `assert_true`, `assert_equal`, `assert_not_equal`, `assert_contains`, `assert_near`, `test_summary` |
| `ml/`             | Tensors, classical ML, dense neural networks, training, optimizers, data utilities |

## Runtime primitives

These low-level operations are exposed by `toolchain/mayc/runtime.may` and its
native sidecar; higher-level helpers are ordinary library functions:

* **Math**: `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `sinh`,
  `cosh`, `tanh`, `ln`, `log2`, `log10`, `exp`, `sqrt`, `cbrt`, `pow`,
  `hypot`, `round`, `trunc`, `sign`, `abs`, `min`, `max`, `floor`, `ceil`,
  `pi`, `e`.
* **I/O / OS**: `read_file`, `write_file`, `file_exists`, `input`, `clock`,
  `time`, `env`, `exit`.
* **Data**: `json_parse`, `json_stringify`, plus the collection primitives
  (`map`, `filter`, `reduce`, `any`, `all`, `sort`, `reverse`, `sum`, `merge`,
  `remove`, `keys`, `values`, `has`, `len`, `push`, `pop`, `range`).
* **Strings**: the primitive methods `split`, `trim`, `to_upper`, `to_lower`,
  `contains`, `starts_with`, `ends_with`, `replace`, `index_of`, `chars`.

Everything else is ordinary Maylang in this directory.

The [`net` module](../docs/NETWORK.md) uses Linux syscalls directly in Maylang
and supports `mayc`'s full native and `clang-llvm` runtimes. See
[`examples/network`](../examples/network) for a TCP echo client and server.

## Search path

The loader looks for modules in:

1. the directory of the importing file,
2. each directory in `$MAYLANG_STDLIB` (colon-separated) if set,
3. otherwise `./stdlib`, `<exe_dir>/stdlib`, `<exe_dir>/../stdlib`, and
   `~/.maylang/stdlib`.

`prelude.may` is loaded automatically before the entry file; set
`MAYLANG_NO_PRELUDE=1` to skip it.

## Running the tour

```sh
toolchain/mayc/mayc_new examples/stdlib_tour.may -o /tmp/stdlib-tour
/tmp/stdlib-tour
toolchain/mayc/mayc_new examples/stdlib_expanded.may -o /tmp/stdlib-expanded
/tmp/stdlib-expanded
toolchain/mayc/mayc_new examples/ml_xor.may -o /tmp/ml-xor
/tmp/ml-xor
```

The ML toolkit's API and supported model scope are documented in
[`ml/README.md`](ml/README.md).

These examples run in compiler verification. Update API signatures and `///`
comments in the source, regenerate with `python3 reference/generate.py`, and
commit the generated module pages and `reference/inventory.json`. CI checks generation with `--check` and runs
the boundary suite on native and LLVM output.

[Native UI](ui/README.md) provides typed desktop widgets and virtual lists.
The [Mayboard application](../example_projects/apps/mayboard/README.md) demonstrates
real application state, editing, search and persistent storage.
