# FPL entry bundle v1

Refs #980, #983 and #1008. Contract: `fpl_entry_bundle_v1`. The schema is
[`fpl_entry_bundle_v1.schema.json`](fpl_entry_bundle_v1.schema.json) and the synthetic examples
are [`fpl_entry_bundle_v1.examples.json`](fpl_entry_bundle_v1.examples.json).

The FPL forwarder ([ADR 0012](../architecture/decisions/0012-fpl-forwarder.md)) answers
`GET /api/v1/fpl/entry/{entry}/bundle?gw={table gameweek}` with this document: what the device's
entry readers take for one entry, read from FPL on the visitor's request, and the member's
current week. One member costs one request to the Worker. It is never FPL's own JSON. The site
reads it through #983 step 3's client and identity rule (the picks gameweek is the table
gameweek minus 1, and the history covers it): for the live week on a published member's page,
and since step 4 for the whole member page of a team the site does not publish
(`web/src/features/league/forwarded/`).

## Which weeks it holds

- **The table gameweek** `gw` is the week the device plans for. It runs from 2 to the week after
  the latest gameweek whose deadline has passed, which is the week the site's
  `/data/fixtures.json` calls current. A later or earlier one is refused with 404 before FPL is
  asked anything.
- **The held week** is `gw - 1`: its picks were frozen at its deadline.
- **The Free Hit walk-back.** A Free Hit squad lasts one week, so when the held week's picks
  name the Free Hit, the picks of the week before are read too, and so on until a week without
  it, never before the week the entry joined (`heldSquadBasis` in
  `web/src/features/league/entryState/rules.ts`).
- **The opening fifteen.** When the history starts at gameweek 1, the gameweek 1 picks are read
  for the purchase-price replay (`rebuildPurchasePrices` in
  `web/src/features/league/entryState/prices.ts`). A late joiner has none.
- **The current week** is the latest gameweek whose deadline has passed.

No picks are read for a week before the entry's `started_event`.

## Fields

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `fpl_entry_bundle_v1`. |
| `entry_id` | The entry asked for. |
| `gameweek` | The table gameweek asked for, 2 to 38. |
| `source_time` | When the forwarder finished reading FPL (UTC, ISO 8601, ending in `Z`). A last good copy keeps its original time. |
| `entry` | `id`, `name` and `started_event` of `entry/{id}/`: what `readEntry` takes. FPL's answer must declare the entry asked for. |
| `history` | `current`: per played week `event`, `event_transfers`, `event_transfers_cost` and `bank` (an integer, or `null` when FPL gives none); `chips`: per chip played `name` and `event`. What `readHistory` takes. |
| `transfers` | Per transfer `entry`, `event`, `time`, `element_in`, `element_in_cost`, `element_out` and `element_out_cost`: what `readTransfers` takes. |
| `picks` | One document per week read above, in week order, each as `readPicks` takes it: `active_chip` (`null` for none), `automatic_subs` (`entry`, `event`, `element_in`, `element_out`), `entry_history` (`event`, `bank`, `value`) and `picks` (`element`, `position`, `multiplier`, `is_captain`, `is_vice_captain`) in FPL's own positions. |
| `current_week` | The member's in-progress week, or `null` (below). |

Field names are FPL's own, so each part reads with the readers in
`web/src/features/league/entryState/` unchanged. Nothing else of FPL's answers is kept, whatever
else they carry; a week's points appear only in `current_week`.

## The current week

`current_week` is the in-progress member week of #980 comment 6409696721, in `week_live_v1`'s
`memberWeek` shape (the schema's `$defs/memberWeek` is a copy of that contract's, and a test
holds them equal): `entry_id`, `gameweek`, the fifteen `pick_order`, `captain`, `vice`,
`active_chip`, `transfer_cost` (`entry_history.event_transfers_cost`) and, when FPL gives it,
`entry_history_points` (`entry_history.points`), all from the current week's picks.

FPL moves a substitute into the starter's position when it applies an automatic substitution.
`pick_order` is the order named at the deadline: each recorded substitution is undone as
`_original_picks` in `src/squadopt/experiments/benchmark_v2_live.py` undoes it, so positions 1
to 11 are the named eleven and 12 to 15 the captured bench order, as `week_live_v1` requires.
The `picks` documents keep FPL's positions, which `readPicks` expects.

`current_week` is `null` when no picks exist for that week (the entry joined later), or when
`week_live_v1` cannot state them: a chip outside its list, a substitution that cannot be undone,
no single captain and different vice among the named eleven, or no transfer cost.

## Refusals

Every refusal is JSON with `x-squadopt-fpl: 1`, never this document:

- an entry id that is not a positive integer, a `gw` outside 2 to the week after the current
  one, or a query other than `gw`: 404 `not_found`;
- FPL answers 404 for the entry: 404 `entry_not_found`;
- FPL refuses or fails for any part, sends a part this contract cannot be read from, or the site's
  fixture list cannot be read, and no last good copy is held: 503 `upstream_unavailable`.

## Copies

A bundle is kept in the serving data centre for 10 minutes while a fixture of the current week
is unfinished (or the week's fixtures could not be read), and until the next deadline once all
are finished; never past the next deadline, when the held week changes. Its last good copy is
kept two days longer and served unchanged, with `x-squadopt-fpl-cache: last-good`, when FPL
refuses or fails. A 404 for an entry is kept for 10 minutes.

## Synthetic examples

`fpl_entry_bundle_v1.examples.json` holds two invented entries for table gameweek 10:

- `free_hit_walk_back`: an entry from gameweek 1 that played its Free Hit in week 9, so the
  bundle holds the picks of weeks 1, 8 and 9, and a current week with the Free Hit chip;
- `late_joiner`: an entry that joined in week 4, with one automatic substitution in week 9, so
  the bundle holds week 9 only, its picks in FPL's positions and its current week in the named
  order.

The forwarder's node tests build both from synthetic FPL-shaped answers and require the result
to equal the file; `tests/unit/test_fpl_forwarder_contracts.py` validates them against the schema
and the member week against `week_live_v1`.
