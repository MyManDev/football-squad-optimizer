# Phase 2 attacking support-recovery pre-registration

Status: pre-registered before implementation or measurement.

## Question and boundary

Phase 2J could not classify the selected-XI attacking hurdle because its frozen robust-support
rule left only 5 of 37 validation folds and 10 of 37 sensitivity folds eligible. Every excluded
fold contained at least one starter whose exact Phase 2H history held only one to four positive
attacking returns. The arithmetic was available, but its positive-return mean was too thin for
the declared five-observation support floor.

This study asks one narrow question: does filling only that missing positive-severity support
with a leakage-safe historical reference recover enough complete selected-XI folds to read the
same return-reference/severity direction under the frozen recovered rule? It does not lower
Phase 2J's threshold, fit a production model, or search for a better pseudo-count.

The study is measurement-only, uses development data already seen, is not independent
confirmation, is not promotion-eligible, and cannot publish a probability or change a live,
scenario, prediction, optimization, planning or member-facing contract.

## Frozen sources and population

The following committed artifacts are immutable inputs:

- Phase 2H component attribution, SHA-256
  `4023b06b637f3968e762cf7af3b0a9d7b0f45334d8be61d4a0603c1cbe96a3f8`;
- Phase 2I attacking structure, SHA-256
  `0ee1dafa085b7ce417ec7be603c30ad299a015cc5fe34d676353a9592b834fc2`;
- Phase 2J attacking hurdle, SHA-256
  `5b3dc676bbc21642cd027823d90f43c97e27297d06764660bcf8d627666f3f2b`;
- the exact in-season residual export named by those artifacts, SHA-256
  `17f88e6e75618adc01ec6357317a6849bdb053e7eeed1cd6627c8eceab15fc7a`.

The runner must reproduce the same 139 folds, season counts 29/36/37/37, 1,529 selected
starters, XI, captain, control score, q10 reading, Phase 2H summaries, Phase 2I summaries and
classification, and every Phase 2J support count and eligible-fold summary before the recovered
arm may be written. The scenario matrix is generated exactly once per fold from the pinned
inputs, configuration and seed; that same matrix is used for every arm, and the recorded control
and component readings must replay. The new arm is only an alternate reading of these fixed
objects.

Requested and loaded panel seasons are exactly 2020-21 through 2024-25. The locked 2025-26
holdout must not be enumerated or read. All input digests, the residual/model identity, archive
pin, requested and loaded seasons, repository revision, clean-tree state, execution metadata and
warnings are recorded and checked again immediately before publication.

Before any generic table loader sees the residual export, its manifest must declare exactly the
pinned residual SHA-256 above. The measurement parses one digest-verified byte snapshot; any
prior validator read must agree with that pinned digest. A declaration mismatch, byte mismatch
or changed source is a refusal rather than a diagnostic result.

The 2021-22 and 2022-23 seasons are descriptive only and cannot choose, tune or reverse a result.
The frozen decision seasons remain 2023-24 validation and 2024-25 sensitivity.

## Chronology and Phase 2H pool

For a target starter `i`, `H_i` is the exact Phase 2H all-player-gameweek pool selected by the
unchanged source ladder:

1. the stable player in the current position when at least eight historical player-gameweeks
   are available;
2. the current position;
3. pooled history.

Development targets use only their declared prior fold ids. Every 2024-25 sensitivity target
uses the same history frozen at the end of 2023-24. A target or future fold, a repeated
`(fold_id, player_id)`, a season/fold mismatch, or non-FIT sensitivity history is refused.
Positive support counts distinct aggregated player-gameweeks, never fixture rows or a captain
copy. Fixture rows remain aggregated before this study; double-gameweek attacking points are a
player-gameweek sum.

## One frozen support-recovery rule

Let:

- `A_i` be realized attacking points in the target player-gameweek;
- `I_i = 1(A_i > 0)`;
- `n_i` be the number of rows in `H_i`;
- `k_i` and `S_i` be the count and sum of positive attacking returns in `H_i`;
- `mu_i = mean_H_i(A)` be the exact Phase 2H historical attacking mean;
- `w_i = 2` for the captain and `1` for every other starter;
- `K = 5`, inherited from Phase 2J's pre-registered robust-support floor.

`K` is not tuned or swept. When `k_i >= K`, the positive-return reference is unchanged:

```text
m_tilde_i = S_i / k_i
```

When `1 <= k_i < K`, a background positive-return mean `b_i` is selected before the target
outcome from the first eligible pool containing at least five positive player-gameweeks:

1. the target's current position in the exact allowed history, excluding the target player;
2. pooled allowed history, excluding the target player.

When `k_i = 0`, `b_i` is the exact Phase 2J zero-positive fallback: current-position positive
returns first and pooled positive returns second, with Phase 2J's original player-inclusion
semantics. The current-position pool cannot contain a positive return from the target's exact
`H_i`, but the pooled fallback can contain a historical positive return from that player in a
different position. This branch is kept deliberately so `k_i = 0` remains exactly Phase 2J; the
target-player exclusion above applies only to the newly recovered `1-4` branch.

The target's attacking points, return indicator, minutes, fixture count, score and tail status
cannot affect either selection. If the applicable pool supplies no eligible reference, the row
and fold remain unsupported. Otherwise only the missing support is filled:

```text
nu_i      = K - k_i
m_tilde_i = (S_i + nu_i * b_i) / K
```

