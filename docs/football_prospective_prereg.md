# The football model on live gameweeks: protocol

Status: pre-registered. Written on 2026-09-25. On that date no match of gameweek 6 of 2026-27
had been played: the bootstrap in the newest capture on disk
(`fpl-live-20260922T214539Z-364991a4f832`) puts the gameweek 6 deadline at
2026-10-10T10:00:00Z. No reading under this protocol has been taken. This document changes no
forecast, model, default, copy or live control, and it promotes nothing.

It binds from the moment it merges. If it merges before the gameweek 6 deadline, gameweek 6 is
the first gameweek it scores. If it merges later, the first scored gameweek is the first one
whose deadline falls after the merge. That way a late merge can never admit a week whose
matches could already have been seen.

## Why this is written

Members can choose `football_team_share_v1` instead of the current model for their advice
(`live-football-model.md`). It was offered on development evidence: at weekly free squad
selection, over 56 weeks of 2024-25 and 2025-26, it scored 4.9821 points a week more than the
component control (`research/football_candidate_results.md`). That record describes itself
as reused development data and not independent evidence. The member page says that live
superiority is unverified. The only thing that can change that sentence is a comparison on
live gameweeks whose outcomes nobody had read for it, scored by a rule fixed before them.
This document is that rule. A live gameweek read without it is evidence spent.

## What has already been read

- **2024-25 and 2025-26** are the development seasons of the candidate
  (`research/football_candidate_results.md`), of the contextual candidate
  (`research/football_contextual_development.md`) and of the component study
  (`research/football_component_ablation.md`). They are reused and are not read here.
- **2026-27 gameweeks 1 to 5** were read by the 22 September component study. Its outer
  evaluation includes the completed gameweeks 1 to 5 of 2026-27 and reports the v1 point
  error on them (`research/football_component_ablation.md`). Those five weeks are spent for
  this question and are not scored here.
- **Gameweek 6 onwards**: no match played.

`measurements_index.md` has one football row, the development record. Nothing in it compares
the football model with the current one on live gameweeks.

## What is on disk, as of 2026-09-25

From `artifacts/football/` and `data/handoffs/by-capture/` on the operator machine, and the
deadlines in the bootstrap of the newest capture:

| Gameweek | Deadline | `football_team_share_v1` artifacts | Current handoff for the same captures | Outcome |
| --- | --- | --- | --- | --- |
| 5 | 2026-09-18T17:30:00Z | one, for `fpl-live-20260918T122516Z-cd5c04029774`, file written 2026-09-21T16:48Z, after the deadline | `phase_c_control_components_v1` | settled, and already read (above) |
| 6 | 2026-10-10T10:00:00Z | two, for `fpl-live-20260922T195839Z-3b81864cd038` and `fpl-live-20260922T214539Z-364991a4f832`, both written on 2026-09-22 | `phase_c_control_components_v1` for both | not played |

