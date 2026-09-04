# Sprint 0 Optimization Specification

## Scope

Sprint 0 solves one gameweek from externally supplied player projections. It selects a
squad, starting lineup, unordered bench, and captain. The optimizer is independent of data
vendors and fantasy platforms.

The following are out of scope: data ingestion, projection models, transfers,
multi-gameweek planning, uncertainty scenarios, risk objectives, vice-captain selection,
bench ordering, Design of Experiments, and Bayesian Optimization.

Provisional factors and evaluation requirements for future experimentation are documented in
[the experiment parameter contract](experimentation_spec.md). That contract does not change
the Sprint 0 optimizer or activate future-only parameters.

## Canonical data contract

The input is a pandas `DataFrame` with at least these columns:

| Column | Required representation |
| --- | --- |
| `player_id` | Unique non-null integer or non-empty string; one type per column |
| `name` | Non-empty string |
| `team_id` | Non-null integer or non-empty string; one type per column |
| `position` | Exactly `GK`, `DEF`, `MID`, or `FWD` |
| `price_tenths` | Non-negative integer |
| `expected_points` | Finite, numeric, non-negative value |

The optimizer does not normalize identifiers or positions. Extra input columns are carried
through to result tables. Validation and optimization operate on copies and do not modify
the caller's `DataFrame`.

Basic pool deficiencies, such as fewer players than the configured squad size or too few
players in a required position, raise `InsufficientPlayerPoolError`. A valid pool that is
infeasible because of budget, team, or interacting model constraints returns a structured
`INFEASIBLE` result.

## Default configuration

| Setting | Default |
| --- | ---: |
| Budget in tenths | 1000 |
| Squad size | 15 |
| Squad positions | 2 GK, 5 DEF, 5 MID, 3 FWD |
| Starting size | 11 |
| Starting GK | exactly 1 |
| Starting DEF | 3 to 5 |
| Starting MID | 2 to 5 |
| Starting FWD | 1 to 3 |
| Players per team | at most 3 |
| Bench weight | 0.1 |
| Expected-points scale | 1000 |
| Solver time limit | 10 seconds |
| Solver deterministic-time limit | disabled (`None`) |
| Deterministic seed | 0 |

Configuration mappings are copied into immutable mappings. The configuration is validated
when it is constructed.

## Formulation

Let `I` be the player set, `I_p` the players in position `p`, and `I_t` the players belonging
to team `t`.

For every player `i`, define binary variables:

- `x_i`: player `i` is in the squad;
- `s_i`: player `i` is in the starting lineup;
- `c_i`: player `i` is captain.

There is no separate bench variable. Because `s_i <= x_i`, the expression `x_i - s_i` is
one exactly for bench players.

### Constraints

Squad and starting sizes:

```text
sum_i x_i = squad_size
sum_i s_i = starting_size
```

Exact squad position quotas:

```text
sum_{i in I_p} x_i = squad_position_limits[p]    for each position p
```

Starting formation bounds:

```text
starting_position_min[p]
    <= sum_{i in I_p} s_i
    <= starting_position_max[p]                  for each position p
```

Budget and team limits:

```text
sum_i price_tenths_i * x_i <= budget_tenths
sum_{i in I_t} x_i <= max_players_per_team       for each team t
```

Selection relations and captain:

```text
s_i <= x_i                                       for every player i
c_i <= s_i                                       for every player i
sum_i c_i = 1
```

The implied constraint `c_i <= x_i` is not duplicated.

## Numerical precision and rounding

CP-SAT constraints use integer arithmetic. Player projections are converted with an
explicit decimal rule:

```text
scaled_points_i = ROUND_HALF_UP(
    Decimal(str(expected_points_i)) * expected_points_scale
)
```

With the default scale of 1000:

```text
6.2374 -> 6237
6.2375 -> 6238
6.2376 -> 6238
```

Python's built-in `round()` is not used. Bench coefficients are computed as:

```text
bench_coefficient_i = ROUND_HALF_UP(bench_weight * scaled_points_i)
```

For scale 1000, the maximum projection-rounding error per value is 0.0005 points. Exact
halfway values round upward, so data containing many such values can have a small positive
bias. Very close solutions can change order after scaling. A scale of 10,000 can be used
when greater precision is required, subject to CP-SAT integer limits. Coefficient bounds
are checked before solving.

