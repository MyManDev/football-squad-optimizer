# Rank-probability objective: first rehearsal against a template rival

Artifact: `rank_objective_rehearsal.{json,md}` (contract `rank_objective_rehearsal_v1`,
objective contract `rank_probability_objective_v1`). Runner:
`scripts.run_rank_objective_rehearsal` on the control's residual export
(`calendar_blind_baseline`, 147 folds); 2024-25 folds with at least eight prior folds of
history (37 folds), 100 scenarios per fold, solver 30 s wall / 12 deterministic.
Measurement only; the locked holdout was not read; nothing here reaches the live path.

## What was asked

Per fold the risk-neutral deterministic squad is frozen as the **template rival**. The
rank objective (`optimize_rank_probability_squad`) picks the squad that is ahead of the
template in the most scenarios, at each expected-points budget (how far below the
template's scenario mean the chosen squad may fall: 0, 2, 4, unconstrained). The
optimizer's **claimed** P(ahead) — its share of scenarios won — is compared with the
**realized** frequency of finishing ahead on the fold's actual points.

## What it found (honest negative)

| Budget | Folds | Claimed P(ahead) | Realized ahead [90%] | Ties | Expected cost | Realized cost | Proven |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 0 | 33 | 0.53 | 0.33 [0.22, 0.48] | 7 | -0.38 | +1.24 | 0.82 |
| 2 | 37 | 0.52 | 0.41 [0.28, 0.54] | 2 | +0.79 | +1.59 | 0.11 |
| 4 | 37 | 0.46 | 0.35 [0.24, 0.49] | 1 | +2.27 | +4.14 | 0.03 |
| none | 37 | 0.33 | 0.32 [0.21, 0.46] | 1 | +6.31 | +4.51 | 0.00 |

1. **The claims are optimistic.** At every budget the claimed P(ahead) (~0.5) sits at or
   above the top of the realized interval; among the 27 budget-0 folds the solver
   *proved* optimal, claimed 0.51 against realized 0.22. The squad chosen to win the most
   of 100 sampled scenarios wins fewer real weeks than it says — the same
   selection-time optimism the scenario audit found for expected points, now at the
   scenario level (a winner's curse over the sample). Realized cost also exceeds the
   expected cost at every budget (budget 0: the chosen squads had a *higher* scenario
   mean than the template, −0.38, and still lost 1.24 real points on average).
2. **Ties are real and unmodelled.** With two starters changed on average, 7 of 33
   budget-0 folds ended level; scenario points are continuous and never tie, so a
   "P(ahead)" that counts strict wins is compared with a realized frequency where ties
   count as not-ahead. Any goal statement must say what a tie is.
3. **The solver does not finish.** Only the tightest budget is mostly proven (0.82);
   the unconstrained problem was proven in no fold and its incumbents are *worse* than
   the constrained ones (claimed 0.33 < 0.53) — 100 big-M scenario indicators at
   30 s / 12 deterministic is not enough, and the objective weighting (one scenario
   outweighs any expected-score difference) gives the LP relaxation little to work with.
   Four budget-0 folds returned no solution inside the limit and are absent from the row.

## What this means

The **mechanism** works end to end (rival scored in the same scenarios, shared players
cancel, indicators pinned both ways, menu sweep) and the tests prove it on synthetic
worlds; the **claim** it makes is not yet honest, so it stays a measurement instrument.
It is not offered on the live path and no report states a P(ahead) from it. This is the
"calibration first" gate of the league-relative roadmap, and it failed on the first pass
as it should have been allowed to.

Next steps, in order: (a) claim on **held-out scenarios** — choose the squad on one half
of the scenario sample and report P(ahead) on the other half (or on a fresh draw), the
scenario-level analogue of the selection-optimism shift; (b) state ties explicitly (a
margin of one point, or report ahead / level / behind); (c) fix the formulation before
widening the menu — fewer, better scenarios (the calibrated draw from #103), a scenario
sample the solver can prove, and a warm start from the template; (d) only then rehearse
against a rival that is *not* the template (an ownership-weighted rival from the capture),
which is the case the recommender exists for.
