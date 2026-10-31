# NodeOS target

`--target x86_64-nodeos` builds programs for [NodeOS](https://github.com/mirged/nodeos),
a capability-based microkernel for x86-64. The full, core and raw runtimes are
all supported, and the compiler itself runs on NodeOS: a `mayc` built for
NodeOS compiles programs there, including its own source. The compiler that
`mayc` builds on NodeOS is byte-identical to the one cross-built on Linux.
As everywhere, programs use fat values
([FAT_VALUES.md](../design/FAT_VALUES.md)). NodeOS's loader copies an image into one contiguous
kernel block of at most 4 MiB, so larger images fail with "Not enough
memory"; `tests/nodeos.py` checks that the compiler's own image fits.

```sh
compiler/mayc/mayc_new --target x86_64-nodeos examples/hello.may -o hello.nxf
compiler/mayc/mayc_new --target x86_64-nodeos compiler/mayc/main.may -o mayc.nxf
```

In a NodeOS checkout, `make maylang` builds the compiler for NodeOS from a
sibling Maylang checkout and puts it on the disk image, and `make test-maylang`
runs it in QEMU. `MAYLANG=/path/to/maylang` selects another checkout.

## What is different about NodeOS

NodeOS is not a Unix. Its kernel has 32 syscalls and no files, terminals or
`fork`. A process starts with one handle, a bootstrap channel in RDI, and
receives everything else as the first message on that channel: its console and
filesystem channels, and its arguments. Reading a file is an `FS_READ` message
to the filesystem service. Memory is a memory object mapped into a window of
the address space. Executables are NXF images, not ELF.

Maylang's runtimes and libraries reach the operating system through Linux
x86-64 syscall numbers (`syscall(2, path, flags, mode)` is `open`), and so does
any program that calls `syscall` itself. The NodeOS target keeps all of that
source unchanged and supplies three pieces:

1. **A syscall gate** (`x86_emit_nodeos_gate` in `src/backend/x86_64.may`).
   Every `syscall` site, including the ones the backend emits for `exit` and
   the core runtime's host primitives, becomes a `call` to the gate. The gate
   preserves everything a `syscall` instruction preserves (all registers but
   RAX, RCX and R11, plus the SSE registers), aligns the stack and calls
   `rt_nodeos_syscall(number, a0, ..., a5)`. Register allocation therefore
   treats the call exactly like the instruction.
2. **A personality** (`runtime/nodeos.may`). It answers the Linux calls in
   the program's own process with NodeOS syscalls and IPC, using only the
   handles the program was given. It is written in the raw subset, like
   `runtime/fat.may`, and is appended to the runtime in every runtime mode; for
   `--raw` programs it is parsed as their runtime. It issues NodeOS syscalls
   through the internal `__nodeos_syscall` builtin, which emits the real
   instruction and is rejected on other targets.
3. **An NXF writer** (`src/formats/nxf.may`). The image uses the ELF writer's
   address layout at `0x400000`, so code and relocations are unchanged; only
   the container differs. It declares the channel, memory and clock
   capabilities as required, files, process creation and loading as optional,
   an 8 MiB stack, and a CRC-32 that NodeOS's loader verifies.

`_start` stores the bootstrap handle for the personality, which receives the
bootstrap message on the first syscall. That is always before the program
runs, because the full runtime's `rt_init` maps the heap through it.

## The personality

| Linux call | NodeOS |
| --- | --- |
| `read`, `write` on 0-2 | `CONSOLE_READ_LINE` and `CONSOLE_WRITE_TEXT` on the console channel. A line holding only Ctrl+D is end of input. Output is also copied to the kernel log as `may: \| <line>`. |
| `open`, `openat`, `read`, `write`, `lseek`, `close` on files | `FS_OPEN`/`FS_CREATE`, `FS_READ`/`FS_WRITE` in 32 KiB requests, `FS_TRUNCATE`, `FS_CLOSE`. Offsets are kept in a 64-entry descriptor table. |
| `open` on a directory, `getdents64` | One `FS_LIST`, kept in a mapped buffer and returned as `linux_dirent64` records. |
| `stat`, `lstat`, `fstat`, `newfstatat`, `access` | `FS_STAT`. Modes are synthesized (`0644`, `0755`); FAT has no owners. |
| `mkdir`, `rmdir`, `unlink`, `rename` | `FS_MKDIR`, `FS_UNLINK`. `rename` copies and unlinks, because the filesystem has no rename; it refuses directories. |
| `getcwd`, `chdir` | A working directory kept in the personality, starting at the environment's `PWD` (the shell's directory) or `/`. Relative paths are resolved against it. |
| `mmap` (anonymous), `munmap` | `memory_allocate` and `memory_map` in the heap window, committed on first touch; `memory_unmap` by base address. |
| `clock_gettime`, `gettimeofday`, `time`, `nanosleep` | The kernel's monotonic clock. NodeOS has no wall clock, so time starts at boot. |
| `exit`, `exit_group` | `process_exit`, after logging `may: exited with N`. |
| `uname` | `NodeOS`. A compiler running on NodeOS uses this to default to `--target x86_64-nodeos`. |
| `readlink("/proc/self/exe")`, `/proc/self/cmdline`, `/proc/self/environ` | The bootstrap arguments, and the environment message a launcher sends when it sets the bootstrap's `ENVIRONMENT` flag (the shell sends its exported variables); without one, `PATH=/bin`, `HOME=/`, `TERM=dumb`. |
| `fork`, `vfork`, `execve` | `ENOSYS`. |
| 1024 (spawn) | A Maylang extension: load an NXF with `process_create`/`process_load`, hand it the console and filesystem, and start it. |
| `wait4` | `wait` for `PROCESS_TERMINATED`, then the exit code from `capability_query`. |

