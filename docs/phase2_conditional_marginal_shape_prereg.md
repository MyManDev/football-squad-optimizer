# Phase 2 conditional marginal-shape diagnostic

Status: pre-registered exploratory development reuse. This study is not independent
confirmation, is not a promotion gate, and may not read the locked 2025-26 holdout.

## Question

The preceding marginal-source diagnostic found that the selected-XI q25 miss is carried mainly
by players who actually completed at least 60 minutes in 2022-23, 2023-24 and 2024-25. Their
mean residual stays close to zero, so a mean shift alone cannot explain why their realized
downside rate is much greater than the canonical scenario expectation.

This study distinguishes two remaining mechanisms without changing production:

1. the pre-fold raw residual pool already carries an adequate marginal left tail, but the
   hierarchical centering, decomposition, scaling and independent recombination used by the
   canonical generator erase it;
2. even the raw residual pool does not carry the selected player's required conditional shape,
   in which case a projection-conditional or discrete outcome model is needed before changing
   dependence.

An appearance-conditioned raw arm is included to ask whether explicitly separating completed
appearances is necessary. No arm becomes a production candidate in this study.

## Frozen population and replay

The fold universe, residual export, projection model, optimizer decision, selected XI, scenario
matrix, q25 definition, scenario count, seed, frozen shift and chronological history boundary
are exactly those in `phase2_marginal_downside_sources`. Only selected starters whose realized
minutes are at least 60 enter this comparison. Minutes are post-outcome data used only after the
decision and all three thresholds are frozen.

The same 2024-25 full-score replay must reproduce the recorded mean PIT and S2 rate to
`1e-12` before an artifact may be written. Roles remain:

- 2021-22 and 2022-23: screening;
- 2023-24: descriptive validation classification;
- 2024-25: already observed development sensitivity;
- 2025-26: locked and forbidden at the loader boundary.

## Three fixed marginal arms

For every eligible starter, compute three q25 residual thresholds from the exact pre-fold history:

1. **canonical** — the existing hierarchical scenario-marginal threshold and its measured
   scenario event rate; nothing is regenerated or reoptimized;
2. **raw unconditional** — direct empirical residuals, with no centering, decomposition,
   standardization, scaling or recombination;
3. **raw completed appearance** — the same direct empirical rule after joining historical
   residual rows to their canonical panel outcomes and retaining `minutes >= 60`.

Both raw arms use the generator's existing source hierarchy and minimum-observation rule:

- use that player's pool when it has at least `ScenarioConfig.min_player_observations`;
- otherwise use the player's position pool;
- otherwise use the pooled history;
- refuse if the chosen pool is empty or contains a non-finite value.

The empirical q25 uses NumPy's linear quantile. Its expected downside rate is the fraction of
the same source pool strictly below that threshold, rather than an assumed 0.25; this preserves
ties and discreteness. The realized event uses the same strict comparison.

## Summaries

For every season and pooled, report each arm's starter rows, source hierarchy counts, realized
and source-expected event rates, and the fold-level paired gap
`realized event - expected rate`. Report the mean gap and a fold-clustered 90% bootstrap
interval with 5,000 resamples and seed 0. Also report mean q25 threshold. The canonical arm's
numbers must reconcile with the completed-appearance rows in
`phase2_marginal_downside_sources`.

## Descriptive classification

Only 2023-24 assigns one label. A gap is *compatible with zero* when its pre-registered 90%
bootstrap interval contains zero.

- `appearance_conditioning_candidate`: only the raw completed-appearance interval contains
  zero;
- `direct_marginal_recombination_candidate`: only the raw unconditional interval contains
  zero;
- `direct_marginals_both_adequate`: both raw intervals contain zero while the canonical
  interval does not;
- `conditional_marginal_shape_unresolved`: neither raw interval contains zero, the canonical
  interval contains zero, fewer than 30 folds are available, or any required row is missing.

The first and third labels make direct empirical marginal preservation worth a separate
candidate study; they do not choose an implementation. The second is descriptive and needs
explanation before use. The unresolved label sends the next study toward expected-points bins,
position-specific discreteness or a two-part appearance/returns model.

## Limits

This is development reuse after the failure was observed. Bootstrap intervals are diagnostic,
not confirmatory. Conditioning on realized minutes is valid for source attribution but is not a
live feature. No result changes scenario generation, projections, optimization, publication or
evidence status, and no probability is published.
