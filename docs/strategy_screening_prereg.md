# Pre-registration: the overlap-knob screening, and what earns a search dimension

Written **2026-08-27, before the screening runs** — the decision rule below is fixed
before any fold is solved, so it cannot drift toward the numbers once they arrive. The
rule this screening applies is `planner_doe`'s, made quantitative the way
`fw10_screening` made it: *a knob whose levels barely move the fold-mean objective does
not deserve a search dimension.* A failed gate is a result, not a retry.

## What is being screened, and what is not

The strategy catalogue declares knobs for nine strategies, but today the solver
realizes exactly one constraint family: the first-week overlap band
(`FirstWeekOverlap`, through `solve_strategy_plan`). This screening therefore covers
the two knobs that are actually wired: **`ortak-koru`'s `overlap_floor`** (declared
6–11, default 9) and **`fark-yarat`'s `overlap_ceiling`** (declared 3–8, default 5).
Every other declared knob is unwired as of this writing and is *not screened* — an
unwired knob has no measurement, which is "yok", not zero, and it enters no search
until it is wired and screened under its own pre-registration.

The bench's gate bands (`strategy_bench_prereg.md`) are fixed at overlap ≥ 9 and
overlap ≤ 5 and **do not move with this screening**, whatever it finds. The screening
decides only whether the finer knob inside each declared range deserves a Bayesian
search dimension in layer 2, or is frozen at its default.

## Declared before measurement

- **Population**: the four development seasons (2021-22 .. 2024-25), origins
  gameweek 5, 15, 25 and 33 in each — sixteen folds. Horizon **1**: the constraint
  binds the first week only, and h=1 isolates the knob from horizon policy. The spent
  2025-26 holdout is not read; the current season is never touched.
- **Fold construction**: the `measure_mode_plan_selection` instrument — the control
  residual table's predicted points at the origin, the ownership-template rival from
  the fold's own pre-deadline snapshot, the pool restricted to the top fifteen per
  position by predicted points plus the five cheapest, with the rival's eleven and the
  held squad always kept; the held squad is the unconstrained `optimize_squad` pick on
  the fold's projection, bank = 1000 − cost, one free transfer.
- **Levels**: the declared knob ranges, exhaustively — a full-factorial design over
  each strategy's own `search_factors()`, so the searched space *is* the declared
  space, with the design fingerprint recorded in the artifact.
- **Objective, per fold and level**: the banded plan's expected points from a
  **proven** solve (`solve_strategy_plan`; an unproven or infeasible band is `None`,
  recorded as infeasible for that fold, never imputed). The control plan is solved
  once per fold and shared; `expected_points_cost` is recorded per level.
- **Pairing**: each non-default level is compared to **its strategy's default level**
  (floor 9 / ceiling 5), fold-paired, over exactly the folds where both levels proved.
  Interval: the season-aware moving-block bootstrap
  (`season_aware_moving_block_interval`) at 90%, `PromotionPolicy` defaults
  (5000 resamples, block length 4, deterministic seed 0).

## The decision rule

A knob **earns a layer-2 search dimension** if and only if at least one non-default
level satisfies both:

1. **Feasibility**: the level's proven-solve share is at least 0.75 of the sixteen
   folds (12/16) — a band the solver mostly cannot prove is not a searchable setting;
2. **Movement**: the fold-paired expected-points difference against the default level
   has a 90% interval that excludes zero, in either direction — the screening asks
   whether the knob *moves* the objective, not which way; direction and its price are
   the bench's business.

Otherwise the knob is **frozen at its default** (which is the bench band) and layer 2
does not search it. Both verdicts are recorded per knob in the artifact.

## Declared fall-backs

- If a **default level** itself proves in fewer than 12/16 folds, the screening
  reports that and renders **no verdict** for that knob (the pairing reference is not
  trustworthy); the knob stays out of layer 2 until the band's feasibility is
  understood. Menu presence at h=1 remains the bench's and the product's business,
  not this screening's.
- Monotonicity of cost in the band tightness is expected by construction and is
  **not** a finding; only the paired movement against the default is.