Anything else returns `ENOSYS`, including sockets: NodeOS has no network
service yet, so `import "net"` compiles but its calls fail.

`exec(argv)` and `system(command)` try `fork` first. When it returns `ENOSYS`,
they use the spawn extension instead: `exec` with the argument list, `system`
with the command line split at spaces (there is no `/bin/sh`). A bare program
name runs `/bin/<name>.nxf`, as at the NodeOS shell. Spawned programs share
the parent's console and filesystem and inherit its environment, and `wait`
returns their exit status.

The personality never allocates from the Maylang heap, which is created
through it. Its state lives in one 192 KiB region mapped on first use, and all
its globals start at zero because runtime initializers do not run.

## Compiler hosting

A `mayc` built for NodeOS finds its sidecars as on Linux: next to the
executable, so `/bin/mayc.nxf` uses `/bin/native.may`, `/bin/prelude.may`
and `/bin/runtime/*.may`. The standard library is found by
walking up from the executable, so it lives in `/stdlib`. Output defaults to
`<name>.nxf`, which the shell runs by name. NodeOS's FAT driver reads long
names but creates only 8.3 names, so output names must fit 8.3.

Compiling `hello.may` on NodeOS needs about 100 MiB; compiling the compiler
needs about 400 MiB, so the self-hosting test boots with 1 GiB.

## Limits

- No C externs: NodeOS has no dynamic loader. The compiler rejects them.
- No sockets, signals, `fork` or threads beyond Maylang's cooperative fibers.
- `munmap` of part of a mapping keeps the pages until exit.
- Time is monotonic from boot; there is no real-time clock.

## Tests

- `python3 compiler/mayc/tests/nodeos.py --compiler compiler/mayc/mayc_new`
  (part of `make test-compiler`) checks that full, core and raw images pass
  the loader's structural and CRC-32 checks, the `.nxf` default output, and
  that `__nodeos_syscall` and externs are rejected where they cannot work.
- In a NodeOS checkout, `make test-maylang` boots NodeOS and runs a
  cross-compiled smoke test (files, directories, maps, closures, faults, GC
  pressure, fibers, the clock, environment, `exec` and `wait`), then `mayc`
  compiling and running programs on NodeOS. `make test-maylang-selfhost` also
  rebuilds the compiler on NodeOS and compares it byte for byte with the
  host's.
