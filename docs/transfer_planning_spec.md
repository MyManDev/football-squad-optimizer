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

## Chips (bench boost, triple captain, wildcard, free hit)

`optimize_transfer_plan(..., chips=ChipAvailability(...))` names the chips the planner may
play in which gameweeks of the horizon; omitted or empty, the model is exactly the chip-less
planner (tested). The caller derives availability from the season's published rules —
`squadopt.live.chip_availability_for(SeasonRules, gameweeks, used=...)` applies the two
half-season windows and drops chips already used inside a window — so the planner never
hard-codes a season. `forced` pins a chip to a gameweek (hand-timed play).

- One Boolean per available chip per gameweek; at most one chip per gameweek; each chip at
  most once per horizon (window bookkeeping across horizons is the caller's).
- **Bench boost**: every squad member scores in full — an auxiliary Boolean per player,
  bounded above by the chip, the squad variable, and one minus the starter variable, adds
  the unweighted remainder `(points − bench)`; upper bounds suffice because the coefficient
  is non-negative and the objective is maximised.
- **Triple captain**: an auxiliary Boolean bounded by the chip and the captain variable
  adds the captain's points once more.
- **Wildcard**: paid transfers move to inequality form (`paid ≥ count − free_before −
  squad_size × wildcard`, `paid ≥ 0`), so the negative-weighted variable takes its old
  value without the chip and zero under it. `TransferPlanningConfig.
  wildcard_preserves_free_transfers` (default `True`) states the assumed rule that transfers
  under a wildcard do not consume banked free transfers; the source does not publish this,
  so it is a flag rather than a constant.
- Wildcard free-transfer accounting is pinned in both directions (`consumed = count`
  without the chip, `0` under it): the bank it feeds is not always in the objective (a
  horizon's last week, a full bank), and a free variable there left the accounting
  inconsistent — found by the season-long chain, which plays wildcards in last weeks.
- Tie-break, two tiers above every rank term: among plans with equal objective, fewer
  chips (a chip that buys nothing on paper is worth more later); among plans playing the
  same number, the later week (a rolling planner re-decides a deferred chip next week
  with fresher information; committing early buys nothing on paper). Both are paper
  ties only — a horizon still plays a chip worth anything now rather than hold it for a
  season it cannot see, which is why the season chain also carries a reservation policy.
- Extraction re-verifies chip accounting (zero paid transfers under a wildcard, the
  free-transfer bank per the flag, full bench value and tripled captain in the reported
  contribution) and reports `chips_played`; `chip_availability_fingerprint` and
  `chips_available` are in the diagnostics.
- **Free hit** (contract `deterministic_transfer_planning_v2`): the week's squad is
  temporary. Transfers under it cost no hits and (per the flag) leave the free-transfer
  bank alone, the per-gameweek cap is lifted, and the next week starts from the squad and
  bank the free-hit week started from — carried as per-week *base* variables pinned to
  either this week's squad and bank or the previous ones by the chip's Boolean
  (`base ≥ squad − fh`, `≤ squad + fh`, `≥ previous − (1 − fh)`, `≤ previous + (1 − fh)`;
  the bank likewise with the bank bound as big-M). Extraction reverts the carried squad
  and bank after a free-hit week and verifies continuity against the base.

## Current limitations

- Projections are deterministic; scenario-aware multi-stage recourse is not implemented.
- The player universe must remain constant across the horizon.
- Automatic substitutions are excluded; the value a chip buys depends entirely on the
  projection's view of doubles and blanks (see the rolling-horizon and season-chain
  measurements).
- Future buy and sell prices must be supplied; this layer does not forecast them.
- There is no terminal squad or bank value beyond the final included gameweek.
- Runtime grows with both players and horizon length, so long horizons require explicit
  performance testing before operational use.
