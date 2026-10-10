# Strategy rule scale preregistration proposal

Status: draft awaiting the owner's confirmation on
[issue #1002](https://github.com/MyManDev/football-squad-optimizer/issues/1002).
Written: 2026-10-08, before this task computes any scale beyond GW3.
The six recommended Decision defaults below are proposed for approval. This
document becomes the binding preregistration only after the owner accepts or
amends them on the issue and the declaration PR merges. Merge before
2026-10-12T19:00:00Z, during an idle weekly-operation window.

## Prior observation and question

The issue's 2026-10-07 declaration record reports one reading of the standings
totals, whose widest gap was 111, and a computation on GW1 to GW3 only. That
computation used capture `fpl-live-20261007T105015Z-4e18c56cbb04`, fifteen
members of league 352490 and 315 pair-weeks. Its net-score root mean square
was 21.203, rounding to the existing 21.2. These are the issue's previously
disclosed observations, credited to the issue's record, not a new execution of
this declaration. The author of this document read no capture outcome for any
week this declaration measures, GW1 through N, before writing it.

The question is the weekly differential scale to use in the already declared
`gap_and_weeks_strategy_rule_v1` band. One shared constant is measured on 352490,
the league with captured histories, and used for every listed league. The
measurement does not establish that following a suggested strategy helps.
The three strategies retain `PREREG_OPEN` status.

## Named input and admitted population

The registered runner is `scripts/measure_strategy_rule_scale.py`. It takes
`--snapshot-root`, a required explicit `--snapshot-id`, `--league` and
`--through-gameweek`. There is no latest-capture default. The primary league
is 352490 in 2026-27. N is the highest gameweek marked both finished and
data_checked in that capture's bootstrap. Every gameweek 1 through N must have
those flags, and this checkpoint requires N at least 6. The declared through-week
must equal N, and any other value refuses the run, so no more favorable subset
can be selected after a result is seen. It is recorded beside N.

Membership is every entry in that capture's `league-352490-standings.json`.
Weekly net score is the `points` field minus `transfer_cost` returned by
`fpl_entry_history_points`. A standings member without its history payload, or
a history row without `event_transfers_cost`, refuses the run. A missing weekly
history row drops only the pair-weeks that need that row. Counts of expected,
counted and dropped pair-weeks are recorded. Chip weeks count as scored, as in
the original 21.2 measurement. No entry id, manager name or individual score is
committed.

## Estimator and rounding

For every unordered pair of members i and j and every admitted gameweek t where
both have a row, let `d(i,j,t) = net(i,t) - net(j,t)`. With P counted pair-weeks,

```text
S = sqrt(sum(d(i,j,t)^2) / P)
```

Round S half up to one decimal. This equals the root mean square of the 2P
differences taken with both signs; their mean is zero by construction. Neither a
sample-variance divisor nor a new estimator replaces it. An empty population is
unavailable, never zero.

## Fixed companion readings

All readings come from the same named capture. None changes the update rule.

1. Control (a): S on GW1 to GW3 must round to 21.2. A mismatch does not stop
   the run. The runner still writes the aggregate record with the control
   marked failed, and no step 4 PR opens until the difference is explained on
   #1002. Two details are read conservatively: a control with no counted
   pair-week is unavailable and is marked failed, and the same hold applies to
   the constant PR of any later checkpoint whose control fails.
2. Reading (b): S for each single gameweek, with its observed pair count. The
   fifteen-member complete population has 105 unordered pairs per week.
3. Reading (c): S on GW1 to k for every k from 3 through N.
4. Reading (d): for each k, the root mean square over pairs of their cumulative
   k-week differences, divided by `sqrt(k)` times the unrounded S on GW1 to N.
   Record coverage alongside this diagnostic. A cumulative k-week observation
   needs both members' rows for all k weeks; count unavailable cumulative pairs
   separately, with no zero imputation. This reading does not change the
   square-root shape of the strategy rule.
5. Reading (e): the listed leagues are those in `config/leagues.json` at the
   repository revision the measurement runs from, which the record names. For
   every listed league other than 352490, the record carries either its S,
   computed descriptively by the estimator above on gameweeks 1 through N of the
   same named capture, or a mark that it is unavailable. A secondary league is
   available only when that capture holds its standings and, for every member
   in them, a readable history row carrying `event_transfers_cost` for every
   gameweek 1 through N; requiring a row for every week is the conservative
   reading. Otherwise, including when its standings are absent, it is recorded
   as unavailable with no number. A missing or unavailable secondary league
   never refuses or changes the primary reading. This reading introduces no
   per-league constant and no new capture.

Week and prefix readings serialize as lists in numeric gameweek order, including
weeks 10 and 11. Text-key sorting must not reorder them.

## Value and rule-version update

The new constant is S on GW1 to N, rounded. If it equals the value the constant
holds when the checkpoint runs, retain both that value and the rule id in force
and update only the provenance comment. At GW6 that value is 21.2 and the id is
`gap_and_weeks_strategy_rule_v1`. Otherwise use the recorded rounded S, and the
rule id's version increments by one from the id in force, so a change at GW6
gives `gap_and_weeks_strategy_rule_v2`. The version increments only when the
value changes: at the GW12 and GW19 checkpoints an unchanged value keeps its id,
and a changed value takes the next version after the id in force.
`BAND_EDGE_DIFFERENTIALS`, `SEASON_FINAL_GAMEWEEK`, the symmetric band and its
square-root scaling stay as declared.

The step 4 provenance names the capture, N, member count, counted/dropped
pair-weeks and result path. Its pin test compares the constant with the rounded S
in the committed JSON. Existing historical records naming 21.2 retain their original meaning.
If #983 step 4 has already merged, update its TypeScript value and parity test in
the same PR. #981 step 6 reads the Python rule directly. Post the resulting value,
rule id and merged step 4 PR on #983.

## Execution, records and checkpoints

Nobody computes S beyond GW3 before this declaration merges with its method
accepted. The wired-into-nothing step 2 script uses synthetic FPL-shaped histories
for its tests: hand-computed S, hit subtraction, missing pair-weeks, unchecked-week
refusal, absent transfer-cost refusal, half-up ties and numeric week rendering.

Step 3 reads the first capture marking GW6 finished and data_checked. That capture
is expected from the owner's Tuesday settle on 2026-10-13. The owner performs the
weekly run. The measurement never opens a running run's `run.json`.

The record is `docs/strategy_rule_scale.json` with its Markdown twin at
`docs/strategy_rule_scale.md` and one row in `docs/measurements_index.md`. Record the
named source capture, admitted weeks, member and pair-week counts, unrounded and
rounded S, the control result, passed or failed, and the companion readings. A
failed control is recorded the same way. Outputs contain aggregates only.

Step 4 merges after the GW6 publish and at or after 2026-10-10T10:00:00Z, aiming
for the GW7 publish. A failed control holds it as control (a) states. After the owner's release approval, the first live publish
with a non-null suggestion must carry the resulting rule id and
`band_edge_points = round(1.0 * C * sqrt(weeks_remaining), 1)`, where C is the
rounded S, which `WEEKLY_POINTS_DIFFERENTIAL_POINTS` holds after step 4 whether
it was retained or changed, not the unrounded S. Until then a league build test
pins that same equality. No release or weekly run is authorized by this
declaration alone.

A follow-up issue, #1044, covers GW12 and GW19 using this same script and
preregistration, including the rule-version clause above.
Their readings follow each week's final match, currently scheduled for
2026-11-29T16:30:00Z and 2027-01-03T16:30:00Z respectively. The captured finished
and data_checked flags remain the execution gate if that schedule changes. Once
the TypeScript port exists, later value changes update both languages and parity
in one PR.

## Scope and approval gate

This proposal contains no measured GW4-or-later number, code change, member copy,
TypeScript port, new league capture, per-league/device scale or shape change.
The owner may amend any recommended default on #1002 before merge. Any accepted
amendment must be reflected here before the declaration becomes binding. The
step 1 PR remains draft pending that decision and is not enqueued by this task.
