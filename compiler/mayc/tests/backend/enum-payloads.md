# Enum payload reads by slot — issue #134 step 4

A `match` arm with a variant pattern used to probe the value through
`rt_map_get` once for the tag and once per payload binding, even when the
subject's static type is a known enum: each probe is a runtime call that
searches the map's entries. The record layout already keeps the tag entry at
slot 0 and the payload entries in declaration order, so the pattern's tag proof
gives those entries fixed addresses.

## Changes

**IR** (`src/ir.may`). A variant-pattern arm lowers its tag read and every
payload binding to an `E_GET` carrying the fixed slot and the field name as
interned text: tag slot 0, payload binding `i` slot `i + 1`. The value is read
through the same guarded slot path a struct field read uses. The fallback is
the existing map probe, so an `Any`-typed value, a grown record (entries moved
out of the block), a compacted record, a foreign map and a non-matching value
all behave exactly as before. `Result` patterns keep the runtime probe: `Ok`
and `Err` are ordinary maps built by the prelude, not fixed-layout records.
Everything is skipped under `--no-opt`, where lowering emits the old
`rt_map_get` calls.

Two audit notes scope the fallback list above: strict checking rejects a
variant pattern on an `Any` subject, so the `Any`-value coverage here exercises
the tag-value/legacy path rather than the slot read; and a compacted fixed
record is not reachable from source (`remove` returns a copy), so the
compaction half of the guard is defensive.

**Key objects** (`src/backend/x86_64_fat.may`). The guard compares the slot's
key against the site's key object by pointer, so the match's synthesized field
name has to be the same object the constructor wrote. Synthesized literals
(`E_STRB`, which also carries the tag key, the `ok`/`value`/`error` keys and
the compiler's own messages) are now interned by text the way source string
literals already are (`fat_key_text` shares `fat_key`'s table). Strings are
immutable and equality is by value, so this is not observable; it makes the
per-site field cache and the match guard share one key object per text,
instead of one data object per emitting site.

**IR CSE** (`src/ir_opt.may`). The value-numbering pass names an `E_GET` field
by its source span. The match reads name theirs by interned text, so the pass
uses that text when it is present; otherwise two different payload slots of one
subject could be treated as the same field and merged.

**Backend** (`src/backend/x86_64_fat.may`). `fat_field_get` now takes the key
object and slot directly, so the struct and match paths share
`fat_field_slot_check`: the value must be a map, its entries pointer must be
the block plus 48, and the slot must hold the key object; then the two value
words load from the slot. Otherwise the site runs its field-cache probe and
`rt_field_get`, which has the same result as `rt_map_get` for these reads.

## Behaviour

The slot fast path is only taken while the record is still in its fixed
layout. The key check also makes it correct for a *different* record that
happens to occupy the same slot: if slot `i` holds the key, the value stored
there is that key's value. Grown and compacted records, `Any` values and
foreign maps fail a guard and take the runtime probe; `record_dup_keys.may`
still pins the variant whose payload field is named `tag` and therefore keeps
the map constructor.

`enum_payloads.may` covers typed payload bindings (including a recursive
`Expr` tree), `Any`-typed values, a payload field updated through an `Any`
alias, a grown enum record, a no-payload variant, guarded arms, a wildcard arm,
`Result` patterns with a nested match, and a multi-arm loop over a typed list.
It is pinned in `legacy_behavior.json` and compiled optimized and `--no-opt`
by the oracle test. `backends.py` compiles a two-variant match and requires
objdump to show the tag-slot and payload-slot guards (`entries == p + 48`, the
slot-0 and slot-2 key compares) only in the optimized image.

The compiler's own bootstrap fixpoint passes twice with the change (stage 2 =
stage 3), so the compiler built from a compiler that uses slot reads in its own
`match` still reproduces itself; `gc.py`, `gc_stress.py --self-test`,
`runtime_maps.py`, `verify.py` and the compliance suite pass.

## Measurements

Raw samples: [`enum-payloads-performance.json`](enum-payloads-performance.json),
5 interleaved rounds after a warm-up, medians of user+system CPU time, every
workload's output identical before and after. Before is a compiler built from
the integration base `62c3c45` with its own runtime sidecars
(`artifacts/baseline/enum-134`, compiler sha `5468034f…`); after is the commit
that adds the payload reads (compiler `8bc6975f…`); both embed the same runtime
(`1a4c10aa…`), so the difference is only generated code. The machine was
shared (load average 3.5-5.4 during the runs).

| Workload | Before | After | Change |
| --- | ---: | ---: | ---: |
| `eval_tree`: recursive enum evaluator, depth 10, 20 000 evaluations | 7007 ms | 1369 ms | 5.12x faster |
| `match_loop`: 3-arm matches over a 900-value typed list, 8 000 rounds | 610 ms | 164 ms | 3.71x faster |
| `control`: Int arithmetic loop, no matching | 74.1 ms | 72.7 ms | noise (-2%) |
| `read_local`: struct-field read floor from the struct suite | 3.9 ms | 5.8 ms | startup/layout noise (4-6 ms scale) |

The win is the removed runtime calls: before, every arm test cost one
`rt_map_get` for the tag plus one per binding, each a function call with a map
search; now the tag and payloads are two-instruction loads behind the layout
guard, and only the tag comparison still calls `rt_eq`. Peak RSS is unchanged
on every row (18.8 MiB, the runtime's reservation floor): the values are the
same records, only the read path changed.

Reproduce with:

```sh
python3 compiler/mayc/tests/backend/enum_payloads/run.py \
    /path/to/artifacts/baseline/enum-134/mayc_new compiler/mayc/mayc_new \
    /tmp/enum-payloads.json --rounds 5
```

## Limits

- The tag is still compared by value through `rt_eq`. Comparing the tag object
  by pointer would remove that call too, but a dynamically built tag string
  (legacy mode can match maps built at run time) must keep matching by value,
  so it is left as a follow-up with its own guard design.
- `Result` patterns still use the map probe; `Ok`/`Err` are prelude maps, not
  records.
- The guard keeps the key check; a bare offset read needs the record
  descriptor discussed in [STRUCT_LAYOUT.md](../../../../docs/design/STRUCT_LAYOUT.md).
- Synthesized literals are now shared by text. That shrinks the data section
  slightly and is not otherwise observable.
