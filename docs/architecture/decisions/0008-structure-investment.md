# ADR 0008: Spend the structure budget on repetition and boundaries, not on renames

- **Status:** accepted
- **Date:** 2026-09-15
- **Decider:** Ertuğrul
- **Related:** [ADR 0001](0001-modular-monolith.md), [ADR 0006](0006-backend-hosting.md),
  [dependency rules](../dependency_rules.md)

## Context

The owner decided to invest in structure: more modular folders, more explanatory naming, a
scalable architecture, and dead code removed. He also asked a question that is itself a
finding: what is the difference between `src` and `src/squadopt`?

That question has a one sentence answer. `pyproject.toml` sets `where = ["src"]` and
`include = ["squadopt*"]`, so `src/` is the source root of the standard src layout and
`squadopt` is the only package in it. There is no second thing. A reader having to ask means
the tree does not explain itself, and the answer to that is a paragraph in the README, which
now exists, rather than a refactor.

The rest of the brief was measured before anything was decided, and the measurement changed
the plan.

**Dead code is not the problem.** Zero of 283 modules under `src/squadopt` are unreferenced. A
reachability walk from every non-test entry point, including all 112 scripts, reaches 273 of
them. `ruff` reports zero unused imports, zero unused variables and zero redefinitions across
`src`, `scripts`, `tests` and `web`. One `TODO` marker exists in the tree. What is genuinely
removable is about 250 lines, and one candidate on that list, `integration.py`, turned out not
to be removable at all: it is re-exported from the package root, exercised six times by the only
end-to-end CSV test, and pinned by path and hash in a committed architecture artifact.

**Repetition is the problem.** `scripts/` grew from 27 files to 112 since 2026-08-15 and now
holds **512 distinct twelve-line blocks that appear in more than one file**. The worst pair,
`measure_anchored_calibration.py` and `measure_overlap_calibration.py`, shares 303 of 311
distinct lines.

But a line census is the wrong instrument for deciding what to extract, and this is the sharpest
lesson in this ADR. Comparing the same-named top-level functions by **normalised AST**:

| pair | functions with identical AST |
| --- | --- |
| `measure_anchored_calibration` vs `measure_overlap_calibration` | 3 of 5 |
| `run_player_risk_screening` vs `run_risk_screening` | **0 of 4** |

The second pair shares 164 lines and not one function. Those lines are argparse and report
scaffolding scattered inside functions that do genuinely different things, and extracting them
would put two different measurements behind one signature. **Identical AST is a proof that code
is the same; a shared line count is a hint, and the second pair is exactly how the hint
misleads.**

**The architecture itself is sound.** `lint-imports` analyses 283 files and 1186 dependencies
and reports three contracts kept, zero broken, with zero `ignore_imports` entries. Backend and
frontend are already separated: `web/` and `src/squadopt/`.

**One boundary is real and invisible.** Importing `squadopt.platform.weekly_operations` loads
**169 of the 283 modules**. The split is not arbitrary:

| fully loaded | not loaded at all |
| --- | --- |
| `application` 38/38, `data` 27/27, `live` 15/15, `scenarios` 14/14, `features` 13/13, `optimization` 8/8, `planning` 5/5, `contracts` 3/3 | `experiments` 0/41, `backtest` 0/15, `uncertainty` 0/8, `risk` 0/6, `preflight` 0/5, `recalibration` 0/5, `bayesopt` 0/4, `api` 0/4 |

`prediction` is 16/18 and `evaluation` 12/14. **`platform` is 17 of 38**, and it is the only
package that is genuinely divided, which is precisely the mismatch ADR 0006 describes when it
names four deployment units while the tree keeps the worker and the operator CLI in one package.

That table also settled a question independently: `risk` and `uncertainty` load zero modules in
the weekly run, exactly like the five packages the laboratory contract already named.

## Decision

The structure budget goes to four things, and renaming is not one of them.

1. **State the laboratory boundary while it is free.** Done, and the run closure above is the
   independent confirmation.
2. **Remove repetition where an AST comparison proves it is real**, and nowhere else.
3. **Write the run boundary down as a generated artifact**, so every later structural change is
   self-classifying instead of argued.
4. **Stop shipping bytes for pages no member can reach.**

The two changes that look most like architecture, splitting `platform` along ADR 0006's
deployment units and renaming packages, are deferred on measurement rather than on taste. The
reasons are in "Rejected" below.

## Moves, in order

