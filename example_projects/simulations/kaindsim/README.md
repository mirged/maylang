# KaindSim — The river remembers

A canal city caught between an upstream river and a rising tide. Rain falls,
gardens absorb it, canals carry it, and four pump stations compete for a shared
energy budget. Which decision keeps more residents out of the floodwater?

KaindSim runs entirely in strict Maylang, compiled to a native executable with
`mayc` and managed by `maypkg`. It exports a self-contained interactive replay:
scrub the hourly timeline, switch pump policies at the same hour, inspect each
catchment, and compare exposure curves. Open **[demo.html](demo.html)** for the
included 144-hour experiment. The replay works offline without a server.

## Build and try it

From the Maylang repository root:

```sh
make -C example_projects/simulations/kaindsim demo
```

This compiles a local copy of `maypkg`, lets it build and lock the four source
modules using `mayc`, and generates `demo.html`, `demo.json`, and `demo.csv`.
Open `example_projects/simulations/kaindsim/demo.html` in a browser. A ready-built `build/kaindsim`
executable is also present in this workspace.

For your own experiments:

```sh
cd example_projects/simulations/kaindsim
./build/kaindsim compare --steps 240 --seed 7 --budget 40 --out experiment
./build/kaindsim run --policy homes --steps 96 --seed 19 --out homes
./build/kaindsim run --policy canal --steps 96 --seed 19 --out canals
./build/kaindsim help
```

No arguments run the default demo. `demo` and `compare` run all three policies;
`run` selects one with `--policy`. Output defaults to `kaindsim-run`. The output
prefix's parent directory must already exist. Reusing a prefix replaces its
three export files.

| Option | Default | Accepted values |
| --- | --- | --- |
| `--steps` | 144 | 1–360 model hours |
| `--seed` | 42 | 0–2147483645 |
| `--budget` | 24 | 0–96 water units pumped per hour |
| `--policy` | homes | `none`, `homes`, `canal`; used by `run` |
| `--out` | kaindsim-run | File prefix |

## The three policies

| Policy | Decision |
| --- | --- |
| `none` | Leave the pumps off; observe passive drainage and infiltration. |
| `homes` | Prioritise catchment water plus excess depth weighted by residents. |
| `canal` | Prioritise catchment water with an additional preference for canals. |

Every policy sees exactly the same weather draws and starts with a dry city.
The active policies share four fixed stations and the same budget. Each station
can lift water from its own cell or its four immediate neighbours. Pumped water
leaves the city; one water unit costs one energy unit. A dry catchment cannot
spend the budget.

For the included seed-42 experiment, the cumulative exposure index is:

| Pumps off | Protect homes | Clear canals |
| ---: | ---: | ---: |
| 6,138,567 | 2,469,958 | 2,977,593 |

Protecting homes reduces this index by approximately 60% for this experiment.
The replay shows when and where the strategies diverge; a different seed or
budget can change their relative performance.

## How water moves

The city is a fixed 12×8 grid. Two vertical canals and a cross-channel connect
the river inlet to two tidal outlets. Other cells contain homes or rain gardens,
with deterministic elevations and resident counts. There are no wraparound
edges. Depth and elevation are arbitrary integer units.

Each hour advances through these operations:

1. Add seeded rain to every catchment and river water to the northern inlet.
   A 48-hour weather cycle contains a 14-hour storm window.
2. Route water through two transport substeps. Only adjacent cells exchange
   water, driven by differences in elevation plus water depth. Heads are read
   from a shared snapshot; source budgets prevent negative water or spending
   incoming water twice. Traversal alternates each hour to reduce directional bias.
3. Exchange water with a 24-hour triangular tide at the southern canal outlets.
   High tide can push seawater back into the city.
4. Apply the chosen pump policy and shared hourly budget.
5. Infiltrate up to four units in gardens and one in residential catchments.
6. Measure exposure, check conservation, and save a replay frame.

The exact ledger is:

```text
rain + river + sea inflow = water stored + drainage + infiltration + pumping
```

All quantities use integer arithmetic. A nonzero balance error aborts the run.
People are exposed when their home's depth exceeds eight units. The cumulative
exposure index sums `(depth - 8) × residents` over flooded homes and hours.
It measures severity and duration in this model; it is not a monetary damage
estimate. Residents remain in place, with no evacuation, mortality or relocation.

The model simplifies catchments, flow capacity, weather, infiltration and pump
energy. It is a reproducible routing experiment, not a calibrated flood forecast.
Runs are bounded to 360 hours so the full replay stays small.

## Project management and verification

```sh
make build
.tools/maypkg info
.tools/maypkg tree
.tools/maypkg run help
make check
make test
```

`make build` uses `maypkg`'s incremental build and content lock. The Makefile
adds a local compiler symlink to `PATH`, so the selected `MAYC` builds the project
without a global compiler installation. You can override `MAYC` or `MAYPKG`.
The existing `maypkg run` supports positional commands; use the native binary
for experiments with named options.

Tests execute the native program and independently recompute exposure and water
totals from exports. They check seeded identity, policy isolation, matched weather,
zero-budget equivalence, the maximum duration and budget, input validation, and
CSV/JSON/HTML agreement. If Node is available, they also execute the exported
JavaScript with a minimal DOM to check timeline, policy switching, catchment
inspection, playback, and restart handlers. These are functional UI checks;
they do not replace visual inspection in a browser.

| File | Responsibility |
| --- | --- |
| `src/model.may` | Typed city records, terrain, RNG, tide and ledger helpers |
| `src/hydrology.may` | Weather, conservative transport, coast, pumps and simulation |
| `src/view.may` | Terminal map, exports and embedded browser replay |
| `main.may` | CLI parsing, validation and policy comparison |
| `mayproj.json` / `mayproj.lock` | Project metadata and source-content lock |
| `tests/` | Native black-box checks and replay-control checks |

Simulation records and contracts use concrete types. `Any` is confined to
heterogeneous replay/report data and its JSON boundary. Python and JavaScript
are used for tests; the browser JavaScript renders the completed Maylang run.
