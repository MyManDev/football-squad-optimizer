# Published fixture difficulty live runner

This is #1009 part (b), step 2. Its sole statistical specification is the
protocol in [#1033](https://github.com/MyManDev/football-squad-optimizer/pull/1033).
Preparing synthetic code does not accept an unmerged protocol or authorize its
real reading. The executable verifies #1033's actual merged declaration, its
exact digest and clean committed ancestry before opening any real input.
An amended protocol requires corresponding reviewed runner changes.

## Decisions accepted by the owner on 2026-10-10

The owner accepted the reviewer's recommendations on #1009 on 2026-10-10. The
runner follows #1033's text with them, and its pinned digest is that text's:

- The free squad is solved by the #844 method, as reading 3 of #1033 states it.
- The runner reads the snapshot root and the handoff root the backend served
  from, and passes over and lists every capture without a served handoff.
- Two served captures at the same latest instant make the week missing.
- The paired handoff file is read by the runner itself, and its sha256 and
  pre-deadline modification time are recorded.
- GW20 settlement, and each week's, is read through the two event flags
  `scored_gameweeks` reads.
- The primary interval is `_bootstrap` with `resamples=2000` and `seed=0`.
- The gate reads the pooled figures; the split by handoff version has no verdict.
- The difficulty signal reads each fixture on the club's own side.

`DECLARATION_SHA256` in `scripts/measure_published_difficulty_live.py` is
`0d5178b56be82a8cf0786b11e0404da6e551118f878dc3cce12651899c79c13a`, the sha256
of `docs/research/published_difficulty_live_prereg.md` after CRLF to LF
normalization as #1033 carries it with these decisions (commit 226299a6). This
runner merges after #1033. If #1033's text changes again before it merges, the
runner refuses every real reading until a reviewed update re-pins it.

## The candidate and the free squad

The candidate reuses `apply_adjustment` and `_squad` from
`src/squadopt/experiments/opponent_projection.py`. Its coefficient values and
the development record's file hash after CRLF to LF normalization are fixed.
Nothing is fitted, and no archive is an input.

Each arm's squad, XI and captain come from `optimize_squad`, called through
`_squad`, which prepares the players as the study does. The squad rules are the
study's: budget 1000 tenths, squad 15, XI 11, at most three per club, bench
weight 0.1, expected-points scale 1000, seed 0. The solver runs at
`linearization_level=2` with one search worker, a wall ceiling of 1800 seconds
and a deterministic ceiling of 60 units. An arm whose primary and tie-break are
both proven OPTIMAL at 60 units is decided by that solve. Otherwise it is solved
once more at 240 units, and that solve decides it. A week is missing for the
joint gate when either arm is still not proven at 240 units, or when
`wall_clock_stopped_the_search` holds for any solve of either arm; a clock stop
at 60 units is not solved again. A tie-break counts as proven only when it was
attempted and completed. The study's own call passes no level, so its answers
are unchanged. The record names, for each arm and week, the budget that decided
it and, for each solve, its limits, primary and tie-break status, deterministic
time, whether the clock stopped it, and the squad, XI and captain.

## Inputs and the one reading

The runner reads its roots from `SQUADOPT_BACKEND_SNAPSHOT_ROOT` and
`SQUADOPT_BACKEND_HANDOFF_ROOT`, the two variables the backend serves from, and
the record names both. No command-line argument can stand in for either.
Inventory reads verified bootstrap and fixtures only, and excludes other season
capture names and future capture instants before opening their payloads. The
bootstrap's season is checked before an event-live payload is opened. No actual
inventory or outcome has been read while preparing this draft.

After the first capture whose bootstrap marks GW20 `finished` and
`data_checked`, invoke `python -m scripts.measure_published_difficulty_live`
with `--as-of`, `--output-directory`, `--owner-approved` and
`--weekly-run-idle`, with both served-root variables set. Every instant is UTC.
The output directory must be below this worktree's ignored `artifacts/`.
The executable derives its persistent private claim directory from the Git common
directory, shared by all worktrees; the operator cannot substitute another folder.
Before claiming, it validates every decision capture, paired handoff and projection
join input without opening an outcome. An absent handoff root or no valid paired
week refuses without creating the claim or output. After any outcome reading
begins, retain the claim after refusal or crash; the executable never removes it.
An existing committed verdict record also prevents a second reading.

No real-week comparison is produced before that settled-GW20 condition. The
first such capture is chosen by capture instant then snapshot id, and it
supplies every week's outcomes: a week it does not count in `scored_gameweeks`,
or whose live payload it lacks, is missing. Fixture fields decide no settlement.

For each post-merge deadline through GW20, the decision capture is the latest
capture whose own target is that week and for which `handoff_fingerprint_for`
finds a served baseline handoff in the served handoff root. A capture without
one was never served; it is passed over and listed with the week, scored or
missing. Two served captures at the same latest instant make the week missing.
Once the latest served capture is chosen, a refused paired handoff makes the
week missing; an earlier capture is never chosen instead.

The paired file is the gameweek alias when it matches the capture, else the one
retained copy under `by-capture/<capture>/` that matches it. Its fingerprint
must be the one `handoff_fingerprint_for` returns. Its modification time must
fall before the deadline; a file written at or after it makes the week missing
and never falls back to another copy. The record holds its version, fingerprint,
file sha256, modification time and whether it was the alias. No backend process
is needed.

Captured availability is applied once by production `project`, before the fixed
decision-week adjustment. The difficulty signal is minus the club's mean
captured fixture rating, each fixture read on the club's own side:
`team_h_difficulty` at home and `team_a_difficulty` away. A double averages both
ratings without multiplying the calendar again; a blank leaves the comparator
unchanged. Later-week projections are never adjusted.

Join outcomes by persistent player code, retain observed zero-minute rows and
drop absent players from both arms. Record every eligible week as scored or
missing, with its reason. A week whose settled live payload is refused or
matches no captured player is missing; the settled roster itself is validated
before the claim. The three readings use the same scored weeks with equal
gameweek weights; squared error is primary, and absolute error is diagnostic.
The primary interval is `_bootstrap` with `resamples=2000` and `seed=0` on the
weekly values in ascending gameweek order. The gate reads the pooled figures;
the JSON also reports each handoff version's figures, which carry no verdict.
It holds squad decisions, input identities, fixed constants and the code commit.
Full player evidence stays in private CSV files.

## Details the decisions left open

Where a decision leaves a detail open, the runner takes the most conservative
reading:

- When the alias does not match, two retained copies that both match the
  capture leave the paired file ambiguous, even with one fingerprint, so the
  week is missing.
- The settled GW20 capture supplies every week's outcomes; no other capture is
  searched for a week it lacks. The collector stores every played week's live
  payload in each capture (`live_history_endpoints` in
  `src/squadopt/platform/fpl_capture.py`), so that capture holds them all.
- The served roots come only from the backend's two variables; the command line
  names neither.
- Both arms are solved and recorded even when the first is already unproven.

## What the runner does not do

The command writes no committed result or measurements-index row. Those are
the separate step 3 PR after the single owner-approved reading. A passed
verdict still requires the owner's yes and the separate ship PR. This runner
adds no Friday operation, publication, promoted version or member-page text.
