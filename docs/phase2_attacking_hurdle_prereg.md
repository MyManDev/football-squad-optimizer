# Phase 2 attacking occurrence/severity attribution

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Question

Phase 2H found that attacking-point surprise carries much of the fixed selected XI's lower-tail
miss. Phase 2I did not localize that signal to a completed-appearance marginal blank bias,
common-week reference excess or same-team reference excess. Before any attacking model is
built, this study asks:

> Is the Phase 2H attacking surprise carried by whether an attacking return occurs, by the
> size of a positive return, by both, or by neither with the available support?

No model is fitted. The optimizer decision, scenario matrix, projection, score policy and q10
threshold remain unchanged. No live, production, canonical-schema or publication path changes.

## Frozen population and chronology

The residual export and manifest, archive pin, projection model, fold universe, optimizer
settings, selected squad, starting XI, captain, scenario configuration, seed and history are
exactly those used by `phase2_component_attribution_v1` and
`phase2_attacking_structure_v1`.

Roles remain:

- 2021-22 and 2022-23: descriptive screening;
- 2023-24: carrier classification;
- 2024-25: already observed directional sensitivity;
- 2025-26: locked and forbidden before any filesystem read.

Development folds use only `fold.prior_fold_ids`. Every 2024-25 fold uses one history frozen at
the end of 2023-24. Target and future folds are rejected at the attribution boundary. The study
must reproduce the recorded 29/36/37/37 fold universe, 139 folds, 1,529 starter rows, one captain
per fold, the Phase 2H control and attacking summaries, and the Phase 2I structural summaries
before an artifact may be written.

The exact Phase 2H and Phase 2I artifact SHA-256 digests are verified before the run. Their
digests, all upstream source-artifact digests, the residual export and archive pins, actual
loaded seasons, repository commit and clean-tree flag are recorded in the output. A mismatch or
dirty tree refuses the study before measurement.

The holdout refusal runs before archive enumeration or reading. Raw and component loaders receive
only the explicit 2020-21 through 2024-25 season list; requested and loaded seasons plus
`locked_holdout_accessed: false` are recorded.

One optimizer decision and one scenario matrix are created per fold. That same decision supplies
the component attribution, starter identities, captain, hurdle rows and control q10 reading. A
second solve or scenario draw may not supply any arm.

## Exact two-part decomposition

The calculation uses all selected starters. It does not condition on realized minutes. For one
starter, let:

- `A` be realized attacking points;
- `I = 1(A > 0)`;
- `H` be the exact all-player-gameweek historical pool selected by the Phase 2H source ladder;
- `p = mean_H(1(attacking > 0))`;
- `m_plus = mean_H(attacking | attacking > 0)`;
- `w = 2` for the captain and `1` for every other starter.

When `H` contains a positive return, its historical mean is exactly `p * m_plus`. The two
weighted terms are:

```text
occurrence = w * (I - p) * m_plus
severity   = w * I * (A - m_plus)
```

and must satisfy, for every player and fold:

```text
occurrence + severity = w * (A - mean_H(attacking))
```

The fold sum must equal the Phase 2H captain-weighted attacking surprise within `1e-9`. Captaincy
changes score weight only; the captain remains one player observation. Bench players and
automatic substitutions remain outside the score policy.

## Source support and the zero-positive case

The Phase 2H source ladder is unchanged:

1. same stable player and current position with at least 8 historical player-gameweeks;
2. same position;
3. pooled history.

`p` and `m_plus` come from that same selected pool. A player row is carrier-supported when the
pool contains at least 5 positive attacking returns. If it contains 1-4, the exact arithmetic is
recorded but the entire fold is unavailable to carrier classification; replacing `m_plus` with
another pool would break the Phase 2H identity.

If the selected Phase 2H pool contains zero positive returns, then `p = 0` and its historical
mean is zero. Only in this special case, `m_plus` is selected before the target outcome from the
first pool with at least 5 positive returns:

1. same current position within the exact allowed chronology;
2. pooled history.

