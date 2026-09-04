# Pre-registration: the play-mode price list

Written **2026-08-19, before the measurement runs**. The modes, the grid, and the gate are
fixed here so none of them can be adjusted after the numbers arrive.

## What is being measured, and why now

The product will let a manager choose a **play mode**. One family is rival-independent:
**Saf Puan** — maximise expected points, which is today's default behaviour under a new
name, and it is not measured here because it is the existing control. The other family is
competitive, played against rivals in the manager's league:

| Mode | `margin_points` | Reading |
| --- | ---: | --- |
| **Garantici** | −0.001 | a level finish counts as success — defend a position |
| **Agresif** | 0.0 | finish strictly ahead — today's only implemented target |
| **Aşırı Agresif** | +5.0 | finish at least five points ahead — a small win is no win |

Each mode is priced across the four expected-points budgets already in the rehearsal
(0, 2, 4, unbounded), giving a 3 × 4 grid. The rehearsal is unchanged
(`rank_objective_rehearsal_v2`, 2024-25, 37 folds, 100 scenarios per fold,
`held_out_half` claim scenarios, rival = the fold's risk-neutral squad). The margin dial
already exists in `RankObjectiveConfig` and accepts negative values; no solver code changes.

`rank_cost_calibration` (2026-08-19) established that the accounting is honest — expected
cost tracks realized cost (+1.339 vs +1.365 pooled) and the held-out claim tracks the
realized frequency. What it also found is the motivation here: the single implemented
target finishes **behind more often than ahead at every budget**, because it values a tie
at zero. Whether the other targets buy what their names promise is exactly what a mode
price list has to answer before a mode selector can be put in front of a user.

## The gate, fixed now

The product feature is a **selector**, and a selector is only honest if the options differ.

- **Separation (must pass):** Garantici at budget 0 must reduce the frequency of finishing
  behind, relative to Agresif at budget 0, with the fold-level bootstrap 90% interval of
  the difference excluding zero. That is the pair the two mode names disagree about most
  directly, at the budget where the solver proves optimality most often.
- **Direction (must pass):** pooled over budgets, P(behind) must be lowest under Garantici,
  and P(ahead by more than five) must be highest under Aşırı Agresif. Each mode must be
  best at the thing its name claims.
- **Honesty (must hold, inherited):** within every cell, the held-out claimed probability
  must stay within ten percentage points of the realized frequency, as it did in the
  calibration run.

If separation fails, the recorded conclusion is that the modes are indistinguishable on
this rehearsal and **the mode selector does not ship on this evidence** — a smaller margin
grid or a different rival is future work, not a retroactive adjustment. If direction fails
for one mode, that mode is dropped from the product mapping and the others stand.

## What this does not claim

Prices are measured against the fold's own risk-neutral squad in a two-manager duel. A
real league has more managers and a real rival is not the risk-neutral squad; the template
rival built from ownership (measured separately) and, once league payloads exist, real
league rivals will re-price the same grid. One season, 37 folds: intervals will be wide,
and the price list ships with them shown.
