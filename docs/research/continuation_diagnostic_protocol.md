# Chronological continuation diagnostic, declared before fitting

Sources: the 24 explicitly enumerated historical season-chain files in night45-input-audit.json, with their SHA256 hashes. They contain 80 chains and 2940 decision records, all previously consumed development evidence. No live owner state, new outcome fetch or unpublished future event is used.

Target: mean realized net points over the next 3 or 5 calendar weeks under the recorded continuation policy, after the recorded decision. Only complete contiguous target windows qualify. Current-week realized points, bench/captain outcomes and future planned chips are never features. No row may bridge a missing calendar week or a season boundary.

Six decision-time features, fixed now: gameweek, bank_after_tenths, squad_sell_value_tenths, free_transfers_after, projected_points and transfer_count. Do not fabricate injury, fixture, purchase-lot, renewable-chip or tactical features missing from the artifacts. These coarse features describe a partial observation, not a Markov state. Current projections are those of the original historical runner, not the modern football model.

Train: 2021-22 and 2022-23. Select: 2023-24. Diagnostic evaluation: 2024-25, already consumed in earlier research and explicitly NOT an independent holdout. Entire seasons and all alternative chains for a deadline stay in one partition. Within each partition weight every (season, gameweek) group equally, so policy variants do not manufacture sample size. Standardization fits training only. After selection, refit train + selection; evaluate each final model once. No cross-season future-to-past fits.

Controls: weighted training mean, Ridge(alpha=10), HistGradientBoostingRegressor(max_leaf_nodes=7,max_iter=100,min_samples_leaf=30,l2_regularization=20,random_state=0). ANN: four prespecified MLPRegressor configurations, one hidden layer of 16 or 32 ReLU units, alpha 1 or 10, lbfgs, max_iter=500, seed=0 for selection. Pick minimum group-weighted validation MAE (stable order ties). Refit only selected ANN with seeds 0,1,2. Existing sklearn 1.9.0 supports sample weights; no new dependency.

Fallback: for any feature outside the training min/max box, nonfinite features or predictions, return the weighted training mean and record fallback coverage. Fit failures and nonconvergence are reported, not hidden or tuned away. Controls and ANN share the same observation-domain fallback. Missing fields and nonfinite training values reject the dataset.

Report per-window group-weighted MAE/RMSE, coverage, selected configuration, seed spread and actual fit warnings. If comparing uncertainty, aggregate errors by deadline before moving-block resampling (block length 5, 2000 draws, 95%). This estimates dependent development error differences, not independent policy gains. Lower target MAE alone cannot satisfy the night-plan promotion rule. No ANN term is added to the optimizer; archived alternative chains are not counterfactual actions from the same full state. IQL/CQL/fitted-Q training on these incomplete logs is ineligible.

This diagnostic is a different target and chronological design from the earlier failed end-of-season Gaussian process. The same old data remain development data. A useful outcome is deciding whether to collect richer prospective state/action/observation records, not announcing a better live planner.
