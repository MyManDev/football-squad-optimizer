# Pre-registration: the tail-mean rank selector, measured before it is wired

This document is written and committed **before** the runner it describes is run. Nothing
in it is changed by what the run says. It fixes the arms, the population, the estimator and
the drop rule in advance, so the answer cannot be read and then argued with.

It registers a **measurement**, not a change. Nothing here touches a member-facing surface,
`PUBLISHABLE_FIELDS`, `RankingCriterion`, the plan selector's sort key or any payload. If
the measurement passes, the wiring is a separate pre-registration and a separate review; if
it fails, this line closes the way the rank-probability line closed.

## The question

The member path maximises expected points. Against a named rival what a member wants is to
finish ahead, and those are different objectives: behind, variance is worth paying for;
ahead, it is worth avoiding. Expected-point maximisation cannot express that at any level of
model quality.

**Does replacing the mean with a tail mean of the per-scenario gap, taken on the side the
captured standings select, pick a better plan than the mean does?** One number answers it:
the paired per-fold difference in realized points between the plan the tail-mean selector
picks and the plan the mean selector picks, over the declared population.

## The arms

One factor, five levels, frozen here:

| Arm | Tail fraction | What it is |
| --- | --- | --- |
| `t10` | 1/10 | |
| `t20` | 1/5 | |
| `t30` | 3/10 | |
| `t50` | 1/2 | |
| `t100` | 1/1 | **the null** |

`t100` is the null and it is not a comparison arm. At a tail fraction of one the tail is the
whole sample, every side collapses to the same sum, and the criterion's argmax is the
argmax of the candidate's own total. That is today's mean selector, exactly, and
`tests/unit/test_rank_tail_selector.py` pins it bit for bit rather than asserting it here.
An arm that did not reproduce the null exactly would mean the instrument, not the idea, is
what the run measured.

No other level is added after the run. No level is dropped after the run.

## The criterion

For candidate `k`, rival `j` and scenario `s`, the gap is `g(k, j, s) = score(k, s) - score(j, s)`,
both scored on the **same** scenario draw so shared players cancel inside the scenario rather
than in expectation.

Each rival is assigned a side from the sign of the captured standings gap against
`application/strategies/rule.py::band_edge_points` — the same band the published strategy
rule already uses, at the same edge, with no second constant introduced here:

- **behind** (gap below the negative edge): the mean of the best `m` of the `S` values of `g`.
- **ahead** (gap above the edge): the mean of the worst `m`.
- **level** (inside the band): the mean of all `S`.

with `m = ceil(fraction * S)`. Every rival enters at once and at equal weight. The equal
weight needs no measurement: one rival passed is one place gained.

The criterion is computed in exact integers over a common denominator, the construction
already used at `scenarios/selection.py:60-63`, so no comparison turns on a float's last
bits. Ties break to the lowest candidate index, which puts the control first, matching
`scenarios/selection.py:258-262`.

### Why a tail mean and not a rank probability

Three pre-registered attempts to publish rank probabilities failed and a stop rule closed
that line. The defect they hit was **location**: `docs/rival_calibration.md:8-9` records a
claimed 0.763 against a realized 0.345 at h=1, and 0.869 against 0.321 at h=3.

A tail mean is shift-equivariant. A constant per-rival edge `e` moves every candidate's term
for that rival by the same amount and cannot change which candidate wins. This design is not
claiming the rival model is calibrated; it is claiming invariance to the one defect that was
actually measured, which is a checkable property rather than a hope, and
`tests/unit/test_rank_tail_selector.py` checks it.

The property does **not** cover a scenario-correlated edge — a rival whose error moves with
the scenario rather than sitting on it as a constant. That is named below as an unmeasured
limit, not waved away.

## The population

The **147 development folds**, 2021-22 through 2024-25. The 2025-26 holdout is locked and is
not read, listed or hashed by this measurement.

A fold drops out of the paired comparison only when its control plan or its candidate menu
cannot be proven, and it drops out for every arm together. Nothing is imputed; the drop is
recorded per fold and per arm.

### The candidate menu

`_solve_within_free_transfers` returns inside its loop on the first level that solves, so it
produces exactly one plan at the strictest reachable rung. **It is not a menu**, and the menu
this measurement needs has to be built. It is built explicitly, from the catalogue's own
declared knob levels and nothing else:

- `ortak-koru` at each declared `overlap_floor` in 6..11,
- `fark-yarat` at each declared `overlap_ceiling` in 3..8,
- `kaptan-ayris`,
- the control, `saf-puan`, solved once and handed back in so every price is priced against
  the same control.

An unproven band yields no candidate, exactly as `application/strategies/candidates.py::solve_strategy_plan`
already returns `None`: the menu shortens honestly rather than carrying an unproven entry.

Two of those entries are expected to be duplicates of the control and are **declared here
rather than discovered later**. `candidates.py::_band` reads `overlap_floor` and
`overlap_ceiling` and nothing else, so `kaptan-ayris`, whose only constraint is
`captain_must_differ`, produces a band of `None` and therefore the control's own plan. The
runner de-duplicates candidates by decision identity and records how many entries collapsed.
A duplicate would otherwise enter the criterion twice at equal weight.

