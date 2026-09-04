# Phase C component player-model pre-registration

This document freezes the first Phase C contract before a component model is fitted or
measured. It defines what the components mean, which labels are admissible, how their means
compose, and how later candidates will be compared. It does not declare a candidate, choose a
promotion threshold, read the locked holdout, or change the operational control.

## Objective and boundary

Phase C separates four questions that a single expected-points value cannot distinguish:

1. Will the player appear at all?
2. If the player appears, will he start?
3. How many minutes will he play in that role?
4. How many points will those minutes, fixtures and role produce?

The component result remains inside the prediction layer. The existing
`prediction_to_optimization_v1` handoff continues to carry only the optimizer-ready point
estimate and player fields. Probabilities are not published to members, passed to the
optimizer, or treated as calibrated scenario probabilities in this phase. Joint outcomes and
correlations belong to Phase D.

Three arms remain distinct:

- **operational control**: the currently promoted live point model;
- **component base**: the Phase C model without optional Phase B evidence;
- **evidence candidate**: the same component model with one declared evidence family added.

The operational control cannot change through this foundation work.

## Random variables and component semantics

For player `i` at decision gameweek `t`, let:

- `A = 1` mean at least one minute was played in at least one fixture;
- `S = 1` mean at least one fixture was started;
- `k` be the number of scheduled fixtures known at the decision timestamp.

Starting implies appearing, so `S <= A`. The model must represent that relation
structurally rather than clipping two independently fitted probabilities after prediction:

```text
p_appearance = P(A = 1 | X)
q_start_given_appearance = P(S = 1 | A = 1, X)
p_start = p_appearance * q_start_given_appearance
```

The mutually exclusive state probabilities are:

```text
p_none = 1 - p_appearance
p_substitute = p_appearance * (1 - q_start_given_appearance)
p_start = p_appearance * q_start_given_appearance
```

They must be finite, lie in `[0, 1]`, and sum to one within the declared numerical tolerance.
This also guarantees `p_start <= p_appearance` without a repair step.

For a double or triple gameweek, `start` means starting at least one fixture. Fixture-level
start counts are deliberately deferred; inventing them at player-gameweek grain would claim
information the current panel does not contain.

## Minutes composition

When a verified start label is available, define:

```text
mu_start = E[minutes | S = 1, X]
mu_substitute = E[minutes | A = 1, S = 0, X]

expected_minutes =
    p_start * mu_start
    + p_substitute * mu_substitute
```

Both conditional means must be finite and within `[0, 90 * k]`. The contract does not require
`mu_start >= mu_substitute`: it is a plausible empirical pattern, not a mathematical law.

If the start component is unavailable, the honest reduced form is:

```text
mu_appearance = E[minutes | A = 1, X]
expected_minutes = p_appearance * mu_appearance
```

The result must record that the start component is unavailable. It must not synthesize a start
label or report a zero probability. In every route, `expected_minutes` must lie in
`[0, 90 * k]`.

## Points composition

The full role-aware form evaluates one conditional points model in the two appearance roles:

```text
g_start = E[points | A = 1, role = start, minutes = mu_start, X]
g_substitute = E[points | A = 1, role = substitute, minutes = mu_substitute, X]

expected_points =
    p_start * g_start
    + p_substitute * g_substitute
```

The reduced form integrates over the unobserved role:

```text
g_appearance = E[points | A = 1, minutes, fixture and role information in X]
expected_points = p_appearance * g_appearance
```

No-appearance points are zero. The player model does not contain captain multipliers,
automatic substitutions, bench order or transfer hits; those remain decision and scoring
rules.

The existing production model's linear `expected_minutes / 90 * expected_points_per_90`
calculation is an admissible component-base implementation, not a mathematical identity that
future candidates must preserve. A direct cold-start price prior remains a separate fallback:
it already estimates expected points and must not be multiplied by expected minutes a second
time.

Expected points delivered to the optimizer must remain finite and non-negative.

## Calendar override

