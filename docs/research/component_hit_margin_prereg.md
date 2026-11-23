# Pre-registration: the member planner's hit margin on the component forecast

Status on the day this was frozen: protocol fixed, no number of the measurement seen. The
record that fulfils it is `docs/research/component_hit_margin.{json,md}`, written by
`scripts/measure_component_hit_margin.py`; its row in the
[measurements index](../measurements_index.md) is the current state. Measurement only,
nothing promoted. Nothing in this document (arms, grid, gate, readings, seasons, budgets)
changes after any number of the measurement is seen.

## The question

The member planning policy (`MEMBER_PLANNING_POLICY` in `src/squadopt/live/transfers.py`,
`member_planning_policy_v2`) plans an extra transfer at 8 points while the game charges 4.
The margin is a caution on projected gains: a transfer is paid for only when the forecast
promises more than twice what the game takes.

The 8 was chosen on [the hit cost grid](../member_policy_hit_cost_grid.md): planning costs 4
to 8 on the lookahead-1 season chain, chips off, five seasons, where 8 beat 4 by +2.44 points
a gameweek [+1.04, +3.94] while paid transfers fell from 193 to 37. That record reads its own
gain as hits not paid on a projection that is optimistic about what a transfer brings, names
8 as the top of the measured grid and asks for a wider range before 8 is read as an interior
optimum. [The transfer discipline reading](../transfer_discipline_note.md) walked the same
chain with chips reserved and found 6 and 8 worse than 4.

Both were walked on the form-window control, because the season chain builds its projection
from that control and takes no other forecast. The squads a member is served are decided on
the Phase C component base, which [its evaluation](../phase_c_component_evaluation.json)
scores 4.62 points a decision ahead of its ridge control over 147 single decisions. A margin
that pays for one forecast's
optimism may be too cautious, or not cautious enough, under another. So the question is: on
the component base, is 8 still the planning cost to hold, and is any margin above the game's
4 supported at all?

## What makes the measurement possible

`supplied_decision_week_v1` (`squadopt.experiments.multi_gw_rehearsal`) lets a season chain
decide on a forecast handed to it for each decision gameweek, in place of the control. The
forecast is taken as it stands: a model that forecasts the gameweek it decides for has read
that gameweek's fixtures, so a double is not scaled a second time, and a team without a
fixture projects zero as under every rule. The rule plans one gameweek and refuses a longer
horizon, because the handoff holds no forecast for a later week.

`squadopt.experiments.component_chain` composes the component base's projection for every
development decision exactly as the component evaluation does: the frozen v1 reader verifies
the handoff, the ridge control folds on the same panel supply the handoff's direct-control
rows, and `prepare_phase_c_component_folds` builds one table a fold. Nothing is fitted.

## Seasons and data

- 2021-22, 2022-23, 2023-24 and 2024-25, from the pinned archive (`data/raw/vaastav-fpl`,
  archive commit `8c97b2adb123863c3dd581e730f1360e89815ac2`), each walked once as a chain
  from its first decision gameweek to its last, state carried, as
  [the season chain](../season_chain.md) does.
- The component forecast is the frozen handoff `phase_c_component_oof_v1` whose table,
  roster and manifest digests `docs/phase_c_component_evaluation.json` names. The runner
  refuses any other.
- 2025-26 is not read. The frozen handoff holds no forecast for it, and the control arm is
  walked on the same four seasons so that the two arms differ in the forecast only. This is
  one season fewer than the hit cost grid, which read 2025-26 as declared development data.
- The free-transfer bank cap is the chain's per-season assumption: 2 in 2021-22, 2022-23 and
  2023-24; 5 in 2024-25 (`MAX_FREE_TRANSFERS` in `squadopt.experiments.season_chain_runs`).

## Planner configuration, every arm

The member planning policy as far as the chain expresses it, with the planning hit cost as
the one thing that varies:

