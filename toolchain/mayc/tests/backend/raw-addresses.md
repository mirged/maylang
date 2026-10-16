# Rematerialized x86-64 addresses — issue #76, eighth pass

Raw string literals and literal `addr`/`cstr` results are rematerialized directly
in their consumers' destination registers. Literal `len` becomes a rematerialized
integer. The allocation view excludes metadata-only string operands from those
intrinsics, so an unread string producer no longer consumes a callee-save
register or emits an unused pointer/data copy. Parameter names, preceding local
declarations, globals and source functions continue to shadow builtin names.

Raw results with no readers reserve neither registers nor stack homes. Effectful
instructions still execute, including unused calls, memory loads and divisions
that may trap. This preserves the existing trap regressions and source evaluation
order. Ordinary raw string operands still materialize their actual address;
address operands on the right of arithmetic use the reserved r11 scratch register.

The x86 address encoder also emits zero-extending imm32 loads for ELF data,
tagged data and code addresses. The fixed 4 MiB ELF base and bounded image prove
these fit in 32 bits; patching checks the final relocated value too. Low-register
loads take five bytes and extended-register loads six. Other layouts retain
full-width relocations. Compact code fixups participate in reachability so
closures and function values retain their target bodies.

The motivating raw write now has this setup, with no r12-r15 save/restore or
unused string address in the function:

```asm
mov eax, 1
mov edi, 1
mov esi, 0x403000
mov edx, 14
syscall
```

Regressions check all address flavors and all sixteen destination registers,
including layouts above 4 GiB, literal escapes/lengths, a single data copy,
address arithmetic, builtin shadowing and unused-result allocation. Existing
reachability, native/core cross-target execution, forced GC, signed arithmetic
oracles, traps, workload checksums and bootstrap convergence also pass.

The [50-run pinned report](raw-address-performance.json) compares this pass with
`0563a35` and the original compiler. Static instructions fall from 1,291 to 1,230.
End-to-end medians are 27.532 ms before and 26.737 ms after, with standard
deviations of 0.869 and 0.815 ms. The difference is comparable to the dispersion;
this report does not establish a stable kernel runtime gain for this pass alone.
Original RAW and GCC medians in the same run are 44.083 and 17.905 ms.
All checksums match, and the report retains counters, PMU coverage and hashes.
The separate instrumented-driver memory test was left aside at the user's
request; focused codegen, ABI, GC, reachability, LLVM and bootstrap checks pass.
