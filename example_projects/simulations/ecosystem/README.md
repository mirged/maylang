# Artificial Ecosystem

A headless artificial-life experiment written in strict Maylang. Each creature
is an inherited genome, an energy reserve and a tiny neural controller. There
is one creature record: hunters, scavengers and grazers are labels assigned
**after observing what they ate**, never classes, flags or assigned roles.

## Build and run

From the repository root, using the self-hosted compiler:

```sh
make -C example_projects/simulations/ecosystem build
example_projects/simulations/ecosystem/build/ecosystem run --generations 100000 --seed 42 \
  --out example_projects/simulations/ecosystem/results/seed42-100000
```

The output prefix's parent directory must exist. The supplied `results/`
folder is ready for runs. For a quick experiment:

```sh
example_projects/simulations/ecosystem/build/ecosystem demo --out example_projects/simulations/ecosystem/results/demo
```

No arguments print help. `demo` evaluates 1,000 generations; `run` defaults to
100,000. Runs are seeded and deterministic. Resume to a **total generation
target**, preserving the random stream and exact binary64 state:

```sh
example_projects/simulations/ecosystem/build/ecosystem resume \
  example_projects/simulations/ecosystem/results/seed42-100000.checkpoint.json \
  --generations 150000 --out example_projects/simulations/ecosystem/results/continued
```

Resume permits changes to the target, output and reporting/checkpoint intervals.
It preserves the ecological and mutation settings. Extinction stops the run;
there is no automatic reseeding, immigration or fictional completed generations.

The CLI runs batches of at most 512 generations in isolated Maylang worker
processes, preserving exact checkpoints between them. This bounds native heap
usage and avoids a confirmed collector failure under sustained allocation.
Regression tests compare a worker boundary with uninterrupted evolution: the
world, genomes and RNG stream remain identical. A worker failure is reported
and leaves the preceding checkpoint available to resume. Intermediate summaries
have status `paused`; the final summary reports `completed` or `extinct`.
The `.progress` file is a small execution marker, separate from simulation data.

## What a generation means

The default experiment starts with 16 founders on a 6×6 toroidal grid. A
cohort lives for eight ecology steps, then surviving adults fund offspring
and die. Each offspring has its parent's lineage depth plus one. Thus
100,000 generations means **100,000 actual parent-to-offspring replacements**,
not 100,000 world ticks. This discrete life cycle is a simplifying assumption;
there are no overlapping adult generations or sexual recombination.

Adults must retain enough reserve energy to pay for a mutated child's body,
its initial reserve of 3 energy units, and a genome-controlled safety margin.
The neural reproduction output can suppress reproduction. When paid offspring
exceed nursery capacity, uniform reservoir sampling admits at most 16: no
fitness score, sorting by traits or artificial reward determines selection.
Discarded offspring return their energy to carrion. More reproductive parents
supply more candidates, and therefore tend to leave more descendants.

## Genome and neural control

Six continuous genes control mass, metabolic pace, mobility, digestive diet,
armor, and reproductive reserve. Mutation changes physiology and neural
parameters independently. Founders are viable mobile plant feeders with
small bodies, low armor and a bias toward grazing; every trait remains mutable.
There are no seeded hunters. The mutation implementation uses geometric gaps,
which sample independent Bernoulli mutations without scanning every locus.

The neural controller uses the **Maylang ML library**:
`stdlib/ml/fixed.may`, `nn_fixed_model` and `nn_fixed_predict`. It is an
8→3→4 dense network with 43 inherited integer parameters, scale 1024, and
softsign activation `z / (1 + abs(z))`. Network weights are bounded to ±4 in
real units. Fixed-point arithmetic deliberately trades sub-unit precision
for substantially less allocation during millions of decisions; there is no
backpropagation or externally supplied action training.

Sensors observe local plants, carrion, the creature's reserve, plant gradients
in two axes, neighboring creature displacement, and relative body size.
Outputs control movement in two axes, mouth behavior and reproduction.

A negative mouth output grazes plants. A positive output eats local carrion;
if strong enough it also attempts to bite a nearby living creature. Mass and
armor determine damage. Killing transfers prey body and reserve energy through
the attacker's digestive efficiency; any unconsumed energy becomes carrion.
Attack costs energy even when no kill succeeds. Plant efficiency decreases as
the diet gene rises; animal efficiency increases. Hunting must pay for its
costs and offspring through actual intake. It receives no special reward.

