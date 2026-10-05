# Rust bootstrap

A small source-only stage-zero compiler: **Maylang → GNU C → native executable**.
It reuses the repository's Rust lexer/parser, module resolver and closure analysis;
it has no external Rust dependencies and does not use the Rust native backend or
any prebuilt Maylang compiler. Library helpers come from `mayc/native.may` and
`stdlib/prelude.may`.

Requires Rust, an x86-64 Linux host, and GCC or Clang with GNU C11 support.
`CC` can name an alternative C compiler executable. From the repository root:

```sh
sh toolchain/bootstrap/build.sh
toolchain/mayc/mayc_new examples/hello.may -o /tmp/hello
/tmp/hello
```

This installs a self-hosted native compiler and its runtime sidecars in the
ignored `toolchain/mayc/build/bin/` directory. The `mayc_new` launcher runs this
build automatically if its cached compiler is missing. Run the build script
again after changing compiler source. `CARGO_TARGET_DIR` is respected.

To build the stage-zero compiler and successive stages manually:

```sh
cargo build --offline --locked --release -p may_bootstrap
mkdir -p toolchain/bootstrap/build
target/release/may-bootstrap toolchain/mayc/main.may -o toolchain/bootstrap/build/mayc1
```

Keep runtime sidecars beside the generated compiler:

```sh
ln -sf ../../mayc/runtime.may toolchain/bootstrap/build/runtime.may
ln -sf ../../mayc/native.may toolchain/bootstrap/build/native.may
ln -sfn ../../mayc/runtime toolchain/bootstrap/build/runtime
ln -sf ../../../stdlib/prelude.may toolchain/bootstrap/build/prelude.may
toolchain/bootstrap/build/mayc1 toolchain/mayc/main.may -o toolchain/bootstrap/build/mayc2
toolchain/bootstrap/build/mayc2 examples/hello.may -o /tmp/hello
/tmp/hello
```

To inspect or compile the C separately:

```sh
target/release/may-bootstrap --emit-c examples/hello.may -o /tmp/hello.c
cc -std=gnu11 /tmp/hello.c -lm -o /tmp/hello
```

The CLI accepts one source file, `-o`, `--emit-c`, and `--help`. The default
output drops `.may`; `--emit-c` defaults to a `.c` file. Imports resolve relative
to their owner, with optional `.may` extensions and cycle deduplication.

This bootstrap implements the dynamic subset needed by `mayc`: integers, floats,
byte strings, lists/maps, structs/enums lowered to constructors, functions and
shared captures, branching/loops, interpolation, and `may`/`otherwise`. Type
annotations are parsed and ignored; strict checking happens in the generated
`mayc`. The runtime uses libc and retains allocations until exit. It intentionally
omits GC, optimization, cross compilation, fibers and FFI. Unsupported runtime
primitives report an error when called. Use the self-hosted compiler for normal
Maylang development.

Verify the complete source-only chain (Python 3):

```sh
python3 toolchain/bootstrap/test.py
```

The test builds stage 1 through C, then stages 2 and 3 through the freshly built
compilers, checks strict source and hello output, and requires stages 2 and 3
to be byte-identical. All test executables live in a temporary directory.
The [GitHub workflow](../../.github/workflows/bootstrap.yml) runs this test on
fresh checkouts without a precompiled Maylang compiler.
