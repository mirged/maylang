# Maylang roadmap

Current work is tracked in GitHub issues and outcome-based audit milestones.
Priorities describe impact; they do not promise a release date. The
[repository audit](docs/AUDIT.md) records the evidence and local validation behind
this backlog. Completed initiatives remain in [roadmap history](docs/history/ROADMAP_HISTORY.md).

## Focus: Linux x86-64

[Tracking issue #102](https://github.com/mirged/maylang/issues/102) ·
[plan](docs/design/LINUX_X86_64_FOCUS.md)

For now Maylang supports only Linux x86-64. Other targets (ARM64, RISC-V,
macOS, Windows, NodeOS), the core runtime, maybrowser, mayos and `stdlib/ml`
move to `frozen/`, where they are kept but not built, tested or maintained.
The effort goes into speed, correctness, ergonomics, the standard library,
documentation and tools. Issues in frozen areas carry `status:frozen` and are
not scheduled.

## Correctness and bounded resources

[GitHub milestone](https://github.com/mirged/maylang/milestone/1)

Retain the original sustained-GC report [#2](https://github.com/mirged/maylang/issues/2).
Address source-reading/allocation bounds and reproduced workspace/installer failures
before expanding related capabilities.

- [x] [#37: fix(compiler): reject or fully read source files above 1 MiB](https://github.com/mirged/maylang/issues/37)
- [x] [#38: fix(compiler): enforce import expansion buffer capacity](https://github.com/mirged/maylang/issues/38)
- [x] [#39: fix(compiler): bound source arena allocation and handle mmap failure](https://github.com/mirged/maylang/issues/39)
- [x] [#40: fix(may): include declared environment inputs in native cache identity](https://github.com/mirged/maylang/issues/40)
- [x] [#41: fix(may): skip non-executable entries during PATH lookup](https://github.com/mirged/maylang/issues/41)
- [x] [#42: fix(may): bound child shutdown and escalate after SIGTERM](https://github.com/mirged/maylang/issues/42)
- [ ] [#89: fix(runtime): fault on out-of-range Float to Int conversions](https://github.com/mirged/maylang/issues/89)
- [x] [#43: fix(distribution): reject archive links that escape the toolchain bundle](https://github.com/mirged/maylang/issues/43)
- [x] [#44: feat(maybrowser): enforce network and decoded-image resource budgets](https://github.com/mirged/maylang/issues/44)

## Maintainability and contributor confidence

[GitHub milestone](https://github.com/mirged/maylang/milestone/2)

Make internal ownership, native dependencies, licensing and missing integration
coverage explicit. Changes should preserve compiler generation convergence,
existing public tool entry points and self-contained release sidecars.

- [x] [#46: refactor(maybrowser): compile the curl adapter against official headers](https://github.com/mirged/maylang/issues/46)
- [ ] [#47: test(native): run malformed-input adapter tests with sanitizers](https://github.com/mirged/maylang/issues/47)
- [ ] [#48: refactor(native): track shared vendored headers and upstream provenance](https://github.com/mirged/maylang/issues/48)
- [ ] [#49: refactor(compiler): replace ambient frontend globals with typed context](https://github.com/mirged/maylang/issues/49)
- [ ] [#50: refactor(tooling): extract shared filesystem and import helpers from maypkg](https://github.com/mirged/maylang/issues/50)
- [ ] [#51: test(runtime): enforce prelude parity across bootstrap and self-hosted tools](https://github.com/mirged/maylang/issues/51)
- [ ] [#52: test(vscode): cover language server lifecycle and configuration changes](https://github.com/mirged/maylang/issues/52)
- [ ] [#53: test(mayos): exercise deterministic boot and disk persistence in CI](https://github.com/mirged/maylang/issues/53)
- [ ] [#54: docs: clarify repository license scope and third-party notices](https://github.com/mirged/maylang/issues/54)
- [ ] [#57: test(stdlib): add independent numerical oracles for experimental ML APIs](https://github.com/mirged/maylang/issues/57)

## Platform and application evolution

[GitHub milestone](https://github.com/mirged/maylang/milestone/3)

Broader platform work needs a design and acceptance tests before becoming a
supported capability.

- [ ] [#45: feat(maybrowser): keep navigation cancellable during network requests](https://github.com/mirged/maylang/issues/45)
- [ ] [#55: feat(bootstrap): define a roadmap for native ARM64 and desktop compiler hosts](https://github.com/mirged/maylang/issues/55)
- [ ] [#56: feat(may): record native host toolchain identity for reproducible recipes](https://github.com/mirged/maylang/issues/56)

## Performance

[GitHub milestone](https://github.com/mirged/maylang/milestone/4) ·
[tracking issue #101](https://github.com/mirged/maylang/issues/101) ·
[performance roadmap](docs/design/PERFORMANCE_ROADMAP.md)

Make Maylang run like a compiled language: faster than CPython on every
benchmark and close to Java and Node on typed code. Fix runtime algorithms
first, then object layout, type-directed code generation, an IR optimizer and
allocation. Each step needs a measured report and oracle tests.

- [ ] [#97: perf(runtime): Map hashes only Str keys; Int and other keys use a linear scan](https://github.com/mirged/maylang/issues/97)
- [ ] [#99: perf(runtime): lists, strings and join slower than CPython with 4-8x its memory](https://github.com/mirged/maylang/issues/99)
- [ ] [#98: perf(runtime): struct field access is a string-keyed map lookup](https://github.com/mirged/maylang/issues/98)
- [ ] [#96: perf(codegen): register-allocated temporaries for fat x86-64 code](https://github.com/mirged/maylang/issues/96)
- [ ] [#94: refactor(compiler): restore or remove native-word extern calls under fat values](https://github.com/mirged/maylang/issues/94)

## Propose or change priorities

Search open and closed issues, provide source evidence or a minimal reproduction,
and follow [contribution conventions](CONTRIBUTING.md). Use `design:discussion`
for unresolved architecture choices. Update an existing issue when evidence changes
and keep this index synchronized when initiatives close or are superseded.
