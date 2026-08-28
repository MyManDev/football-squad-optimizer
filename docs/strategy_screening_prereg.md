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

## Amendment — 2026-08-27, after the first run, before the binding analysis

The first run executed the analysis exactly as declared above and produced
**degenerate intervals**: every 90% interval collapsed to its own mean. The defect is
structural, not numerical — with four folds per season and `PromotionPolicy`'s
default `moving_block_length = 4`, the only possible block *is* the season, so every
resample reproduces the sample exactly and the bootstrap has zero variance by
construction. An interval that cannot widen "excludes zero" for any nonzero mean,
which would have made the movement gate pass vacuously.

Recorded in the record-error tradition rather than silently replaced: the first
run's artifact is superseded, its fold values (deterministic solves) are unchanged,
and the **binding analysis** re-computes only the intervals with
`moving_block_length = 2` (two blocks per season, the largest length that resamples
at all on this population), all other policy parameters unchanged. The interval
policy is recorded in the artifact. The feasibility half of the rule is untouched.
This amendment was written after seeing the first run's output; what it changes is
justified by the structure of the population alone, and whichever verdicts the
corrected intervals produce are the result.

## Corrective-run amendment — 2026-08-28, holdout no-read boundary

Review established that the binding run loaded the archive with `build_panel`'s
unrestricted default and filtered to the development population only downstream.
Because that default includes the locked 2025-26 season, the committed artifact's
`holdout_untouched: true` statement was not supported. The existing result is therefore
non-binding; its numbers cannot justify either knob verdict.

No factor, fold, threshold, bootstrap rule, seed or verdict rule changes. Before a
corrective run, the loader must receive the explicit history list 2020-21 through
2024-25, excluding 2025-26 before any file is loaded. Provenance and
`holdout_untouched` derive from seasons actually present in the returned panel, and an
unexpected holdout row aborts before residual construction or artifact writes. These
rules and their boundary tests are committed before the corrective execution.
