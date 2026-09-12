# Development baseline and retained work

Owner-directed workflow, 9 September 2026.

## Branch roles

- `main` is the published release baseline. Repository preparation does not publish a new site.
- `develop` starts from main's complete tracked tree. Subsequent work is recorded there in
  small, topical commits, with appropriate checks before integration.
- Active contributor branches remain independent. Before integrating a branch based on the
  earlier develop tree, review its required unpublished dependencies against the new baseline.
- `archive/pre-main-alignment-20260909` retains the former develop tree and retired topic
  commit tips. Its `docs/archive/BRANCHES.json` maps original names to exact commits.

Branch protection remains in force. When GitHub requires a PR, publish the prepared develop
commits through a temporary integration branch, merge with the required checks, then remove
that temporary branch. This does not require keeping a permanent branch per finished task.

## What alignment means

The baseline alignment commit has the former develop and published main as parents, and its
tree is exactly the published main tree. No force-push or branch-protection change is needed.
Main becomes an ancestor of develop; legacy development ancestry is intentionally retained.
The ahead count can therefore include old commits whose code is already represented by a
squashed release. Check the actual tree diff, not just the history counter.

New organization commits follow the baseline commit. Verify that their diff from main contains
only the intended changes. A future release is a separate reviewed main integration and site
deployment, using the normal immutable artifact/tag verification.

## Recovering an archived topic

Read the manifest on the archive branch, locate the original name and inspect its commit:

```text
git show archive/pre-main-alignment-20260909:docs/archive/BRANCHES.json
git show COMMIT:path/to/file
git switch -c restored/topic COMMIT
```

Recover or port only the needed topic, verify its dependencies, and keep the active contributor's
work intact. Do not merge the aggregate archive commit into develop: its parents preserve
history, not approval of every old implementation.

Dirty and ignored files in old worktrees remain local unless explicitly archived elsewhere.
The saved primary publication snapshot is identified in the archive manifest. Private captures,
ledger, advice records and scratch reports still need their own retention/backup procedure.

## File organization

Use the [documentation index](../README.md) for product, operations and research entry points.
New narrative documentation belongs in the relevant directory. Existing measurement artifacts,
public schemas and embedded source-reference paths move only with a reviewed compatibility plan.
Keep source modules in their established layers until a separately checked boundary extraction.

[Branching background](branching.md) and [PR discipline](pr_discipline.md) retain the required
checks, ownership and live-path safeguards. This workflow changes the development baseline and
branch lifecycle, not the scientific promotion rules or deployed runtime.
