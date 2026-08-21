# GW1 run sheet — Friday 2026-08-21

The runbook (`opening_week_runbook.md`) is the authority; this sheet is the *order of
commands for this specific Friday*, written the day before so nothing is improvised at
15:30Z. Deadline **17:30Z**; first kickoff 19:00Z. The live tree is frozen (Thu 17:30Z →
Sat 17:30Z): the operational steps only run that immutable code. Generated public views enter
Git later through separate review branches and never by committing from the detached live tree.

**GW1-only deployment exception:** the approved order below publishes the decision view after
the 17:30Z deadline. From GW2 onward, `deployment_runbook.md` is authoritative: publish the
decision view before the deadline and publish a second settled view after results arrive.

Current state going in: the capture store (`data/snapshots/`) is machine-local and not
tracked by git, so no sheet can enumerate it for every machine — on the morning, run
`python -m scripts.capture_deadline_snapshot --list` on the machine that will run the tick
and treat that output as the authority. On the operating machine it currently shows one
snapshot, `fpl-live-20260816T081259Z-e44ade0095e5` (2026-08-16 — five days stale by Friday,
superseded by the 15:30Z capture below). A 2026-08-20 health-check capture on the data
owner's machine (`fpl-live-20260820T170525Z-545aaf5df705`) confirmed the source responds
and the schema is unchanged; it is not on the operating machine and is not needed there.
Ledger empty. The tick's capture window opens at T−3h (14:30Z; `capture_window_hours = 3.0`
in `live/tick.py`) — 15:30Z below is the chosen time inside that window, not its edge.

**Which tree runs the tick.** The historical release tag `v2026-27.gw01` and the `main` it
sits on predate the unified CLI (`src/squadopt/platform/cli.py` is absent there), so the
`squadopt` command this sheet invokes does not exist in those trees. Do not move that tag and
do not run from it. The Friday-morning release below fixes this properly: a deliberate
develop-to-main release whose main-push CI is green, then the immutable annotated execution
tag `run-2026-27-gw01` on that exact main SHA. Before pushing the tag, verify the tree:

```console
git switch main
git pull --ff-only
git cat-file -e HEAD:src/squadopt/platform/cli.py
git cat-file -e HEAD:scripts/record_preseason_difficulty.py
git tag -a run-2026-27-gw01 -m "Freeze the GW01 operational tree"
git push origin run-2026-27-gw01
```

The tag is created only after the exact `main` push CI is green. **Fallback, stated now
rather than improvised at 15:30Z:** if the tag does not exist when the capture window opens,
run from `develop` at a recorded commit — the runbook's own words are "Every command runs
from the repository root on a clean, tested `develop`", and it is the only other tree that
carries the CLI. Record in the ledger PR which tree ran. What is not allowed is the third
option: silently falling back to the older release tree, which cannot run this sheet at all.

## 15:30Z — capture (T−2h)

```console
git switch --detach run-2026-27-gw01   # fallback: git switch develop && git pull --ff-only
git rev-parse HEAD           # record this; it is the tree the tick ran from
python -m pip install -e .   # the squadopt entry point, without -c constraints.txt
python -m pytest -q          # green, or stop
squadopt --help              # installed unified CLI from this tree, or stop
python -m scripts.capture_deadline_snapshot
```

`constraints.txt` pins the 3.13 measurement environment, so passing it to `pip install` on a
3.11 interpreter fails to resolve. If the entry point cannot be installed for any reason,
`python -m scripts.run_gameweek_ops --phase decide` is the pre-CLI equivalent and exists in
every tree.

Note the printed `snapshot_id`. If the source hiccups, re-capture later — both are kept,
the later one wins by default.

**A2 first drift reading** (one command, the whole measurement):

```console
python -m scripts.record_preseason_difficulty --compare <new-snapshot-id>
```

Expected under H0: `0 of 760 fixture sides changed`. Any other number is the season's
first evidence on the pre-registered thresholds (`preseason_difficulty_prereg.md`) —
record it, do not interpret it beyond the prereg.

## ~15:45Z — decide

```console
squadopt gameweek decide
```

- Exit 1 = nothing was recorded; read the failure, fix the *input* (usually: re-capture),
  never the checks.
- **No `--risk-residuals`** — `not_requested` is the honest GW1 risk state.
- Human read before 17:30Z: the report's prior-dependence statement (high reliance on
  carry-over + opening price prior is *expected* at GW1), and the projection source line
  (`operational_control`; anything else is stop-everything).

## After the deadline (17:30Z+) — site and replay

```console
git fetch origin
git worktree add -b feature/gw01-decision-site ../squadopt-gw01-decision origin/develop
python -m scripts.build_site --out ../squadopt-gw01-decision/web/public
python -m scripts.recommend_current_squad --snapshot-id <id> --output artifacts/live/gw1_replay.txt
git -C ../squadopt-gw01-decision add web/public/data
git -C ../squadopt-gw01-decision commit -m "site: publish the gw01 decision view"
```

The live checkout stays on the recorded execution commit (the tag, or the recorded `develop`
commit under the fallback); do not commit from it. Replay must reproduce the report from that
same commit — one spot-check, then done.
Raw `data/ledger` remains local as required by the opening-week runbook; do not add it to this
branch. Push `feature/gw01-decision-site`, send the generated view through the normal
develop-to-main release path, create the immutable annotated tag
`site-2026-27-gw01-decision`, and manually dispatch the trusted Pages workflow. If automation
is unavailable, use the exact-artifact fallback in `deployment_runbook.md`. Neither the
historical `v2026-27.gw01` tag nor the new execution tag is moved.

The site must not claim crowd-relative
probabilities — the mode selector ships price *tags*, and windowed claims are
diagnostics (`windowed_rank_note.md`).

## Monday-ish — settle (after the gameweek finishes)

```console
python -m scripts.capture_deadline_snapshot   # realized event_points
git fetch origin
git worktree add -b feature/gw01-settled-site ../squadopt-gw01-settled origin/develop
squadopt gameweek settle --gameweek 1
python -m scripts.build_site --out ../squadopt-gw01-settled/web/public
python -c "from pathlib import Path; import shutil; shutil.copy2(Path('docs/season_ledger_2026-27.md'), Path('../squadopt-gw01-settled/docs/season_ledger_2026-27.md'))"
git -C ../squadopt-gw01-settled add docs/season_ledger_2026-27.md web/public/data
git -C ../squadopt-gw01-settled commit -m "site: publish the settled gw01 view"
```

The settle ledger itself remains local in the detached operational checkout; only its generated
summary and published view enter the separate branch. Push that branch through the same
develop-to-main release path, create the new annotated tag `site-2026-27-gw01-settled`,
manually dispatch production, and require all seven smoke checks to pass. Decision and settled
tags identify different immutable commits.

## Do-not list for Friday

- Do not merge anything into `live/`, `optimization/`, `prediction/`, `scenarios/`
  (frozen until Sat 17:30Z). Docs/experiments PRs may merge but not from this checkout.
- Do not "fix" a failing decide check in code on Friday; the tree is the release.
- Do not point risk at the development residual export.
- The generated site-data commit goes through a branch and PR like everything else; the
  execution tags are not moved. Raw ledger entries stay local; only generated public view
  data and the settled season summary enter Git.
