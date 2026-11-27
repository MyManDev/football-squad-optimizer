# Pre-registration: a carried free transfer valued by a Bellman model

Declared 27 Nov 2026, before any number of this protocol was computed. It follows the
[fixed-level record](component_banked_transfer_value.md), its
[path diagnostic](component_banked_transfer_value_path_diagnostic.md) and the
[computed-each-week record](component_computed_banked_value.md), and reuses their chains for
every fixed level. Nothing below changes after the first number is seen.

## The question

A constant value per carried free transfer prices the first one held and the fourth the same.
The owner asked for a model in which the values fall with each transfer held, reach zero at the
bank cap, and rest on mathematics rather than a chosen number. Free transfers are treated as a
stock and valued by dynamic programming over the rest of the season.

## The model

**State.** `b`, the free transfers held at a decision, `1 <= b <= C` with `C = 5` (the 2026-27
cap).

**A week's opportunity.** For a held squad, bank and forecast, `P(k)` is the objective of the
member policy's one-week plan with `k` free transfers (hit cost 8, no carried value). The
`k`-th free transfer is worth `g_k = P(k) - P(k-1)`, `k = 1..C`. It lies in `[0, 8]`: one more
free transfer never hurts, and it can never be worth more than the hit it saves. A week's
opportunity is the vector `g = (g_1, ..., g_C)`.

**Bellman equation.** With the season's decision gameweeks `t_1 < ... < t_T`,

    V_{T+1}(b) = 0
    V_t(b) = E_g [ max_{0 <= m <= b} ( g_1 + ... + g_m + V_{t+1}(min(b - m + 1, C)) ) ]

where `m` is the free transfers used. The expectation is the mean over a sample of observed
opportunity vectors, the same sample for every week. No discount.

**The value used in a decision.** At gameweek `t` the planner adds `V_{t+1}(n)` to its
objective, where `n` is the free transfers it carries into next week. The marginal value of
the `k`-th transfer carried is `w_{t,k} = V_{t+1}(k) - V_{t+1}(k-1)`. The equation itself makes
it fall towards zero at the last decision of a season, and adds nothing past the cap.

**Assumptions, declared.** Opportunities are independent from week to week: a move not made
is not assumed to still be there next week. The opportunity distribution does not change
within a season. Both are approximations; the chain is the judge of the result.

## Estimating the opportunity distribution

The vectors `g` are measured on the states the policy's own chain visits: the primary cell of
the fixed-level record (component forecast, cap 5) at value 0, walked again with `P(0..5)`
solved at every decision from the squad, bank and forecast of that decision. 147 vectors.

**Out of season.** A season's values are computed from the vectors of the **other three
seasons** only, so no season is decided with its own opportunities.

## The arm and its decision

`component_rules_2026_27_bankmodel`: the primary cell with the value function above. At each
decision the chain solves the week with no transfer, with at most `c` transfers for
`c = 1..f`, and without a cap, adds `V_{t+1}(n)` for the `n` each plan carries, and plays the
best; a tie goes to fewer transfers. This is exact for a value that depends only on `n`, and
it changes nothing else in the decision.

## Comparisons and readings

Paired over the 147 decisions, moving-block bootstrap (block 4, 2000 resamples), as the
record.

1. **Primary: the model against 1.12**, the value the owner chose and #1523 wires. `better`
   if the 90% interval is above zero, `worse` if below, otherwise `not_separable`.
2. **The model against 0** with the record's gate (at least 1.5 a week, interval above zero,
   at most one losing season).
3. **The model against 0.5**, read by interval.

**Proposal rule, fixed now.** If the primary reads `better`, the proposal to the owner is to
replace the constant with the model. If it reads `not_separable`, the model is reported as
the principled form of the same decision and the owner chooses. If `worse`, 1.12 stays.

## Described, not gated

The value tables `w_{t,k}` per season (first, middle and last decisions), the mean opportunity
vector, the share of weeks with `g_1 = 0`, free transfers used, paid, lost at the cap and held
on average, and the decisions where the model holds a transfer that 1.12 spends.

## What does not change

No default and no product file. The model, the probe and the chain live in the experiment
module.
