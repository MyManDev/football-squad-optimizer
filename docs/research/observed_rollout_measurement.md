# Observed rollout measurement

The 14-case full-universe sensitivity completed with 0 failures. Expanded proposals improved supplied weighted forecast value in one case, choosing an action outside the baseline-plus-hold menu. Raw forecast points decreased in that same case; preference-utility gains must not be presented as point-prediction gains.

These are retrospective engineering comparisons on one immutable capture, two constructed squads and authored low/high forecast stresses. They are not realized points, calibrated injury probabilities, independent season replications or evidence for a live model promotion.

## Paired results

Each control is the best baseline-plus-hold action evaluated with exactly the same continuations as the expanded menu. A nonnegative delta is therefore a menu-inclusion property. Its magnitude and the frequency of different first actions are the measurements. It is not an independent re-run speed comparison or a global MDP bound.

Baseline indices identify squad/chip resource transitions after deduplication. If another proposal supplies a better current XI or captain for that same transition, both menus receive it. The ablation therefore isolates additional resource transitions, not the original proposal lineups before deduplication.

| Squad | Weeks | Top100 | Constraints | Status | Weighted delta | Raw point delta | Chosen min node | Expected hits |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| 1000 | 3 | 0 | none | OPTIMAL_RESTRICTED_MENU | 0.000000 | 0.000000 | 157.214175 | 0.00 |
| 1000 | 3 | 20 | none | OPTIMAL_RESTRICTED_MENU | 0.000000 | 0.000000 | 156.086367 | 2.00 |
| 1000 | 3 | 50 | none | OPTIMAL_RESTRICTED_MENU | 0.340046 | -0.172988 | 155.381816 | 2.00 |
| 1000 | 5 | 0 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 264.810299 | 0.00 |
| 1000 | 5 | 20 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 265.419073 | 2.00 |
| 1000 | 5 | 50 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 262.423861 | 2.00 |
| 900 | 3 | 0 | none | OPTIMAL_RESTRICTED_MENU | 0.000000 | 0.000000 | 152.847670 | 0.00 |
| 900 | 3 | 20 | none | OPTIMAL_RESTRICTED_MENU | 0.000000 | 0.000000 | 152.801860 | 0.00 |
| 900 | 3 | 50 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 147.444355 | 4.00 |
| 900 | 5 | 0 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 259.069829 | 0.00 |
| 900 | 5 | 20 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 258.613748 | 0.00 |
| 900 | 5 | 50 | none | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 250.424204 | 4.00 |
| 1000 | 5 | 20 | keep/no hits/save chips | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 262.975140 | 0.00 |
| 900 | 5 | 20 | keep/no hits/save chips | FEASIBLE_RESTRICTED_MENU | 0.000000 | 0.000000 | 254.219535 | 0.00 |

## Interpretation and limits

The selected Top100 setting remains a user preference. Weighted utility and raw forecast points use different units and are both retained. The minimum information-node value is a sensitivity statistic, not a downside percentile. FEASIBLE means a complete legal policy was found without an optimality proof. OPTIMAL_RESTRICTED_MENU refers only to the generated menu and the integer-scaled subproblem objectives.

The scenario authoring time is the actual analysis time, after the old capture. This is not a historical decision-time replay. The protocol, input hashes, source hashes, every candidate and all failed cases are retained in the accompanying JSON. Attempt 01 was stopped before a case completed because its runner incorrectly assigned the old capture time to newly authored stresses; no result from that attempt is used.

No BoTorch search was run: this ablation changes candidate generation without fitting parameters. Optimizing a new parameter against these same authored forecasts would not identify future policy quality. Existing negative terminal-value evidence and the future evaluation boundary are preserved.

The new explicit-lookahead service separately passes synthetic 3/5-week resource-retention counterexamples. This matrix does not measure that service. The captured artifact contains only five weeks, so a five-week decision window has no supplied tail. No missing forecasts or sale-price paths were fabricated.

The service is an opt-in offline application path. Website defaults, published advice, production prediction identities and backend processes are unchanged. A broader information process, path-dependent purchase lots beyond the first transition and independent future outcomes remain necessary before claiming better season decisions.

See [mathematical contract](observed_rollout.md) and [machine-readable evidence](observed_rollout_measurement.json).
