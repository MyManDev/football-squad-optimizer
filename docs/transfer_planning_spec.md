# Deterministic transfer-planning specification

Status: **Sprint 14 implementation complete**.

This layer optimizes a sequence of deadline decisions. It consumes projections and explicit
transaction prices; it does not fetch data, predict prices, or know a fantasy platform's
API.

## Public interface

```python
optimize_transfer_plan(
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig | None = None,
) -> TransferPlanResult
```

`PlanningHorizon.table` contains one row per player and planned gameweek:

```text
gameweek
player_id
name
team_id
position
buy_price_tenths
sell_price_tenths
expected_points
```

Gameweeks must be consecutive and contain the same player universe. Prices remain integers in
tenths. The buy and sell prices are supplied independently because the optimizer must not infer
platform-specific sale-price rules. Required values must be complete, projections must be
finite and non-negative, and `sell_price_tenths <= buy_price_tenths`.

The horizon is copied, validated, and fingerprinted. The optimizer revalidates the fingerprint
before every solve so mutation after construction fails explicitly.

## State and decision variables

For player `i` and gameweek `t`:

```text
x_it       player is in the squad
s_it       player starts
c_it       player is captain
in_it      player is transferred in before deadline t
out_it     player is transferred out before deadline t
```

The existing squad, position, team, formation, starter, and captain constraints apply in every
gameweek. Stateful bank accounting replaces the isolated single-gameweek budget inequality.
This is necessary because a legal current squad may have a market value above the original
budget after price movements.

## Squad continuity

For the first gameweek, `x_i,-1` is supplied by `InitialSquadState`. Thereafter:

```text
x_it = x_i,t-1 + in_it - out_it
in_it + out_it <= 1
```

Because squad size is fixed in every gameweek, transfer-in and transfer-out counts balance.
The public result still reports both directions explicitly.

## Bank accounting

Let `bank_t` be the bank after deadline `t`, `buy_it` the supplied acquisition price, and
`sell_it` the supplied sale price:

```text
bank_t = bank_t-1
       + sum_i sell_it * out_it
       - sum_i buy_it * in_it

bank_t >= 0
```

No terminal bank value is added to the objective. Money is useful only when it enables a
better legal plan within the declared horizon.

## Free transfers and hits

`ft_t` is the free-transfer count before deadline `t`, `n_t = sum_i in_it`, and `paid_t` is the
number of transfers charged a hit:

```text
paid_t     = max(n_t - ft_t, 0)
unused_t   = max(ft_t - n_t, 0)
ft_t+1     = min(max_free_transfers, unused_t + free_transfer_accrual)
```

CP-SAT `MaxEquality` and `MinEquality` constraints encode these exact state transitions.
Defaults are configurable rather than hidden in platform-specific logic.

## Objective

For discount factor `gamma`, projected starting score `Y_t`, bench projection `B_t`, baseline
bench weight `w_b`, transfer hit `h`, and paid-transfer count `paid_t`:

```text
maximize sum_t gamma^t * (Y_t + w_b * B_t - h * paid_t)
```

`Y_t` counts the captain for a second time. `B_t` is squad depth rather than realized score.
The result reports projected scores, bench projections, hits, bank, and free-transfer state for
every gameweek, plus horizon totals and solver diagnostics.

## Integer scaling and determinism

- Expected points and hit cost use `OptimizationConfig.expected_points_scale` with
  `ROUND_HALF_UP`.
- Discount weights use `TransferPlanningConfig.objective_weight_scale`, also with
  `ROUND_HALF_UP`.
- A discounted weight that rounds to zero is rejected instead of silently ignoring a future
  gameweek.
- Conservative objective and bank bounds are checked before solving.
- Players use stable `player_id` order, CP-SAT uses one worker and the configured seed, and a
  second solve applies a stable rank tie-break after a proven primary optimum.
- `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, and `UNKNOWN` remain solver-independent statuses.

## Current limitations

- Projections are deterministic; scenario-aware multi-stage recourse is not implemented.
- The player universe must remain constant across the horizon.
- Wildcard, free hit, bench boost, triple captain, and automatic substitutions are excluded.
- Future buy and sell prices must be supplied; this layer does not forecast them.
- There is no terminal squad or bank value beyond the final included gameweek.
- Runtime grows with both players and horizon length, so long horizons require explicit
  performance testing before operational use.
