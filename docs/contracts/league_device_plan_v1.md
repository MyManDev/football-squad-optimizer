# League device plan v1

What a member's one-week plan needs, published so the member's own device can solve it.
Two documents, both inside the `provisional_league_ui_v1` envelope the league tree uses:

- `data/leagues/<league id>/device-plan.json`, one per publication: the capture's projection table in
  the order the server's solver sees it, the server's integer objective coefficients, and
  the season's rules and the member planning policy as numbers.
- `device_plan` on `data/leagues/<league id>/entries/<id>.json`, one per member: the fifteen, the bank
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
| `rules.hit_charged_scaled` | The same charge on the objective's integer scale: the rival price tag's anchor is solved at the charge, not at the margin. Absent on documents from before the field; a device then scales `hit_points_charged` itself. |
| `rules.expected_points_scale` | The integer scale; the objective divided by it is in points. |
| `rules.strategies` | Each rival strategy's overlap band on the decided week, by slug: `overlap_floor` or `overlap_ceiling` (the other null), from the strategy catalogue. Absent on documents from before the field; a device then uses the catalogue's values as it knows them. |
| `rules.top100` | Present where the week has Top 100 counts: the `weights` the menu offers, the `cohort_size` the counts are out of, and the counts' source record (`cohort_snapshot_id`, `picks_snapshot_id`, `table_sha256`, `picks_gameweek`). Absent where the week has none; a device then offers no weight. |
| `players[]` | The table in solver order: `id`, `name`, `short_name`, `team`, `position`, `buy_tenths`, `expected_points`, and `coefficients` as `[squad, starter, captain]`, the server's exact integers. With `rules.top100`: `top100_count`, how many of the cohort started him, and `top100_scaled`, his weighted points on the integer scale by weight (as text keys), scaled exactly as the server scales them; the device derives the bench coefficient from the integer by the server's rounding rule. |

`players` is sorted by id, the order the planner sorts its own table into before it
solves. The order is part of the contract: the server breaks ties between equal plans by
rank in that order, and a device that reorders the table resolves the same tie
differently.

The bench is ordered by the goalkeeper first and then by descending expected points, the
document's order on a tie. That is what the server publishes for this plan: the one-week
member path's planning table carries no appearance chance, so the shared bench rule's
expected-points fallback is the rule in force, and the device restates that fallback.

Two things the device model takes as given: a player not held has no sale price (the
planner fills the buy price, which a one-week answer never uses, since a player not held
cannot be sold), and no per-week transfer cap applies under the member policy except the
one a rival strategy sets on itself (the free transfers the member holds, at least one).

## A rival strategy on the device

A rival strategy needs one more published input: the rival's eleven and captain, read from
the rival's own entry document (`starting_xi` and the captain it marks). The device then
restates `advice._advise_against_rival`: two candidates under the band, the strictest
level the free transfers reach with no hits and the declared target with hits allowed; the
one with the higher net expected points is the plan and the other the alternative; the
price is the member's own pure-points plan at the game's charge, floored at the best plan
solved, less the banded plan, both net of hits; the gap against the rival is the two
elevens on the same table, net of the plan's hits.

## The member block

| Field | Meaning |
| --- | --- |
| `held` | The fifteen player ids. |
| `bank_tenths` | The spending power the live path computes from the stated squad sale value, not the raw bank. |
| `free_transfers` | The free transfers under the cap. |
| `sell_tenths` | Each held player's sale price in tenths, keyed by player id as text. |
| `top100_weights` | Present where the shared document carries `rules.top100`: the weights it carries, so a page can offer them before it reads the document. |

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
