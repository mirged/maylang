# May workspaces

`may` runs an explicit graph of applications, project tests and native build
recipes. A workspace keeps its declaration in `may.json`, dependency pins in
`may.lock`, and generated files in `.may/`. Builds leave the declaration alone.

```sh
toolchain/mayc/mayc_new toolchain/may/main.may -o /tmp/may
export MAYC="$PWD/toolchain/mayc/mayc_new"
/tmp/may new my-project
cd my-project
/tmp/may run
/tmp/may test
/tmp/may dev
```

Installed bundles place `may` beside `mayc`; compiler and stdlib discovery then
work without an environment override. The current tool host is Linux x86-64.

`may new my-desktop-app --ui` creates a runnable [native UI](../../stdlib/ui/README.md)
application and its explicit native adapter prerequisite. It needs a C compiler,
X11/Xi/Xcursor/OpenGL development libraries, a font and X11/XWayland with
OpenGL 4.3 for interactive Sokol windows.

## Workspace model

```json
{
    "schema": 1,
    "name": "my-project",
    "default": "app",
    "targets": {
        "app": {"kind": "app", "entry": "src/main.may"},
        "tests": {"kind": "test", "root": "tests"}
    },
    "dependencies": {},
    "profiles": {
        "dev": {"flags": ["--debug"]},
        "release": {"flags": []}
    }
}
```

An application names its entry, target architecture and runtime. A test group
discovers `.test.may` files recursively beneath its declared root. Each test is
an executable: zero means success, and compilation errors or nonzero exits fail
the group. A native target declares an argument-array command, inputs, outputs
and prerequisite targets. A task runs an explicit command whenever selected;
reserve it for actions rather than reusable build outputs. Target names use
letters, digits, underscores or hyphens. Unknown fields, missing prerequisites
and dependency cycles fail before commands run.

```json
{
    "generated": {
        "kind": "native",
        "inputs": ["tools/generate.py", "resources"],
        "outputs": ["data.txt"],
        "command": ["python3", "tools/generate.py", "{out}/data.txt"]
    },
    "app": {
        "kind": "app",
        "entry": "src/main.may",
        "depends": ["generated"]
    }
}
```

Commands receive individual arguments, including paths with spaces and quotes.
Placeholders are `{root}`, `{out}`, `{stdlib}`, `{profile}`, `{target:NAME}`
(a prerequisite's artifact directory) and `{dep:NAME}` (a local dependency
root). Native inputs may name files or directories. Outputs are file names
inside the staging directory; `artifact.json` and `output-hashes` are reserved.
Generated native library directories become the application's library path.

## Build behavior

Applications hash their transitive source imports, compiler, known launcher
binary, runtime sidecars, workspace settings, profile and prerequisite keys.
Native recipes hash their declared inputs and command executable. Output bytes
are verified on cache reuse. Each completed artifact has a SHA-256 identity
under `.may/store/`; a build lock serializes publication. Failed builds never
publish an artifact or run an older binary. Changed inputs during compilation
require a retry. Damaged cached artifacts are quarantined before replacement.

Declare every source/header/resource a native recipe reads in `inputs`. System
headers and dynamically linked system libraries belong to the host toolchain;
their installations are not captured by local dependency locks. `may clean`
removes generated artifacts when rebuilding against a changed host environment.

Local dependencies declare `path` and an optional `modules` directory. Their
module roots precede the selected stdlib. `may lock` records their content
hashes; builds reject missing/stale pins until you review changes and relock.
This release supports local dependencies, with no central package registry.

## Commands

- `may tasks`: inspect named targets and prerequisites.
- `may build [TARGET] [--all] [--profile NAME]`: populate verified artifacts.
- `may run [TARGET] -- ARGS`: build prerequisites and run an application.
- `may test [GROUP]`: run all groups or one selected group.
- `may check [TARGET] [--all]`: compiler syntax/type/name checks.
- `may fmt [--check]`: shared CLI/editor formatting for workspace sources.
- `may dev [TARGET] -- ARGS`: watch declared inputs and restart after a complete
  successful build; a failed edit leaves the previous application running.
- `may doctor`: show workspace, compiler, stdlib, profile and compiler version.
- `may lock`: refresh explicitly declared local dependency pins.
- `may clean`: remove `.may/`, preserving source and configuration.
- `may migrate`: create `may.json` from the current directory's `mayproj.json`,
  preserving the original; translate dependency declarations to local paths.

Run from any workspace subdirectory. Use `--profile release` for builds without
the default development traces. `maypkg` remains available for existing
`mayproj.json` projects; new applications use the workspace model.

Validate the workflow with `python3 toolchain/may/tests/run.py`.

## Runner performance

Cached commands still hash input and output bytes. Their overhead should stay
small even with a long `PATH`, Unicode paths and a large inherited environment.
The native prelude scans UTF-8 strings by byte ranges for `split`, `chars` and
`substring`; environment lookup matches complete entries without repeated
codepoint scans. The shared path helpers also avoid building and joining a list
of characters for each path slice.

Measure identical cached artifacts with a fixed compiler and environment:

```sh
python3 toolchain/may/tests/benchmark.py --binary /tmp/may \
    --baseline /path/to/previous/bin/may --compiler /path/to/bin/mayc \
    --samples 5 --report /tmp/workspace-benchmark.json
```

The benchmark checks cache hits, application output and artifact identities,
and reports wall/user/system time without a CI timing gate. See the
[measured performance report](PERFORMANCE.md). The optional GitHub performance
workflow also records measurements for an extracted bundle.
