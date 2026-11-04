# MOSAIC trace simulator

Milestone M1 of the [MOSAIC GC roadmap](../../../../docs/design/MOSAIC_GC.md):
record allocation traces of the [GC workloads](../gc_workloads/README.md) and
replay them under grouping policies, to decide whether a cohort collector is
worth building. The result is in [mosaic-m1.md](../backend/mosaic-m1.md).

- [`trace_hooks.may`](trace_hooks.may) — hooks appended to a *copy* of
  `runtime/fat_linux.may`; they wrap `rt_alloc_kind`, `rt_grow_in_place`,
  `rt_gc` and `rt_gc_stats_report` and write binary records to fd 3:
  allocations with a call-stack signature, and at every collection the roots,
  every allocated block with the words the marker would follow, and the
  survivors. The shipped runtime never contains them.
- [`trace.py`](trace.py) — builds a compiler copy with the hooked runtime,
  compiles the workloads with it (reusing `../gc_workloads.py`) and records
  one trace per workload. The checksums of the deterministic workloads are
  checked, so a hook that breaks a program fails the run.
- [`sim.py`](sim.py) — replays a trace under object-level mark-sweep, static
  segment policies (allocation window, allocation site), learned lifetime
  classes with and without fracturing, and an oracle that groups objects by
  their real death collection. It aborts if any policy reclaims an object the
  real collector kept. Its docstring describes the cost model and its known
  optimism and pessimism.

```sh
python3 compiler/mayc/tests/gc_sim/trace.py --out /tmp/traces --only trees
python3 compiler/mayc/tests/gc_sim/sim.py /tmp/traces --json /tmp/trees-sim.json
python3 compiler/mayc/tests/gc_sim/sim.py /tmp/traces --segment 16   # self-check
```

`--segment 16` puts every object in its own segment; every policy must then
reproduce mark-sweep exactly (no dead bytes retained, segment edges equal to
object edges). Traces are large (trees ~0.6 GiB, maylsp ~1 GiB) and a
simulation takes from seconds to a few minutes in plain Python; none of this
runs in CI.

Limits of the instrument:

- Allocation sites come from the stack, not from the compiler: the hook records
  the first 24 return-address-shaped words above it and the simulator rebuilds
  the real call chain (each `call rel32` must target the function containing
  the previous link) and takes the first user-code frame. Signatures that are
  not resolved (stale words, a crowded intern table) count as one unknown site.
  Compiler-emitted site IDs (`--gc-sites`, roadmap M1) would remove this.
- The hooks run just before the real collector at the same stack depth, so
  the collector can keep an object through a stale word they left. The
  simulator adds such objects as roots (at most two per workload).
- A forked child (maylsp's workers) stops tracing; only the parent's heap is
  in the trace.
- Programs with C externs exit through libc and never flush the trace.
