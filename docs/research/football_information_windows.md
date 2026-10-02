# Football information windows

Measured on 1 October 2026. This package adds a bounded, experimental decision layer to the existing football forecast. It does not retrain the forecast or establish higher realized FPL scores.

## Product contract

Three and five week windows retain the chosen Top100 influence and player preferences. For the team-share v1 producer, an explicit captured 25%, 50% or 75% playing chance can create two possible information updates before the second decision deadline. One held player is selected by expected exposure. Only the next week changes. Later recovery dates are not inferred. Existing conditional minutes and rotation remain in the forecast.

If baseline points are x and source eligibility is p, the eligible branch has x/p and the unavailable branch zero. Their weighted mean remains x. Appearance probabilities use the same transformation and are validated separately. The source percentage was already applied by the producer, so it must not be multiplied twice. This is an assumed information-resolution experiment, not a calibrated injury recovery model. Contextual team-share totals cannot be inverted this way and retain the original planner when fixture components are unavailable.

The decision criterion is current utility plus the probability-weighted utility of legal continuations. Current XI and captain decisions are fixed across both branches. Utility retains the existing bench weight and transfer caution; displayed points use base football forecasts and actual charged hits. Top100 weighting influences selection, not the displayed point gain. Free transfers and bank matter through future feasible decisions, with no added terminal bonus. Purchase lots, Free Hit restoration, dated chips, keep/avoid, no-hit and save-chip preferences pass through the existing state adapters.

At most three distinct first squad/XI/captain/chip actions are compared: the guarded baseline, a legal hold, and a proposal based on one possible information update. Every candidate faces both branches. The total deterministic budget is allocated 40% to the baseline, 10% each to hold and information proposals, 30% to continuations and 10% to nominal reconciliation. All actual solver work is recorded. An incomplete comparison keeps the complete baseline; a wall-clock safety interruption retains the existing refusal semantics. A restricted feasible menu is not a global optimum certificate, so unrelated nominal optimality gaps are not published.

The API publishes the captured source playing percentage and conditional moves, not modeled win/rank probabilities. Future moves are labelled conditional. The football decision cache identity includes the new planner version. Rival-constrained alternatives and automatic chip reservations keep their existing compatible paths rather than receiving unconstrained alternatives.

## Complete-policy revision

The complete_observed_window_v2 consumer reuses entire feasible decision sequences. It refreshes forecasts only, then independently certifies each sequence in the final constrained model before bounded improvement. Every branch contains today and all later weeks on the original clock. Purchase lots, sale rules, bank, free transfers and dated chip rights are never reconstructed from a sliced suffix. The first squad, XI, captain and chip are fixed across both information branches.

The existing hold certificate is also reused inside the hold proposal's allocation. When that phase has more than one deterministic unit, one unit is reserved for a constrained, full-horizon no-transfer probe and the remainder funds a search that can still transfer in later weeks. Both probe and search work are charged; their wall ceilings also fit the phase. A probe interrupted by the clock is refused. The small-budget path does not add an unbudgeted probe.

An optional information proposal may fail without discarding two already complete alternatives. A comparison requires at least two distinct feasible current actions; a one-action menu reports no_distinct_alternative. Every admitted action must complete both branches. Certified policy utility is also protected on the unrounded comparison scale, since a rounded integer-objective optimum can lose a small amount of unrounded utility. Returned selection status is FEASIBLE with cleared optimum bounds; physical search status is recorded separately.

Weighted experimental requests now use one selected-weight planner invocation. Base football points, source counts and the selected Top100 setting remain published. Counts from the captured previous week are carried through the window. An uncomputed second, zero-weight plan is not used to claim a paired cost or changed-player attribution. Existing current-model and rival routes retain their contracts.

The first cold-capture matrix passed thirteen of fourteen combinations. Five weeks at Top100 50 correctly reported no_distinct_alternative because its cold hold proposal exhausted ten units without a solution. That recorded failure motivated the general hold-certificate reuse above, without enlarging any phase or changing the forecast. The corrected case completed in 92.83 seconds with two actions, both full branches and 84.83653 of 100 units. The completed final matrix is recorded below. These reused-capture runs measure completion and accounting, not prospective football accuracy.

## Final complete-policy acceptance

A fixed 667-player captured forecast covered GW6 to GW10. All fourteen cold application requests used one planner invocation and completed at least two distinct current actions, with both full-horizon information branches. Every selected candidate met the same baseline utility floor. All seven three-week settings completed in 43.47 to 49.75 seconds; all seven five-week settings in 90.00 to 97.80 seconds. The original acceptance cases were three weeks at Top100 0 and five weeks at Top100 20. Their times were 45.50 and 93.15 seconds.

| Weeks | Top100 | Actions | Seconds | Actual work / budget | Utility gain |
| --- | --- | --- | --- | --- | --- |
| 3 | 0 | 2 | 45.50 | 47.71857 / 60 | 0.00000 |
| 3 | 5 | 2 | 48.03 | 50.50444 / 60 | 0.00000 |
| 3 | 10 | 2 | 48.02 | 47.57157 / 60 | 0.00000 |
| 3 | 20 | 2 | 49.75 | 50.56870 / 60 | 0.00000 |
| 3 | 30 | 2 | 45.00 | 47.89038 / 60 | 0.00000 |
| 3 | 40 | 2 | 43.47 | 46.91135 / 60 | 0.00000 |
| 3 | 50 | 2 | 44.40 | 48.04710 / 60 | 0.00000 |
| 5 | 0 | 2 | 93.54 | 84.83913 / 100 | 0.00000 |
| 5 | 5 | 3 | 90.00 | 85.00554 / 100 | 0.00000 |
| 5 | 10 | 2 | 91.35 | 84.86381 / 100 | 0.00000 |
| 5 | 20 | 3 | 93.15 | 84.99177 / 100 | 0.00000 |
| 5 | 30 | 2 | 97.80 | 84.83528 / 100 | 0.00000 |
| 5 | 40 | 3 | 91.07 | 85.02986 / 100 | 0.00000 |
| 5 | 50 | 2 | 92.83 | 84.83653 / 100 | 0.00000 |

