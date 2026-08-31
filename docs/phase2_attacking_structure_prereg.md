# Phase 2 attacking downside structure diagnostic

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Question

The exact score-component attribution found that replacing the selected XI's attacking-point
surprise with its leakage-safe historical mean removes much of the recorded lower-tail miss,
but it did not identify why. This study asks one narrower question before any attacking model
is proposed:

> Is the attacking miss explained by player-level blank frequency, a common gameweek shock,
> same-team clustering, or none of those mechanisms with the available support?

No scenario generator, optimizer, projection, canonical schema or live path changes here. The
study measures the outcome structure of the same fixed selected XIs. It does not tune a
threshold or authorize a production candidate.

## Frozen population and chronology

The residual export and manifest, archive pin, projection model, fold universe, optimizer
settings, selected squad, starting XI, captain, scenario configuration, seed and chronological
history are exactly those used by `phase2_component_attribution_v1`.

Roles remain:

- 2021-22 and 2022-23: descriptive screening;
- 2023-24: classification population;
- 2024-25: already observed directional sensitivity;
- 2025-26: locked and forbidden before any filesystem read.

Development folds use only `fold.prior_fold_ids`. Every 2024-25 fold uses one history frozen at
the end of 2023-24. The target and future are rejected at the boundary. The study must
reproduce the recorded 29/36/37/37 fold universe, 1,529 selected-starter rows, exact Phase 2H
attacking surprise summaries and 2024-25 control replay before an artifact may be written.

## Fixed attacking blank event

The structural event is fixed before any subgroup output is read:

```text
completed appearance = realized minutes >= 60
attacking blank       = completed appearance and realized attacking points == 0
```

Only completed appearances enter the structural metrics. Zero-minute and 1-59-minute starters
are reported separately, because they have a different opportunity to return, but they do not
select a source pool and are not silently counted as attacking blanks. No alternative event
threshold will be tried in this study.

For each eligible target starter `i` in fold `f`, the pre-fold blank probability `q[f,i]` is the
empirical blank rate in the first available completed-appearance pool:

1. same stable player and current position with at least 8 completed appearances;
2. same position;
3. pooled completed appearances.

The source order is fixed. Target outcomes, future folds and 2024-25 outcomes are unavailable
to a 2024-25 source pool. Captaincy does not create a second observation: every structural
metric contains each eligible starter once. Captain weighting is retained only to reconcile
the Phase 2H attacking-score surprise.

## Fold-level diagnostics

Let `X[f,i]` be the attacking-blank indicator, `q[f,i]` its historical probability, and
`e[f,i] = X[f,i] - q[f,i]`.

### Player-level marginal frequency

```text
G[f] = mean_i e[f,i]
```

Positive `G` means attacking blanks occur more often than the historical marginal model says.
Marginal adequacy is an equivalence claim, not a failure to reject zero: the 90% interval for
mean `G` must lie wholly inside `[-0.05, +0.05]`.

### Common gameweek dependence

For `N[f] = sum_i X[f,i]`, `mu[f] = sum_i q[f,i]` and
`V[f] = sum_i q[f,i] * (1 - q[f,i])`:

```text
O[f] = (N[f] - mu[f]) ** 2 - V[f]
```

`O` is excess blank-count dispersion relative to independent heterogeneous Bernoulli
marginals. It is supported by the mean centred product among different-team pairs:

```text
U[f] = mean_(team_i != team_j) e[f,i] * e[f,j]
```

Neither raw joint blank rates nor a pooled-binomial approximation are used.

### Same-team clustering beyond the common shock

For folds containing both pair types:

```text
K[f] = mean_(team_i == team_j) e[f,i] * e[f,j]
       - mean_(team_i != team_j) e[f,i] * e[f,j]
```

This is a same-team selected-player contrast, not a fixture-level causal effect. The current
player-gameweek contract cannot separate team, opponent-fixture and double-gameweek mechanisms
without a new time-aware fixture contract, so this study will not claim that distinction.

## Support, uncertainty and sensitivity

All uncertainty is fold-clustered: 5,000 bootstrap resamples, 90% percentile intervals and seed
0. Player and pair rows are never independent resampling units. A missing pair type makes the
fold unavailable for that metric; it is not imputed as zero.

Classification requires at least 30 eligible 2023-24 folds for `G`, `O` and `U`, at least 30
eligible folds with both pair types for `K`, both blank and non-blank observations overall, and
the frozen population/control/component reconciliations. Source and pair counts are recorded.
The 2024-25 sensitivity season is direction-only and cannot create a positive classification.

The metrics use all eligible validation folds. They are not fitted only on control q10 failures:
conditioning the dependence estimate on the total-score tail would mechanically select the
outcome being explained. Control-tail contrasts may be reported as descriptive context only and
cannot affect the classification.

## Frozen classification tree

The tree is evaluated in this order:

1. Any population, chronology, identity, replay or minimum-support failure returns
   `diagnostic_inconclusive`.
2. If the 2023-24 90% interval for mean `G` lies wholly above `+0.05` and the 2024-25 mean is
   non-negative, return `attacking_marginal_blank_excess`.
3. If that interval lies wholly below `-0.05` and the 2024-25 mean is non-positive, return
   `attacking_structure_wrong_direction`.
4. If the interval is not wholly inside `[-0.05, +0.05]` and neither prior directional rule
   applies, return `diagnostic_inconclusive`. Common and same-team metrics remain descriptive
   because incorrect marginals confound their interpretation.
5. With equivalent marginals, common-gameweek dependence passes only when the lower bounds of
   both 2023-24 mean `O` and mean `U` are strictly above zero, and both 2024-25 point estimates
   are non-negative.
6. With equivalent marginals, same-team clustering passes only when the 2023-24 mean `K` lower
   bound is strictly above zero and its 2024-25 point estimate is non-negative.

The resulting classes are:

- `shared_attacking_structure` when common-gameweek and same-team gates both pass;
- `common_gameweek_attacking_shock` when only the common-gameweek gate passes;
- `same_team_attacking_cluster` when only the same-team gate passes;
- `attacking_structure_not_localized` when neither gate passes;
- the marginal, wrong-direction or inconclusive classes defined above.

## Interpretation limits and stop rule

This is a descriptive structural diagnostic. The completed-appearance restriction uses realized
minutes and therefore is not a live feature. Estimated historical blank probabilities are a
transparent reference, not a claim that they are the best forecast. `O` and `U` are consistency
checks derived from the same blank vector, not independent experiments. Same-team membership is
not proof of a fixture mechanism.

Exactly one binding run is authorized after this document is committed and the implementation
passes the full quality suite. The result chooses at most the subject of a separate
pre-registration. It does not authorize parameter sweeps, alternative blank definitions,
hierarchical models, Monte Carlo changes, a candidate transform, promotion or production use.