### The rivals, and the weakness that belongs with them

**The archive holds no manager entries at all.** `application/strategies/rule.py:52-61`
states it, and `data/raw/vaastav-fpl` carries per-player gameweek rows only. There is no
historical league of fifteen members to replay.

The fourteen rivals in this sweep are therefore **constructed**, from
`scenarios/rivals.py::template_rival_from_ownership` plus declared perturbations, and they
are not real league members. This is a weakness of the population and it is stated here,
before the run, rather than discovered in the record afterwards. It bounds what a pass would
license: a pass says the criterion beats the mean against a constructed field of fourteen,
and says nothing yet about the real fifteen.

### The scenario draw

One shared draw per fold, the V2 component sampler:
`scenarios/components.py::sample_component_scenarios` through
`scenarios/decision_scoring.py::score_component_scenario_decision`. Every candidate and every
rival is scored on that one draw, so shared players cancel per scenario, and the official
scorer's autosub and vice-captain recovery is inside the numbers. That channel is why V2 is
declared rather than V1: across the same 147 folds official scoring adds +2.626 to SquadOpt
and +3.401 to the constrained template (`docs/measurements_index.md:74`), and the +0.775
between them is exactly the channel a V1 draw cannot see.

The draw is keyed on the fold and the window only — never on which candidate or which rival
is being scored, and never on who is asking. The budget is CP-SAT deterministic time, not
wall clock, following `scenarios/rank.py:85-96`, which names #239 and sets the wall ceiling
explicitly as a safety stop rather than a budget.

## The estimator

`evaluation/statistics.py::season_aware_moving_block_interval`, at `PromotionPolicy`
defaults: **5000 resamples, block length 4, seed 0, 90%**. A resampled block never spans the
boundary between two seasons.

## The drop rule

Stated against the corrected instrument, not against the 3.78 that was quoted at this work
when it was commissioned.

**The 3.78 does not apply here.** It is `docs/measurement_instrument.json` line 2220,
`iid_mde_alpha_0_05_power_0_8`, and it sits inside a `forward_diagnostic.adjusted` block whose
own `folds` field reads 123, not 147. It is an IID normal figure, and
`docs/measurement_instrument.md:34-36` says of exactly that pair of numbers: "These are
different quantities... these descriptive figures do not certify a new gate." Wrong fold
count, wrong estimator, and self-declared as not a gate.

The arm this measurement actually runs is a **paired objective swap on one population**,
which is far quieter than the template-gap series. The nearest measured comparator is
`rotation_oracle_ceiling` (`docs/measurements_index.md:167`): a paired 147-fold arm whose 90%
season-aware moving-block half-width is **0.803**. A paired effect near 1.0 to 1.5 points a
week is resolvable on this instrument.

So, frozen:

- **The line closes** if the best arm's paired mean is **below 1.0 points per week**, or its
  90% interval contains zero. Nothing is wired, the record says so, and this is the end of
  the line rather than a reason to add a level or change a seed.
- **The line continues** only if some arm clears both. Continuing means one further
  pre-registration and one further review; it does not mean the criterion ships.

`PromotionPolicy.min_mean_improvement` is 0.5 and is deliberately **not** the threshold used
here: a criterion swap on the live member path is a larger commitment than a component
change, and 1.0 is declared above it on purpose.

If more than one arm clears, the reported arm is the **smallest tail fraction that clears**,
declared now so the choice is not made by looking at which number is largest.

## What may not be published, and is not

No probability, percentage, quantile, spread, likelihood, chance or odds reaches a
member-facing surface from this work, in any language. The tail fraction, the criterion's own
value, the per-rival tail means and the side assignments live in the measurement artifact and
nowhere else. The criterion is points-denominated throughout: it is a sum of tail means of a
points difference, read back through a common denominator into points.

This measurement adds nothing to `PUBLISHABLE_FIELDS` and changes no `RankingCriterion`.

## Unmeasured quantities this measurement does not supply

Named so nobody later reads a number here as covering them:

1. **A scenario-correlated rival edge.** Shift-equivariance covers a constant per-rival error
   and nothing else. Whether the rival model's error moves with the scenario has not been
   measured.
2. **Real league rivals.** The constructed template rivals are not the fifteen members.
3. **The whipsaw rate.** How often a member's side assignment flips between weeks on noise,
   and what that costs at four points a hit, is not measured here. The band is what is meant
   to stop it, and the band's adequacy is a separate question.
4. **Inertness this season.** At gameweek 5 with 34 weeks left the band edge is about 124
   points, which in a fifteen-member league covers most of the table, so almost every rival
   reads level and the criterion reproduces today's selector. That is the design's whipsaw
   guard working, not a defect, but it does mean a pass here would be a statement about
   development folds and about later gameweeks, not about the coming weeks.