All final selections retained the baseline. An intermediate five-week Top100 5 run had gained 1.4240779 selection-utility units, but that gain did not reproduce after reserving the hold certificate. The same first hold action obtained a weaker later transfer policy under bounded search. Its legality and arithmetic passed independent replay. This quality/completion tradeoff is retained in the evidence, not tuned away on this capture.

Machine-readable results are in [football_complete_policy_acceptance.json](football_complete_policy_acceptance.json). Source budget, state and full-branch invariants were independently reviewed. These numbers are local completion evidence; they do not substitute for full quality gates or the separate deployed and phone acceptance.

## Historical v1 controlled information comparison

The following four rows describe the previous v1 layer; their one-action menus do not satisfy the v2 requirement for two distinct current actions. The configuration was fixed before measurement: eight-player synthetic roster, three/five weeks, source chance 25/75, five deterministic units per method, 120 second safety ceiling, bench weight 0.1, selection hit penalty 8 and actual hit charge 4, at most one move per week. The comparator receives the full five-unit guarded nominal budget. No cases were used for parameter fitting.

| Weeks | Source chance | Guarded nominal net | New nominal net | Conditional expected net | New actual deterministic work |
| --- | --- | --- | --- | --- | --- |
| 3 | 25% | 86 | 86 | 86 | 0.01025 |
| 3 | 75% | 89 | 89 | 89.75 | 0.00906 |
| 5 | 25% | 146 | 146 | 146 | 0.03529 |
| 5 | 75% | 149 | 149 | 149.75 | 0.03066 |

All four first actions were unchanged. The information menu gained zero utility over its own baseline first action in all four cases. The 0.75 conditional difference in two cases values hypothetical later information against a fixed nominal plan. It does not show improvement over the deployed planner, which can also replan next week. No measured live uplift is claimed.

A separate constructed correctness case checks an actual first-action change: selling an appreciated player makes him unaffordable to buy back if good news arrives. The nominal plan sells; the information plan holds, retains him after good news and sells after bad news. The hand-designed utility difference is 0.4. This tests the decision mechanism and purchase-price option, not predictive accuracy or empirical uplift. It was added during self-review and is not part of the preregistered four-case comparison.

## Shared football-world diagnostic

The new window consumer accepts explicit player-fixture components and uses the existing shared goal/assist, opponent, clean-sheet, minute and DEFCON sampler. Official substitutions, captain/vice, chips and charged hits use the existing scorer. All candidate plans face the same 64 worlds, seed 31, with week-specific seeds. Worlds across weeks are independent. Double fixtures are combined; blank weeks have no invented playing points. This diagnostic evaluates fixed plans and does not optimize after seeing sampled realized points.

Inputs were wholly generated by the existing football development test fixture, including its synthetic season label. No season archive or 2025-26 holdout was read. Windows start at synthetic GW16 (blank), with a doubled GW17 and ordinary later weeks. A balanced legal roster uses the last GK/MID and first DEF/FWD players, matching the existing candidate application fixture. Both nominal and fixed-hold plans use three deterministic units and a 120 second ceiling. The first attempt correctly refused the initially invalid four-per-club hold roster; it produced no comparison. The valid roster was corrected before the recorded run.

| Weeks | Nominal plan sample mean | Hold sample mean | Paired difference | Nominal p10 | Hold p10 |
| --- | --- | --- | --- | --- | --- |
| 3 | 123.17 | 116.49 | 6.68 | 99.01 | 93.15 |
| 5 | 211.47 | 200.59 | 10.88 | 180.44 | 175.76 |

These numbers compare the existing nominal optimizer with doing no transfers on synthetic draws. They are not gains caused by the new information layer. The sampler's player-fixture mean point gaps against analytic expectations ranged from -0.1793 to -0.0379 by nonblank week; mean absolute gaps ranged from 0.3148 to 0.3643. These finite-sample differences remain visible rather than being corrected using test outcomes. Detailed diagnostics are in football_information_worlds.json.

The deployed weekly artifact has expected points and appearance probabilities, not explicit fixture components. It cannot support reconstructed joint match events. The shared-world consumer is available for explicit components but is not a live scenario selector. No unsupported component is enabled by default. The available observation layer is integrated into experimental football windows; the joint-world diagnostic is separate.

## Parameter search and limitations

BoTorch is declared as an optional research dependency but is not installed in the current runtime. More importantly, no independent cohort of captured information and subsequent outcomes is available for this package. No dependency was installed and no BO, RL or ANN search was run. Fixed, recorded allocation is preferable to tuning against these reused synthetic examples.

Covered functional behavior includes complete 3/5-week decisions, no double availability scaling, shared first actions, source timing, transaction prices, bank/FT, dated chips, incomplete-budget fallback, base-point rescoring, API/worker cache separation, user preferences and conditional UI explanations. Prospective realized performance, calibrated recovery timing, correlated injuries and joint fixture scenarios from live artifacts remain unmeasured or unavailable.
