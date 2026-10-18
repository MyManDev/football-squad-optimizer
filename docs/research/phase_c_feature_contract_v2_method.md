# Phase C feature contract v2: declaration and comparison method

This note declares the second feature contract of the Phase C components and the comparison
it is measured by. It is written before the measurement and is not changed by it. It changes
nothing in the frozen v1 contract, the served feature set or any evaluation protocol, and it
promotes nothing.

## What v2 is

`phase_c_component_form_window_v2` (`COMPONENT_FEATURE_CONFIG_V2`): the v1 feature set plus
the one-gameweek and ten-gameweek windows for minutes and appearance rate. Every column is
the same shifted rolling mean over the player's own season that v1 uses, grouped by season
and player, so a feature for gameweek t reads only gameweeks before t; nothing crosses a
season, no ratio enters, no new source column is read, and the points windows stay (3, 5).

| column set | v1 | v2 |
| --- | --- | --- |
| minutes windows | 3, 5 | 1, 3, 5, 10 |
| points windows | 3, 5 | 3, 5 |
| appearance-rate windows | 3, 5 | 1, 3, 5, 10 |
| pre-match columns | price, fixture count, home fixture count | the same |

A row's route is unchanged: a player's first gameweek of a season has no history and takes
`direct_control`; every later gameweek has a value for every window under
`min_periods = 1`. So the two contracts score exactly the same rows.

## Why

The private research that preceded the gradient-boosting candidate found the extra as-of
features worth about four points of appearance log loss over the product-like set. A
pre-check on the product's own modelling frame (`.codex-tmp/football-ann-research/v2/study-060`,
nine test windows over 2023-24 to 2025-26, 28,117 rows) read the windows alone, with the
gradient-boosting pair, at 0.2955 to 0.2805 appearance log loss, 13.87 to 12.91 minutes MAE
and 0.9360 to 0.9222 points MAE. The cross-season carry-over columns were also tried and are
not part of v2: they are missing for every player without a qualifying earlier season, which
would send half the rows to the fallback route under the no-imputation policy.

## The two arms

Both arms are the gradient-boosting pair (`phase_c_control_components_gbm_v1`, equal
weighting, the declared constants) under the v2 development scope and the same walk-forward
folds; only the feature contract differs.

- **A, control:** the v1 feature contract, the table
  `phase_c_component_oof_development_v2_equal_gradient_boosting`.
- **B, candidate:** the v2 feature contract, `--feature-contract v2`, the table
  `phase_c_component_oof_development_v2_equal_gradient_boosting_features_v2`.

`scripts.compare_component_oof_development --candidate-arm gradient_boosting_windows` reads
both through the development reader, refuses arms that differ in anything but the feature
contract, and applies the v2 acceptance rule unchanged: the candidate is preferred only if
its 2025-26 points MAE is lower, the 90% season-aware moving-block interval of the per-fold
paired differences on 2025-26 lies above zero, and the same interval on 2024-25 does not lie
below zero.

## What a serving change would need

`COMPONENT_HISTORY_WINDOW` is the largest window of the served configuration, and the capture
reads that many settled weeks of live history before a target gameweek. Serving v2 therefore
means captures carrying ten weeks instead of five, and a pin of the v2 contract beside the
served model version in the live path's exact-contract checks. None of that is part of this
declaration.
