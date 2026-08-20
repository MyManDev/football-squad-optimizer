# GW1 run sheet — Friday 2026-08-21

The runbook (`opening_week_runbook.md`) is the authority; this sheet is the *order of
commands for this specific Friday*, written the day before so nothing is improvised at
15:30Z. Deadline **17:30Z**; first kickoff 19:00Z. The tree is frozen (Thu 17:30Z →
Sat 17:30Z), which is fine: everything below *runs* code, none of it changes code.

Current state going in: one stored capture (`fpl-live-20260816T081259Z-e44ade0095e5`,
2026-08-16 — five days stale by Friday, superseded below), ledger empty, release tag
`v2026-27.gw01` on `main`. Run everything from `main` at that tag, per the runbook's
"all green or the live run does not happen from that tree".

## 15:30Z — capture (T−2h)

```console
git checkout v2026-27.gw01
python -m pytest -q          # green, or stop
python -m scripts.capture_deadline_snapshot
```

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
