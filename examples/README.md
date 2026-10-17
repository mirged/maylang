# Examples

## Single-file examples

Compile any of these with `mayc <file> -o /tmp/example` and run the result.
Start with [hello.may](hello.may) and [strict.may](strict.may); the
[runnable examples](../docs/reference/EXAMPLES.md) page explains more.

| Topic | Files |
| --- | --- |
| Basics | [hello](hello.may), [strict](strict.may), [m_to_km](m_to_km.may), [closures](closures.may), [pipeline](pipeline.may), [features](features.may) |
| Recovery and behavior | [may_otherwise](may_otherwise.may), [ledger](ledger.may), [behavior](behavior.may) |
| Libraries | [stdlib_tour](stdlib_tour.may), [stdlib_expanded](stdlib_expanded.may), [ml_xor](ml_xor.may), [modules/](modules/) |
| Systems | [sovereign](sovereign.may), [network/](network/), [market](market.may) (fibers) |
| Graphics | [game](game.may) (raycaster), [ui_showcase](ui_showcase.may) |
| Compiler fixtures | [mayc_conformance](mayc_conformance.may), [selfhost_test](selfhost_test.may) |

## Projects

Larger applications and experiments are grouped by what they demonstrate.
Multi-file projects keep their entry point and project metadata at the root,
supporting May modules in `src/`, tests in `tests/`, and compiled outputs in
`build/`. Each project documents its own build commands where relevant.

| Group | Projects |
| --- | --- |
| [Apps](apps/) | [Mayboard](apps/mayboard/README.md), [May NES](apps/maynes/README.md), [MayTasks](apps/maytasks/README.md), [TextStats](apps/textstats/README.md) |
| [Games](games/) | [Starfall Salvage](games/starfall/README.md) |
| [Graphics](graphics/) | [SDL test](graphics/sdl_test/) |
| [Learning](learning/) | [Learn](learning/learn/), [Study](learning/study/) |
| [Simulations](simulations/) | [Artificial Ecosystem](simulations/ecosystem/README.md), [KaindSim](simulations/kaindsim/README.md) |
| [Tools](tools/) | [Rivet storage](tools/rivet/README.md) |

Use the compiler from [compiler/](../compiler/README.md) and the `may`
workspace runner from [tools/](../tools/README.md).
