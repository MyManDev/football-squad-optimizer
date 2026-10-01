# Football information windows

Measured on 1 October 2026. This package adds a bounded, experimental decision layer to the existing football forecast. It does not retrain the forecast or establish higher realized FPL scores.

## Product contract

Three and five week windows retain the chosen Top100 influence and player preferences. For the team-share v1 producer, an explicit captured 25%, 50% or 75% playing chance can create two possible information updates before the second decision deadline. One held player is selected by expected exposure. Only the next week changes. Later recovery dates are not inferred. Existing conditional minutes and rotation remain in the forecast.

If baseline points are x and source eligibility is p, the eligible branch has x/p and the unavailable branch zero. Their weighted mean remains x. Appearance probabilities use the same transformation and are validated separately. The source percentage was already applied by the producer, so it must not be multiplied twice. This is an assumed information-resolution experiment, not a calibrated injury recovery model. Contextual team-share totals cannot be inverted this way and retain the original planner when fixture components are unavailable.

The decision criterion is current utility plus the probability-weighted utility of legal continuations. Current XI and captain decisions are fixed across both branches. Utility retains the existing bench weight and transfer caution; displayed points use base football forecasts and actual charged hits. Top100 weighting influences selection, not the displayed point gain. Free transfers and bank matter through future feasible decisions, with no added terminal bonus. Purchase lots, Free Hit restoration, dated chips, keep/avoid, no-hit and save-chip preferences pass through the existing state adapters.

At most three distinct first squad/chip actions are compared: the guarded baseline, a legal hold, and a proposal based on one possible information update. Every candidate faces both branches. The total deterministic budget is allocated 40% to the baseline, 10% each to hold and information proposals, 30% to continuations and 10% to nominal reconciliation. All actual solver work is recorded. An incomplete comparison keeps the complete baseline; a wall-clock safety interruption retains the existing refusal semantics. A restricted feasible menu is not a global optimum certificate, so unrelated nominal optimality gaps are not published.

The API publishes the captured source playing percentage and conditional moves, not modeled win/rank probabilities. Future moves are labelled conditional. The football decision cache identity includes the new planner version. Rival-constrained alternatives and automatic chip reservations keep their existing compatible paths rather than receiving unconstrained alternatives.

## Controlled information comparison

The configuration was fixed before measurement: eight-player synthetic roster, three/five weeks, source chance 25/75, five deterministic units per method, 120 second safety ceiling, bench weight 0.1, selection hit penalty 8 and actual hit charge 4, at most one move per week. The comparator receives the full five-unit guarded nominal budget. No cases were used for parameter fitting.

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
