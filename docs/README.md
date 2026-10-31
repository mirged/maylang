# Documentation

| I want to… | Start here |
| --- | --- |
| Install a release, upgrade, or configure an editor | [Installation](guide/INSTALL.md) |
| Build and test a checkout | [Development](guide/DEVELOPMENT.md), [contributing](../CONTRIBUTING.md) |
| Understand repository boundaries | [Repository map](REPOSITORY.md) |
| Learn current syntax | [Strict guide](guide/STRICT.md), [grammar](guide/GRAMMAR.md), [examples](reference/EXAMPLES.md) |
| Look up public APIs | [Reference](reference/README.md), [library contracts](../stdlib/CONTRACTS.md) |
| Understand native compilation | [Compiler guide](../compiler/mayc/README.md), [native internals](internals/NATIVE.md) |
| Understand runtime memory | [GC](internals/GC.md), [core memory](../frozen/docs/internals/CORE_MEMORY.md) |
| Stress GC and inspect native codegen | [Limits experiments](../compiler/mayc/tests/limits/README.md) |
| Use networking | [Networking](guide/NETWORK.md) |
| Configure language-server support | [LSP](guide/LSP.md), [server guide](../tools/maylsp/README.md) |
| Review cross-target execution | [Native target tests](../frozen/docs/internals/NATIVE_TARGETS.md) |
| Build for NodeOS or run the compiler there | [NodeOS target](../frozen/docs/internals/NODEOS.md) |
| Make a release | [Releasing](guide/RELEASING.md), [distribution](../dist/README.md) |
| Review findings and priorities | [Audit](AUDIT.md), [roadmap](../ROADMAP.md) |

[Implementation history](history/IMPLEMENTATION.md) and [roadmap history](history/ROADMAP_HISTORY.md)
record earlier work. [Legacy syntax](history/LEGACY_TOUR.md) is historical. Generated
references are updated through their generators; `make check` verifies freshness
and local file links.
