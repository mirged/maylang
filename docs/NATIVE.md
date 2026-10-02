# The Native Backend (`may_native`)

Maylang compiles **directly to x86-64 machine code** and emits a freestanding
ELF or Mach-O executable — with **no assembler, linker, libc, dynamic loader or
bytecode interpreter**. Verified on Linux ELF; Mach-O is emitted too but is only
structurally validated on Linux hosts.

```sh
maylang build -o hello examples/hello_native.may
./hello

# cross-emit (no runtime test on a Linux host):
maylang build --target macos -o hello.macho examples/hello_native.may
```

## Pipeline

```
source -> may_parser -> may_ast
                        |
                        v
              may_native::compile
                        |
        +---------------+----------------+
        | x86 encode    | runtime (as m/c)|
        +---------------+----------------+
                        |
                elf::build / macho::build
                        |
                   executable image
```

Everything under `may_native` is hand-rolled:

| File         | Role |
|--------------|------|
| `x86.rs`     | x86-64 instruction encoder (REX/ModRM, labels, fixups) |
| `runtime.rs` | `rt_write` / `rt_print_*` routines as machine code |
| `codegen.rs` | AST → machine code for the supported subset |
| `elf.rs`     | ELF64 `ET_EXEC`, one `PT_LOAD` segment |
| `macho.rs`   | Mach-O 64 `MH_EXECUTE`, `LC_SEGMENT_64` + `LC_MAIN` |

## Value representation

Values are 64-bit tagged words:

| low 3 bits | meaning |
|------------|---------|
| `000` | integer, stored as `n << 3` |
| `001` | pointer to `{ len: u64, bytes }` (string data in the image) |
| `010` | `nil` |
| `011` | `false` |
| `100` | `true` |

The `n << 3` encoding keeps tag bits clear and makes integer `+`, `-` and
signed comparisons work on the tagged words directly. `*`, `/`, `%` shift the
tag out and back. Truthiness is `value - nil > 1` (so `nil` and `false` are
falsy, everything else including tagged `0` is truthy).

Strings and globals live in the same loadable segment as code (the segment is
marked writable so top-level `mut` bindings can be updated). Every string/global
offset is 8-byte aligned so the pointer tag stays valid, and code is padded to
an 8-byte boundary before the data begins.

## Calling convention

System V AMD64: up to six integer arguments in `rdi, rsi, rdx, rcx, r8, r9`,
with the 7th and later passed on the stack; result in `rax`. Functions use a standard frame:

```
push rbp
mov  rbp, rsp
sub  rsp, <frame>      ; 16-byte aligned, patched after body is known
...
mov  rsp, rbp
pop  rbp
ret
```

Local `i` lives at `[rbp - 8*(i+1)]`. Callee-saved registers are never used,
which keeps the runtime routines simple.

## Tail calls

Direct **self** tail calls are optimised: a `return f(...)` or a self-call in a
tail position (including `if`/`unless` branch tails) rebinds the parameters and
jumps to the function entry instead of growing the stack, so tail-recursive
loops run in constant stack space. Non-self and non-tail calls use C-style
calls; `fib(25)` compiles to a direct recursive call tree and runs in about a
millisecond.

## Supported subset

It compiles the whole language:

* literals: integers, floats, booleans, `nil`, string literals and
  interpolation `"n = ${n}"` (desugared to `+`)
* `let`/`mut` locals and top-level globals, compound assignments
* arithmetic `+ - * / % **` over ints and (boxed) floats, comparisons
* dynamic strings: `+` concatenation, `str`/`int`/`float`, indexing, `len`, and
  the prelude's `split`, `trim`, `to_lower`, `to_upper`, `contains`,
  `starts_with`, `ends_with`, `replace`, `index_of`, `chars`, `substring`,
  `repeat`, `join`, `pad_left`, `pad_right`, `split_lines`, the numeric helpers
  (`sqrt`, `floor`, `ceil`, `round`, `abs`, `min`, `max`, `clamp`), plus
  `s.trim()` method syntax
* **lists**: literals, `len`, indexing, index assignment, `for x in xs`,
  `push`, `pop`, `sort`, `reverse`, `sum`, `product`, `count`, `find`, `slice`,
  `enumerate`, `zip`, `flatten`, `unique`, list printing
* **maps**: literals, `m.k` / `m["k"]` / property assignment, `len`,
  `keys`, `values`, `has`, `merge`, `remove`, `get`, and printing
* `has` scans maps by key, lists by value and strings for a substring
* **safe navigation** `a?.b` / `a?.method()` (short-circuits to nil)
* higher-order functions: `map`, `filter`, `reduce`, `any`, `all`, `times`,
  `each` with named functions, lambdas, or **first-class function values**,
  plus comprehensions
