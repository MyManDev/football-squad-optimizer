# Phase C empirical appearance control pre-registration

Status: pre-registered implementation contract; no binding measurement has been run.

This document freezes the first appearance control that will populate the Phase C component
boundary. It exposes a quantity the operational two-stage projection already uses. It does not
declare a learned candidate, claim calibration, change an optimizer decision or promote a model.

## Estimand and label

For player `i` at decision gameweek `t`, the appearance event is

```text
A(i, t) = 1 if official settled minutes(i, t) > 0, otherwise 0.
```

The settled label is read only after the gameweek. A missing minutes value is not an absence and
must be rejected from an evaluation population rather than converted to zero. Start status is not
inferred from minutes or points and remains unavailable.

The empirical control is the existing shifted rolling appearance rate with window six:

```text
p_control(i, t) = mean(A(i, j)) over the available gameweeks j in [t - 6, t - 1].
```

The canonical feature is `appearance_rate_last_6`. Its feature builder shifts the appearance
outcome before rolling, so neither target-gameweek nor future minutes may affect the value.

## Calendar and missing-history rules

- `fixture_count = 0` overrides history and returns appearance probability zero.
- A positive fixture count does not multiply or otherwise transform the probability. In a double
  gameweek the event is still any appearance in the gameweek; fixture independence is not assumed.
- An observed rolling value of zero is evidence and remains zero.
- Missing current-season appearance history remains missing. No Beta prior, carry-over probability,
  price-derived probability or imputed sample count is introduced.
- Non-finite values and values outside `[0, 1]` fail closed.

The window remains owned by the existing `ExpectedMinutesConfig`. A second appearance config would
create two sources of truth and is deliberately excluded.

## Component-control mapping

The adapter must preserve the operational production projection exactly.

Where current-season history supports the existing two-stage route and `p_control > 0`:

```text
appearance_probability = p_control
expected_minutes_if_appearance = operational_expected_minutes / p_control
expected_points_if_appearance = operational_expected_points / p_control
composition_route = component_model
evidence_status = not_requested
```

Where the operational two-stage result is exactly zero with `p_control = 0`, the conditional
contributions are zero and the same component route may be used.

Rows that cannot be decomposed without inventing a probability use:

```text
fallback_expected_points = operational_expected_points
composition_route = direct_control
evidence_status = not_requested
```

This includes price-prior rows and carry-over-only rows. A price prior already estimates expected
points; dividing it by an invented probability or multiplying it by minutes would double-count
playing time. The adapter may not do either.

For every row, the component snapshot's `expected_points` must equal the operational control's
`expected_points` within absolute tolerance `1e-12`. The optimizer handoff remains the existing
canonical six-column point-estimate snapshot and receives no probability column.

## Leakage and determinism requirements

- Feature construction uses only rows visible at the decision timestamp and shifted historical
  outcomes.
- Mutating target-gameweek or future minutes and points must not change the component snapshot.
- Mutating an earlier visible appearance may change it, proving that the leakage guard is not a
  constant-output test.
- Input frames are not mutated.
- Reordered but otherwise identical player rows produce the same canonical table and fingerprint.
- Phase B evidence is not read; every row remains `not_requested`.
- The locked 2025-26 holdout is not read.

## Later descriptive evaluation

No binding evaluation is authorized by this document. A later measurement contract may report:

- Brier score as the primary player-level metric;
- log loss with fixed clipping epsilon `1e-6`;
- calibration-in-the-large and ten fixed equal-width reliability bins;
- probability coverage and explicit direct-control fallback counts;
- season, position, single-fixture and double-plus-fixture slices.

Blank-gameweek rows are excluded from skill and calibration metrics and reported separately as
calendar-rule checks. Direct-control rows without an appearance probability are excluded from the
score numerator but remain in the coverage denominator. Player rows must not be treated as
independent evidence for confidence intervals; later comparative inference must aggregate by
gameweek and use season-aware blocks.

These diagnostics cannot promote the empirical control. Any learned or evidence-augmented
candidate needs a separate pre-registration that freezes its algorithm, features, folds,
preprocessing, numerical settings, thresholds and promotion rule before one binding run.

## Deliberate exclusions

This delivery does not add logistic regression, probability calibration, a generic estimator
protocol, a model registry, Phase B evidence, a start proxy, Monte Carlo changes, an optimizer
objective, a public probability field or a live recommendation change.
