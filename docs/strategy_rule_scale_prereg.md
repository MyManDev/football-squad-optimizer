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
disclosed observations, not a new execution of this proposal.

The question is the weekly differential scale to use in the already declared
`gap_and_weeks_strategy_rule_v1` band. One shared constant is measured on 352490,
the league with captured histories, and used for every listed league. The
measurement does not establish that following a suggested strategy helps.
The three strategies retain `PREREG_OPEN` status.

## Named input and admitted population

The runner takes `--snapshot-root`, a required explicit `--snapshot-id`, `--league`
and `--through-gameweek`. There is no latest-capture default. The primary league
is 352490 in 2026-27. N is the highest gameweek marked both finished and
data_checked in that capture's bootstrap. Every gameweek 1 through N must have
those flags, and this checkpoint requires N at least 6. The declared through-week
is recorded beside N and must describe this admitted checkpoint, rather than
selecting a more favorable subset after a result is seen.

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

1. Control (a): S on GW1 to GW3 must round to 21.2. A mismatch stops the binding
   run; its difference must be explained on #1002 before a step 4 PR opens.
2. Reading (b): S for each single gameweek, with its observed pair count. The
   fifteen-member complete population has 105 unordered pairs per week.
3. Reading (c): S on GW1 to k for every k from 3 through N.
4. Reading (d): for each k, the root mean square over pairs of their cumulative
   k-week differences, divided by `sqrt(k) * S`. Record coverage alongside this
   diagnostic. A cumulative k-week observation needs both members' rows for all
   k weeks; count unavailable cumulative pairs separately, with no zero imputation.
   This reading does not
   change the square-root shape of the strategy rule.
5. Reading (e): if a second listed league has at least six settled weeks in the
   same capture, record its S descriptively. This neither changes the primary
   league nor introduces a per-league constant or a new capture.

Week and prefix readings serialize as lists in numeric gameweek order, including
weeks 10 and 11. Text-key sorting must not reorder them.

## Value and rule-version update

The new constant is S on GW1 to N. If it rounds to 21.2, retain both the value
and `gap_and_weeks_strategy_rule_v1` and update only the provenance comment.
Otherwise use the recorded value and `gap_and_weeks_strategy_rule_v2`.
`BAND_EDGE_DIFFERENTIALS`, `SEASON_FINAL_GAMEWEEK`, the symmetric band and its
square-root scaling stay as declared.

The step 4 provenance names the capture, N, member count, counted/dropped
pair-weeks and result path. Its pin test compares the constant with the committed
JSON. Existing historical records naming 21.2 retain their original meaning.
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
rounded S, control result and companion readings. Outputs contain aggregates only.

Step 4 merges after the GW6 publish and at or after 2026-10-10T10:00:00Z, aiming
for the GW7 publish. After the owner's release approval, the first live publish
with a non-null suggestion must carry the resulting rule id and
`band_edge_points = round(1.0 * S * sqrt(weeks_remaining), 1)`. Until then a league
build test pins that same equality. No release or weekly run is authorized by
this declaration alone.

A follow-up issue covers GW12 and GW19 using this same script and preregistration.
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