**M1. The laboratory contract covers `risk` and `uncertainty`.** Landed 2026-09-15. Two entries
in `forbidden_modules` plus the paragraph in the dependency rules. Zero imports changed, three
contracts still kept. Reversible by revert.

**M2. Extract only AST-identical functions from the measurement runners.** `scripts/` only. The
shared body goes into `scripts/_experiment_cli.py`, which already exists and is imported by 74
runners, so this extends an established helper rather than inventing a layer. **No renames and
no deletions**: the measurement register records, for published numbers, the command that
produced them, and a record naming a command stays true only while the command keeps its name.
Every artifact must be byte-identical before and after, and the AST tables go in the PR body.
Reversible by revert.

**M3. Stop preloading the routes a member cannot reach.** The `scores` branch of `manualChunks`
in `web/vite.config.ts` preloads chunks for pages that are not on the member journey. Dropping it
is reported to take initial JavaScript from about 149 kB gzip against a 150 kB budget to about
135 kB. **That figure is not yet independently verified and must be measured in the PR rather
than quoted from here.** Every `lazy()` boundary moves, so the whole Playwright suite is the test
obligation. Reversible by revert.

**M4. Generate the run boundary.** A script that imports `weekly_operations` and prints the
resulting module closure under `src/`, a generated table in the dependency rules, and a test that
fails when a module crosses between tiers. This is the prerequisite for every later structural
change, because it turns "is this on the run path" from an argument into a lookup. The numbers in
the Context section are its first output. Reversible by revert.

**M5. Make the settled record reachable.** `/league` carries the scoreboard and has exactly one
inbound link in the whole application, from `RivalsPage`, which is itself not in the navigation.
On the first Tuesday that settles, the first row of the only instrument that accumulates lands on
a page nothing links to. This one needs an owner decision first, because `web/e2e/quality.spec.ts`
currently **asserts** that a cold visitor sees zero links to `/league`.

**M6. Split `platform` along ADR 0006's units.** Deferred, see below.

## Rejected, with the measurement

**Renaming `application`, `platform`, `data` or `scenarios`.** Their names are the enforced
import-linter layers, so the rename edits the file that proves the architecture, on top of 355,
249, several hundred and 195 import lines respectively, and forces a rewrite of 37 CODEOWNERS
path rules under joint approval. Breadth is a size problem and a rename does not fix size.

**Flattening `src/squadopt` to `squadopt/`.** Nothing to disambiguate, and the layout is pinned in
five places in `pyproject.toml`. The question deserves the README paragraph it now has.

**Mass renaming or restructuring `scripts/`.** 154 script mentions across 71 documentation files,
three hard-coded subprocess strings in `weekly_publish.py`, and a catalogue with one row per
script by filename. One nuance worth recording because it was measured and contradicted a claim:
no document under `docs/` contains the string `measure_anchored_calibration`; the citations are to
the artifact stem, not the script name. The single genuine command-provenance link in the
repository is `docs/route_a_declaration.json`, `"produced_by": "scripts/build_opponent_signal.py"`,
and nothing guards it. The no-rename rule holds either way, and that one link is now known.

**Deleting `integration.py` as dead code.** See Context. If it goes at all, it goes as its own
change with a one-release re-export, not inside a sweep.

**Re-tiering the nineteen layers by theme.** ADR 0001 already measured the alternative: 16
violations across 9 package pairs, against 5 across 3 for the current order.

**Web test and fixture debt.** A twelve-line block census over `web/src` and `web/e2e` found zero
blocks appearing in more than one file. There is nothing there.

**Splitting `platform` now (M6).** The seam is real: 17 of 38 modules load in the weekly run. It
is deferred because 34 of its module paths are pinned by path and SHA-256 in a committed
architecture artifact, its rewrite surface is larger than first estimated, an open draft modifies
two of the modules it would move, and the backend it would separate has never been deployed. A
deployment-shaped split has no operational payoff until there is a deployment. M4 is the
prerequisite that makes it cheap when the time comes.

## Consequences

Most of this tree stays exactly as it is, and that is the finding rather than a failure to act.
The investment goes where a measurement points: 512 duplicated blocks, one invisible boundary,
one preloaded bundle, and one orphaned page.

Every move above is reversible by revert, and none of them touches the weekly run path. That is
deliberate: the publish stage was rewritten and has not yet executed, and structural work waits
behind a run that has proven itself.

The AST criterion generalises beyond `scripts/`. Wherever this repository considers deduplicating
anything, identical AST is the bar, and a shared line count is only a reason to go and look.