Prices are already canonical integers and are never rescaled.

## Primary objective

Let `p_i` be the scaled points and `b_i` the scaled bench coefficient. The integer objective
is:

```text
maximize
    sum_i p_i * s_i
  + sum_i p_i * c_i
  + sum_i b_i * (x_i - s_i)
```

The captain term adds the captain's projection a second time. A starter receives no bench
contribution. The public objective value is the integer objective divided by the configured
expected-points scale.

`projected_score` is computed from the original projections as starting-lineup points plus
the captain bonus. Consequently, it can differ slightly from the scaled model objective
before the bench contribution is considered.

## Determinism and tie-breaking

Players are ordered by `player_id` before variables are created: numeric order for integer
IDs and lexicographic order for string IDs. The solver uses one search worker and the
configured deterministic seed.

When the primary result is `OPTIMAL`, a second solve fixes the integer primary objective to
its proven optimum. A secondary objective then prefers lower stable ranks in this priority:

1. captain;
2. starting lineup;
3. selected squad.

The weights are derived from pool and squad sizes and checked against safe integer bounds.
Both solves share one wall-clock deadline. They also share
`solver_deterministic_time_limit` when that optional limit is configured. CP-SAT
deterministic time measures solver work rather than elapsed seconds; using it as the binding
benchmark limit makes an incumbent reproducible under the pinned solver version, one-worker
policy, fixed seed, and identical model. The value is a solver stopping target, not a hard
counter: CP-SAT can report a small overshoot when it finishes a unit of work. The secondary
target subtracts the primary solve's reported work instead of granting a fresh full target.
The wall-clock limit remains a safety cap. If the second solve cannot produce a solution in
the remaining target, the proven primary solution is retained.

When the primary result is only `FEASIBLE`, tie-breaking is skipped because the optimum is
not known. Stable ordering, a single worker, and a fixed seed improve repeatability. A
wall-clock cutoff alone cannot guarantee the same feasible incumbent across machines. The
production benchmark therefore configures a deterministic work limit and rejects a run if
its wall-clock safety cap binds first. Reproducibility across a different OR-Tools version is
not claimed.

## Result and termination semantics

`OPTIMAL` and `FEASIBLE` results contain independent DataFrames for the selected squad,
starting lineup, and bench, plus a Series for the captain. Rows are returned in stable
player-ID order and indices are reset.

`INFEASIBLE` and solution-free `UNKNOWN` results contain empty DataFrames with the validated
input columns. Captain, cost, projected score, and objective value are `None`.

CP-SAT statuses map to the public statuses with the same names. `MODEL_INVALID` and
unrecognized statuses raise `SolverExecutionError`; implementation failures are not hidden
as ordinary `UNKNOWN` terminations.

Diagnostics include the backend, solve time, best bound, optimality gap, scale, seed, worker
count, and tie-break status. Extracted feasible solutions are defensively rechecked against
all constraints before they are returned.

## Data-pipeline integration boundary

Upstream data owners are responsible for stable identifiers, canonical positions, price
conversion to tenths, and expected-points generation. The optimizer does not fetch,
normalize, join, or overwrite source data. A future pipeline can supply additional columns;
they are preserved but ignored by Sprint 0 decision logic.

The top-level `optimize_squad_from_csv` adapter provides the Sprint 0 end-to-end path for a
local UTF-8 CSV that already satisfies this contract. It performs no platform-specific
transformation and delegates validation and optimization to `optimize_squad`. In particular,
it does not convert decimal prices to `price_tenths`.

## Known limitations

- Only one gameweek is modeled.
- Bench slots are not ordered.
- There is no vice captain.
- The Sprint 3 package can attach calibrated marginal projection intervals, but this
  baseline objective still ignores uncertainty and player correlation. The separate Sprint
  4 risk package reuses this feasible set with a documented conformal lower-bound objective.
- The objective is subject to the documented integer scaling approximation.
- Feasible time-limited solutions are not guaranteed to match across different machines.
- Solver performance has only been designed and tested for Sprint 0-sized pools.