* **first-class functions and closures**: named functions, lambdas and nested
  `fun` declarations as values (`let f = add1;`, `let g = |x| x * 2;`),
  passed around and called indirectly (`fn(v)`, `fs[i](x)`). Captured variables
  are boxed into shared heap cells, so mutation is shared between a closure and
  its enclosing scope *and* between sibling closures (e.g. `make_counter`)
* `if`/`else`, `unless`, `while`, `for … in a..b` / `a..=b` (ascending **or
  descending**), `match`
* `chr`, `ord`, `even`, `odd`, `assert_eq`, `range_step`
* **`may { .. } otherwise { .. }`** with a handler stack; `fail(msg)`, type
  faults and division by zero unwind to the innermost handler. `err` is a
  structured object (`err.kind`, `err.message`, `err.stack`), bare `may`
  yields nil, and an uncaught fault prints its message and exits 70
* functions (any arity; 7th+ args on the stack, recursion), `return`,
  `break`, `continue`
* `print(...)`, `read_stdin()`, `input([prompt])`, `args()`, `env(name)`
* `syscall(nr, [args])` — a raw syscall (freestanding FFI); `spawn`/`yield`/`run`
  for cooperative fibers
* **transcendental math** via the x87 unit: `sin`, `cos`, `tan`, `asin`, `acos`,
  `atan`, `atan2`, `sinh`, `cosh`, `tanh`, `ln`, `log2`, `log10`, `exp`,
  `pow`, `hypot`, `cbrt`, `sign`, `round`, `trunc`, `pi`, `e`
* `clock()` (epoch seconds as a float) and `time()` (epoch ms as an int)
* file I/O: `read_file`, `write_file`, `file_exists`, `mkdir`, `read_dir`, `exit`
* subprocesses: `exec(argv)`, `wait(pid)`, `system(command)`, `sleep(ms)`
* the **sovereign trio**: `ptr`, `addr`, `cstr`, `load8/16/32/64`,
  `store8/16/32/64`, variadic `syscall(id, ...)`, `ccall(fn, argv)`,
  `extern_c(fn)` — raw pointers, raw syscalls and C-ABI calls
* JSON: `json_parse`, `json_stringify`
* `??` nil-coalescing, and float `**` float
* a **garbage collector**: see [`GC.md`](GC.md)

Float formatting is shortest-round-trip for plain magnitudes; values outside
`[1e-4, 1e16)` use scientific notation with a 15-significant-digit mantissa.
Remaining limitations: self tail calls are optimised, but there is no general
optimiser pass (constant folding, register allocation, …).

## The native prelude

Every native program is compiled with a prelude written in Maylang
(`crates/may_native/src/native_prelude.may`) on top of a small set of machine
code primitives:

```
str_of  int_to_str  char_at  char_from  str_cmp  cmp  value_eq  value_tag
map_get  map_set  map_keys  map_values  map_has  to_map  read_stdin
len  push  pop  print  raise  clock  time  input  exit
sin  cos  tan  asin  acos  atan  atan2  ln  log2  log10  exp  pow  powf
read_file  write_file  file_exists  mkdir  read_dir  exec  wait  system  sleep
addr  cstr  load8  load16  load32  load64  store8  store16  store32  store64
ccall  extern_c  syscall
```

### Directory and process primitives

* `mkdir(path)` creates a directory (mode `0755`); it raises a catchable `io`
  fault if the path exists or cannot be created.
* `read_dir(path)` returns a list of entry names (excluding `.` and `..`). On
  Linux it uses `getdents64`; the macOS build raises `io` (no equivalent
  syscall is wired up yet).
* `exec(argv)` — `fork` + `execve(argv[0], argv, environment)` — returns the
  child pid (or a negative value on failure). `argv` is a list of strings.
* `wait(pid)` blocks for a child and returns its exit status (`0..=255`).
* `system(command)` runs `command` through `/bin/sh -c` and returns its exit
  status, inheriting this process's environment (captured at `_start`).
* `sleep(ms)` blocks for `ms` milliseconds via `nanosleep`.

Argument vectors are copied into a demand-zero BSS scratch region
(`proc_argv` / `proc_str`) rather than the GC heap, so they never move or get
collected between construction and `execve`.

### Raw pointers, syscalls and the C ABI

* `ptr(n)` is the identity: a pointer is just an `Int` whose numeric value is a
  machine address, so ordinary arithmetic is pointer arithmetic.
* `addr(x)` returns the payload address of a string (`base + 8`), list, map or
  float (`base`), and `0` for immediates. `cstr(s)` copies a string to a fresh,
  NUL-terminated buffer and returns its address.
