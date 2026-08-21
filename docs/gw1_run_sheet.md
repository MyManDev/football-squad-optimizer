# GW1 run sheet — Friday 2026-08-21

The runbook (`opening_week_runbook.md`) is the authority; this sheet is the *order of
commands for this specific Friday*, written the day before so nothing is improvised at
15:30Z. Deadline **17:30Z**; first kickoff 19:00Z. The tree is frozen (Thu 17:30Z →
Sat 17:30Z), which is fine: everything below *runs* code, none of it changes code.

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

**Run from `develop`, not from the release tag.** `v2026-27.gw01` and `main` do not contain
`src/squadopt/platform/cli.py`, so the `squadopt` command this sheet invokes below does not
exist in those trees — checking the tag out and then running `squadopt gameweek decide` fails
at the third command. `develop` is the only tree that has it, and the runbook this sheet
defers to says so in as many words: "Every command runs from the repository root on a clean,
tested `develop`." Record the commit before starting and treat it as the release for this
tick, per the runbook's "all green or the live run does not happen from that tree". Neither
`v2026-27.gw01` nor any other tag is moved.

## 15:30Z — capture (T−2h)

```console
git switch develop
git pull --ff-only
git rev-parse HEAD           # record this; it is the tree the tick ran from
python -m pip install -e .   # the squadopt entry point, without -c constraints.txt
python -m pytest -q          # green, or stop
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
python -m scripts.build_site --out web/public
git add data/ledger web/public
git commit -m "live: record the gw01 decision"
python -m scripts.recommend_current_squad --snapshot-id <id> --output artifacts/live/gw1_replay.txt
```

Replay must reproduce the report from the same commit — one spot-check, then done.
Deploy: per Tunay's setup if it landed; otherwise the manual path he documented (CI's
`web/dist` artifact + platform CLI). The site must not claim crowd-relative
probabilities — the mode selector ships price *tags*, and windowed claims are
diagnostics (`windowed_rank_note.md`).

## Monday-ish — settle (after the gameweek finishes)

```console
python -m scripts.capture_deadline_snapshot   # realized event_points
squadopt gameweek settle --gameweek 1
```

## Do-not list for Friday

- Do not merge anything into `live/`, `optimization/`, `prediction/`, `scenarios/`
  (frozen until Sat 17:30Z). Docs/experiments PRs may merge but not from this checkout.
- Do not "fix" a failing decide check in code on Friday; the tree is the release.
- Do not point risk at the development residual export.
- The commit recording the ledger goes to a branch and PR like everything else; the
  release tag itself is not moved.