This is deterministic threshold-fill partial pooling, not an empirical-Bayes fit. It introduces
no learned hyperparameter, grid, alpha or alternate threshold. At `k_i = 0` it uses the
already-declared Phase 2J zero-positive reference exactly; at `k_i >= 5` it is Phase 2J exactly.

## Exact decomposition

For sparse rows, `m_tilde_i` no longer satisfies `mu_i = (k_i/n_i) * m_tilde_i`. Therefore the
first term is deliberately named **return-reference**, not pure occurrence probability:

```text
reference_i = w_i * (I_i * m_tilde_i - mu_i)
severity_i  = w_i * I_i * (A_i - m_tilde_i)
```

It must satisfy for every row and fold:

```text
reference_i + severity_i = w_i * (A_i - mu_i)
```

and the fold sum must reproduce Phase 2H's captain-weighted attacking surprise within `1e-9`.
The descriptive alignment gap

```text
alignment_gap_i = w_i * ((k_i / n_i) * m_tilde_i - mu_i)
```

is recorded in aggregate so broad-reference dependence remains visible. It is zero in the
unchanged `k_i >= 5` case. Captaincy changes score weight only; the captain remains one
observation. Bench players and automatic substitutions remain outside the scoring policy.

## Fold readings

For fold `f`, let `Ref[f]` and `Sev[f]` be the selected-XI sums, `R[f]` the canonical realized
score, `Q[f]` the unchanged control scenario q10, and `Y[f] = 1(R[f] < Q[f])`.

```text
R_without_reference[f] = R[f] - Ref[f]
R_without_severity[f]  = R[f] - Sev[f]
Y_without_x[f]         = 1(R_without_x[f] < Q[f])
reduction_x[f]         = Y[f] - Y_without_x[f]
```

The same strict `< q10` event is used. The scenario matrix is not regenerated. These are
nonlinear diagnostic counterfactuals, not additive causal shares.

## Support, uncertainty and frozen classification

A recovered fold is eligible only when all eleven starters have a finite reference from the
rule above and every row/fold identity closes. Classification requires at least 30 eligible
folds in 2023-24 validation and 30 in 2024-25 sensitivity, both tail and non-tail control folds,
and both positive and zero target attacking returns in each season. Missing support is never
imputed as zero.

For each part `x` in `{reference, severity}`:

```text
contrast_x = mean(X[f] | Y[f] = 1) - mean(X[f] | Y[f] = 0)
```

Intervals use the existing canonical percentile bootstrap and its NumPy linear-quantile rule,
with 5,000 fold-clustered resamples, 90% confidence and seed 0. Player rows are not independent
resampling units. Each draw resamples the eligible folds with replacement. A contrast draw
containing no tail or no non-tail fold is discarded; if no valid contrast draw remains, the
result is `diagnostic_inconclusive`. This discard applies only to the contrast statistic. Point
contrasts use the original eligible folds. Paired q10 reductions are formed within each fold,
and their interval retains all 5,000 resamples of those precomputed fold-level differences.

A validation signal passes only when the 90% contrast interval has an upper bound strictly
below zero and the 90% mean-reduction interval has a lower bound strictly above zero. The
2024-25 direction must not reverse it: point contrast at most zero and mean reduction at least
zero.

The frozen result classes are:

- `attacking_return_reference_signal` when only reference passes;
- `attacking_positive_severity_signal` when only severity passes;
- `shared_attacking_reference_severity_signal` when both pass;
- `attacking_support_recovered_not_localized` when neither passes;
- `diagnostic_inconclusive` when population, support, replay, source or identity is unavailable.

Parts are not ranked and the larger point estimate is not selected. A reference result is not a
probability claim and cannot be described as player-specific occurrence where position or pooled
support materially contributes.

## Required diagnostics and stop rules

The artifact records by season:

- robust Phase 2J support and its exact replay;
- recovered/excluded starters and folds;
- original `k_i` bins `0`, `1-4`, `5+`;
- unchanged, position-reference and pooled-reference counts, including a `k_i` bin by source
  cross-tab that separates inherited `k_i = 0` fallback from newly recovered `1-4` rows;
- fill fraction `rho_i = (K - k_i) / K` for `k_i < K`, otherwise zero, with its count, mean and
  maximum by season (`rho_i = 1` for the inherited `k_i = 0` fallback);
- signed mean, mean absolute and maximum absolute `alignment_gap_i` by season;
- minutes and fixture-count descriptions;
- maximum row and fold identity errors;
- validation and sensitivity contrasts, reductions and fold-bootstrap intervals.

If fewer than 30 folds remain in either required season, the result is
`diagnostic_inconclusive` and the study stops. `K`, the reference order and fallback policy are
not changed. A non-localized result stops. A single-part or shared signal authorizes only a new
pre-registration for that modelling family; it does not authorize Beta-Binomial fitting,
severity distributions, a hurdle/count model, GP, Monte Carlo, a scenario change, promotion or
production use.

Minutes and fixture counts are post-outcome descriptive context and never conditioning inputs.
Finite historical references, shared observations between player and position pools, and source
mean uncertainty are not propagated by the fold bootstrap. These limitations remain visible in
any interpretation. The pooled fallback also mixes position-dependent attacking-return point
scales across GK, DEF, MID and FWD; its use is therefore a visible broad-reference fallback, not
a position-specific player estimate.

Exactly one binding run is authorized after this document is committed and implementation has
passed the complete quality suite. The recorded result stands without post-result retuning or a
second candidate.