The identity remains exact because `p = 0`. If neither fallback has 5 positive observations,
the row and fold are unsupported. Source selection never depends on target `I`, `A`, minutes or
score. Positive support is counted in distinct aggregated player-gameweek observations, never
fixture rows or a captain duplicate. Zero-positive fallback rows and folds plus source counts are
recorded separately.

## Fold readings and counterfactuals

For fold `f`, let `Occ[f]` and `Sev[f]` be the starter-weighted sums, `R[f]` the canonical
realized score, `Q[f]` the unchanged control scenario q10, and
`Y[f] = 1(R[f] < Q[f])`.

```text
R_without_occurrence[f] = R[f] - Occ[f]
R_without_severity[f]   = R[f] - Sev[f]

Y_without_x[f] = 1(R_without_x[f] < Q[f])
reduction_x[f] = Y[f] - Y_without_x[f]
```

The same strict `< q10` event is used in every arm. The scenario matrix is not regenerated.
Occurrence and severity reductions are nonlinear indicator readings and are not additive shares
or causal effects.

For each part, the validation contrast is:

```text
contrast_x = mean(X[f] | Y[f] = 1) - mean(X[f] | Y[f] = 0)
```

PIT and S1/S2-band membership may be reported descriptively but do not decide this attribution.
The question is which part carries the recorded tail separation, not whether removing one part
is already a production-ready calibration fix.

## Support and uncertainty

Classification uses only folds where all 11 selected starters satisfy the positive-severity
support rule. It requires at least 30 eligible folds in 2023-24 and 30 in 2024-25, both control
tail and non-tail folds in validation and sensitivity, exact identities on every measured fold,
and both zero and positive target attacking returns in validation and sensitivity. Missing
support is never imputed as zero.

Eligible and excluded fold counts and exclusion reasons are recorded by season. A carrier result
describes only the supported subset and cannot be generalized silently to excluded Phase 2H
folds.

Intervals use fold-clustered bootstrap with 5,000 resamples, 90% confidence and seed 0. Player
rows are never independent resampling units. Tail-contrast draws containing only one group are
discarded. Paired q10 reductions resample the same fold indices.

## Frozen carrier classification

For either `x = occurrence` or `severity`, the validation carrier gate passes only when:

1. the 90% bootstrap interval for `contrast_x` has an upper bound strictly below zero; and
2. the 90% bootstrap interval for mean `reduction_x` has a lower bound strictly above zero.

The 2024-25 sensitivity direction must not reverse either reading: its point contrast must be at
most zero and its mean reduction at least zero.

The study returns one of:

- `attacking_occurrence_carrier` when only occurrence passes;
- `attacking_positive_severity_carrier` when only severity passes;
- `shared_attacking_hurdle_failure` when both pass;
- `attacking_hurdle_not_localized` when neither passes;
- `diagnostic_inconclusive` when population, history, support, replay or identity is unavailable.

Parts are not ranked and the larger point estimate is not selected.

## Descriptive support only

Minutes buckets (`0`, `1-59`, `60+`) and fixture-count distributions are reported, but they do
not select a pool or affect a gate. In a double gameweek, `A` is the sum over fixtures and `I`
means any attacking return in the player-gameweek. This is not a fixture-level or causal claim.
All-starter occurrence combines availability, minutes and return opportunity; it is not a pure
skill probability. A zero-positive player fallback uses a broader positive-size reference; if
those rows materially carry a result, the interpretation remains occurrence under that broad
reference rather than a player-specific or causal effect.

Finite historical pools make this exploratory. The fold bootstrap does not propagate source
mean estimation uncertainty or model dependence across adjacent gameweeks. A carrier result
authorizes only a separate pre-registration for that modelling subject. It does not authorize
parameter sweeps, an alternate threshold, a hurdle model, a count model, GP, Monte Carlo,
promotion, production use or member-facing probability publication.

Exactly one binding run is authorized after this document is committed and implementation has
passed the complete quality suite. The recorded result stands without post-result retuning.
