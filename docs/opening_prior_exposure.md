# What the opening price prior carries, and what refitting it moves

Artifacts: `opening_prior_exposure.{json,md}` (contract `opening_prior_exposure_v1`). Runner: `scripts.measure_opening_prior_exposure`. 147 development folds, `2021-22-gw02` to `2024-25-gw38`, 101,447 player-gameweek rows -- the same count `in_season_residual_export` reports over the same folds, which is the cheapest available check that this is the benchmark's population and not a differently shaped one. The locked holdout is cut from the panel before any feature window can reach it.

## Why this exists

`in_season_blend_benchmark.md` records a caveat about its own headline and names this as the first thing a follow-up should do: `FITTED_OPENING_PRICE_COEFFICIENT` was fitted on opening rows from 2020-21 through 2024-25, the same seasons these folds evaluate, so a control-versus-blend gap could partly reflect differing reliance on that constant rather than projection quality.

The reliance is **measured, not re-derived**. Each projection is built at the coefficient `c` and again at `c * (1 + e)`; a row's attributable mass is the difference divided by `e`, which is `c * d(points)/dc`. That is the row's whole projection where the prior priced it outright, the carried portion where a rung is shrunk toward it, and zero everywhere else -- one quantity, correct on every rung, and incapable of drifting from the precedence rules because it interrogates them.

## What it found

**The differing reliance the caveat suspected is real, and it is large.** The archive-fed control takes 0.79% of its projected points from the constant; the blend takes 29.58% and the carry-over floor 35.26%. Nearly half the blend's and the floor's rows touch it at all (45.59%) against 0.71% of the control's. The two arms of the headline are not leaning on that constant to remotely the same degree.

**And it is almost absent where a decision is made.** Restricted to a squad-shaped selection, the same shares are 0.00%, 0.46% and 0.00%. The reliance is concentrated in players the prior prices at a point or two -- who are exactly the players an optimizer does not pick. So the exposure is enormous in the row population and near zero in the selected one, and those two facts have to be read together or either one misleads.

**Refitting it honestly moves it up, not down.** Every walk-forward coefficient is *larger* than the frozen one, converging toward it as seasons accumulate (+0.0352 on one season of history, +0.0038 on four), and the resulting level shifts are at most +0.0447 mean projected points. If the in-sample fit biases anything it is downward, which is the opposite direction from the one the caveat worried about.

**The projection-level gap does not even carry the sign of the decision-level one, and that is the most important line in this record.** The blend projects **-0.1696** mean points against the carry-over floor -- it projects *lower* -- while the benchmark measures it **+13.78 realized squad points** *higher*. The mechanism is legible (the floor over-prices the many players who will not appear, which lifts a mean over a hundred thousand rows while doing nothing for the top of the ranking), but the point stands regardless of mechanism: no number in this record may be read as a correction to the `+13.78`, because the two quantities disagree in sign on this very pair.

## How much each projection leans on the constant

| configuration | rows | rows touching the prior | share | attributable share of projected points | same, squad-shaped selection |
| --- | ---: | ---: | ---: | ---: | ---: |
| `control-fw05` | 101,447 | 725 | 0.0071 | 0.0079 | 0.0000 |
| `blend-m270-g6-declared` | 101,447 | 46,254 | 0.4559 | 0.2958 | 0.0046 |
| `carry-over-only` | 101,447 | 46,254 | 0.4559 | 0.3526 | 0.0000 |

The last column is a **proxy** for the population a squad optimizer selects, not the squad: the best two keepers, five defenders, five midfielders and three forwards by projection. It respects the position quotas and ignores budget and the per-club limit, so it overstates what is reachable. It is here because reliance concentrated in players nobody would pick means something quite different from reliance at the top of the ranking -- and that is what separates the first two columns from the third.

## The constant, refit walk-forward

Frozen: **0.29940565**, fitted on 2020-21 through 2024-25. Refit per season on the seasons completed before it, through the same `fit_opening_price_coefficient` the production path uses.

| season | fitted on | coefficient | difference from frozen |
| --- | --- | ---: | ---: |
| 2021-22 | 2020-21 | 0.33463315 | +0.03522750 |
| 2022-23 | 2020-21, 2021-22 | 0.32728779 | +0.02788215 |
| 2023-24 | 2020-21, 2021-22, 2022-23 | 0.31591668 | +0.01651104 |
| 2024-25 | 2020-21, 2021-22, 2022-23, 2023-24 | 0.30324540 | +0.00383976 |

## What the refit does to the level

| configuration | mean projected points, frozen | refit | shift |
| --- | ---: | ---: | ---: |
| `control-fw05` | 1.2222 | 1.2230 | +0.0007 |
| `blend-m270-g6-declared` | 1.5948 | 1.6281 | +0.0333 |
| `carry-over-only` | 1.7645 | 1.8091 | +0.0447 |

The pairs the benchmark's headline is built from, at the projection level:

| pair | gap, frozen | gap, refit | move |
| --- | ---: | ---: | ---: |
| `blend-m270-g6-declared` vs `carry-over-only` | -0.1696 | -0.1810 | -0.0114 |
| `blend-m270-g6-declared` vs `control-fw05` | +0.3726 | +0.4051 | +0.0325 |

## The estimator, checked rather than asserted

The claim that the finite difference is exact rests on the dependence being piecewise linear in the coefficient. Every configuration was therefore measured at two probe scales (`1e-06` and `0.0001`), and the largest relative disagreement between them on any fold is **1.978e-10**. A material disagreement would mean rows sitting on the zero clip, where the dependence bends and a wider probe steps across it; at this magnitude the clip changes nothing this record reports.

## What this decides

Nothing. `measurement_only` is true and `gate_evidence` is false. No declared constant moves: changing one after seeing a surface is choosing the outcome, and a better value would be a separate pre-registered candidate with its own gates.

**Every number here is projection-level.** The benchmark's `+13.78` is *realized squad points*, and prediction quality and decision quality are different quantities that can disagree -- which is why the research agenda scores the decision rather than only the prediction. Converting these shifts into realized points needs the optimizer and the evaluator on every fold, in both coefficient regimes. That run is the named next step; it is not estimated here from a projection-level number, because an estimate is exactly what this record exists to replace.
