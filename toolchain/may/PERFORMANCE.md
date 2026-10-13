# Cached workspace command performance

Tracked in [issue #31](https://github.com/mirged/maylang/issues/31).

On 2026-10-13, the installed v0.11.1 runner took 5.498 seconds wall and
5.416 seconds user time to run the user's unchanged hello-world workspace.
It reported `cached app (211138e0a995)` before printing the greeting.

Instrumenting workspace loading, input collection, hashing, cache validation
and child launch showed that each command launch spent roughly 0.6 seconds
resolving executables and another 0.4 seconds splitting the inherited
environment. A cached application run launches five commands: two input digest
operations, output verification, executable permission verification, and the
application. Hashing the files themselves took only a few milliseconds.

The native prelude's `split` repeatedly called `substring`, which repeatedly
called `char_at`. Each character access walked UTF-8 from the beginning.
`env` and `chars` had the same repeated scans. Path helpers further amplified
the work by indexing strings and joining character slices. The fix walks byte
offsets and copies fresh result strings, while preserving codepoint indices
for `substring`, Unicode characters for `chars`, and empty fields for `split`.
The C bootstrap supplies the same byte-count prefix at `addr(s) - 8`; its
value representation remains unchanged.

## Measurements

Five samples per command on Linux x86-64 under WSL2, with a 3,364-byte `PATH`
and approximately 6.2 KiB of environment data. The unmodified installed runner
and candidate used the same installed v0.11.1 compiler, environment, workspace
and content-addressed executable. Every measured build/run was a verified
cache hit. Compilation time is excluded. These are local measurements, and
absolute times depend on host load and environment size.

| Command | v0.11.1 median wall | Candidate median wall | Speedup |
| --- | ---: | ---: | ---: |
| `may tasks` | 215.323 ms | 2.154 ms | 100.0× |
| cached `may build` | 4,198.181 ms | 23.843 ms | 176.1× |
| cached `may run` | 6,104.849 ms | 26.626 ms | 229.3× |

The [raw report](tests/performance.json) contains individual samples, CPU time,
host details and runner SHA-256 hashes. Reproduce with:

```sh
toolchain/mayc/mayc_new toolchain/may/main.may -o /tmp/may-candidate
python3 toolchain/may/tests/benchmark.py --binary /tmp/may-candidate \
    --baseline /path/to/v0.11.1/bin/may --compiler /path/to/v0.11.1/bin/mayc \
    --samples 5 --report /tmp/workspace-benchmark.json
```

## Correctness checks

The change retains content-based source/compiler/runtime/dependency digests
and output verification. Workspace regressions change source, imported modules,
compiler bytes and runtime sidecars while preserving size and timestamps;
each change rebuilds. Damaged outputs and lost executable permissions also
rebuild. Dependency pins, failed-build handling, serialized publication and
development reload behavior continue to pass.

String regressions compare deterministic Unicode cases with Python's string
oracle, including NUL, combining characters, multibyte delimiters, empty fields,
fresh copies, 12,000-codepoint inputs and large inherited environment values.
They run on native and LLVM. Rust native tests and the C bootstrap have focused
checks too; source-only compiler generations 2 and 3 remain byte-identical.
