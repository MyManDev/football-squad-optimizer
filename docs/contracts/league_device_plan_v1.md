# League device plan v1

What a member's one-week plan needs, published so the member's own device can solve it.
Two documents, both inside the `provisional_league_ui_v1` envelope the league tree uses,
both in the league's tree (`data/leagues/<league id>/` under the league directory,
`data/league/` on a site from before it):

- `device-plan.json`, one per publication: the capture's projection table in the order the
  server's solver sees it, the server's integer objective coefficients, and the season's
  rules and the member planning policy as numbers.
- `device_plan` on `entries/<id>.json`, one per member: the fifteen, the bank after the
  spending-power rule, the free transfers under the cap, and the sale price of each held
  player. Present on every entry document a build writes, since a rendered member has
  passed the same preparation for the baseline plan; `null` is the guard for a provider
  the baseline path did not see; absent on documents from before the field.

The producer is `squadopt.application.device_plan`. The page's solver is
`web/src/features/league/device/`, which restates the server's one-week model over these
numbers and solves it with HiGHS compiled to WebAssembly (the `highs` package, its binary
served from the site's own assets) in a Web Worker:

| File | What it does |
| --- | --- |
| `types.ts` | The two documents' shapes and guards, the chips and rival strategies a request may name, and the answer. |
| `selection.ts` | Which selections the device takes from a request; anything else is the service's. |
| `computable.ts` | The device's statement for a member: the strategies, window one, the rivals it can play against, the weights. |
| `requests.ts` | Which solve answers a request, and the combinations it refuses. |
| `lp/problem.ts` | A mixed-integer program as data, and its text in the LP format the solver reads. |
| `lp/memberWeek.ts` | One member's one-week problem, with what the member path varies: a chip, the charge per paid transfer, a transfer cap, an overlap band, the points chosen on, a tie-break tier. |
| `lp/lineup.ts` | The eleven and the captain for a fifteen taken as given. |
| `solve/week.ts` | The primary solve, the three tie-break solves and the value of a fifteen. |
| `publication/rows.ts` | The server's publication rules: the move rows and their gains, the vice-captain, the bench order. |
| `strategies/chips.ts` | A chip's effect on the objective and on what the week scores, and its gain against the no-chip plan. |
| `strategies/rival.ts` | A rival strategy: `advice._advise_against_rival` restated. |
| `strategies/top100.ts` | A Top 100 weight: `advice.advise_with_top100` restated. |
| `deviceAdvice.ts` | The answer as the advice document the page already reads. |
| `useDevicePlan.ts` | Reads the documents when the member asks, holds them to the capture on screen, runs the worker. |
| `deviceSolver.worker.ts` | The solve off the page's thread: a ready signal once loaded, then one request in; an answer, a refusal or a failure out. |

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
| `rules.strategies` | Each rival strategy's overlap band on the decided week, by slug: `overlap_floor` or `overlap_ceiling` (the other null), from the strategy catalogue. Absent on documents from before the field; a device then uses the catalogue's values as it knows them (`ortak-koru` a floor of nine, `fark-yarat` a ceiling of five). |
| `rules.top100` | Present where the week has Top 100 counts: the non-zero `weights` the menu offers, the `cohort_size` the counts are out of, and the counts' source record (`cohort_snapshot_id`, `picks_snapshot_id`, `table_sha256`, `picks_gameweek`). Absent where the week has none; a device then solves no weight. |
| `players[]` | The table in solver order: `id`, `name`, `short_name`, `team`, `position`, `buy_tenths`, `expected_points`, and `coefficients` as `[squad, starter, captain]`, the server's exact integers. With `rules.top100`: `top100_count`, how many of the cohort started him, and `top100_scaled`, his weighted points on the integer scale by weight (as text keys), scaled exactly as the server scales them; the device derives the bench coefficient from the integer by the server's rounding rule. |

`players` is sorted by id, the order the planner sorts its own table into before it
solves. The order is part of the contract: the server breaks ties between equal plans by
rank in that order, and a device that reorders the table resolves the same tie
differently. The device sorts the table by id itself before it solves, whatever order the
document arrived in. With the best value held, three more solves minimise in turn the
captain's rank, the starters' rank sum and the squad's rank sum, as the server settles a
tie; the value of a fifteen taken as given is the week's points of the eleven and captain
chosen for it on the same objective, a tie settled to the lower rank.

The bench is ordered by the goalkeeper first and then by descending expected points, the
document's order on a tie. That is what the server publishes for this plan: the one-week
member path's planning table carries no appearance chance, so the shared bench rule's
expected-points fallback is the rule in force, and the device restates that fallback. The
vice-captain is the eleven's next-highest expected points after the captain, the lower id
on a tie. The move rows are paired as the server pairs them, by position with both lists
in id order and any leftover paired in id order at the end; each row's gain is what the
value of the fifteen moves by when that swap is applied after the rows above it, so the
rows add up to the gain against holding, and every row, with the gain against holding, is
null where the chain does not end at the plan's own points.

Three things the device model takes as given:

- A player not held has no sale price. The planner fills the buy price, which a one-week
  answer never uses, since a player not held cannot be sold.
- No per-week transfer cap applies under the member policy, except the one a rival strategy
  sets on itself: the member's free transfers, at most `rules.max_free_transfers` and at
  least one.
- Every held player is in the table with a sale price. The producer writes a null block
  otherwise. A held id the table does not carry would be left out of the model, and a held
  player with no sale price would be priced at the buy price.

## What the device answers

Window one only, for a member whose entry document carries the block, on the capture the
shared document is from:

| Selection | What the device solves |
| --- | --- |
| The pure-points plan (`saf-puan`) | The one-week model above. |
| A chip: `wildcard`, `freehit`, `bboost`, `3xc` | The same week with the chip played. The page offers a chip only where the entry document's chip block shows it with a half still available whose window holds the decided gameweek; the solver itself does not check that. In the objective, a Bench Boost adds the bench and a Triple Captain counts the captain once more, each only where the coefficient is positive. The points stated count all fifteen under a Bench Boost and the captain three times under a Triple Captain. A Wildcard or a Free Hit pays no hits. The move rows and the gain against holding are on the chip week's basis, holding meaning the held fifteen with the chip played. Beside it the member's own no-chip plan, and `gain_vs_no_chip`: the chip week net of hits less that plan net of hits. |
| A rival strategy: `ortak-koru`, `fark-yarat` | The section below, against a rival whose entry document is on the same capture and marks a captain in their eleven. |
| A Top 100 weight | The pure-points plan chosen on `top100_scaled` at a weight the member block names: the captain's coefficient is that integer, the bench's a tenth of it rounded half up and the starter's the rest. Everything stated (the points, the rows, the gain against holding) is on the base points with the eleven the weighted choice fields. The price is the member's own pure-points plan net of hits less the weighted plan net of hits, floored at zero; `changed` says whether a move, the eleven or the captain differs from that plan. A row is `points_gain` where that plan also sells the row's outgoing player and buys its incoming one and the base points do not score it below zero, and `top100_preference` otherwise. A weight of zero is the plain plan; the server publishes no document of its own for it. |

## A rival strategy on the device

A rival strategy needs one more published input: the rival's eleven and captain, read from
the rival's own entry document (`starting_xi` and the player it marks `is_captain`). The
band is the strategy's in `rules.strategies`, or the catalogue's. The device then restates
`advice._advise_against_rival`: two candidates under the band, the strictest level a cap
of the member's free transfers (at most `rules.max_free_transfers`, at least one) reaches, a floor relaxed downward to one and
a ceiling upward to eleven, and the declared target with no cap and hits allowed; the one
with the higher net expected points is the plan (the capped one on a tie) and the other the
alternative. The price is the member's own pure-points plan solved at the game's charge,
floored at the best plan solved, less the banded plan, both net of hits; every solve is
proved, so the ceiling is the price. The gap against the rival is the two elevens on the
same table, each captain doubled, net of the plan's hits.

## What the device refuses

`requests.ts` refuses two combinations before any solve: a Top 100 weight beside a chip or
a rival strategy, and a chip beside a rival strategy. The server's one-week chip combines
with nothing. A rival strategy at a Top 100 weight the server does publish
(`advice_variants.advise_rival_with_top100`), and the device declines it by contract.

A solve that ends other than optimal, at the plan, the tie-break or the hold stage, is
refused, so a plan that was not proved is never shown. Only a rival candidate may prove
infeasible: a capped level then tries the next level, and an infeasible uncapped target
drops out of the comparison. So are a rival whose eleven names a
player the table does not carry or whose captain is not in it, a strategy with no band, a
band neither candidate can meet, a pricing plan with no solution, a weight the shared
document does not carry and a player with no weighted points at it. Each is a
`DevicePlanRefused` naming its stage, which the worker replies as a refusal.

The page asks the device only for what `selection.ts` takes: window one, without the
manager's word, on the current model and without preferences; a chip only as above; a
rival strategy only against a named rival, without a chip, and only against a rival the
statement names; a weight only on the pure-points plan and only one the member block
names. It answers without a plan where the shared document is not published, where it or
the rival's entry document is from another capture, and where the rival's eleven marks no
captain. It fails where the shared document is not the expected shape or the rival's entry
document cannot be read. The manager's word, preferences, the football model, the windows beyond one week,
the multi-week model and the lineup expectation step stay with the service.

## The member block

| Field | Meaning |
| --- | --- |
| `held` | The fifteen player ids. |
| `bank_tenths` | The bank the live path plans with. Where the member's purchase prices were rebuilt from the transfers list (`purchase_prices_known` on the entry), the raw bank; otherwise the spending power computed from the stated squad sale value, the bank less any shortfall it covers. |
| `free_transfers` | The free transfers under the cap. |
| `sell_tenths` | Each held player's sale price in tenths, keyed by player id as text. Where the purchase prices were rebuilt, the game's selling rule on each player's purchase price at the capture's price; otherwise the current price less any per-player deduction the spending power takes. |
| `top100_weights` | Present where the shared document carries `rules.top100`: the weights it carries, so a page can offer them before it reads the document. |

## What holds the two solvers together

`scripts/export_device_plan_fixture.py` writes `web/src/fixtures/device-plan/instances.json`:
synthetic instances solved by the repository's planner under the member planning policy,
with the squad, eleven, captain, vice-captain, bench order, transfers, hit, the plan's and
the held squad's points on the published basis, and the move rows with their attributed
gains; the `chips` instances, each chip forced on two of the fifteens; and the `rivals`
world, whose document the real producer writes with the bands, the charge and the Top 100
inputs, answered by `advise_entry` under each rival strategy against each rival and by
`advise_with_top100` at two weights. `tests/unit/test_device_plan_fixture.py` requires the
recorded answers to still be the planner's and the service's; in
`web/src/features/league/device/`, `planModel.parity.test.ts` requires the device to return
the plain and chip answers, `rival.parity.test.ts` the rival answers and the refusal, and
`top100.parity.test.ts` the weighted answers and the refused combinations.
`tests/unit/test_device_plan.py` rebuilds the problem from the two published documents
alone and gets the plan the same build published. `planModel.chips.shipped.test.ts` solves
every chip document of the committed tree on the device and requires what the tree
publishes; `planModel.shipped.test.ts` does the same, player by player, for every human
member's pure-points plan and every rival and Top 100 document of one week the member's
index names, and lists by name each named document the device declines by contract.
