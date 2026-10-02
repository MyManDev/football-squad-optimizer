# League device plan v1

What a member's one-week plan needs, published so the member's own device can solve it.
Two documents, both inside the `provisional_league_ui_v1` envelope the league tree uses:

- `data/league/device-plan.json`, one per publication: the capture's projection table in
  the order the server's solver sees it, the server's integer objective coefficients, and
  the season's rules and the member planning policy as numbers.
- `device_plan` on `data/league/entries/<id>.json`, one per member: the fifteen, the bank
  after the spending-power rule, the free transfers under the cap, and the sale price of
  each held player. Present on every entry document a build writes, since a rendered
  member has passed the same preparation for the baseline plan; `null` is the guard for a
  provider the baseline path did not see; absent on documents from before the field.

The producer is `squadopt.application.device_plan`; the page's solver is
`web/src/features/league/device/planModel.ts`, which restates the server's one-week model
over these numbers and solves it with HiGHS compiled to WebAssembly in a Web Worker.

## The shared document

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `league_device_plan_v1`. |
| `league_id`, `season`, `gameweek` | The league and the deadline the plan is for. |
| `source_snapshot_id` | The capture. The page solves only when it equals the entry's; inputs from another capture are refused as a published plan from one would be. |
| `policy_id` | The member planning policy the rules below are drawn from (`member_planning_policy_v2`). |
| `rules.squad_size`, `rules.starting_size` | Fifteen and eleven. |
| `rules.squad_position_limits` | Squad quota per position. |
| `rules.starting_position_min`, `rules.starting_position_max` | The eleven's bounds per position. |
| `rules.max_players_per_team` | The club limit. |
| `rules.max_free_transfers` | The cap on banked free transfers. |
| `rules.hit_cost_scaled` | The planner's caution margin per paid transfer, on the objective's integer scale. |
| `rules.hit_points_charged` | What the game charges per paid transfer, in points. |
| `rules.expected_points_scale` | The integer scale; the objective divided by it is in points. |
| `players[]` | The table in solver order: `id`, `name`, `short_name`, `team`, `position`, `buy_tenths`, `expected_points`, and `coefficients` as `[squad, starter, captain]`, the server's exact integers. |

`players` is sorted by id, the order the planner sorts its own table into before it
solves. The order is part of the contract: the server breaks ties between equal plans by
rank in that order, and a device that reorders the table resolves the same tie
differently.

Two things the device model takes as given: a player not held has no sale price (the
planner fills the buy price, which a one-week answer never uses, since a player not held
cannot be sold), and no per-week transfer cap applies under the member policy.

## The member block

| Field | Meaning |
| --- | --- |
| `held` | The fifteen player ids. |
| `bank_tenths` | The spending power the live path computes from the stated squad sale value, not the raw bank. |
| `free_transfers` | The free transfers under the cap. |
| `sell_tenths` | Each held player's sale price in tenths, keyed by player id as text. |

## What holds the two solvers together

`scripts/export_device_plan_fixture.py` writes `web/src/fixtures/device-plan/instances.json`:
synthetic instances solved by the repository's planner under the member planning policy,
with the squad, eleven, captain, vice-captain, bench order, transfers, hit, the plan's and
the held squad's points on the published basis, and the move rows with their attributed
gains. `tests/unit/test_device_plan_fixture.py` requires the recorded answers to still be
the planner's; `web/src/features/league/device/planModel.parity.test.ts` requires the
device solver to return them. `tests/unit/test_device_plan.py` rebuilds the problem from the
two published documents alone and gets the plan the same build published.

## What the device does not do

Only the plain pure-points plan over one week: no rival strategy, no Top 100 weight, no
manager's word, no chip, no preferences, no other model. The multi-week model, the
lineup expectation step and the switches stay with the service.