* `load8/16/32/64(p)` read a raw word (zero-extended) from `p`;
  `store8/16/32/64(p, v)` write `v` untagged. `load64` keeps the low 61 bits
  because values are tagged in the top three.
* `syscall(id, a, b, ...)` is variadic: each argument is untagged and placed in
  the syscall register (`rdi`, `rsi`, …); there is no list wrapper any more.
* `ccall(fn, argv)` calls the address `fn` with the System V C ABI, summing the
  (untagged) elements of `argv` into `rdi`/`rsi`/`rdx`/`rcx`/`r8`/`r9`, and
  returns `rax` as a tagged integer.
* `extern_c(fn)` wraps an address as a first-class value; calling it goes
  through `rt_c_trampoline`, which untags the six argument registers, calls the
  target and tags the result. Up to six integer/pointer arguments; no `xmm`
  float arguments and no stack arguments yet.

This keeps the assembly surface small while making the language feel complete:
`split`, `trim`, `to_lower`, `sort`, `merge`, `keys`, `str`, `int`, the JSON
codec and the higher-level math (`sinh`, `cbrt`, `hypot`, ...) are ordinary
Maylang.

## Heap, lists and maps

Lists and maps are heap objects with a stable header, so `push` grows the
backing array without changing the value seen by other variables:

```
list value = address | 101        header = { len, cap, data }
map  value = address | 111        header = { slots (2*entries), cap, data }
                                  data   = [k0, v0, k1, v1, ...]
```

`rt_push` doubles capacity (starting at 4) and copies when full. Maps use a
flat key/value array and linear key lookup via `rt_value_eq`. Every allocation
carries a 32-byte GC header and is served by a first-fit allocator that splits
and coalesces blocks; the heap is one **demand-zero anonymous `mmap` region**
(1 GiB by default) reserved by `_start`, so only touched pages consume physical
memory and nothing is stored in the executable file. A conservative mark-sweep collector reaches from the stack, registers
and data segment, coalesces free space and rewinds the bump pointer — see
[`GC.md`](GC.md). Running out of heap exits with status 70.

## Fibers

`spawn(f)` maps a 256 KiB stack for `f` (a zero-argument function value), `run()`
drains ready fibers round-robin, and `yield()` switches back to the scheduler.
`fib_switch` saves/restores the callee-saved registers and the stack pointer; a
fresh fiber's stack is seeded so the first switch lands in a trampoline that
calls the function and then returns to the scheduler. A fixed 65-entry table in
BSS holds the scheduler (slot 0) plus fibers. The collector scans each ready
fiber's stack (`[rsp, stack_hi)`) in addition to the running stack, whose upper
bound is tracked in `cur_stack_hi` so collection works on fiber stacks too.

## Multifile builds

`maylang build` resolves `import` statements at build time with the same search
path as the runtime loader, **namespaces every top-level name** per module
(`namespace::name`), then inlines all modules into one program in dependency
order, prepends the native prelude, and hands the merged AST to `may_native`. There is no runtime linker:
the result is a single freestanding executable. See
[`example_projects/apps/textstats`](../example_projects/apps/textstats) for a multi-module example.

## Runtime ABI notes

* **Linux**: `write = 1`, `exit = 60`, `syscall`.
* **macOS**: `write = 0x2000004`, `exit = 0x2000001`, `syscall`; entry via
  `LC_MAIN` (the kernel starts execution at `_start`).
* The ELF has `.text`/`.data`/`.bss` sections plus `.symtab`/`.strtab` (every
  function is a global symbol) and a minimal DWARF v2 `.debug_line` mapping
  code addresses to source lines. `nm` names functions and
  `readelf --debug-dump=decodedline` shows line info; `file` reports it as
  "ELF 64-bit LSB executable, x86-64, statically linked, not stripped". There
  are no `.debug_info` types/locals yet.

## AArch64 scaffold

`crates/may_native/src/aarch64.rs` holds the beginnings of an AArch64 backend:
a MOVZ/MOVK/SVC encoder, an `EM_AARCH64` ELF64 writer and a hand-assembled
`_start` that writes a greeting and exits. `maylang aarch64-hello out` emits it;
`readelf -h` reports `Machine: AArch64`. It is **not** a language backend yet —
the code generator, runtime and GC have not been ported, and it cannot be run
in this environment (no AArch64 host or emulator).

## Freestanding FFI

`syscall(nr, [args])` performs a raw syscall with up to six integer arguments
(x86-64: `rdi,rsi,rdx,r10,r8,r9`; the number in `rax`), returning the tagged
result. This is the escape hatch for OS access without libc; there is no
`dlopen`/dynamic linking.

## Tests

`crates/may_native/src/lib.rs` compiles programs, writes the ELF to a temp file,
executes it and checks stdout (Linux only), and validates the Mach-O magic and
CPU type.