The member option was released on 2026-09-21 (#763, #764), after the gameweek 5 deadline.
Gameweek 6 is therefore the first week in which a member could choose it before entries
locked.

## Which capture a gameweek is scored from

The scored capture is the last `fpl-live` capture whose capture instant precedes the
gameweek's deadline. When entries lock, that is the capture the backend answers from
(`latest_snapshot_id` in `src/squadopt/platform/capture_context.py`). Both arms are read for
that capture and no other. If it has no usable football artifact, the football option was not
on offer when entries locked, and the week is missing (see below). An earlier capture's
artifact is never used in its place.

## The two arms

- **Football.** The `football_team_share_v1` artifact for the scored capture, as
  `scripts/build_football_forecast.py` writes it without `--contextual`. It is read by
  `read_football_forecast` (`src/squadopt/live/football_artifact.py`), which applies the
  capture's availability. The first week of that forecast is the decided forecast. Top 100
  weight is zero and the manager's word is off. The arm includes v1's known limit: its goal and
  assist shares are split before availability is applied, so what availability removes from an
  absent player is not passed to his teammates (#829 states this in `live-football-model.md`).
  It is measured as it is served.
- **Current.** The projection handoff the backend pairs with the same capture
  (`load_capture_identity` in `src/squadopt/platform/capture_context.py`). It is projected
  with `project` (`src/squadopt/live/recommendation.py`), which applies the same capture's
  availability, as the backend serves `model=current`. On 2026-09-25 that handoff is
  `phase_c_control_components_v1`. If a later week's handoff is another version, that week is
  scored with it, because it is what a member choosing `current` was given. The record names
  every week's version and reports each version's weeks separately beside the pooled figure.

The football arm is `football_team_share_v1` and nothing else. The contextual version, and any
later version (a fix to the share limit would be one), is a new candidate and needs its own
protocol. A change to the v1 producer that moves its forecasts without a new version name
breaks this protocol; if such a change is found, the record names it.

## Reading one, the verdict: the squad each forecast picks

This is the contrast the development record measured, one freely selected squad per arm per
week, so its 4.9821 has a live counterpart.

**Unit.** One gameweek. For each arm, `optimize_squad` (`src/squadopt/optimization/optimizer.py`)
picks fifteen players, the eleven, the bench and the captain from the scored capture's whole
roster at its captured prices. The budget is 100.0 (`budget_tenths=1000`), the squad rules
are the `OptimizationConfig` defaults, and the objective is that arm's decided forecast. The
solver settings follow the development record's `solver_protocol`
(`research/football_candidate_development_record.json`): linearization level 2, one search
worker, seed 0 and a wall ceiling of 1800 seconds. That record lists two deterministic
budgets, 60 and 240. Here every arm is solved at 60 and solved again at 240 when 60 does not
prove it optimal. The decision is completed by `complete_optimization_decision` and scored by
`score_frozen_squad_decision` (`src/squadopt/evaluation/scoring.py`): normal-week automatic
substitutions and the captain fallback, on the gameweek's settled points. No transfer and no
hit is involved. This measures the forecast's decision value, not a member's transfer plan
(that is reading two).

**Statistic.** `d = realized(football) - realized(current)`, one value per gameweek. Weeks in
which both arms pick the same decision count as `d = 0`, and their number is reported. A week
in which either arm's primary or tie-break objective is not proven optimal at the larger
budget (the development record's `both_primary_and_tiebreak_proven` condition) is left out of
the verdict, counted, and shown beside it.

**Interval.** `season_aware_moving_block_interval` (`src/squadopt/evaluation/statistics.py`)
on the per-gameweek values, all keyed to season `2026-27`. It runs with the `PromotionPolicy()`
defaults (`src/squadopt/evaluation/promotion.py`: 90 percent, 5,000 resamples, blocks of four
gameweeks, seed 0) and the candidate id `football_team_share_v1-live-2026-27`. With fewer
than six scored gameweeks no interval is printed.

## Reading two, direction only: the member's own one-week plan

**Unit.** One member in one gameweek, for every league member whose squad the scored capture
holds. For each arm, `advise_entry` (`src/squadopt/application/advice.py`) computes the
member's one-week `saf-puan` plan from the scored capture with that arm's projection: window
1, no rival, Top 100 weight zero, the manager's word off, no chip. The plans are computed at
reading time, from inputs that all precede the deadline, with the planner revision the record
names, which is the same for both arms. Both plans are scored on
`RECORDED_ADVICE_SCORING_BASIS` (`src/squadopt/application/weekly_suggestion_eval.py`):
official automatic substitutions and captaincy, minus the plan's transfer hit. A pair in which
either plan is not `scoring_complete`, or the planner did not prove it, is left out and
counted.

**Statistic.** `e = realized(football plan) - realized(current plan)` per pair. Reported: the
number of pairs, and how many of them differ in decision; the mean of `e` over all pairs and
over the differing pairs; wins, ties and losses. Each gameweek also gets one value, that week's
member mean, and the same interval as reading one. The members share one projection, one set
of matches and overlapping squads, so the week is the unit. Pairs with the same plan are
counted and reported beside every mean, because they may be most of them. This reading gives
a direction only. It enters the verdict only as the floor in clause 3 of the verdict rule.

## Reading three, explanation: the forecasts' errors

**Unit.** One player in one scored gameweek, for every player both decided forecasts name. The
join to the settled outcome uses the FPL `code`, as `live_projection_audit` does. A player with
no settled row is left out and counted, never scored as zero.

**Statistics.** For each arm: the mean squared error and the bias (realized minus forecast),
over three populations:

- all players;
- the players a decision can act on: the union of each arm's top 40 per position by its own
  decided forecast (`TOP_PER_POSITION` in `src/squadopt/evaluation/live_projection_audit.py`);
- the players who appeared.

For each arm, also the forecast points it put on players who did not appear. Pooled figures
are equal-gameweek means, the convention of the football development documents. The
difference football minus current on the second population gets the same interval as reading
one, at six gameweeks or more. This reading carries no verdict. It says where a squad-level
difference comes from.

## Missing weeks

Every gameweek from the first scored one to the reading's last appears in the record. A gameweek is
missing when any of the following holds, and the record lists it with its reason:

- no `fpl-live` capture precedes its deadline;
- the scored capture has no `football_team_share_v1` artifact, or the artifact file was written
  at or after the deadline, or it names another model version;
- the backend cannot pair the scored capture with exactly one handoff;
- no later capture both marks the gameweek scored (`scored_gameweeks` in
  `src/squadopt/data/sources/fpl_live.py`) and holds its live payload.

A missing week is not repaired. It is never filled with another capture's artifact or with a
forecast rebuilt after the deadline. A week whose artifact was written after the deadline may
be shown beside the pooled tables, labelled `replay`, and is never pooled. An artifact's write
time is its file's modification time as the file system reports it, and the record states it.
`live-football-model.md` already asks for the artifact to be produced before each capture is
accepted; that is what keeps weeks from going missing.

## What is expected, declared before looking

The development record's 56 weekly differences have a standard deviation of 13.3478 points
(computed from `weekly_scores` in `research/football_candidate_development_record.json`).
`squadopt.evaluation.live_series` states the minimum-detectable-effect formula
`(z_(1-alpha/2) + z_power) * sd / sqrt(n)`. Take that formula with a two-sided 90 percent
interval (the verdict's) and power 0.80, and assume the live spread matches the development
spread. The smallest weekly effect reading one would detect is then 8.57 points at 15 scored
weeks (gameweeks 6 to 20) and 5.78 at 33 (gameweeks 6 to 38). The development mean, 4.9821,
is below both. On the same assumptions, a true effect of that size would clear the verdict's
lower bound with power about 0.42 at 15 weeks and 0.69 at 33.

Expectations:

- I expect `d` to average above zero and below the development's 4.9821.
- I expect the final interval to include zero, from the power above alone.
- Two live facts pull in opposite directions, and neither is measured here. Live 2026-27
  points include DEFCON, which the football model forecasts and the component model does not
  explicitly model (`measurements_index.md`, scoring-regime section). The v1 share limit costs
  the football arm attacking points at clubs with absentees (#829).

## When it is read

- **Between the dates below, no outcome is read.** At any time, the runner may check inputs
  (which weeks have both arms, and which are missing and why) without reading an outcome.
- **Interim**, after gameweek 20 settles: all three readings over the scored weeks up to
  gameweek 20. Only the harm clause below may be applied.
- **Final**, after gameweek 38 settles: all three readings over every scored week. The verdict
  rule is applied once.

There is no reading before, between or after these, and none taken once more. The option may
be withdrawn, or stop being served as `football_team_share_v1`. Later weeks are then missing
for that reason, and the readings still happen on the same dates with the weeks they have.
The 2027-28 season is not covered: a new season needs a new protocol.

## The verdict rule

Let `n` be the number of gameweeks that enter reading one's verdict, `m` the mean of `d` over
them, and `[lo, hi]` its interval. Let `hi2` be the upper end of reading two's interval, or
absent when reading two has fewer than six gameweeks.

At the final reading, the first of these that holds is the verdict:

1. `n < 6`: **`insufficient_evidence`**. No interval and no verdict.
2. `hi < 0`: **`football_worse`**.
3. `lo > 0`, and `m >= PromotionPolicy.min_mean_improvement` (0.5 points a week), and the
   member plans show no measured loss (`hi2` absent or `hi2 >= 0`): **`football_better`**.
4. Otherwise: **`not_separated`**. If clauses 1 to 3 fail only because `hi2 < 0`, the record
   says so.

At the interim reading, only clause 2 is applied, and only when `n >= 6`. If it holds, the
record says **`football_worse_interim`**. Otherwise the record says there is no verdict at the
interim, whichever way the figures point.

## What each outcome means

Nothing here switches anything on or off by itself.

- **`football_better`**: the first independent evidence that the football forecast picks
  better squads than the current one on live weeks. It is a reason to open a proposal to make
  it the default, through the model lane's own gate (İbrahim's), and does not decide that
  proposal. The member copy saying that live superiority is unverified may then be changed, in
  its own pull request, to cite this record; the member-facing honesty rules still apply.
- **`not_separated`** or **`insufficient_evidence`**: nothing changes. The option stays opt-in
  and labelled experimental, and its copy stays.
- **`football_worse`**, or **`football_worse_interim`**: the owner decides whether the option
  is still offered. If it is, the page says what the record found, in its own pull request.

## What this protocol does not do

- It fits nothing and tunes nothing. It reads no gameweek before the first scored one.
- It does not read `football_contextual_v3` or any later version, three- and five-week
  windows, chips, Top 100 weights, or the manager's word.
- It reads no member's behaviour: every plan it scores is computed from the capture, and
  whether anybody followed it does not matter.
- Nothing in it is member-facing.
- It writes nothing under `data/` and replaces no artifact.

## Where the record lives

The record follows ADR 0003 (`architecture/decisions/0003-measurement-artifacts.md`):

- **Record, committed.** `football_prospective_gw20.json` and `football_prospective_gw38.json`
  in `docs/`, each with its markdown twin and a row in `measurements_index.md`. Each holds, per
  gameweek: the scored capture, the artifact fingerprint and write time, the handoff
  fingerprint and model version, both arms' realized squad scores and solver statuses,
  reading two's counts and means, reading three's summaries, and the pooled statistics with
  the verdict or the reason there is none. The second reading is a new record and leaves the
  first as it was.
- **Evidence, not committed.** The per-player forecast and outcome rows, and the per-member
  plans, go under `artifacts/`. They are expansions of licence-restricted captures.
- **Operational state, read only.** Captures, handoffs and artifacts are read through their
  existing readers.

## Reproduction

`python -m scripts.measure_football_prospective --season 2026-27 --through-gameweek 20
--data-root <checkout>/data --artifact-root <checkout>/artifacts` (and `38`), to be added in
its own pull request before the interim reading. Its arithmetic is to be tested on synthetic
frames. The runner lives at `scripts/measure_football_prospective.py`. It reads captures,
handoffs and artifacts through their existing readers, solves as stated above, and writes
the two records.
