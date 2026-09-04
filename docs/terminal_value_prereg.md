# Pre-registration: a Gaussian-process terminal value for the squad state

Written **2026-08-20, before any model is fitted**. The features, the baseline, the split
and the gate are fixed here so none of them can be adjusted after the numbers arrive.

## Why

Every rolling-horizon planner in this repository strips value at its edge: a five-week
plan prices week six at zero, so it happily sells the future. The chip holding values
patch the worst of that (+97..114 a season, measured), but they are four constants; the
rest of the squad state — bank, sell value, banked transfers — carries no terminal value
at all. Phase 4 wants a learned one. This is its first, deliberately small test: **can the
end-of-season net points still to come be predicted from the mid-season squad state better
than the constants-plus-average baseline already implied by the planner?**

## Data

The committed season-chain artifacts (six chip-mode variants x four development seasons x
the recorded chains), one row per applied decision week: the state after the decision
(remaining weeks, bank, squad sell value, free transfers, which chips remain) and the
realized target — the sum of net points from the next week to the season's end. No new
simulation; the locked holdout is never read.

## Model and baseline, both fixed now

- **GP**: scikit-learn `GaussianProcessRegressor`, RBF + white kernel, standardised
  features, `normalize_y`. Features: remaining_weeks, bank_tenths,
  squad_sell_value_tenths, free_transfers, and one 0/1 per chip still in hand
  (bboost, 3xc, wildcard, freehit). Nothing else; adding features after seeing results
  is the failure mode this document exists to prevent.
- **Baseline** (what the planner already implies): remaining_weeks x the mean weekly net
  of the *training* seasons, plus the holding values of the chips still in hand at the
  season-chain value-mode constants (bboost 20, 3xc 18, wildcard 12, freehit 20).

## Split and gate

Leave-one-season-out over the four development seasons; every row of the held-out season
is predicted by a model fitted only on the other three.

- **Gate**: the GP's held-out MAE must beat the baseline's, pooled *and* in at least three
  of four seasons. Anything less and the recorded conclusion is that the holding-value
  constants are not improved upon by this state representation — the constants stay, the
  negative is recorded, and the bar is not moved.
- Also reported, not gated: MAE by remaining-weeks band (early/mid/late season), because a
  terminal value that only works in May is not the one a GW10 five-week plan needs.

## What this is not

Not a promotion: nothing consumes the fitted value. A passing gate earns the *next* step —
wiring a terminal-value term into the planner's objective and re-running the season chain
against the holding-value control — which gets its own declaration.
