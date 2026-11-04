# Maylang roadmap

Maylang is experimental and not production-ready. Current work is tracked in
GitHub issues; priorities describe impact, not release dates. Completed work is
recorded in the [changelog](CHANGELOG.md).

## Focus: Linux x86-64

[Tracking issue #102](https://github.com/mirged/maylang/issues/102) ·
[plan](docs/design/LINUX_X86_64_FOCUS.md)

For now Maylang supports only Linux x86-64. Other targets (ARM64, RISC-V,
macOS, Windows, NodeOS), the core runtime, maybrowser, mayos and `stdlib/ml`
were removed from `main`; their last versions are in the `frozen-archive` tag.
The effort goes into speed, correctness, ergonomics, the standard library,
documentation and tools. Issues for the removed areas carry `status:frozen` and
are not scheduled.

## Correctness and typing

- [ ] [#140: fix(type-system): Int ** Int with a negative exponent yields a Float typed as Int](https://github.com/mirged/maylang/issues/140)
- [ ] [#139: fix(runtime): MAYC_GC_STATS reporting and GC harness issues on perf/mosaic-m0](https://github.com/mirged/maylang/issues/139)
- [ ] Concrete types instead of `Any` across the standard library, examples,
  tools and compiler, keeping `Any` only at real dynamic boundaries (JSON,
  heterogeneous data, the runtime's two-word calling convention).

## Compiler architecture

- [ ] [#49: refactor(compiler): replace ambient frontend globals with typed context](https://github.com/mirged/maylang/issues/49)
- [ ] [#51: test(runtime): enforce prelude parity across bootstrap and self-hosted tools](https://github.com/mirged/maylang/issues/51)
- [ ] Unified behavior contracts: follow the
  [implementation ledger](docs/design/BEHAVIOR_PROGRESS.md) towards the
  [design](docs/design/UNIFIED_BEHAVIOR.md).

## Performance

[Tracking issue #101](https://github.com/mirged/maylang/issues/101) ·
[performance roadmap](docs/design/PERFORMANCE_ROADMAP.md)

Make Maylang run like a compiled language: faster than CPython on every
benchmark and close to Java and Node on typed code. Each step needs a measured
report and oracle tests.

- [ ] [#131: perf(ir): add the phase 4 IR optimizer passes](https://github.com/mirged/maylang/issues/131)
- [ ] [#135: perf(gc): inline allocation, returned pages and precise stack maps](https://github.com/mirged/maylang/issues/135)
- [ ] [#137: perf(codegen): native regions — compile all-native loops inside fat functions](https://github.com/mirged/maylang/issues/137)
- [ ] [#138: perf(codegen): complete native Float coverage](https://github.com/mirged/maylang/issues/138)

## Tooling

- [ ] [#56: feat(may): record native host toolchain identity for reproducible recipes](https://github.com/mirged/maylang/issues/56)

## Propose or change priorities

Search open and closed issues, provide source evidence or a minimal reproduction,
and follow [contribution conventions](CONTRIBUTING.md). Use `design:discussion`
for unresolved architecture choices. Update an existing issue when evidence changes
and keep this index synchronized when initiatives close or are superseded.
