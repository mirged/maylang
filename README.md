> [!WARNING]
> **THIS PROJECT WAS WRITTEN MOSTLY BY MULTIPLE LARGE LANGUAGE MODELS (LLMs).**
> Human direction, review, and testing are part of the process, but generated code
> can contain subtle bugs, incorrect assumptions, and optimistic documentation.
> This is an experimental language and toolchain. Read the code, run the tests,
> and bring your curiosity. The robots brought their own confidence.

# Maylang

### A language that compiles itself. Because apparently one compiler wasn't enough.

![Version](https://img.shields.io/badge/mayc-0.8.1%20nightly-8b5cf6)
![Self hosted](https://img.shields.io/badge/self--hosted-Maylang-06b6d4)
![Native output](https://img.shields.io/badge/output-native%20machine%20code-f97316)
![Status](https://img.shields.io/badge/status-experimental-facc15)
![LLM authorship](https://img.shields.io/badge/authorship-mostly%20multiple%20LLMs-f43f5e)

Maylang is a small programming language with a **self-hosted compiler**, strict
checking by default, and direct native executable output. `mayc` emits machine
code and packages ELF, Mach-O, or PE images without an external assembler or
linker. The active compiler and language server are written in Maylang.

Its signature feature is `may { … }`: try something uncertain and provide an
`otherwise { … }` fallback. A language named after a possibility should probably
have a plan B.

```may
fun double(value: Int) -> Int {
    return value * 2;
}

let answer: Int = double(21);
print(answer); // 42. The compiler has read the same books you have.
```

## From clone to native code

**Host requirement: Linux x86-64.** The repository includes one bootstrap
compiler binary so you can start without the archived Rust toolchain.
Python 3 and `readelf` (from binutils) are needed for the verification suite.

```sh
git clone https://github.com/mirged/maylang.git
cd maylang

toolchain/mayc/mayc_new --version
toolchain/mayc/mayc_new examples/hello.may -o /tmp/maylang-hello
/tmp/maylang-hello

toolchain/mayc/mayc_new --check examples/strict.may
```

Expected hello output:

```text
Hello, Maylang!
Hello, world!
```

Build and verify the compiler, including successive self-hosting generations:

```sh
toolchain/mayc/tests/run.sh
```

Keep the compiler with its runtime sidecars. The `mayc_new` launcher wires up
those paths; copying just the underlying executable elsewhere is insufficient.
See the [compiler guide](toolchain/mayc/README.md) for the build pipeline,
runtime selection, benchmarks, and detailed verification commands.

## What's in the language?

- **Strict checking:** typed parameters, inferred local bindings and function
  results, explicit returns, structs, generics, and collection checks.
- **Fault boundaries:** `may`, `otherwise`, structured errors, nil coalescing
  (`??`), and safe navigation (`?.`).
- **Everyday tools:** pattern matching, closures, pipelines, modules, JSON,
  file I/O, and a standard library.
- **Close to the metal:** native code, raw pointers, memory operations,
  syscalls, and C ABI calls in the full runtime.
- **Developer tools:** a Maylang language server, VS Code extension, package
  manager, and an interactive reference site.

Start with the [strict language guide](docs/STRICT.md). The
[historical tour](docs/LEGACY_TOUR.md) preserves older syntax for reference;
use `--legacy` only when intentionally compiling older untyped programs.
The Rust implementation is archived and is not the active toolchain.

## One compiler, several destinations

The compiler itself runs on Linux x86-64. It can emit these targets:

| Target | Executable | Runtime support |
| --- | --- | --- |
| `x86_64-linux` | ELF64 | Full, core, or raw |
| `arm64-linux` | ELF64 | Core or raw |
| `riscv64-linux` | ELF64 | Core or raw (RV64IM) |
| `arm64-macos` | Mach-O | Core or raw; signing required on macOS |
| `x86_64-windows` | PE32+ | Core or raw |

```sh
toolchain/mayc/mayc_new --target arm64-linux examples/hello.may -o /tmp/hello-arm64
```

The full dynamic runtime is Linux x86-64 only. Core programs use a smaller
runtime; closures, maps, floats, exceptions, fibers, and FFI require the full
runtime. Cross-target execution has emulator checks; native macOS and Windows
launches are not yet verified here. See [target details](toolchain/mayc/README.md#cross-compilation).

## Take the scenic route

| Path | What you'll find |
| --- | --- |
| [toolchain/](toolchain/README.md) | `mayc`, language server, package manager, browser experiments, and MayOS |
| [examples/](examples/) | Small programs to read, compile, and tinker with |
| [example_projects/](example_projects/README.md) | Games, apps, simulations, graphics, and storage experiments |
| [stdlib/](stdlib/README.md) | Standard library modules, including ML experiments |
| [docs/](docs/) | Strict syntax, grammar, native internals, GC, and editor docs |
| [editors/vscode/](editors/vscode/README.md) | VS Code integration |
| [guide/](guide/README.md) | Interactive React/Vite language reference |
| [tests/compliance/](tests/compliance/README.md) | Additional runtime and language regressions |
| [toolchain/legacy-rust/](toolchain/legacy-rust/) | The archaeological department |

Try the terminal game:

```sh
toolchain/mayc/mayc_new example_projects/games/starfall/main.may -o /tmp/starfall
/tmp/starfall demo
```

## Experimental means experimental

The full runtime's collector has a documented corruption issue under sustained
allocation workloads. Core allocation retains heap chunks until process exit.
Some features and ABIs have target-specific restrictions. Read the
[compiler limitations](toolchain/mayc/README.md) before relying on a feature.
Performance reports describe particular local workloads, not universal speed
promises. The badges above describe the project; they do not claim passing CI.

Build outputs, dependencies, scratch binaries, and local assistant configuration
are ignored. One Linux x86-64 bootstrap compiler is deliberately versioned at
`toolchain/mayc/build/bin/mayc_new` so a fresh clone can build itself.

## Roadmap

See the [community roadmap](ROADMAP.md) for planned milestones, linked issues,
and how to propose changes to priorities and scope. The plan evolves with
community needs and implementation evidence.

## Contributing

Small reproductions and focused changes are welcome. Include the source that
triggers a bug, the compiler version, the target, and the actual output. For
compiler changes, run `toolchain/mayc/tests/run.sh` and the relevant specialized
checks listed in the compiler guide. Review generated code with the same care
as any other contribution.

The compiler version lives in `MAYC_VERSION` near the top of
[main.may](toolchain/mayc/main.may). Maylang uses immutable `let` bindings for
constants. Update the bootstrap executable and version badge when making a
versioned release.

<details>
<summary>You found the emergency otherwise clause.</summary>

If the compiler becomes self-aware, please ask it to fix the garbage collector
before discussing philosophy.

Achievement unlocked: **read the README all the way down**. No dependencies
were installed to award this achievement.

</details>

<!-- Secret compiler motto: may the source be with you. -->
