# Phase C component evaluation protocol

Status: pre-registered evaluation foundation; no binding candidate measurement has run.

This document freezes how Phase C component outputs are checked and scored before any
candidate-specific thresholds are selected. It does not promote a model, authorize the locked
holdout, or change the live control.

## Compared arms

The following identities remain distinct:

- `operational_control`: the model used by the live system at the decision timestamp;
- `component_base`: the component model without optional Phase B evidence;
- `component_plus_availability`;
- `component_plus_ownership_transfer`;
- `component_plus_elite`;
- `combined`: a separately fitted candidate containing only evidence families justified by
  their individual measurements.

An arm name is not evidence that the named inputs were used. Every run must bind the model,
feature, target and artifact versions and their SHA-256 digests. The current live control uses
prospective Top-100 evidence and cannot be reconstructed honestly on seasons without
deadline-valid cohort captures. Historical comparisons must therefore name their replayable
comparator precisely; they must not relabel a rollback or component base as the current
operational control.

## Required chronological handoff

One OOF row represents one player at one decision gameweek. The primary key is:

```text
(season, target_gameweek, player_id)
```

The handoff must carry the fold, decision timestamp, position, fixture count, realized targets,
component predictions and exact model/feature/target identities. Its manifest must additionally
carry, per fold, the training cutoff and either the ordered training fold IDs or a digest of the
ordered training keys. The evaluator rejects a fold unless its latest training instant is
strictly earlier than its decision instant and the target fold is absent from its training set.
Row counts or a target `fold_id` alone do not prove an out-of-fold prediction.

Decision-level evaluation also requires an immutable decision roster containing `name`,
`team_id`, `position` and `price_tenths`, exact-keyed to the OOF table. Ownership is optional and
may be used only for a descriptive feasible-template comparison when its timing is verified.

The locked 2025-26 holdout is not loaded, listed, hashed or filtered after loading. Development
work uses only explicitly allowed earlier seasons. Prospective 2026-27 decisions are a separate
confirmation population.

## Component semantics

Let `A` denote any appearance and `S` at least one start in the gameweek. The structural start
contract is:

```text
p_appearance = P(A = 1 | X)
q_start_given_appearance = P(S = 1 | A = 1, X)
p_start = p_appearance * q_start_given_appearance
```

The evaluator requires all probabilities to be finite and in `[0, 1]`, `p_start <=
p_appearance`, and the composition identity above. Start labels and predictions may be missing
only where the start component is explicitly unavailable; missing is not zero. A minutes-based
start proxy is forbidden.

Blank gameweeks are calendar audits, not skill observations. Their component probabilities,
minutes and points must be zero and any realized appearance is reported as a violation.

## Player-level metrics

All point estimates are micro-averages over eligible player-gameweek rows. Every result reports
population, eligible, scored and missing counts.

Appearance:

```text
Brier_A = mean((p_appearance - A) ** 2)
log_loss uses epsilon 1e-6
calibration_bias = mean(p_appearance) - mean(A)
```

Reliability uses ten fixed equal-width bins. Blank rows are excluded.

Start, only where verified labels exist:

```text
Brier_start = mean((p_start - S) ** 2)
Brier_start_given_appearance = mean((q_start_given_appearance - S) ** 2), A = 1 only
```

Minutes:

```text
overall error = expected_minutes - realized_minutes
appeared-player error = expected_minutes_if_appearance - realized_minutes
```

Points:

```text
overall error = expected_points - realized_points
appeared-player error = expected_points_if_appearance - realized_points
```

Minutes and points report MAE, RMSE and signed mean error. Conditional and unconditional
metrics are never merged. Results are sliced descriptively by season, position and fixture
group (`blank`, `single`, `double_plus`) without treating the slices as independent tests.

### Decision-scoring execution amendment

This amendment was recorded before any complete 147-fold Phase C decision comparison. It
clarifies execution semantics exposed by the frozen handoff; it changes no arm, metric, gate or
threshold.

`points_target` and `minutes_target` are conditional component targets and are therefore absent
when `appearance_target == 0`. They are not a substitute for the canonical settled-outcome
table: an official `total_points` value can be non-zero even when recorded minutes are zero.
Decision scoring consequently uses exact-key canonical `total_points` from the historical
control fold and minutes implied by the handoff appearance target. Appeared-player points must
agree across both sources. Missing, extra, duplicated or contradictory rows refuse the entire
comparison; no silent intersection or zero imputation is allowed.

For `component_model` rows, the component-base decision uses the handoff's composed
`control_expected_points`. For `direct_control` rows, where the component handoff deliberately
carries no invented prediction, it uses the exact-key historical control projection. Both arms
must contain the same complete ordered fold and player populations before either is optimized.

## Evidence ablations

Each evidence arm is compared with the same `component_base` on exactly identical ordered keys,
targets, folds, decision contexts and optimizer settings. Silent intersections are forbidden.
An entirely absent requested family must reproduce the component base exactly; partial missing
evidence follows the candidate's pre-declared fallback and remains explicitly counted.

Availability, ownership-transfer and elite evidence are measured separately. A combined model
is not formed arithmetically after viewing results. If later justified, the prediction side emits
a separately versioned combined arm with an exact frozen family list.

Player-level calibration and error metrics are diagnostics. They cannot by themselves promote
a model.

## Decision-level comparison

Every arm is optimized over the same player pool and scored with
`official_autosub_captain_v2`. The paired response at fold `t` is:

```text
delta_t = realized_score_candidate_t - realized_score_control_t
```

Reports include attempted, feasible, scored and comparable fold counts; mean and median paired
difference; win/tie/loss counts; season means; zero-minute starters; autosub points and
vice-captain recoveries. A missing or infeasible fold remains visible and makes a promotion
comparison ineligible. A feasible ownership-template gap is descriptive and is not a second
independent success claim.

Intervals, when authorized by a candidate declaration, operate on gameweek-level paired
differences with season-aware moving blocks. Player rows are not independent bootstrap units.

## Promotion boundary

This foundation does not freeze a candidate or numerical promotion thresholds. Before one
binding run, a candidate-specific declaration must name:

- exact arm and control identities and artifact digests;
- exact ordered development folds and prospective confirmation population;
- model, feature, target and scoring versions;
- evidence family and missing-data policy;
- numerical gates, confidence level, block length and seed.

A development pass means only `eligible_for_future_confirmation`. It is not live promotion.
Promotion against the current operational control requires matched prospective decisions because
its deadline-frozen Top-100 input does not exist historically. A failed or incomplete candidate
retains the operational control.

## Deliberate exclusions

This work does not fit models, read raw captures, create evidence features, run a binding
measurement, access the locked holdout, publish probabilities, generate scenarios, change an
optimizer objective or implement Phase D dependence. Those are separate responsibilities and
hypotheses.