When `k = 0`, the player has a blank gameweek. Appearance and start probabilities, conditional
minute contribution, expected minutes and expected points are all zero. Historical form cannot
override a known empty calendar.

For `k > 0`, the contract permits conditional minutes above 90 up to `90 * k`; otherwise a
double gameweek would be forced into a single-fixture support.

## Label admissibility

Labels are outcomes and may only be read after the gameweek has completed:

- appearance: `minutes > 0`;
- minutes: official realized minutes;
- points: official realized player points;
- start: the source's verified start indicator only.

The current archive adapter does not map `starts` across every supported season because the
field is not present throughout the archive. Therefore `minutes >= 60`, points, lineup
membership or any other proxy must not be used as a start label. Until a verified source and
population are declared, the start component is `unavailable` and its metrics are
`not_evaluable`, not zero.

## Phase B evidence boundary

Optional evidence may enter only through the versioned Phase B player-by-decision handoff.
Every evidence row must identify its decision timestamp, capture timestamp, snapshot and
contract version. Evidence captured after its decision deadline is invalid and must fail
closed; it is not ordinary missing data.

The following cases remain distinct:

- `not_requested`: the control arm intentionally does not consume the evidence family;
- `available`: deadline-valid evidence exists for the player and candidate;
- `missing`: the family was requested but has no value for this player;
- invalid timing or provenance: reject the run.

A missing optional value falls back to the component base for that player. It must not be
imputed as a genuine zero. If an evidence family is absent for the whole candidate run, the
candidate output must reproduce the component base exactly.

Evidence families are introduced one at a time:

1. captured availability;
2. overall ownership and transfer movement;
3. lagged elite-cohort evidence;
4. a combined candidate only if the individual measurements justify one.

The Phase A frozen Top-100 cohort remains the primary prospective cohort. Top-50 and Top-200
are sensitivity cohorts and cannot silently replace it.

## Chronological evaluation protocol

Every candidate and control use identical chronological folds, target rows, player pools,
optimizer configuration and official V2 autosub/vice-captain scoring. All preprocessing,
imputation and scaling is fitted only on rows strictly earlier than the decision being scored.

Reported player-level metrics are:

- appearance: Brier score as the primary metric, log loss with a fixed clipping epsilon, and
  reliability diagnostics;
- start: unconditional start Brier score and start-given-appearance Brier score, only on a
  population with verified labels;
- minutes: unconditional MAE/RMSE and appeared-player MAE, with starter/substitute slices when
  the start label is admissible;
- points: overall and appeared-player MAE/RMSE, plus position and fixture-count bias.

Reported decision-level metrics are:

- official V2 realized squad score;
- paired score difference against the operational control;
- feasible-fold rate;
- zero-minute starter rate;
- points recovered through automatic substitutions and vice-captain replacement;
- feasible ownership-template minus system gap.

Calibration diagnostics do not by themselves promote a model. A later candidate-specific
pre-registration must freeze its model, evidence arm, folds, numerical thresholds and
promotion rule before one binding measurement. A failed candidate leaves the operational
control unchanged.

## Foundation invariants

The first typed contract and its synthetic tests must establish:

- all supplied probabilities are finite and in `[0, 1]`;
- `p_start = p_appearance * q_start_given_appearance` when the start component is available;
- the state probabilities sum to one;
- expected minutes and points equal their declared composition route;
- blank gameweeks produce zero contribution;
- missing evidence is not interpreted as zero;
- invalid or late evidence is rejected once evidence is connected;
- player identifiers align exactly and deterministically;
- input frames are not mutated;
- the same input and provenance produce the same result;
- the existing optimizer snapshot and live operational control remain unchanged.

## Deliberate exclusions

This foundation does not introduce a fitted model, model registry, generic probability
framework, Gaussian process, hidden Markov model, Monte Carlo generator, optimizer objective,
public probability field or locked-holdout run. Those are separate hypotheses or later phases,
not prerequisites for defining this boundary.
