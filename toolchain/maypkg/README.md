# maypkg — a build manager for Maylang projects

A small Cargo-style tool, written in Maylang itself, built for **development on
the fly**. There is no manifest to write by hand: maypkg finds the entry point,
walks the import graph, scans the tree, classifies local vs stdlib modules, and
can derive `mayproj.json` from what the code actually does. It builds, runs and
watches *by itself* — the runtime gives it `read_dir`, `mkdir` and process
spawning.

The command entry point is `main.may`, implementation modules are under
`src/`, and compiled outputs plus generated scripts live in `build/`.

## Build

```sh
mkdir -p toolchain/maypkg/build
toolchain/mayc/mayc_new toolchain/maypkg/main.may -o toolchain/maypkg/build/maypkg
```

## The fast path

Inside any directory that has a `main.may` (or `app.may`, `src/main.may`, or
any file defining `main`):

```sh
/path/to/maypkg dev      # run, then rerun on every save — no flags
/path/to/maypkg build    # incremental; runs the selected mayc
/path/to/maypkg run      # compile and run the entry
```

`maypkg dev` runs the program, then polls the sources (recursive scan + content
digests) every 400 ms and reruns the instant anything changes. The watch loop is
native Maylang; use `--script` to emit `build/maypkg.dev.sh` instead.

## Commands

| Command | What it does |
|---------|--------------|
| `maypkg new <dir> [name]` | create a project (and its directory) |
| `maypkg init [name] [entry]` | write `mayproj.json` + starter here |
| `maypkg sync` | regenerate `mayproj.json` from the code |
| `maypkg info` | show the detected project |
| `maypkg status` / `st` | sources on disk, orphans, what changed since the lock |
| `maypkg deps` | declared, imported and local modules |
| `maypkg tree` | resolve and print the import tree |
| `maypkg check` | imports, disk scan, orphans, brace balance |
| `maypkg dot` | print the import graph as Graphviz DOT |
| `maypkg lock` / `verify` | content digests for reproducible builds |
| `maypkg build [--force\|--script]` | incremental build with the selected `mayc` |
| `maypkg dev [--script]` | run, then rerun on every save |
| `maypkg run [--script] [args]` | compile and run the entry |
| `maypkg add` / `rm <name>` | manage dependencies |
| `maypkg fmt` | tidy local modules (strip trailing whitespace) |
| `maypkg clean [--dry-run]` | delete generated files and the executable |

Every command auto-detects the project. maypkg searches for a manifest in the
current directory and every ancestor; with none, it searches for a conventional
entry the same way, so it works from anywhere inside a project.

## Automatic detection

* **Entry point** — `$MAYPKG_ENTRY`, then the manifest's `entry`, then the first
  existing conventional file (`main.may`, `app.may`, `src/main.may`,
  `src/app.may`, `<name>.may`), then any source under the root that defines
  `fun main`.
* **Modules** — every file reachable from the entry through `import "…"` and
  `from "…" import …`, resolved exactly like the compiler.
* **Sources on disk** — a recursive `read_dir` walk finds every `.may` file;
  anything the entry does not reach is reported as an **orphan** in `status` and
  `check`.
* **Dependencies** — imports that resolve into the standard library.
* **Manifest** — `sync` (and the first `build`/`dev`/`lock`) writes a
  `mayproj.json` derived from all of the above, preserving hand-written fields.

## Incremental development

`maypkg status` compares every source against `mayproj.lock`:

```
  sources       7 on disk, 6 in the build
  1 orphan module(s) (not imported by the entry):
    scratch.may
  1 module(s) changed since the lock:
    util.may
  affected (to re-check): 2 module(s)
```

`maypkg build` runs the selected `mayc`, then writes the lock and a separate
successful-build state, so the next unchanged `build` short-circuits:

```
up to date - myapp is current (6 modules)
```

`maypkg dev` skips digests as a gate and uses them to watch:

```
  watching for changes; Ctrl-C to stop

hello from demo
  change detected - running
hello from demo
```

Build state includes source and imported-library bytes, compiler path/version
and bytes, runtime/prelude sidecars, manifest settings and output existence.
Writing a lock manually does not mark an old executable current. Failed builds
do not update successful-build state. Successful state is published with a
same-directory atomic rename, so readers see a complete previous or replacement
record even when publication fails. Generated scripts use the same selected
compiler and shell-quote paths and arguments, including spaces and apostrophes.
`dev` watches source, compiler and configuration changes. `run -- --flag value`
passes flag arguments to the application.

## Manifest

```json
{
  "name": "hello",
  "version": "0.1.0",
  "entry": "main.may",
  "target": "host",
  "compiler": "",
  "runtime": "auto",
  "strict": true,
  "flags": [],
  "description": "",
  "authors": [],
  "dependencies": {},
  "modules": ["main.may", "util.may"],
  "output": "build/hello"
}
```

`target` is `host` or a target accepted by `mayc`, such as `x86_64-linux`,
`arm64-linux`, `riscv64-linux`, `arm64-macos`, `x86_64-windows` or `clang-llvm`.
`runtime` is `auto`, `full`, `core` or `none`; `strict` selects strict or legacy
checking. Optional `flags` supports `--time` and `--debug`. Invalid JSON and
invalid configuration fail without replacing the manifest.

Compiler selection is `$MAYC`, manifest `compiler`, an adjacent `mayc`, then
`mayc` on `PATH`. Relative configured paths resolve from the project root.
Library lookup uses `$MAYLANG_STDLIB`, project `stdlib`, then directories beside
and above the selected compiler. `sync` preserves compiler configuration.
`output` is relative to the project root; place it under `build/` when desired.

## Modules

* `fs.may` — path math, `mkdirs` (mkdir -p), `list`, and the stdlib search path.
* `scan.may` — recursive `.may` discovery via `read_dir`.
* `manifest.may` — manifest discovery and `mayproj.json` parsing/defaults.
* `graph.may` — comment/string-aware import scanner, resolution, DFS (topological
  order, missing imports, cycles, brace balance).
* `project.may` — auto-location/discovery, inventory (build vs orphans) and
  incremental state (digests, dirty set, affected set, manifest derivation).
* `checksum.may` — FNV-1a source digests for locks and status.
* `compiler.may` — selection, argument quoting and streamed SHA-256 build identity.
* `render.may` — tree, table and Graphviz rendering.
* `commands.may` — subcommands; `main.may` — dispatch.

## Requirements

Run the isolated workflow suite after building the tool:

```sh
python3 toolchain/maypkg/tests/test_workflows.py --binary toolchain/maypkg/build/maypkg
```

It verifies compiler selection, quoting, source/dependency/configuration changes,
failed-build recovery and atomic state publication. Broader watcher and cleanup
coverage remains tracked in [issue #18](https://github.com/mirged/maylang/issues/18).

maypkg uses the native primitives `read_dir`, `mkdir`, `exec`, `wait`, `system`
and `sleep`. `build`/`run`/`dev` require a usable `mayc`, a POSIX shell and
`sha256sum` (coreutils). The tool currently runs on Linux x86-64 with the full
runtime; cross-target output does not make the project manager portable.