## Environment and energy

Plants grow from an external sunlight input, limited by cell fertility and
capacity. A 257-generation seasonal cycle changes sunlight between 0.5 and
1.0. Carrion decays; nutrients improve growth but are not an energy source.
Movement, metabolism, incomplete digestion and carrion decay dissipate energy.
Bodies and newborn reserves are paid for rather than appearing for free.

The ledger checks:

```text
initial energy + sunlight = living reserves + bodies + plants + carrion + heat
```

A small numerical drift is expected after long floating-point accumulation.
All creatures decide from the same positions; movement occurs before feeding.
Turns use a seeded random order, and spatial buckets restrict interactions to
the same cell or four adjacent cells. This avoids quadratic all-pairs scans.

## Results and interpretation

Each run writes:

- `.csv`: sampled adult behavior, traits, population, diversity and energy error.
- `.summary.json`: configuration, cumulative outcomes and sampled cohorts.
- `.genomes.json`: final hereditary parameters and neural network metadata.
- `.checkpoint.json`: exact state at a generation boundary, including RNG state.

Strategies are measured from each adult's lifetime assimilated energy:
more than half from live kills = hunter; more than half from carrion =
scavenger; more than half from plants = grazer; otherwise mixed. Creatures
with no intake are inactive. Victims are included, avoiding a survivor-only
view. Trait diversity is the mean variance of the six physiology genes.
The final newborn population has not yet acted; the last sampled cohort
describes evaluated adults. If extinction happens between samples, this may
precede the extinction generation. CSV samples do not show every intermediate event;
cumulative counters include events between samples.

One seed is an observation of this particular model, not evidence that a
strategy is universal. Predation may emerge, remain rare, or never appear.
Resource supply, density, mutation scale and the inherited controller affect
which strategies can survive. Small populations can lose diversity by drift.

## Architecture

| Module | Responsibility |
| --- | --- |
| `src/model.may` | Typed domain records and physical mappings |
| `src/genome.may` | Founders, mutation, neural decoding and hatching |
| `src/environment.may` | Resource cycles, spatial buckets and corpse accounting |
| `src/controller.may` | Sensing, ML inference and movement |
| `src/ecology.may` | Grazing, scavenging, attacks, digestion and metabolism |
| `src/evolution.may` | Paid reproduction and cohort replacement |
| `src/metrics.may` | Behavior-derived strategy labels and measurements |
| `src/checkpoint_codec.may` | Lossless floating-point JSON codec |
| `src/persistence.may` | Checkpoints, replay and result exports |
| `src/simulation.may` | Generation loop and reporting cadence |
| `runner.may` | Bounded worker execution and validated progress |
| `cli.may` / `main.may` | Validated options and entrypoint |

Domain records, collections, variables and function contracts use explicit
types. `Any` is limited to existing RNG/ML interfaces and JSON/report data.
The simulation itself runs entirely in Maylang. Python is used only for
black-box tests and post-run plots.

## Verify

```sh
make -C example_projects/simulations/ecosystem test
```

Tests compare dense ML inference to its existing batch path, fixed-point
inference to a floating reference, and validate genome isolation, mutation
bounds, toroidal sensing, physical predation, no double harvesting, energy
conservation, funded births, lineage depth, carrying capacity, extinction,
seeded determinism exact checkpoint continuation and identity across process boundaries. Compiler literal-bit
parity and the existing compiler/ML regressions cover the numerical changes
that make the long experiment practical.

## Experiment options

| Option | Default |
| --- | --- |
| `--generations` | 100000 |
| `--seed` | 42 |
| `--population` | 16 nursery slots |
| `--width` | 6 cells per side |
| `--ticks` | 8 per generation |
| `--report` | 1000 generations |
| `--checkpoint` | 10000 generations |
| `--mutation-rate` | 0.04 per locus |
| `--mutation-step` | 0.24 neural units; physiology uses 0.4× this step |

Neural mutation uses integer increments at scale 1024; physiology remains
floating point. A higher mutation step explores larger behavioral changes but
can destroy viable controllers. Changes to density and resources should be
reported alongside outcomes. The checked-in experiment has its exact settings
in the summary and checkpoint, so it can be independently reproduced.
