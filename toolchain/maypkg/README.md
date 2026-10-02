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
/path/to/maypkg build    # incremental; runs maylang build for you
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
| `maypkg build [--force\|--script]` | incremental build (runs `maylang build`) |
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

`maypkg build` runs `maylang build`, then **writes the lock automatically**, so
the next `build` short-circuits:

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

## Manifest

```json
{
  "name": "hello",
  "version": "0.1.0",
  "entry": "main.may",
  "target": "host",
  "description": "",
  "authors": [],
  "dependencies": {},
  "modules": ["main.may", "util.may"],
  "output": "build/hello"
}
```

`target` is `host`, `linux` or `macos`; `output` is relative to the project
root, so generated executables belong under `build/`.

## Modules

* `fs.may` — path math, `mkdirs` (mkdir -p), `list`, and the stdlib search path.
* `scan.may` — recursive `.may` discovery via `read_dir`.
* `manifest.may` — manifest discovery and `mayproj.json` parsing/defaults.
* `graph.may` — comment/string-aware import scanner, resolution, DFS (topological
  order, missing imports, cycles, brace balance).
* `project.may` — auto-location/discovery, inventory (build vs orphans) and
  incremental state (digests, dirty set, affected set, manifest derivation).
* `checksum.may` — FNV-1a content digests.
* `render.may` — tree, table and Graphviz rendering.
* `commands.may` — subcommands; `main.may` — dispatch.

## Requirements

maypkg uses the native primitives `read_dir`, `mkdir`, `exec`, `wait`, `system`
and `sleep`. `build`/`run`/`dev` call `maylang`, so it must be on `PATH` (or use
`--script` to emit a shell script). `read_dir` uses `getdents64` and is Linux
only; the macOS build of those commands raises an `io` fault.