- lookahead 1, no transfer cap (the one-week member plan has none);
- `hit_points_charged` 4.0 on the planner and on the chain's sheet;
- no banked transfer value, `horizon_discount_factor` 1.0;
- chips off (no chip windows, no holding values);
- sell-on fee halved (the game's sell rule);
- pool rule as the committed chains: the top 20 by the arm's own forecast plus the cheapest
  8 per position; the opening squad is the arm's own optimum at its first decision;
- deterministic solver budget 8.0 per solve with the wall clock raised to 60 s so the budget
  binds.

## Arms

Two forecasts by nine planning hit costs, eighteen chains a season and seventy-two in all.

| Arm | Forecast | Projection rule | Planning hit cost |
| --- | --- | --- | --- |
| `component_hit<c>` | Phase C component base | `supplied_decision_week_v1` | 4, 5, 6, 7, 8, 9, 10, 11, 12 |
| `control_hit<c>` | form-window control, window 5 | `naive_calendar_scaling_v1` | 4, 5, 6, 7, 8, 9, 10, 11, 12 |

The component arm is the measurement. The control arm is the reference: it repeats the hit
cost grid on these four seasons and extends it to 12, so that a difference between the two
arms is the forecast's and not the seasons'. Within a forecast every level shares the opening
squad, the pool rule, the sell rule and the scoring, so levels are paired by gameweek. The
two forecasts open with different squads and are never paired with each other.

## Primary comparison

On the component arm, each level other than 8 minus 8: realized points net of charged hits,
paired per gameweek over the four chains. Interval: 90% season-aware moving-block bootstrap
on the per-gameweek paired differences, blocks of four consecutive weeks, 2,000 resamples,
seed 0 (`squadopt.experiments.season_chain_runs.chain_comparison` through
`squadopt.evaluation.statistics.season_aware_moving_block_interval`).

## Secondary comparisons

- On the component arm, each level other than 4 minus 4, the game's charge.
- On the control arm, the same two families, as the reference.
- Per forecast and level: season nets, mean season hit points, paid transfers, the proven
  share of solves, and the mean over decisions of the planner's projected score minus the
  points the week realized on the chain's sheet. That last number is what the grid's note
  called optimism; it is reported for both forecasts and enters no gate.

## Gate

A comparison **passes** if all three hold:

1. its mean paired gain is at least +1.5 points a gameweek;
2. its 90% interval lies above zero;
3. the variant's season net is lower than the baseline's in at most one of the four seasons.

The noise floor is 1.5 points a gameweek: a smaller effect does not pass whatever its
interval.

## Readings

Read once, from the component arm only, in this order.

- **move**: at least one level passes the gate against 8. The candidate is the passing level
  with the highest pooled mean, the one nearer 8 on a tie.
- **confirmed**: no level passes against 8, and 8 passes the gate against 4.
- **unsupported**: neither. No level is shown better than 8, and 8 is not shown better than
  the game's own charge on this forecast.

In every reading the record also names the level with the highest pooled mean against 8 and
says whether it sits on the edge of the grid (4 or 12). An optimum on the edge is not
bracketed, and the record says so in those words. The control arm's readings by the same
rule are reported beside it and decide nothing.

## What each reading licenses

No reading changes `MEMBER_PLANNING_POLICY` or anything else under `live/`, `planning/`,
`optimization/`, `prediction/` or `scenarios/`. **move** licenses a proposal to the owner to
change the planning hit cost to the candidate, as a new policy id. **confirmed** licenses
the sentence that the margin holds on the forecast that decides the served squads.
**unsupported** licenses the record, and the sentence that the margin's evidence is the
control's only.

## What the measurement can and cannot see

Four seasons give about 147 paired gameweeks. On the hit cost grid the standard error of the
8-against-4 difference was 0.85 points a gameweek over 184; over 147 the same spread gives
about 0.95, so a true difference under about two points a gameweek between distant levels
will usually not pass the gate, and neighbouring levels differ by less. The measurement
ranks levels and tests the two ends; it does not certify a value between them.

Not measured: automatic substitutions (the chain's sheet has none, as in every committed
chain); chips; a horizon longer than one week; the Top 100 evidence uplift and the
experimental football model, which the served forecast may add on top of the component base;
price changes inside a gameweek; 2025-26 and the running season.

## Timing pilot

Before this document was committed, one pilot sized the grid: season 2024-25, the first five
decision gameweeks, the component arm, by
`scripts.measure_component_hit_margin --pilot-gameweeks 5`, which writes only under
`artifacts/` and prints seconds, not points. Composing the forecast took about seven
minutes, once a process. Each of the nine levels then took 3.6 to 4.3 seconds a decision and
proved every one of its five solves inside the budget. At that rate a season of 37 decisions
at nine levels is about 22 minutes of single-process work, and the eight processes, run in
parallel on the 32 logical cores of the machine that runs the measurement, are expected to
finish in about half an hour. Nothing in this protocol was set from the pilot.

## Procedure

1. Commit this protocol with the rule, the composer, the runner and their tests.
2. At that clean commit, run one process per season and forecast, eight in all, each to its
   own artifact under `artifacts/component_hit_margin/`, then `--merge` the eight into the
   record. The merge writes the per-week expansion to
   `artifacts/component_hit_margin/weeks.json` and records its sha256; the committed JSON
   holds per-chain totals, the pooled table per level, the paired comparisons with intervals
   and the reading.
3. Commit the record, its Markdown twin, the index row and the link from the research guide.
   If the code changed between the run and the record, the record says exactly what changed
   and why the numbers stand, or the run is repeated.

[Research guide](README.md).
