# GitHub contribution workflow

Issue forms collect reproduction details and acceptance criteria. Maintainers
apply one primary `type:*`, one `priority:*`, affected `area:*` labels and one
current `status:*`. The label catalog in [labels.json](labels.json) mirrors the
repository's established labels plus component areas added by the audit.

Search open and closed issues before creating a report. Reproduced failures
can use `status:confirmed`; source-inspection findings and proposals begin at
`status:needs-triage`. Move status labels as work changes rather than stacking
contradictory states. Do not infer priority solely from an issue's title.

The October audit uses three outcome-based milestones for correctness,
maintainability/coverage, and platform/application evolution, with no due dates.
See the [active roadmap](../ROADMAP.md) and [audit evidence](../docs/AUDIT.md).

Use the PR template, keep work in a topic branch, and report actual checks.
The `repository` job in `bootstrap.yml` runs quick link/reference/distribution
validation independently of the compiler, browser and native-target jobs. Branch workflows cancel
superseded runs; a tagged release reruns `bootstrap.yml` before it publishes.

Maintainers can inspect the live state with:

```sh
gh label list --limit 100
gh issue list --state open --limit 100
gh pr list
gh run list --limit 20
```

Update the catalog deliberately after changing remote labels:

```sh
gh label list --limit 100 --json name,color,description > .github/labels.json
```

Read [CONTRIBUTING.md](../CONTRIBUTING.md) for style, checks and issue conventions.
